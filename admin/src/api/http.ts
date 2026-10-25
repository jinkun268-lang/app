// 统一 HTTP 客户端：模拟与真实请求走同一套请求/响应/错误解析，生产构建不启用模拟，
// 请求失败不回退为演示数据。业务页通过各域 api 模块调用本客户端，不得自行拼 URL 或维护第二套字段。
//
// - 基础路径 /api/v1（开发与生产均同源 /api 转发）
// - 注入 Bearer、X-Client-Version、X-Request-Id、可选 Idempotency-Key
// - 错误统一解析为 ApiError（code/message/details/request_id/status）
// - 401 expired 仅触发一次共享刷新，各请求等待后最多重放一次；刷新失败不递归
// - 迟到的旧 401（令牌已被并发刷新轮换）直接复用当前令牌，不再次刷新
// - 会话切换（登录/退出/换账号）后，旧会话在途请求不刷新、不重放、不清理新会话
// - 刷新区分永久失效与临时故障：网络异常、429、5xx、无效成功响应保留会话并向调用者报错
// - 永久认证拒绝（AUTH_INVALID、ACCOUNT_DISABLED、重放后再拒）统一终结会话；普通 403 不清理
// - 预期 JSON 的成功响应收到 HTML/非法 JSON 时抛结构化 ApiError
// - 支持 JSON、FormData、Blob/二进制、204、非 JSON 错误体
import { getAccessToken, getRefreshToken, setTokens, clearTokens, emitUnauthorized, getSessionEpoch } from '../auth/tokens'
import { isMockEnabled, mockDispatch } from '../mocks'
import { uuidv7 } from '../util/uuid'
import type { ErrorResponse } from '../types'

const BASE = '/api/v1'
const CLIENT_VERSION = 'admin/1.0.0'

export class ApiError extends Error {
  status: number
  code: string
  details: Record<string, unknown> | undefined
  requestId: string | undefined

  constructor(status: number, code: string, message: string, requestId?: string, details?: Record<string, unknown>) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
    this.requestId = requestId
  }
}

export interface RawResponse {
  status: number
  headers: Record<string, string>
  body: string | Blob | null
}

export interface RequestOptions {
  path: string
  method?: 'GET' | 'POST' | 'PATCH' | 'PUT' | 'DELETE'
  query?: Record<string, string | number | boolean | undefined | null>
  body?: unknown
  form?: FormData
  headers?: Record<string, string>
  signal?: AbortSignal
  responseType?: 'json' | 'blob' | 'none'
  skipAuth?: boolean
  idempotencyKey?: string
}

type ErrorPayload = ErrorResponse | null

function buildUrl(path: string, query?: RequestOptions['query']): string {
  const url = new URL(BASE + path, 'http://local')
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v === undefined || v === null || v === '') continue
      url.searchParams.set(k, String(v))
    }
  }
  return url.pathname + url.search
}

function parseErrorPayload(res: RawResponse): ErrorPayload {
  if (typeof res.body !== 'string' || res.body === '') return null
  try {
    return JSON.parse(res.body) as ErrorResponse
  } catch {
    return null
  }
}

function bodyToApiError(status: number, res: RawResponse): ApiError {
  const payload = parseErrorPayload(res)
  if (payload && payload.error) {
    return new ApiError(status, payload.error.code, payload.error.message, payload.error.request_id || res.headers['x-request-id'], payload.error.details)
  }
  return new ApiError(status, 'INTERNAL', `请求失败（HTTP ${status}）`, res.headers['x-request-id'])
}

function isExpiredAuth(status: number, res: RawResponse): boolean {
  if (status !== 401) return false
  const payload = parseErrorPayload(res)
  return payload?.error?.code === 'AUTH_INVALID' && (payload.error.details as { reason?: string } | undefined)?.reason === 'expired'
}

// 永久认证拒绝：401 AUTH_INVALID（到达该判断时刷新恢复已尝试或不可用，含重放后再拒）
// 与 403 ACCOUNT_DISABLED。普通权限 403（FORBIDDEN）不终结会话。
function isTerminalAuthRejection(status: number, res: RawResponse): boolean {
  const payload = parseErrorPayload(res)
  const code = payload?.error?.code
  if (status === 401) return code === 'AUTH_INVALID'
  if (status === 403) return code === 'ACCOUNT_DISABLED'
  return false
}

// 将临时刷新故障转为合成错误响应（沿用服务端错误码语义），让 request/requestRaw 统一按 ApiError 抛出。
function apiErrorToRawResponse(err: ApiError): RawResponse {
  return {
    status: err.status,
    headers: err.requestId ? { 'x-request-id': err.requestId } : {},
    body: JSON.stringify({ error: { code: err.code, message: err.message, request_id: err.requestId } }),
  }
}

interface DispatchInput {
  method: string
  url: string
  headers: Record<string, string>
  body?: string | FormData | null
  signal?: AbortSignal
}

async function dispatch(input: DispatchInput): Promise<RawResponse> {
  if (isMockEnabled()) {
    return mockDispatch({
      method: input.method,
      path: input.url,
      headers: input.headers,
      body: input.body,
    })
  }
  const res = await fetch(input.url, {
    method: input.method,
    headers: input.headers,
    body: (input.body as BodyInit | null) ?? undefined,
    signal: input.signal,
    credentials: 'same-origin',
  })
  const contentType = res.headers.get('content-type') || ''
  const isBinary = !/application\/(json|problem\+json)|text\//.test(contentType)
  const headers: Record<string, string> = {}
  res.headers.forEach((v, k) => {
    headers[k.toLowerCase()] = v
  })
  const body = isBinary ? await res.blob() : await res.text()
  return { status: res.status, headers, body }
}

// 401 刷新共享任务：同一会话（代际）内并发 401 只刷新一次，其余请求等待；
// 不同会话各自持有刷新任务，互不共用。
// 刷新结果分三类：ok 已换新令牌（或会话已切换、结果不适用）；
// invalid 刷新令牌缺失/被服务端拒绝（401），会话永久失效；
// temporary 网络异常、429、5xx、无效成功响应，属临时故障，保留会话与刷新令牌。
type RefreshOutcome =
  | { kind: 'ok' }
  | { kind: 'invalid' }
  | { kind: 'temporary'; error: ApiError }

interface RefreshTask {
  epoch: number
  promise: Promise<RefreshOutcome>
}
let refreshTask: RefreshTask | null = null

async function doRefresh(epoch: number): Promise<RefreshOutcome> {
  const refreshToken = getRefreshToken()
  if (!refreshToken) return { kind: 'invalid' }
  let res: RawResponse
  try {
    res = await dispatch({
      method: 'POST',
      url: BASE + '/auth/refresh',
      headers: {
        'content-type': 'application/json',
        'x-client-version': CLIENT_VERSION,
        'x-request-id': uuidv7(),
      },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
  } catch {
    // 网络异常属临时故障：保留会话与刷新令牌，仅向调用者报错
    return { kind: 'temporary', error: new ApiError(503, 'UNAVAILABLE', '网络异常，无法刷新会话') }
  }
  if (res.status === 200) {
    let parsed: unknown
    try {
      parsed = JSON.parse(res.body as string)
    } catch {
      // 200 但非 JSON（如网关 HTML 页）：按临时故障处理
      return { kind: 'temporary', error: new ApiError(502, 'INTERNAL', '刷新响应不是有效的 JSON') }
    }
    const data = parsed as { access_token?: unknown; refresh_token?: unknown } | null
    if (!data || typeof data.access_token !== 'string' || data.access_token.trim() === '' || typeof data.refresh_token !== 'string' || data.refresh_token.trim() === '') {
      // 成功状态但令牌字段缺失/为空：不覆盖原有令牌，按临时故障处理
      return { kind: 'temporary', error: new ApiError(502, 'INTERNAL', '刷新响应缺少有效令牌') }
    }
    // 刷新期间会话已切换（退出/换账号）：丢弃旧会话结果，不得覆盖新会话令牌
    if (getSessionEpoch() !== epoch) return { kind: 'ok' }
    setTokens(data.access_token, data.refresh_token)
    return { kind: 'ok' }
  }
  if (res.status === 401 || isTerminalAuthRejection(res.status, res)) return { kind: 'invalid' }
  // 429、5xx 等：临时故障，透出服务端错误语义
  return { kind: 'temporary', error: bodyToApiError(res.status, res) }
}

function refreshOnce(epoch: number): Promise<RefreshOutcome> {
  if (!refreshTask || refreshTask.epoch !== epoch) {
    const promise = doRefresh(epoch).finally(() => {
      // 只清理仍属于本任务的共享状态，避免误清新会话的刷新任务
      if (refreshTask?.promise === promise) refreshTask = null
    })
    refreshTask = { epoch, promise }
  }
  return refreshTask.promise
}

async function rawRequest(opts: RequestOptions): Promise<RawResponse> {
  const method = opts.method ?? 'GET'
  const target = buildUrl(opts.path, opts.query)

  const headers: Record<string, string> = {
    'x-client-version': CLIENT_VERSION,
    'x-request-id': uuidv7(),
  }
  const access = getAccessToken()
  const sentEpoch = getSessionEpoch()
  if (!opts.skipAuth && access) headers.authorization = `Bearer ${access}`
  if (opts.idempotencyKey) headers['idempotency-key'] = opts.idempotencyKey

  let body: string | FormData | null = null
  if (opts.form) {
    body = opts.form
  } else if (opts.body !== undefined) {
    headers['content-type'] = 'application/json; charset=utf-8'
    body = JSON.stringify(opts.body)
  }
  Object.assign(headers, opts.headers || {})

  let res = await dispatch({ method, url: target, headers, body, signal: opts.signal })

  if (isExpiredAuth(res.status, res) && !opts.skipAuth) {
    if (getSessionEpoch() !== sentEpoch) {
      // 请求发出后会话已被替换（登录/退出/换账号）：按原样返回失败，
      // 不刷新、不重放（避免旧账号写请求拿新账号令牌重执行），也不清理当前会话。
      return res
    }
    const current = getAccessToken()
    if (current && current !== access) {
      // 迟到的旧 401：请求携带的令牌已被并发刷新轮换，直接复用当前令牌重放一次
      headers.authorization = `Bearer ${current}`
      res = await dispatch({ method, url: target, headers, body, signal: opts.signal })
    } else {
      const outcome = await refreshOnce(sentEpoch)
      if (getSessionEpoch() !== sentEpoch) {
        // 刷新期间会话已切换：按原样返回，旧会话的失败不得清空新会话
        return res
      }
      if (outcome.kind === 'ok' && getAccessToken()) {
        headers.authorization = `Bearer ${getAccessToken() as string}`
        res = await dispatch({ method, url: target, headers, body, signal: opts.signal })
      } else if (outcome.kind === 'temporary') {
        // 临时刷新故障：保留会话与刷新令牌，向调用者返回可理解的错误，不重放
        return apiErrorToRawResponse(outcome.error)
      }
      // invalid（永久失效）：保留原 401，落入下方统一终态清理
    }
  }
  // 永久认证拒绝统一终结当前会话：普通请求的 AUTH_INVALID（含重放/迟到 401 复用后的再拒）
  // 与账号停用。仅当请求仍属于当前会话代际时清理，旧会话失败不得清空新会话。
  if (!opts.skipAuth && isTerminalAuthRejection(res.status, res) && getSessionEpoch() === sentEpoch) {
    clearTokens()
    emitUnauthorized()
  }
  return res
}

function parseResponse<T>(res: RawResponse, responseType?: RequestOptions['responseType']): T {
  if (res.status >= 400) {
    throw bodyToApiError(res.status, res)
  }
  if (responseType === 'none' || res.status === 204) {
    return undefined as T
  }
  if (responseType === 'blob') {
    if (res.body instanceof Blob) return res.body as T
    return new Blob([res.body ?? ''], { type: res.headers['content-type'] || 'application/octet-stream' }) as T
  }
  if (typeof res.body === 'string' && res.body !== '') {
    try {
      return JSON.parse(res.body) as T
    } catch {
      // 预期 JSON 的成功接口返回 HTML/非法 JSON：抛结构化错误，不伪装成业务对象
      throw new ApiError(502, 'INTERNAL', '服务响应不是有效的 JSON', res.headers['x-request-id'])
    }
  }
  throw new ApiError(502, 'INTERNAL', '服务响应不是有效的 JSON', res.headers['x-request-id'])
}

export async function request<T>(opts: RequestOptions): Promise<T> {
  const res = await rawRequest(opts)
  return parseResponse<T>(res, opts.responseType)
}

export async function requestRaw(opts: RequestOptions): Promise<RawResponse> {
  return rawRequest(opts)
}

export function throwIfError(res: RawResponse): void {
  if (res.status >= 400) throw bodyToApiError(res.status, res)
}

export function parseJsonBody<T>(res: RawResponse): T {
  if (typeof res.body !== 'string' || res.body === '') return undefined as T
  return JSON.parse(res.body) as T
}
