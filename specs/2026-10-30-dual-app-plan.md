# 双功能 Android App 实施计划

> 使用 superpowers:subagent-driven-development / executing-plans 按任务执行。用户已批准手机原型并授权实施。所有代码留工作区，不做 Git 写操作。

**Goal:** 实现独立数据采集与面向非专业人员的病虫害识别、处理建议、观察记录。
**Architecture:** 复用现有 Compose / Room / Retrofit / FastAPI；独立识别记录不写 samples；后台对真实模型结果做知识适用条件与置信度筛选。知识浏览和图谱不进入 App。
**Spec:** /home/pc/文档/23-胡柚病虫害视觉识别调研/citrus-prototype-dual-workflow.html，用户批准去除知识入口后的版本。
**Tech Stack:** Kotlin Compose, Room, Retrofit, FastAPI。

## 约束与裁定
- 不配置、不下载模型；未配置真实 503，不导入 demo 分类结果。
- 沿用现有登录与 collector 身份，不擅自扩展现有权限体系；普通使用者无需批次即可识别。
- 主导航：首页 / 拍照识别 / 数据采集 / 我的记录。采集照片、批次、咨询保留为二级入口。
- 采用独立 Room 识别库，按 server+username 隔离；旧采集库不破坏。
- 相机/相册导入到 App 私有文件；真实成功与失败记录保存，网络失败可重试；换账号禁止在途结果泄漏。
- 知识从管理员文件加载，要求 approved、来源、适用类别/部位/树龄；默认空，不假装正式资料已审核。
- 不自动将识别转成采集或训练标签。转入需显式同意、选择开启的批次，保留不确定初判。
- 观察日期与现场记录本地保存，不承诺系统通知。

## 共享接口
POST /api/v1/diagnoses: 与 /recognitions 相同原始图片body及 X-Image-ID，query crop_id=huyou|xiangyou|citrus, part=leaf|fruit|branch, tree_age=adult|young|unknown。
返回 {recognition:现有RecognitionOut, advice:{status,title,message,actions:[{title,detail}],sources:[{title,url}],version?:string}, receipt:string}。
状态 matched / uncertain / healthy / unmapped / conflict / unavailable。仅匹配经审核资料时有针对性 actions。
POST /api/v1/diagnoses/advice body {receipt:string} 返回 advice；凭据签名、绑定当前用户，不接受任意客户端模型类别伪造建议。

## Task 1 后台
- [x] 失败测试：未配置模型503；不建samples；低分/接近结果阻断；未审核/未映射/部位冲突无方案；篡改/跨用户凭据拒绝。
- [x] 实现 server/app/diagnosis.py 及后台知识加载、注册路由；复用识别函数，不改旧接口协议；更新OpenAPI。
- [x] 后端完整回归通过。

## Task 2 Android 数据层
- [x] 新增 DiagnosisService DTO 和独立 DiagnosisDatabase/Repository（房间/账号隔离/原图保存/错误持久化/建议重试/观察/贡献）。
- [x] 测试账号边界、服务合同、失败保留、贡献不污染原始样本；集成 AppContainer。

## Task 3 Android UI
- [x] AppNav 双入口首页及四tab；保留原采集页面二级导航。
- [x] 新识别页相机/相册、作物/部位/树龄/现象、图片同意、真实状态；结果建议、重试、显式贡献、后续观察。
- [x] 我的记录：识别历史、失败重试、观察记录及咨询/退出入口；无知识库入口。

## Task 4 集成验收
- [x] APK构建/单元测试/设备测试，真服务未配置模型失败流程和保存恢复；旧采集流程回归。
- [x] 独立评审与修复；更新README、安装同签名APK并打开。

## Review Focus
1 换账号在途请求：固定owner且落库前复核。
2 任意/伪造识别结果：后台签名receipt，默认空知识库。
3 选择相册大图/损坏文件：大小界限，后台解码，失败保留状态。
4 已关闭批次贡献：拒绝，不变更已上传原始标注。
5 重试与App重启：持久化失败、识别成功和后续观察，运行中状态可恢复为可重试。

## 验收结果（2026-10-30）
- 后端 pytest：61 passed，1 deselected（MySQL环境项），1依赖弃用warning。
- Android testDebugUnitTest：60 tests，无失败；assembleDebug / assembleDebugAndroidTest通过。
- 模拟器设备验收：7 tests通过，含实际CameraX拍照→同意上传→真实503→报告重试、失败持久化、贡献删除后重新贡献幂等、账号隔离、旧数据迁移与图片质量检查。
- 独立审查修复：删除贡献记录导航回退及失效引用、EXIF方向预览。
- 同签名覆盖安装保留旧数据；模型与后台审核资料仍未配置，真实成功识别及正式建议需接入后联调；未进行实体手机验收。
- 本轮未执行git写操作。
