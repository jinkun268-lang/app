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

## 单张识别

Android 照片缩略图下的“识别此图”连接 `POST /api/v1/recognitions`，返回真实模型候选并保存在该图片的本地记录中。结果不会自动更改类别，需点击“采用结果”；旧的多图记录会只把选中图片单独成条，其他图片不改。已开始上传的记录不能重新识别或采用结果，已保存结果可以只读查看。重拍会清除旧识别结果。Room 2→3 的迁移仅新增图片识别结果字段。

未配置模型时接口返回503，不使用模拟结果。配置 `APP_RECOGNITION_PYTHON` 为已安装 PyTorch/torchvision 的独立 Python，`APP_RECOGNITION_MANIFEST` 为模型清单的绝对路径；主 API 环境不需要安装 PyTorch。清单示例见 [deploy/recognition.example.json](deploy/recognition.example.json)，`weights` 替换为本机训练权重路径，类别顺序必须与训练时一致。当前 worker 支持 torchvision EfficientNet-B0 的 state_dict，用 `weights_only=True` 加载、不下载预训练权重，使用2个CPU线程。

当前接入的是实验性叶片五分类模型，仅供人工复核，不用于果实或虫体。分数不是诊断确定性；无法映射到现有启用字典的类别，采用时使用“不确定”，原始模型建议仍保留。接口只接受采集账号，单图最多20MiB、2400万像素，单并发、推理超时45秒；临时图片在推理结束后清除，不自动加入训练集。

识别前会先跑一次本地 YOLO 检测（SciDB 15 类，`mAP50 0.964`）判断画面里有没有叶片：没有检出叶片类目标时直接返回 `422 NO_LEAF`，不再让闭集分类器强行给类别；检出叶片时按最大叶片框裁剪，再交给五分类模型。检测器不可用时自动退化为纯分类，不阻断主链路。权重与 Python 环境写在 `server/config/detector.json`（指向本机已训练的 YOLO11n），不下载模型；分类模型的 manifest 仍由 `APP_RECOGNITION_MANIFEST` / `APP_RECOGNITION_PYTHON` 提供。

## 采集记录粒度

Android 端一张照片就是一条采集记录：每次按下快门立即创建独立记录，品种、部位、类别、症状、备注和识别结果都只属于这一张图片；编辑、上传、撤回也按单条记录进行，互不影响。拍摄页只维护本次会话的缩略图用于跳转，不写入数据库，也不引入批次、批量上传或记录合并。旧版本留下的多图记录仍可打开、上传和撤回，界面会标注它们共用同一条信息，新拍的照片不会追加进去。
