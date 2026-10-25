# 柑橘图像采集与数据管理

Android 采集、Web 专业核验和训练数据准备，共用 FastAPI 服务。

| 目录 | 内容 |
| --- | --- |
| `android/` | Kotlin、CameraX、Room 采集客户端 |
| `admin/` | Vue 3、TypeScript 管理端 |
| `server/` | FastAPI、元数据与文件适配、测试和数据库DDL |
| `contracts/` | OpenAPI、枚举、JSON Schema和测试夹具 |
| `deploy/` | PostgreSQL配置示例与Nginx配置生成器 |
| `tools/` | 通用启动、网关及契约工具 |

## 本地启动

需要 Python 3.10+、Node.js 20+；Android构建需要JDK17和Android SDK35。

在项目根目录执行（PowerShell）：

```powershell
python -m venv server/.venv
./server/.venv/Scripts/python.exe -m pip install -r server/requirements.txt
npm --prefix admin ci
./tools/run-app.ps1
```

访问 `http://127.0.0.1:8000`。开发默认SQLite，数据保存在`.runtime/`。首次空库会创建演示账号`super`、`admin`、`expert`、`collector1`、`collector2`，演示密码均为`12345678`；它们仅用于本地开发。

也可分别启动API和前端热更新：

```powershell
./server/.venv/Scripts/python.exe -m uvicorn server.app.main:app --host 127.0.0.1 --port 8000
npm --prefix admin run dev
```

Linux/macOS使用`server/.venv/bin/python`替代Windows Python路径；`npm --prefix admin run build`后API可同源提供管理页面。管理端默认连接真实API，显式设置`VITE_ENABLE_MOCK=true`才启用模拟。

## 配置与职责

PostgreSQL部署使用受支持版本（已兼容17），参考`deploy/.env.postgres.example`。把配置放在不提交的本地文件，再执行`./tools/run-app.ps1 -ConfigFile <配置路径>`；Linux使用进程环境变量。生产须设置`APP_SEED_DEMO=false`和私有初始密码。

- collector：声明、逐图上传、缺图补传，以及本人采集记录只读。
- expert：专业核验；admin：训练图片质量、排除／恢复、导出；super_admin：跨区及账号管理。
- 元数据通过`MetadataStorage/DataTransaction`访问，图片和ZIP通过`FileStorage`访问；数据库中不保存图片字节。
- 默认单API进程：上传最多4个在途请求；导出同时1批、每账号每分钟6批、最多5000图／候选样本、ZIP不超过1GiB。满额429、超范围413；异常重启后可按原快照重试导出。
- 生产使用Nginx等HTTPS入口，API／数据库保持私网或回环；网关生成器入口为`python deploy/nginx/render.py --help`。

Android用Android Studio打开`android/`，配置本机SDK后构建；模拟器访问宿主机API通常使用`http://10.0.2.2:8000/api/v1/`。实体设备需使用可达的HTTPS服务地址。

## 检查

```powershell
$env:APP_DATABASE_URL='memory'
./server/.venv/Scripts/python.exe -m pytest server/tests -q -k 'not mysql'
npm --prefix admin run typecheck
npm --prefix admin test
npm --prefix admin run build
./android/gradlew.bat -p android :app:testDebugUnitTest :app:assembleDebug
```

接口变更同步`contracts/openapi.yaml`及相关测试，再运行`npm --prefix admin run generate:types`。DDL基线由`python tools/export-schema.py`生成；切换数据库URL不会自动搬迁数据。运行数据、凭据和本机路径配置不得提交。
