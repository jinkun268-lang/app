# 采集端功能闭环设计与执行计划

> For agentic workers: use superpowers:subagent-driven-development. 用户已授权全部非模型功能；不执行任何 Git 写操作。

## 目标和约束
沿用 Kotlin/Compose/Room、FastAPI/SQLAlchemy、Vue。完成账号隔离、可靠后台批量上传、批次跨设备同步、审核反馈、质量提醒/GPS、图文咨询及说明。模型不部署、不下载、不伪造结果，不擅自编造正式病害目录。旧数据无损迁移，历史无主数据隔离保留。仅工作区修改，不提交。

## 共同接口
- PUT /api/v1/batches/{batch_id}: {name,place,collector,default_cultivar_id,note,closed,created_at?}; 响应为上述字段加 batch_id, owner_id, updated_at。collector 只能改自己的，expert/admin/super_admin 可查看授权范围，跨账号不能读取。
- GET /api/v1/batches: {items:[batch],total,page,page_size}，分页1起。
- 上传声明新增可选 batch_id, latitude, longitude, location_accuracy_m；批次先同步再上传。兼容旧声明；服务端核对批次归属；审核列表/详情/导出暴露批次快照和位置信息。
- GET /api/v1/samples/{id}: 复用现有审核详情；Android保存/展示 review_status, final_class_name, review_note, reviewed_at 与图片质量信息，刷新不改原始采集标注。
- POST /api/v1/questions: {question_id, text, sample_id?}；可关联本人已上传记录，服务端从记录图片构建图文详情；幂等同ID同内容，异内容409。
- GET /api/v1/questions: {items:[question],total,page,page_size}；collector仅本人，expert/super_admin可读待答及历史。
- GET /api/v1/questions/{id}: question_id,text,sample_id,status(open/answered),answer,owner_id,created_at,answered_at, images（可复用现有鉴权图片URL），sample相关展示信息。
- PATCH /api/v1/questions/{id}/answer: {answer}；仅expert/super_admin；持久化真实答复。
- 所有新增接口进入 contracts/openapi.yaml 并生成前端类型。

## 任务和归属
- [x] A 后端：迁移/存储适配、批次API、采集元数据、咨询API、审核/导出字段、跨账号权限和持久化测试。归属 server/ 和 contracts/（Python服务端agent）。
- [x] B Android数据：账号隔离、旧数据隔离提示、后台WorkManager队列/网络自动重试/批量入队、批次同步、审核反馈缓存和咨询DTO/API。归属 Android data/network/CitrusApplication.kt 与Gradle依赖（Android数据agent）。
- [x] C 界面：批量上传与状态、批次编辑/关闭/同步、审核反馈、咨询提交/查看/回答的Android与Web入口、管理端批次筛选和展示。归属 Android ui（CaptureScreen除外）与 admin/（界面agent）。
- [x] D 采集质量与定位：相机拍后本地模糊/过曝/欠曝提醒，保留图片、可确认继续；显式可选定位与拒绝兜底、不阻断拍摄；批次地点手填仍可用。归属 CaptureScreen.kt、新quality/location模块、Manifest、相关测试（主agent）。
- [x] E 集成：接口类型、完整测试、Android构建、SQLite旧库迁移、模拟器登录与关键流程，README和可安装APK（主agent）。

## 行为细节与验收
账号维度同时包含服务器和用户；切换账号后查询/编辑/上传/后台任务均不得访问其他分区；旧无主记录保留并明确提示，不自动归属。
Worker持久化队列、每条唯一任务；联网执行、仅网络/服务暂不可用重试，校验错误展示失败；登出/切换账号不能借新凭据传旧任务，任务内容固定账号且同账号恢复后可重试。
批次可编辑、关闭/重开；关闭批次不可新增拍摄；同步失败保留本地；云端分页完整拉取，服务端归属强校验。
咨询由人答复，无模拟回答；附件仅允许用户本人已上传样本，图片访问继承权限；弱网保留输入，不假称已提交。
质量启发式仅是拍摄建议，不作为诊断或强制删除；定位需权限、可跳过，缺失不伪造0,0，不上传过期定位。
覆盖跨账号ID直接访问、任务执行时会话变化、旧库升级、同ID请求重试、分页、断网/权限拒绝等情形。

## 验证命令
server/.venv/bin/python -m pytest server/tests -q -k 'not mysql'
npm --prefix admin run typecheck && npm --prefix admin test && npm --prefix admin run build
GRADLE_USER_HOME=../work/gradle ANDROID_HOME=../work/android-sdk bash android/gradlew -p android :app:testDebugUnitTest :app:assembleDebug :app:compileDebugAndroidTestKotlin


## 验收结果
- 后端 43 passed，1 deselected（需要MySQL实库）；Memory/SQLite与真实旧库迁移通过。
- Android JVM 53 tests passed；APK与设备测试包构建通过。
- Android模拟器4项隔离/队列/2→5迁移/实际JPEG检查通过。
- Android→真实FastAPI服务1项完整链路通过：新建批次→拍摄测试图片→关闭批次→WorkManager上传→审核缓存→关联图片咨询→幂等提交→专家真实答复→采集端读取。
- Web typecheck、53项测试、生产build通过。
- 独立审查发现的识别期间换账号、导航局部状态保留、关闭离线批次拒收照片三项已修复并复核。
- 旧无主照片保留且不自动归属；正式病害目录需管理员维护；模型保持未部署。质量阈值尚需实际相机校准，未连接MySQL/PostgreSQL实库。
- 本地SQLite升级前备份在工作目录中间文件；APK沿用原调试签名，无损升级已安装版本。
