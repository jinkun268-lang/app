# 阿里云生产发布

生产域名为 `api.homemanager.com.cn`，SSH 发布目标为 `47.87.69.34:22`。服务端和 Android 工作流共用仓库的 `SSH_HOST`、`SSH_USER`（`deploy`）及 `SSH_KEY`。Android 客户端使用正式域名。旧网关保留转发时，新网关需要信任旧网关的真实来源地址。

## 服务端

宿主机 `/opt/citrus-app/publish.sh` 安装自本目录的 `publish.py`。`/usr/local/libexec/citrus-ci-ssh` 安装自 `ci-ssh.py`。这两个文件由 root 管理。发布用户的 SSH 公钥使用 OpenSSH 的 `restrict` 和固定命令，允许工作流所需的 SFTP、版本发布和 APK 发布。工作流上传的 `/tmp/publish.sh.new` 随该次上传包一并清理。修改宿主机发布程序时，管理员需从审核后的源文件重新安装。

生产运行环境位于宿主机 `/opt/citrus-runtime/rootfs`。发布程序在其中创建独立版本目录，以单独的系统账号准备发生变化的 Python 依赖，在宿主机 `/var/backups/citrus-app/` 备份实际生产库 `citrus_production`，再原子切换 `/opt/citrus-app/current`。API 与推理服务重启后，发布程序必须通过网关读到就绪接口，并确认推理套接字已加载分类及检测模型。失败时恢复之前的版本及其 Python 环境。

网关直接从 `current/admin/dist` 提供前端。TLS、可信转发来源及限流配置位于运行环境的 `/var/lib/citrus-gateway/nginx.conf`，由宿主管理员维护。重复发布同一提交会构建独立目录，保留可回退版本。脚本保留最近五个自动发布目录，保留当前版本及前一版本，生产库的发布前备份保留最近十份。

## Android

工作流上传版本 APK 及 latest APK 到宿主机的 `/opt/citrus-app/downloads/` 暂存目录。现有工作流随后通过 SSH 查看下载目录。受限 SSH 入口在此步骤检查版本包的 Android 清单和 dex 条目并原子更新公开文件。两个下载名使用同一个已完成的版本包。正式下载入口为 [最新 APK](https://api.homemanager.com.cn/downloads/citrus-collect-latest.apk)。

## 现场核对

以下命令在新机宿主运行。

```sh
readlink /opt/citrus-runtime/rootfs/opt/citrus-app/current
systemctl is-active citrus-app citrus-inference citrus-postgresql citrus-gateway
curl -fsS https://api.homemanager.com.cn/api/v1/health/ready
```
