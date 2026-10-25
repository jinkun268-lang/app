import { ApiError } from '../api/http'

// 错误信息按 code 分支展示；未知码附带 request_id 便于定位。
const CODE_TEXT: Record<string, string> = {
  AUTH_REQUIRED: '未登录或登录已失效',
  AUTH_INVALID: '账号或密码错误，或登录已过期',
  ACCOUNT_DISABLED: '账号已停用',
  FORBIDDEN: '无权限执行该操作',
  NOT_FOUND: '对象不存在或不可见',
  VALIDATION_FAILED: '提交内容校验失败',
  STATE_CONFLICT: '当前状态不允许该操作',
  VERSION_CONFLICT: '数据已被他人更新，请刷新后重试',
  IDEMPOTENCY_CONFLICT: '重复请求内容不一致，请重试',
  FILE_MISMATCH: '文件内容校验不一致',
  MISSING_IMAGES: '仍有图片未上传完成',
  RATE_LIMITED: '操作过于频繁，请稍后重试',
  UNAVAILABLE: '服务暂不可用，请稍后重试',
  INTERNAL: '服务内部错误',
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    const base = CODE_TEXT[err.code] ?? err.message ?? '请求失败'
    if (CODE_TEXT[err.code]) return base
    return err.requestId ? `${base}（${err.requestId}）` : base
  }
  if (err instanceof DOMException && err.name === 'AbortError') return '请求已取消'
  if (err instanceof TypeError || (err as Error)?.message === 'Failed to fetch') return '网络错误，请检查连接后重试'
  if (err instanceof Error) return err.message
  return '发生未知错误'
}

export function isVersionConflict(err: unknown): boolean {
  return err instanceof ApiError && err.code === 'VERSION_CONFLICT'
}
