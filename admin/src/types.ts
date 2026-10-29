// 类型单一来源：`src/api/generated/schema.d.ts`（由 openapi-typescript 从 contracts/openapi.yaml 生成，禁止手改）。
// 本文件仅做便捷重导出与少量客户端侧补充，不定义业务字段，避免页面各自发明字段。
import type { components } from './api/generated/schema'

export type Schemas = components['schemas']

// 身份与配置
export type Role = Schemas['Role']
export type AdminRole = Schemas['AdminRole']
export type AuthUser = Schemas['AuthUser']
export type LoginRequest = Schemas['LoginRequest']
export type LoginResponse = Schemas['LoginResponse']
export type RefreshRequest = Schemas['RefreshRequest']
export type RefreshResponse = Schemas['RefreshResponse']
export type MeResponse = Schemas['MeResponse']
export type BootstrapResponse = Schemas['BootstrapResponse']
export type ErrorResponse = Schemas['ErrorResponse']

// 枚举
export type ReviewStatus = Schemas['ReviewStatus']
export type QualityStatus = Schemas['QualityStatus']
export type QualityReasonCode = Schemas['QualityReasonCode']
export type ViewType = Schemas['ViewType']
export type Part = Schemas['Part']
export type UploadState = Schemas['UploadState']
export type ExportStatus = Schemas['ExportStatus']
export type QuestionStatus = Schemas['QuestionStatus']
export type TicketStatus = Schemas['TicketStatus']
export type TicketOutcome = Schemas['TicketOutcome']

// 样本
export type SampleSummary = Schemas['SampleSummary']
export type SampleSummaryPage = Schemas['SampleSummaryPage']
export type SampleDetail = Schemas['SampleDetail']
export type SampleImage = Schemas['SampleImage']
export type SampleReviewEvent = Schemas['SampleReviewEvent']
export type ImageQualityEvent = Schemas['ImageQualityEvent']
export type SampleReviewRequest = Schemas['SampleReviewRequest']
export type ImageQualityRequest = Schemas['ImageQualityRequest']
export type ExcludeRequest = Schemas['ExcludeRequest']
export type RestoreRequest = Schemas['RestoreRequest']
export type MediaPendingResponse = Schemas['MediaPendingResponse']

// 采集上传（四步协议：声明→逐图字节→查缺图→完成；字段定义见 OpenAPI，勿在此另写字段）
export type UploadDeclareRequest = Schemas['UploadDeclareRequest']
export type UploadDeclaredImage = Schemas['UploadDeclaredImage']
export type UploadStatus = Schemas['UploadStatus']
export type UploadImageReceipt = Schemas['UploadImageReceipt']
export type UploadCompleteResponse = Schemas['UploadCompleteResponse']

// 导出
export type ExportJob = Schemas['ExportJob']
export type ExportJobPage = Schemas['ExportJobPage']
export type ExportFilters = Schemas['ExportFilters']
export type ExportCreateRequest = Schemas['ExportCreateRequest']

// 字典
export type Cultivar = Schemas['Cultivar']
export type ClassEntry = Schemas['Class']
export type CultivarCreateRequest = Schemas['CultivarCreateRequest']
export type CultivarPatchRequest = Schemas['CultivarPatchRequest']
export type ClassCreateRequest = Schemas['ClassCreateRequest']
export type ClassPatchRequest = Schemas['ClassPatchRequest']
export type ClassImportPreviewResponse = Schemas['ClassImportPreviewResponse']
export type ClassImportConfirmRequest = Schemas['ClassImportConfirmRequest']
export type ClassImportResult = Schemas['ClassImportResult']

// 账号与审计
export type UserRow = Schemas['User']
export type UserPage = Schemas['UserPage']
export type UserCreateRequest = Schemas['UserCreateRequest']
export type UserCreateResponse = Schemas['UserCreateResponse']
export type UserPatchRequest = Schemas['UserPatchRequest']
export type ResetPasswordResponse = Schemas['ResetPasswordResponse']
export type AuditRow = Schemas['AuditRow']
export type AuditPage = Schemas['AuditPage']

// 专家工单（F2）
export type TicketSummary = Schemas['TicketSummary']
export type TicketSummaryPage = Schemas['TicketSummaryPage']
export type TicketDetail = Schemas['TicketDetail']
export type TicketEvent = Schemas['TicketEvent']
export type TicketActionRequest = Schemas['TicketActionRequest']
export type TicketDraftRequest = Schemas['TicketDraftRequest']
export type TicketRequestInfoRequest = Schemas['TicketRequestInfoRequest']
export type TicketAnswerRequest = Schemas['TicketAnswerRequest']
export type TicketUnresolveRequest = Schemas['TicketUnresolveRequest']

// 通用列表
export interface Page<T> {
  items: T[]
  page: number
  page_size: number
  total: number
}

// 同步采集批次与真实专家咨询
export type Batch = Schemas['Batch']
export type BatchPage = Schemas['BatchPage']
export type CollectionQuestion = Schemas['CollectionQuestion']
export type CollectionQuestionPage = Schemas['CollectionQuestionPage']
