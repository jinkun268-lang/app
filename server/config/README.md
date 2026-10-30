# 诊断建议知识配置

默认不加载知识，不附带正式病虫害资料。`diagnosis-knowledge.json` 是空配置。模型仍须独立配置；模型未配置返回 503，绝不产生演示识别。

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

仅 Top1 ≥ 0.80 且与第二名分差 ≥ 0.20 时进入知识匹配。这是模型尚未校准时的保守门槛，不代表准确率承诺。模型 scope 必须等于所选 part。未映射、未审核不输出动作；适用条件不符或同一条件有多条资料返回 conflict；健康只来自已审核 healthy 条目，不依据模型显示名猜测。

## API

- `POST /api/v1/diagnoses`：collector 认证；原始 JPEG/PNG/WebP body、X-Image-ID UUIDv7。query crop_id 默认 huyou、part 默认 leaf、tree_age 默认 unknown。图片上限20MiB/2400万像素，与旧 recognition 共用单并发和推理。返回 `{recognition, advice, receipt}`；不创建 samples。
- `POST /api/v1/diagnoses/advice`：collector 认证；JSON `{receipt}`。返回 advice 本身，重新读取当前知识，不再次推理。不能传入自选类别或上下文。
- advice 包含 status（matched/uncertain/healthy/unmapped/conflict/unavailable）、title、message、actions（title/detail）、sources（title/url）、version（字符串或 null）。只有 matched 有针对性动作。
- receipt 为 HMAC-SHA256 签名、不加密的凭据，绑定 user_id、完整识别结果和作物/部位/树龄，30天过期。不要作为公开分享链接。篡改/过期返回422 INVALID_RECEIPT，其他账号使用返回403 RECEIPT_FORBIDDEN；注销/停用仍受现有认证控制。
- `APP_DIAGNOSIS_SECRET` 可指定至少32字节的强随机秘密。未指定时在私有 files 目录生成 diagnosis-secret（0600），重启复用。多进程部署应预先生成或设置统一 secret；多节点必须使用统一 secret。轮换或丢失密钥会使旧凭据失效，需重新识别。备份时保护该文件。

配置只表示本地管理员审核状态，不构成来源内容真实性的自动认证；正式投放前需完成专业审校与真实模型验证。
