# 诊断建议知识配置

未设置 `APP_DIAGNOSIS_KNOWLEDGE` 时，默认按现有叶片五分类模型的 Top1 标签返回固定基础建议，无需接入问答模型或补齐后台类别字典。回复沿用现有 `advice` 结构，Android 可直接展示；版本为 `basic-2026-11-03`。文案位于 `server/app/basic_advice.py`。

| 模型标签 | 回复标题 | status |
| --- | --- | --- |
| black_spot | 黑斑病基础建议 | matched |
| canker | 溃疡病基础建议 | matched |
| greening | 黄龙病基础建议 | matched |
| melanose | 黑点病基础建议 | matched |
| healthy | 健康养护建议 | healthy |

固定建议仅适用于胡柚、香柚及其他柑橘的叶片，树龄可为 adult / young / unknown；四类病害各返回三条基础管理建议和参考来源，健康的养护建议放在 message 中，actions 为空。资料参考农业农村部、省农业农村厅及 UF/IFAS 的公开指导，未经过本项目专业人工审校；不包含具体药剂、剂量或疗效承诺。黄龙病提示先联系农技人员检测确认。它们不是问答模型生成的个体化方案。

模型仍须独立配置；模型未配置返回 503。固定建议按服务端真实识别标签匹配，不按图片文件名、图片指纹或显示病名强制指定结果。未知标签返回 unmapped，低置信度返回 uncertain，部位不符返回 conflict，均不返回处理动作。沿用 Top1 ≥ 0.80 且与第二名分差 ≥ 0.20 的门槛。同一已成功图片的重复请求、历史快照读取和签名凭据获取建议使用相同规则，不重复推理；识别失败后的重试仍会调用模型。

## 自定义已审核资料

`diagnosis-knowledge.json` 继续保留为空的自定义配置模板。显式设置 `APP_DIAGNOSIS_KNOWLEDGE` 后，以指定文件中的已审核资料替代内置基础建议；文件缺失、为空或无效时不会回退到固定建议。

管理员可将 `APP_DIAGNOSIS_KNOWLEDGE` 指向 UTF-8 JSON 文件，服务每次查询重新读取，支持识别成功后仅重试建议。建议采用临时文件写完后原子替换，大小上限 2 MiB。缺失、空条目、非法字段或无法解析均返回 `unavailable`，不会输出处理动作。来源使用 HTTP/HTTPS URL，仅展示而不由服务访问。

格式：根对象必须有 `version`（非空字符串）和 `entries`（数组），不允许未知字段。每条记录要求：

| 字段 | 规则 |
| --- | --- |
| class_id | 已映射且当前仍启用的后台类别 ID |
| approved | 严格布尔值，仅 true 能匹配；审核流程由管理员负责 |
| crop_ids | 非空数组，huyou / xiangyou / citrus；精确匹配，citrus 不是通配符 |
| parts | 非空数组，leaf / fruit / branch |
| tree_ages | 非空数组，adult / young / unknown；unknown 仅匹配明确包含 unknown 的资料 |
| kind | condition（默认）或 healthy；健康条目始终不返回 actions |
| title / message | 非空标题与说明 |
| actions | 数组，每项非空 title / detail；最多20项 |
| sources | 至少1项，非空 title 与 HTTP/HTTPS url；最多20项 |

自定义资料同样要求 Top1 ≥ 0.80 且与第二名分差 ≥ 0.20。这是模型尚未校准时的保守门槛，不代表准确率承诺。模型 scope 必须等于所选 part。未映射、未审核不输出动作；适用条件不符或同一条件有多条资料返回 conflict；健康只来自已审核 healthy 条目，不依据模型显示名猜测。

## API

- `POST /api/v1/diagnoses`：collector认证，X-Image-ID UUIDv7，JPEG／PNG／WebP原图body；沿用crop_id／part／tree_age query。完整校验后先提交默认识别记录并保存原图，再调用现有模型，成功直接更新结果，失败保留默认结果和原因；不创建samples。返回`{recognition, advice, receipt}`，模型失败仍返回对应错误状态，但图片和识别记录已保留。无需客户端回传结果入库。
- `PUT /api/v1/diagnoses/{record_id}`：上传前提交图片SHA／大小、作物／部位／树龄、现象与拍摄时间。`GET`同一路径可读取本人记录状态和已完成结果，失败／识别中result为null。
- `POST /api/v1/diagnoses/advice`：collector 认证；JSON `{receipt}`。返回 advice 本身，重新读取当前知识，不再次推理。不能传入自选类别或上下文。
- advice 包含 status（matched/uncertain/healthy/unmapped/conflict/unavailable）、title、message、actions（title/detail）、sources（title/url）、version（字符串或 null）。只有 matched 有针对性动作。
- receipt 为 HMAC-SHA256 签名、不加密的凭据，绑定 user_id、完整识别结果和作物/部位/树龄，30天过期。不要作为公开分享链接。篡改/过期返回422 INVALID_RECEIPT，其他账号使用返回403 RECEIPT_FORBIDDEN；注销/停用仍受现有认证控制。
- `APP_DIAGNOSIS_SECRET` 可指定至少32字节的强随机秘密。未指定时在私有 files 目录生成 diagnosis-secret（0600），重启复用。多进程部署应预先生成或设置统一 secret；多节点必须使用统一 secret。轮换或丢失密钥会使旧凭据失效，需重新识别。备份时保护该文件。

配置只表示本地管理员审核状态，不构成来源内容真实性的自动认证；正式投放前需完成专业审校与真实模型验证。
