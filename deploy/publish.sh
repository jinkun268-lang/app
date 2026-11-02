#!/usr/bin/env bash
# 服务器端发布脚本：解包 → 装依赖 → 备份数据库 → 原子切换 → 重启 → 健康检查 → 失败自动回滚。
# 由 CI 通过 SSH 调用： sudo /opt/citrus-app/publish.sh /tmp/release-<tag>.tar.gz <tag>
set -Eeuo pipefail

APP_ROOT="${APP_ROOT:-/opt/citrus-app}"
RELEASES="$APP_ROOT/releases"
CURRENT="$APP_ROOT/current"
VENV="$APP_ROOT/venv"
BACKUPS="${BACKUPS:-/var/backups/citrus-app}"
HEALTH="${HEALTH:-http://127.0.0.1:18080/api/v1/health/ready}"
DB_NAME="${DB_NAME:-citrus_app}"
SERVICE="${SERVICE:-citrus-app}"
KEEP="${KEEP:-5}"          # 保留的版本数（含当前）
ATTEMPTS="${ATTEMPTS:-20}" # 健康检查重试次数（每次间隔 1 秒）

log() { printf '[publish] %s\n' "$*"; }
die() { local code="$1"; shift; log "$*"; exit "$code"; }

[ $# -ge 1 ] || die 2 "用法: $0 <release.tar.gz> [tag]"
TARBALL="$1"
[ -f "$TARBALL" ] || die 2 "发布包不存在: $TARBALL"
TAG="${2:-$(basename "$TARBALL" .tar.gz)}"
TAG="${TAG//[^A-Za-z0-9._-]/_}"

NEW="$RELEASES/$TAG"
OLD="$(readlink -f "$CURRENT" 2>/dev/null || true)"

log "目标版本: $TAG"
log "当前版本: ${OLD:-<无>}"

rollback() {
  local code="$1"
  if [ -n "$OLD" ] && [ -d "$OLD" ]; then
    log "回滚到 $OLD"
    ln -sfn "$OLD" "$CURRENT"
    systemctl reload-or-restart "$SERVICE" || true
  else
    log "没有可回滚的旧版本，需要人工处理"
  fi
  exit "$code"
}

# 1. 解包到独立目录，不影响正在运行的服务
mkdir -p "$NEW"
find "$NEW" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
tar -xzf "$TARBALL" -C "$NEW"
[ -f "$NEW/server/app/main.py" ] || die 3 "发布包结构不符合预期（缺少 server/app/main.py）"
log "已解包到 $NEW"

# 2. Python 依赖：仅在 requirements.txt 变化时安装，失败则中止且不切换
LOCKFILE="$APP_ROOT/.requirements.sha256"
NEWLOCK="$(sha256sum "$NEW/server/requirements.txt" | awk '{print $1}')"
if [ ! -f "$LOCKFILE" ] || [ "$(cat "$LOCKFILE")" != "$NEWLOCK" ]; then
  log "检测到依赖变化，安装中"
  "$VENV/bin/pip" install -q -r "$NEW/server/requirements.txt" \
    || die 4 "依赖安装失败，当前版本未切换"
  echo "$NEWLOCK" > "$LOCKFILE"
  log "依赖安装完成"
else
  log "依赖未变化，跳过安装"
fi

# 3. 数据库备份：失败则中止，绝不带着未备份的库升级 schema
mkdir -p "$BACKUPS"
BACKUP_FILE="$BACKUPS/pre-$TAG-$(date +%Y%m%d%H%M%S).sql.gz"
if sudo -u postgres pg_dump "$DB_NAME" 2>/dev/null | gzip > "$BACKUP_FILE"; then
  [ -s "$BACKUP_FILE" ] || die 5 "数据库备份为空，中止发布"
  log "数据库已备份: $BACKUP_FILE"
  ls -1t "$BACKUPS"/pre-*.sql.gz 2>/dev/null | tail -n +11 | xargs -r rm -f
else
  rm -f "$BACKUP_FILE"
  die 5 "数据库备份失败，当前版本未切换"
fi

# 4. 原子切换 + 重启（此后任何失败都回滚）
trap 'rollback $?' ERR
ln -sfn "$NEW" "$CURRENT"
log "软链已切换: $CURRENT -> $NEW"
systemctl reload-or-restart "$SERVICE"

# 常驻推理服务同样从 current 运行代码，跟随切换重启；失败不阻断（API 会退回子进程实现）。
if systemctl list-unit-files 2>/dev/null | grep -q '^citrus-inference\.service'; then
  systemctl reload-or-restart citrus-inference || log "推理服务重启失败，API 将退回子进程推理"
fi

# 5. 健康检查
for i in $(seq 1 "$ATTEMPTS"); do
  if BODY="$(curl -fsS --max-time 3 "$HEALTH" 2>/dev/null)"; then
    trap - ERR
    log "健康检查通过: $BODY"
    ls -1t "$RELEASES" | grep -vx "$TAG" | tail -n +"$KEEP" | while read -r stale; do
      [ -n "$stale" ] && rm -rf "${RELEASES:?}/$stale" && log "清理旧版本: $stale"
    done
    log "发布完成: $TAG"
    exit 0
  fi
  sleep 1
done

log "健康检查连续 $ATTEMPTS 次失败"
rollback 6
