# 阿里云生产部署

生产域名为 `api.homemanager.com.cn`，GitHub Actions 通过 `deploy@47.87.69.34:22` 发布。工作流沿用旧机的 SSH/SCP 命令，上传实际构建的源码包、前端和发布脚本。APK 工作流直接写公开下载目录。部署公钥和家目录采用旧机的普通 SSH 配置。

## 发版

宿主机 `/opt/citrus-app/publish.sh` 安装自本目录的 `publish.py`，在 `/opt/citrus-runtime/rootfs` 的 Ubuntu 环境中调用仓库[原版发布脚本](../publish.sh)。该脚本自更新，解包到 `releases/<tag>`，使用共享 Python 环境，执行 SQL gzip 备份，再切换 `current`。发布失败时按旧机的 API 健康检查判定回滚。重复发布同一提交时，原脚本复用同一目录，不单独生成重试快照。

普通发布直接处理上传包，支持仓库内的相对链接。宿主适配器隔离每次发布的临时目录，并保留对高权限操作的来源核对：当上传的发布器、网关渲染程序与已确认的版本不同，或原脚本将安装 Python 依赖时，需由生产仓库中的相应提交确认。此分支会从 GitHub 获取可信源码，同时使用 CI 上传的前端。普通业务代码更新无整包签名步骤，无需新机下载源码。

生产库是 `citrus_app`，原发版脚本的本地数据库管理调用经 `pg-backup-adapter.sh` 使用新机的管理账号与套接字。发布前备份在宿主 `/var/backups/citrus-app/pre-*.sql.gz`。应用和数据库使用同一台服务器的回环地址，并按客户端默认协商 TLS。

## 网关与数据库

发版使用 `current/deploy/nginx/render.py` 生成公网 80、443 和本机 18081 入口，执行生产 Nginx 校验、备份、替换及热重载。和旧机一样，生成的前端根和证书路径解析为当时的具体版本。Certbot 沿用原定时器与续期后 reload 钩子；如果续期创建了新的证书版本文件，需要再次生成配置才能选择新版本。旧机保持转发期间，新网关信任旧机这个上游传来的客户端地址。

PostgreSQL 14 使用 Ubuntu 的 `pg_ctlcluster` 控制程序，以 `forking` 模式等待数据库启动，使用 fast 模式停库，关闭等待上限 1 小时，systemd 不自动重启故障进程。宿主使用本目录的 `citrus-postgresql.service`，Ubuntu 集群配置为 `/etc/postgresql/14/main/postgresql.conf`（本目录同名配置）。数据目录、管理账号保留新机映射。回环 TCP 及标准 Unix 套接字可用，同时兼容迁移时已使用的套接字。PostgreSQL 采用本机的本地 TLS 证书，日志为 `/var/log/postgresql/postgresql-14-main.log`，按周 copytruncate 轮转，保留 10 份。

新机为 896 MiB 内存，PostgreSQL 的容量设置为最多 35 个连接、32 MiB shared buffers、2 MiB work mem 和 24 MiB maintenance work mem。模型沿用旧命令的默认 2 线程。数据库时区保持原先约定。

```sh
readlink /opt/citrus-runtime/rootfs/opt/citrus-app/current
systemctl is-active citrus-app citrus-inference citrus-postgresql citrus-gateway certbot.timer
curl -fsS https://api.homemanager.com.cn/api/v1/health/ready
```
