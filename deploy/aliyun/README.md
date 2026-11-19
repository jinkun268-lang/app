# 阿里云生产发布

生产域名为 `api.homemanager.com.cn`，发布目标为 `47.87.69.34:22`。API、模型、Nginx 和 PostgreSQL 14 在宿主管理的 Ubuntu 环境中运行。业务路径相对于 `/opt/citrus-runtime/rootfs`。生产库名为 `citrus_app`。

## 服务端发布

工作流经原有 SSH 发布账号上传源码、构建好的管理端及 `deploy/publish.sh`。宿主机的 `/opt/citrus-app/publish.sh` 是本目录的 `publish.py`，负责衔接 Ubuntu 文件路径、宿主 systemd 和发布输入。工作流以现有 CI 密钥为上传包签名，宿主在本地验证签名及包内发布脚本。未携带签名的旧工作流使用公开仓库相应 main 历史提交的源码与已上传的前端产物，需要目标机能访问 GitHub。

Ubuntu 环境内实际运行仓库的 [原版发布脚本](../publish.sh)。它自更新为本次提交的脚本，解包至 `/opt/citrus-app/releases/<提交短号>`，依赖变化时更新共享虚拟环境，备份生产库，然后切换 `current`。重复发布正在运行的同一提交时，宿主入口先保留上一份可运行目录，用于失败回退。

发布前备份位于宿主机 `/var/backups/citrus-app/pre-*.sql.gz`，沿用 `pg_dump | gzip` 和原保留规则。私有 PATH 中的 `pg-backup-adapter.sh` 将旧机的本地管理命令映射到新机 PostgreSQL 套接字与管理账号。API 健康检查使用 `127.0.0.1:18080/api/v1/health/ready`，失败时原脚本恢复前一版本并重启 API。推理服务沿用原版发版判定，默认 2 线程。

## 网关与证书

每次发版从 `current/deploy/nginx/render.py` 生成公网 80、443 和本机 18081 三个入口。新机的 `render-gateway.sh` 通过实际 Nginx 执行 `nginx -t` 后，备份当前配置、安装候选配置并热重载 `citrus-gateway`。前端根解析到本次发布目录。旧机继续转发期间保留其可信来源地址。证书引用 `/etc/letsencrypt/live/`，以便续期钩子重载后读取新证书。

网关生成或校验失败时由原发布脚本记录错误，随后按 API 健康检查判定本次应用发布结果。已安装新配置后若 reload 失败，可使用同目录 `nginx.conf.bak-*` 排查或恢复。证书采用原 `certbot.timer` 调度及 `certbot -q renew`；成功续期后由标准 deploy hook 重载网关。

## Android 与容量

CI 直接将版本 APK 和 latest APK 上传到公开下载目录。宿主的 `/opt/citrus-app/downloads/` 指向 Ubuntu 环境内同名目录，版本文件与 latest 各自独立。[最新 APK](https://api.homemanager.com.cn/downloads/citrus-collect-latest.apk)

新机物理内存 896 MiB。PostgreSQL 当前使用 35 个连接上限、32 MiB shared buffers、2 MiB work mem 和 24 MiB maintenance work mem。数据库名、SQL 备份及应用数据使用旧机约定。

```sh
readlink /opt/citrus-runtime/rootfs/opt/citrus-app/current
systemctl is-active citrus-app citrus-inference citrus-postgresql citrus-gateway certbot.timer
curl -fsS https://api.homemanager.com.cn/api/v1/health/ready
```
