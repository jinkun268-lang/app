// 开发态 HTTP 模拟处理器：与真实客户端走同一 URL、query、JSON/Blob、错误码与权限校验。
// 生产构建不加载本模块（见 index.ts 的 isMockEnabled 判断）；请求失败不回退到本模拟。
// 状态可按测试场景 resetMock() 重置。
import { seedState } from './fixtures'
import type {
  MockClass, MockCultivar, MockImage, MockSample, MockUser,
} from './fixtures'
import { uuidv7 } from '../util/uuid'
import { buildZip, encodeUtf8 } from './zip'
import { sha256Hex } from './sha256'
import type { Role } from '../types'

export interface MockDispatchInput {
  method: string
  path: string
  headers: Record<string, string>
  body?: string | FormData | null
}

export interface MockDispatchResult {
  status: number
  headers: Record<string, string>
  body: string | Blob | null
}

// ---------- 状态 ----------
interface Session { access_token: string; refresh_token: string; user_id: string; family_id: string; access_expires_at: number; refresh_expires_at: number }
interface SnapshotItem { image_id: string; sample_id: string; file_name: string; class_id: string; class_name: string }
interface ExportRecord {
  export_id: string
  format: 'dataset'
  filters: Record<string, string | null>
  snapshot_at: string
  taxonomy_version: number
  item_count: number
  status: 'queued' | 'running' | 'succeeded' | 'failed'
  zip_sha256: string | null
  zip_size: number | null
  error_code: string | null
  error_detail: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  items: SnapshotItem[]
  zip_bytes: Uint8Array | null
  idempotency_key: string
  fail: boolean
}
interface AuditRecord {
  audit_id: string
  at: string
  actor_id: string | null
  actor_display_name: string | null
  actor_role: string | null
  action: string
  object_type: string
  object_id: string
  before_json: Record<string, unknown> | null
  after_json: Record<string, unknown> | null
  request_id: string | null
  ip: string | null
  user_agent: string | null
}
interface TicketRecord {
  ticket_id: string
  question_id: string
  status: 'queued' | 'reviewing' | 'needs_info' | 'done'
  outcome: 'answered' | 'unresolved' | null
  assignee_id: string | null
  draft: string | null
  version: number
  created_at: string
  updated_at: string
  claimed_at: string | null
  closed_at: string | null
  question: {
    question_id: string
    text: string | null
    status: string
    current_version: number
    created_at: string
    last_event_at: string
    attachments: { attachment_id: string; mime_type: string; width: number; height: number; uploaded_at: string }[]
    supplements: { supplement_id: string; author_display_name: string; text: string | null; question_version: number; created_at: string }[]
  }
  events: { event_id: string; action: string; actor_display_name: string | null; at: string; version: number; payload: Record<string, unknown> | null }[]
}

export const mockControl = {
  exportDelayMs: 15,
  previewDelayMs: 10,
  failNextExport: false,
}

let users: MockUser[] = []
let cultivars: MockCultivar[] = []
let classes: MockClass[] = []
let samples: MockSample[] = []
let exportsList: ExportRecord[] = []
let audit: AuditRecord[] = []
let tickets: TicketRecord[] = []
let sessions = new Map<string, Session>()
let previewReady = new Set<string>()
let taxonomyVersion = 1
let idempotency = new Map<string, { status: number; body: unknown; request_hash: string }>()

const ONE_MIN = 60 * 1000
const ONE_DAY = 24 * 60 * 60 * 1000

// 1x1 红色 PNG（占位图）
const PNG_BASE64 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
function pngBytes(): Uint8Array {
  const bin = atob(PNG_BASE64)
  const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
  return bytes
}

export function resetMock(): void {
  const seed = seedState()
  users = JSON.parse(JSON.stringify(seed.users))
  cultivars = JSON.parse(JSON.stringify(seed.cultivars))
  classes = JSON.parse(JSON.stringify(seed.classes))
  samples = JSON.parse(JSON.stringify(seed.samples))
  exportsList = []
  audit = []
  tickets = seedTickets()
  sessions = new Map()
  previewReady = new Set()
  taxonomyVersion = 1
  idempotency = new Map()
  Object.assign(mockControl, { exportDelayMs: 15, previewDelayMs: 10, failNextExport: false })
}

function seedTickets(): TicketRecord[] {
  const now = '2026-10-20T00:00:00Z'
  return [
    {
      ticket_id: '019a0002-0000-7000-8000-000000000001', question_id: '019a0002-0000-7001-8000-000000000001',
      status: 'queued', outcome: null, assignee_id: null, draft: null, version: 0,
      created_at: now, updated_at: now, claimed_at: null, closed_at: null,
      question: { question_id: '019a0002-0000-7001-8000-000000000001', text: '胡柚叶片出现黄斑，是黄龙病吗？', status: 'queued', current_version: 1, created_at: now, last_event_at: now, attachments: [], supplements: [] },
      events: [{ event_id: uuidv7(), action: 'create', actor_display_name: null, at: now, version: 0, payload: null }],
    },
    {
      ticket_id: '019a0002-0000-7000-8000-000000000002', question_id: '019a0002-0000-7001-8000-000000000002',
      status: 'reviewing', outcome: null, assignee_id: '019a0000-0000-7000-8000-000000000003', draft: '初步判断为溃疡病，待核对来源证据。', version: 1,
      created_at: now, updated_at: now, claimed_at: now, closed_at: null,
      question: { question_id: '019a0002-0000-7001-8000-000000000002', text: '香柚果实表面有褐色斑点，怎么处理？', status: 'reviewing', current_version: 1, created_at: now, last_event_at: now, attachments: [], supplements: [] },
      events: [
        { event_id: uuidv7(), action: 'create', actor_display_name: null, at: now, version: 0, payload: null },
        { event_id: uuidv7(), action: 'claim', actor_display_name: '专家', at: now, version: 1, payload: null },
      ],
    },
    {
      ticket_id: '019a0002-0000-7000-8000-000000000003', question_id: '019a0002-0000-7001-8000-000000000003',
      status: 'done', outcome: 'answered', assignee_id: '019a0000-0000-7000-8000-000000000003', draft: null, version: 1,
      created_at: now, updated_at: now, claimed_at: now, closed_at: now,
      question: { question_id: '019a0002-0000-7001-8000-000000000003', text: '溃疡病和疮痂病怎么区分？', status: 'expert_answered', current_version: 1, created_at: now, last_event_at: now, attachments: [], supplements: [] },
      events: [
        { event_id: uuidv7(), action: 'create', actor_display_name: null, at: now, version: 0, payload: null },
        { event_id: uuidv7(), action: 'answer', actor_display_name: '专家', at: now, version: 1, payload: { answer_text: '溃疡病病斑有火山口状开裂，疮痂病为疣状突起。' } },
      ],
    },
  ]
}

resetMock()

// ---------- 响应构造 ----------
function json(status: number, obj: unknown, headers: Record<string, string> = {}): MockDispatchResult {
  return { status, headers: { 'content-type': 'application/json; charset=utf-8', ...headers }, body: JSON.stringify(obj) }
}
function blobResponse(status: number, bytes: Uint8Array, type: string, headers: Record<string, string> = {}): MockDispatchResult {
  return { status, headers: { 'content-type': type, ...headers }, body: new Blob([bytes as unknown as BlobPart], { type }) }
}
function errorResp(status: number, code: string, message: string, details?: Record<string, unknown>, requestId?: string): MockDispatchResult {
  return json(status, { error: { code, message, details, request_id: requestId ?? uuidv7() } })
}

function parseBody(body: string | FormData | null | undefined): Record<string, unknown> {
  if (body == null) return {}
  if (typeof body === 'string') {
    if (body === '') return {}
    try {
      return JSON.parse(body)
    } catch {
      return {}
    }
  }
  return {}
}

// ---------- 认证 ----------
function authenticate(headers: Record<string, string>, requestId: string): { user: MockUser } | { error: MockDispatchResult } {
  const auth = headers['authorization']
  if (!auth) return { error: errorResp(401, 'AUTH_REQUIRED', '缺少认证令牌', undefined, requestId) }
  const token = auth.replace(/^Bearer\s+/i, '')
  const session = sessions.get(token)
  if (!session) return { error: errorResp(401, 'AUTH_INVALID', '令牌无效或过期', { reason: 'invalid' }, requestId) }
  if (session.access_expires_at < Date.now()) {
    return { error: errorResp(401, 'AUTH_INVALID', '访问令牌已过期', { reason: 'expired' }, requestId) }
  }
  const user = users.find((u) => u.user_id === session.user_id)
  if (!user) return { error: errorResp(401, 'AUTH_INVALID', '账号不存在', { reason: 'invalid' }, requestId) }
  if (!user.is_active) return { error: errorResp(403, 'ACCOUNT_DISABLED', '账号已停用', undefined, requestId) }
  return { user }
}

function requireRole(user: MockUser, roles: Role[], requestId: string): MockDispatchResult | null {
  if (roles.includes(user.role)) return null
  return errorResp(403, 'FORBIDDEN', '无权限执行该操作', { required_role: roles[0] }, requestId)
}

// 将现有全部访问令牌标记为过期（新令牌不受影响），用于测试刷新重放路径。
export function expireAccessTokens(): void {
  sessions.forEach((s) => {
    s.access_expires_at = 0
  })
}

function makeSession(userId: string): Session {
  return {
    access_token: 'mock_at_' + uuidv7() + '_' + Math.random().toString(36).slice(2, 8),
    refresh_token: 'mock_rt_' + uuidv7() + '_' + Math.random().toString(36).slice(2, 8),
    user_id: userId,
    family_id: uuidv7(),
    access_expires_at: Date.now() + 30 * ONE_MIN,
    refresh_expires_at: Date.now() + 30 * ONE_DAY,
  }
}

function displayName(user: MockUser | undefined): string {
  return user?.display_name ?? '未知'
}

// ---------- 序列化 ----------
function cultivarName(id: string | null): string | null {
  if (id == null) return null
  return cultivars.find((c) => c.cultivar_id === id)?.name ?? id
}
function className(id: string | null): string | null {
  if (id == null) return null
  return classes.find((c) => c.class_id === id)?.name ?? id
}

function toSummary(s: MockSample): Record<string, unknown> {
  const usable = s.images.filter((i) => i.quality_status === 'usable').length
  return {
    sample_id: s.sample_id,
    tree_id: s.tree_id,
    original_cultivar_id: s.original_cultivar_id,
    original_cultivar_name: cultivarName(s.original_cultivar_id),
    original_part: s.original_part,
    original_class_id: s.original_class_id,
    original_class_name: className(s.original_class_id),
    final_cultivar_id: s.final_cultivar_id,
    final_cultivar_name: cultivarName(s.final_cultivar_id),
    final_part: s.final_part,
    final_class_id: s.final_class_id,
    final_class_name: className(s.final_class_id),
    review_status: s.review_status,
    excluded: s.excluded,
    upload_completed_at: s.upload_completed_at,
    image_count: s.images.length,
    first_image_id: s.images[0]?.image_id ?? null,
    _usable: usable,
  }
}

function toImage(img: MockImage): Record<string, unknown> {
  return {
    image_id: img.image_id,
    view_type: img.view_type,
    captured_at: img.captured_at,
    device_timezone: img.device_timezone,
    device_model: img.device_model,
    mime_type: img.mime_type,
    width: img.width,
    height: img.height,
    file_size: img.file_size,
    quality_status: img.quality_status,
    quality_reason_code: img.quality_reason_code,
    quality_note: img.quality_note,
    quality_version: img.quality_version,
    quality_reviewed_by_display_name: img.quality_reviewed_by_display_name,
    quality_reviewed_at: img.quality_reviewed_at,
    clock_skew_suspected: img.clock_skew_suspected,
    quality_events: img.quality_events,
  }
}

function toDetail(s: MockSample): Record<string, unknown> {
  return {
    sample_id: s.sample_id,
    tree_id: s.tree_id,
    original_cultivar_id: s.original_cultivar_id,
    original_cultivar_name: cultivarName(s.original_cultivar_id),
    original_part: s.original_part,
    original_class_id: s.original_class_id,
    original_class_name: className(s.original_class_id),
    symptoms: s.symptoms,
    note: s.note,
    taxonomy_version: s.taxonomy_version,
    upload_state: s.upload_state,
    upload_completed_at: s.upload_completed_at,
    excluded: s.excluded,
    review_status: s.review_status,
    final_cultivar_id: s.final_cultivar_id,
    final_cultivar_name: cultivarName(s.final_cultivar_id),
    final_part: s.final_part,
    final_class_id: s.final_class_id,
    final_class_name: className(s.final_class_id),
    review_note: s.review_note,
    review_version: s.review_version,
    reviewed_by_display_name: s.reviewed_by_display_name,
    reviewed_at: s.reviewed_at,
    images: s.images.map(toImage),
    review_events: s.review_events,
  }
}

function toExport(e: ExportRecord): Record<string, unknown> {
  return {
    export_id: e.export_id,
    format: e.format,
    status: e.status,
    filters: e.filters,
    snapshot_at: e.snapshot_at,
    taxonomy_version: e.taxonomy_version,
    item_count: e.item_count,
    zip_sha256: e.zip_sha256,
    zip_size: e.zip_size,
    error_code: e.error_code,
    error_detail: e.error_detail,
    created_at: e.created_at,
    started_at: e.started_at,
    finished_at: e.finished_at,
  }
}

function isExportEligibleClass(classId: string | null): boolean {
  if (!classId || classId === 'unknown') return false
  const cls = classes.find((c) => c.class_id === classId)
  return !!cls && !cls.is_provisional
}

function buildSnapshotItems(): SnapshotItem[] {
  const items: SnapshotItem[] = []
  for (const s of samples) {
    if (s.excluded) continue
    if (s.review_status !== 'confirmed' && s.review_status !== 'corrected') continue
    if (!isExportEligibleClass(s.final_class_id)) continue
    for (const img of s.images) {
      if (img.quality_status !== 'usable') continue
      const ext = img.mime_type === 'image/png' ? 'png' : img.mime_type === 'image/webp' ? 'webp' : 'jpg'
      items.push({ image_id: img.image_id, sample_id: s.sample_id, file_name: `${img.image_id}.${ext}`, class_id: s.final_class_id as string, class_name: className(s.final_class_id) as string })
    }
  }
  items.sort((a, b) => (a.image_id < b.image_id ? -1 : 1))
  return items
}

function buildExportZipBytes(items: SnapshotItem[]): Uint8Array {
  const labelLines = ['image_id,sample_id,file_name,class_id']
  for (const it of items) labelLines.push(`${it.image_id},${it.sample_id},${it.file_name},${it.class_id}`)
  const classIds = [...new Set(items.map((i) => i.class_id))]
  const classLines = ['class_id,class_name']
  for (const id of classIds) classLines.push(`${id},${items.find((i) => i.class_id === id)?.class_name ?? id}`)
  const entries = [
    { name: 'labels.csv', bytes: encodeUtf8(labelLines.join('\n') + '\n') },
    { name: 'classes.csv', bytes: encodeUtf8(classLines.join('\n') + '\n') },
    ...items.map((it) => ({ name: `images/${it.file_name}`, bytes: encodeUtf8(`fixture-image:${it.image_id}`) })),
  ]
  return buildZip(entries)
}

function runExport(e: ExportRecord): void {
  e.status = 'running'
  e.started_at = new Date().toISOString()
  setTimeout(() => {
    if (e.fail) {
      e.status = 'failed'
      e.error_code = 'FILE_MISMATCH'
      e.error_detail = '模拟原图哈希不符（测试夹具）'
      e.finished_at = new Date().toISOString()
      return
    }
    const zipBytes = buildExportZipBytes(e.items)
    e.zip_bytes = zipBytes
    e.zip_sha256 = sha256Hex(zipBytes)
    e.zip_size = zipBytes.length
    e.status = 'succeeded'
    e.finished_at = new Date().toISOString()
  }, mockControl.exportDelayMs)
}

function appendAudit(user: MockUser, action: string, objectType: string, objectId: string, before: Record<string, unknown> | null, after: Record<string, unknown> | null, requestId: string): void {
  audit.unshift({
    audit_id: uuidv7(),
    at: new Date().toISOString(),
    actor_id: user.user_id,
    actor_display_name: user.display_name,
    actor_role: user.role,
    action,
    object_type: objectType,
    object_id: objectId,
    before_json: before,
    after_json: after,
    request_id: requestId,
    ip: '127.0.0.1',
    user_agent: 'mock',
  })
}

function idempotencyCheck(key: string | undefined, requestHash: string): MockDispatchResult | null {
  if (!key) return null
  const existing = idempotency.get(key)
  if (existing) {
    if (existing.request_hash !== requestHash) return errorResp(409, 'IDEMPOTENCY_CONFLICT', '同一幂等键对应不同内容', { scope: 'export', key })
    return json(existing.status, existing.body)
  }
  return null
}

function storeIdempotency(key: string, requestHash: string, status: number, body: unknown): void {
  if (!key) return
  idempotency.set(key, { status, request_hash: requestHash, body })
}

// ---------- 路由 ----------
const PUBLIC = new Set(['/api/v1/health', '/api/v1/health/ready', '/api/v1/auth/login', '/api/v1/auth/refresh'])

export function mockDispatch(input: MockDispatchInput): MockDispatchResult {
  const requestId = input.headers['x-request-id'] || uuidv7()
  const url = new URL(input.path, 'http://local')
  const path = url.pathname
  const method = input.method.toUpperCase()
  const query: Record<string, string> = {}
  url.searchParams.forEach((v, k) => {
    query[k] = v
  })
  const body = parseBody(input.body)

  if (!PUBLIC.has(path)) {
    const auth = authenticate(input.headers, requestId)
    if ('error' in auth) return auth.error
    return route(method, path, query, body, input.headers, requestId, auth.user)
  }
  return routePublic(method, path, query, body, input.headers, requestId)
}

function routePublic(method: string, path: string, _query: Record<string, string>, body: Record<string, unknown>, _headers: Record<string, string>, requestId: string): MockDispatchResult {
  if (path === '/api/v1/health' || path === '/api/v1/health/ready') {
    return json(200, { status: 'ok', version: '1.0', time: new Date().toISOString() })
  }
  if (path === '/api/v1/auth/login' && method === 'POST') {
    const username = String(body.username ?? '')
    const password = String(body.password ?? '')
    const user = users.find((u) => u.username === username)
    if (!user || user.password !== password) {
      return errorResp(401, 'AUTH_INVALID', '账号或密码错误', { reason: 'bad_credentials' }, requestId)
    }
    if (!user.is_active) return errorResp(403, 'ACCOUNT_DISABLED', '账号已停用', undefined, requestId)
    const session = makeSession(user.user_id)
    sessions.set(session.access_token, session)
    sessions.set(session.refresh_token, session)
    user.last_login_at = new Date().toISOString()
    appendAudit(user, 'auth.login', 'user', user.user_id, null, null, requestId)
    return json(200, {
      access_token: session.access_token,
      refresh_token: session.refresh_token,
      token_type: 'Bearer',
      expires_in: 1800,
      user: { user_id: user.user_id, username: user.username, display_name: user.display_name, role: user.role },
    })
  }
  if (path === '/api/v1/auth/refresh' && method === 'POST') {
    const rt = String(body.refresh_token ?? '')
    const session = sessions.get(rt)
    if (!session) return errorResp(401, 'AUTH_INVALID', '刷新令牌无效或已轮换', { reason: 'invalid' }, requestId)
    const next = makeSession(session.user_id)
    sessions.delete(rt)
    sessions.set(next.access_token, next)
    sessions.set(next.refresh_token, next)
    return json(200, { access_token: next.access_token, refresh_token: next.refresh_token, token_type: 'Bearer', expires_in: 1800 })
  }
  return errorResp(404, 'NOT_FOUND', '资源不存在或不可见', { resource: path }, requestId)
}

function route(method: string, path: string, query: Record<string, string>, body: Record<string, unknown>, headers: Record<string, string>, requestId: string, user: MockUser): MockDispatchResult {
  // 退出登录
  if (path === '/api/v1/auth/logout' && method === 'POST') {
    const rt = sessions.get(getAccessTokenOf(headers))
    if (rt) sessions.delete(rt.refresh_token)
    return { status: 204, headers: {}, body: null }
  }
  if (path === '/api/v1/me' && method === 'GET') {
    return json(200, { user_id: user.user_id, username: user.username, display_name: user.display_name, role: user.role })
  }
  if (path === '/api/v1/config/bootstrap' && method === 'GET') {
    return json(200, {
      cultivars: cultivars.map((c) => ({ cultivar_id: c.cultivar_id, name: c.name, is_active: c.is_active, version: c.version })),
      classes: classes.map((c) => ({ class_id: c.class_id, name: c.name, parent_id: c.parent_id, is_active: c.is_active, is_provisional: c.is_provisional, introduced_taxonomy_version: c.introduced_taxonomy_version, deprecated_taxonomy_version: c.deprecated_taxonomy_version, version: c.version })),
      taxonomy_version: taxonomyVersion,
      policy_version: 1,
      server_time: new Date().toISOString(),
    })
  }

  // 样本
  if (path === '/api/v1/samples' && method === 'GET') {
    const err = requireRole(user, ['collector', 'expert', 'admin', 'super_admin'], requestId)
    if (err) return err
    let list = user.role === 'collector' ? samples.filter((s) => s.owner_id === user.user_id) : samples
    if (query.review_status) {
      const wanted = query.review_status.split(',')
      list = list.filter((s) => wanted.includes(s.review_status))
    }
    if (query.excluded === 'true') list = list.filter((s) => s.excluded)
    else if (query.excluded === 'false') list = list.filter((s) => !s.excluded)
    if (query.final_cultivar_id) list = list.filter((s) => s.final_cultivar_id === query.final_cultivar_id)
    if (query.final_class_id) list = list.filter((s) => s.final_class_id === query.final_class_id)
    if (query.uploaded_from) list = list.filter((s) => s.upload_completed_at.slice(0, 10) >= query.uploaded_from)
    if (query.uploaded_to) list = list.filter((s) => s.upload_completed_at.slice(0, 10) <= query.uploaded_to)
    if (query.q) {
      list = list.filter((s) => s.sample_id === query.q || (s.tree_id && s.tree_id.startsWith(query.q)))
    }
    list = [...list].sort((a, b) => (a.upload_completed_at < b.upload_completed_at ? 1 : -1))
    const page = Math.max(1, parseInt(query.page || '1', 10) || 1)
    const pageSize = Math.min(100, Math.max(1, parseInt(query.page_size || '20', 10) || 20))
    const start = (page - 1) * pageSize
    return json(200, { items: list.slice(start, start + pageSize).map((s) => toSummary(s)), page, page_size: pageSize, total: list.length })
  }

  const sampleMatch = path.match(/^\/api\/v1\/samples\/([0-9a-f-]{36})$/)
  if (sampleMatch && method === 'GET') {
    const err = requireRole(user, ['collector', 'expert', 'admin', 'super_admin'], requestId)
    if (err) return err
    const s = samples.find((x) => x.sample_id === sampleMatch[1])
    if (!s || (user.role === 'collector' && s.owner_id !== user.user_id)) return errorResp(404, 'NOT_FOUND', '样本不存在或不可见', { resource: 'sample' }, requestId)
    return json(200, toDetail(s))
  }
  const reviewMatch = path.match(/^\/api\/v1\/samples\/([0-9a-f-]{36})\/review$/)
  if (reviewMatch && method === 'PATCH') {
    const err = requireRole(user, ['expert', 'super_admin'], requestId)
    if (err) return err
    const s = samples.find((x) => x.sample_id === reviewMatch[1])
    if (!s) return errorResp(404, 'NOT_FOUND', '样本不存在或不可见', { resource: 'sample' }, requestId)
    if (body.expected_version !== s.review_version) {
      return errorResp(409, 'VERSION_CONFLICT', '该对象已被其他审核者更新，请刷新后重试。', { object: 'sample', expected_version: body.expected_version, current_version: s.review_version }, requestId)
    }
    const status = body.review_status as MockSample['review_status']
    if (status === 'unreviewed') return errorResp(422, 'VALIDATION_FAILED', '不能保存为未审核', { fields: [{ field: 'review_status', reason: 'unreviewed 不可作为保存动作' }] }, requestId)
    const before = { review_status: s.review_status, final_cultivar_id: s.final_cultivar_id, final_part: s.final_part, final_class_id: s.final_class_id, review_note: s.review_note }
    if (status === 'unresolved') {
      const hasFinal = body.final_cultivar_id != null || body.final_part != null || body.final_class_id != null
      if (hasFinal) return errorResp(422, 'VALIDATION_FAILED', '无法判断不应带最终值', { fields: [{ field: 'final_*', reason: 'unresolved 不得带 final_*' }] }, requestId)
      s.review_status = 'unresolved'
      s.final_cultivar_id = null
      s.final_part = null
      s.final_class_id = null
    } else if (status === 'confirmed') {
      if (body.final_cultivar_id !== s.original_cultivar_id || body.final_part !== s.original_part || body.final_class_id !== s.original_class_id) {
        return errorResp(422, 'VALIDATION_FAILED', '确认的最终值必须等于原值', { fields: [{ field: 'final_*', reason: 'confirmed 最终值必须等于原值' }] }, requestId)
      }
      s.review_status = 'confirmed'
      s.final_cultivar_id = s.original_cultivar_id
      s.final_part = s.original_part
      s.final_class_id = s.original_class_id
    } else if (status === 'corrected') {
      const same = body.final_cultivar_id === s.original_cultivar_id && body.final_part === s.original_part && body.final_class_id === s.original_class_id
      if (same) return errorResp(422, 'VALIDATION_FAILED', '修正必须至少一项与原值不同', { fields: [{ field: 'final_*', reason: 'corrected 至少一项变化' }] }, requestId)
      if (body.final_cultivar_id == null || body.final_part == null || body.final_class_id == null) {
        return errorResp(422, 'VALIDATION_FAILED', '修正必须完整填写最终值', { fields: [{ field: 'final_*', reason: 'corrected 必须完整' }] }, requestId)
      }
      s.review_status = 'corrected'
      s.final_cultivar_id = String(body.final_cultivar_id)
      s.final_part = String(body.final_part)
      s.final_class_id = String(body.final_class_id)
    } else {
      return errorResp(422, 'VALIDATION_FAILED', '非法的审核状态', { fields: [{ field: 'review_status', reason: '未知值' }] }, requestId)
    }
    s.review_note = (body.review_note as string | null) ?? null
    s.review_version += 1
    s.reviewed_by_display_name = user.display_name
    s.reviewed_at = new Date().toISOString()
    s.review_events.unshift({ review_id: uuidv7(), action: 'review', actor_display_name: user.display_name, actor_role: user.role, at: s.reviewed_at, note: s.review_note, sample_version: s.review_version, before_json: before, after_json: { review_status: s.review_status, final_cultivar_id: s.final_cultivar_id, final_part: s.final_part, final_class_id: s.final_class_id, review_note: s.review_note } })
    appendAudit(user, 'sample.review', 'sample', s.sample_id, before, { review_status: s.review_status, final_class_id: s.final_class_id }, requestId)
    return json(200, toDetail(s))
  }

  const qualityMatch = path.match(/^\/api\/v1\/samples\/([0-9a-f-]{36})\/images\/([0-9a-f-]{36})\/quality$/)
  if (qualityMatch && method === 'PATCH') {
    const err = requireRole(user, ['admin', 'super_admin'], requestId)
    if (err) return err
    const s = samples.find((x) => x.sample_id === qualityMatch[1])
    if (!s) return errorResp(404, 'NOT_FOUND', '样本不存在或不可见', { resource: 'sample' }, requestId)
    if (!['confirmed', 'corrected'].includes(s.review_status)) return errorResp(409, 'STATE_CONFLICT', '样本尚未通过专业核验', { review_status: s.review_status }, requestId)
    const img = s.images.find((i) => i.image_id === qualityMatch[2])
    if (!img) return errorResp(404, 'NOT_FOUND', '图片不存在或不可见', { resource: 'image' }, requestId)
    if (body.expected_version !== img.quality_version) {
      return errorResp(409, 'VERSION_CONFLICT', '该图已被其他审核者更新，请刷新后重试。', { object: 'image', expected_version: body.expected_version, current_version: img.quality_version }, requestId)
    }
    const status = body.quality_status as MockImage['quality_status']
    if (status === 'pending') return errorResp(422, 'VALIDATION_FAILED', '不能重置为未检查', { fields: [{ field: 'quality_status', reason: 'pending 不可作为保存动作' }] }, requestId)
    if (status === 'unusable' && !body.quality_reason_code) {
      return errorResp(422, 'VALIDATION_FAILED', '不可用必须选择原因', { fields: [{ field: 'quality_reason_code', reason: 'unusable 必填' }] }, requestId)
    }
    const before = { quality_status: img.quality_status, quality_reason_code: img.quality_reason_code }
    img.quality_status = status
    img.quality_reason_code = status === 'unusable' ? String(body.quality_reason_code) : null
    img.quality_note = (body.quality_note as string | null) ?? null
    img.quality_version += 1
    img.quality_reviewed_by_display_name = user.display_name
    img.quality_reviewed_at = new Date().toISOString()
    img.quality_events.unshift({ event_id: uuidv7(), before_status: before.quality_status, after_status: img.quality_status, reason_code: img.quality_reason_code, note: img.quality_note, actor_display_name: user.display_name, at: img.quality_reviewed_at as string, image_version: img.quality_version })
    appendAudit(user, 'image.quality', 'image', img.image_id, before, { quality_status: img.quality_status, quality_reason_code: img.quality_reason_code }, requestId)
    return json(200, toImage(img))
  }

  const excludeMatch = path.match(/^\/api\/v1\/samples\/([0-9a-f-]{36})\/(exclude|restore)$/)
  if (excludeMatch && method === 'POST') {
    const err = requireRole(user, ['admin', 'super_admin'], requestId)
    if (err) return err
    const s = samples.find((x) => x.sample_id === excludeMatch[1])
    if (!s) return errorResp(404, 'NOT_FOUND', '样本不存在或不可见', { resource: 'sample' }, requestId)
    if (body.expected_version !== s.review_version) {
      return errorResp(409, 'VERSION_CONFLICT', '该对象已被其他审核者更新，请刷新后重试。', { object: 'sample', expected_version: body.expected_version, current_version: s.review_version }, requestId)
    }
    const action = excludeMatch[2]
    const next = action === 'exclude'
    if (s.excluded === next) return errorResp(409, 'STATE_CONFLICT', '状态不允许该操作', { object: 'sample', current_state: next ? 'excluded' : 'not_excluded', allowed_from: [s.excluded ? 'excluded' : 'not_excluded'] }, requestId)
    const before = { excluded: s.excluded }
    s.excluded = next
    s.review_version += 1
    s.review_events.unshift({ review_id: uuidv7(), action, actor_display_name: user.display_name, actor_role: user.role, at: new Date().toISOString(), note: (body.reason as string | null) ?? null, sample_version: s.review_version, before_json: before, after_json: { excluded: s.excluded } })
    appendAudit(user, action === 'exclude' ? 'sample.exclude' : 'sample.restore', 'sample', s.sample_id, before, { excluded: s.excluded }, requestId)
    return json(200, toDetail(s))
  }

  // 媒体
  const mediaMatch = path.match(/^\/api\/v1\/media\/sample-images\/([0-9a-f-]{36})$/)
  if (mediaMatch && method === 'GET') {
    const err = requireRole(user, ['collector', 'expert', 'admin', 'super_admin'], requestId)
    if (err) return err
    const imgId = mediaMatch[1]
    const s = samples.find((x) => x.images.some((i) => i.image_id === imgId))
    if (!s || (user.role === 'collector' && s.owner_id !== user.user_id)) return errorResp(404, 'NOT_FOUND', '图片不存在或不可见', { resource: 'image' }, requestId)
    const variant = query.variant
    if (variant === 'preview') {
      if (!previewReady.has(imgId)) {
        // 首次请求：安排稍后生成预览，当前返回 202，客户端按 Retry-After 重查同一 URL
        setTimeout(() => previewReady.add(imgId), mockControl.previewDelayMs)
        return json(202, { image_id: imgId, state: 'pending', retry_after: 1 }, { 'retry-after': '1', 'x-image-id': imgId })
      }
      return blobResponse(200, pngBytes(), 'image/jpeg', { etag: `"${sha256Hex(pngBytes())}"`, 'cache-control': 'private, max-age=300' })
    }
    return blobResponse(200, pngBytes(), 'image/jpeg', { etag: `"${sha256Hex(pngBytes())}"`, 'cache-control': 'private, max-age=300' })
  }

  // 导出
  if (path === '/api/v1/exports' && method === 'POST') {
    const err = requireRole(user, ['admin', 'super_admin'], requestId)
    if (err) return err
    const key = headers['idempotency-key']
    const requestHash = sha256Hex(encodeUtf8(JSON.stringify(body)))
    const replay = idempotencyCheck(key, requestHash)
    if (replay) return replay
    const items = buildSnapshotItems()
    const fail = mockControl.failNextExport
    mockControl.failNextExport = false
    const record: ExportRecord = {
      export_id: uuidv7(),
      format: 'dataset',
      filters: { uploaded_from: (body.uploaded_from as string) ?? null, uploaded_to: (body.uploaded_to as string) ?? null, final_cultivar_id: (body.final_cultivar_id as string) ?? null, final_class_id: (body.final_class_id as string) ?? null, format: 'dataset' },
      snapshot_at: new Date().toISOString(),
      taxonomy_version: taxonomyVersion,
      item_count: items.length,
      status: 'queued',
      zip_sha256: null,
      zip_size: null,
      error_code: null,
      error_detail: null,
      created_at: new Date().toISOString(),
      started_at: null,
      finished_at: null,
      items,
      zip_bytes: null,
      idempotency_key: key ?? '',
      fail,
    }
    exportsList.unshift(record)
    appendAudit(user, 'export.create', 'export', record.export_id, null, { item_count: items.length }, requestId)
    const respBody = toExport(record)
    storeIdempotency(key ?? '', requestHash, 202, respBody)
    runExport(record)
    return json(202, respBody)
  }
  if (path === '/api/v1/exports' && method === 'GET') {
    const err = requireRole(user, ['admin', 'super_admin'], requestId)
    if (err) return err
    const list = [...exportsList].sort((a, b) => (a.created_at < b.created_at ? 1 : -1))
    const page = Math.max(1, parseInt(query.page || '1', 10) || 1)
    const pageSize = Math.min(100, Math.max(1, parseInt(query.page_size || '20', 10) || 20))
    const start = (page - 1) * pageSize
    return json(200, { items: list.slice(start, start + pageSize).map(toExport), page, page_size: pageSize, total: list.length })
  }
  const exportMatch = path.match(/^\/api\/v1\/exports\/([0-9a-f-]{36})(\/download|\/retry)?$/)
  if (exportMatch && method === 'GET') {
    const err = requireRole(user, ['admin', 'super_admin'], requestId)
    if (err) return err
    const e = exportsList.find((x) => x.export_id === exportMatch[1])
    if (!e) return errorResp(404, 'NOT_FOUND', '批次不存在或不可见', { resource: 'export' }, requestId)
    if (exportMatch[2] === '/download') {
      if (e.status !== 'succeeded' || !e.zip_bytes) return errorResp(409, 'STATE_CONFLICT', '仅成功批次可下载', { object: 'export', current_state: e.status, allowed_from: ['succeeded'] }, requestId)
      return blobResponse(200, e.zip_bytes, 'application/zip', { 'content-disposition': `attachment; filename="dataset-${e.export_id}.zip"` })
    }
    return json(200, toExport(e))
  }
  if (exportMatch && exportMatch[2] === '/retry' && method === 'POST') {
    const err = requireRole(user, ['admin', 'super_admin'], requestId)
    if (err) return err
    const e = exportsList.find((x) => x.export_id === exportMatch[1])
    if (!e) return errorResp(404, 'NOT_FOUND', '批次不存在或不可见', { resource: 'export' }, requestId)
    if (e.status !== 'failed') return errorResp(409, 'STATE_CONFLICT', '仅失败批次可重试', { object: 'export', current_state: e.status, allowed_from: ['failed'] }, requestId)
    e.status = 'queued'
    e.error_code = null
    e.error_detail = null
    e.finished_at = null
    e.fail = false
    const respBody = toExport(e)
    appendAudit(user, 'export.retry', 'export', e.export_id, null, { status: 'queued' }, requestId)
    runExport(e)
    return json(202, respBody)
  }

  // 字典（果园已移除：/admin/orchards 不注册，请求落到 404）
  if (path === '/api/v1/admin/cultivars' && method === 'GET') {
    const err = requireRole(user, ['super_admin'], requestId)
    if (err) return err
    return json(200, { items: cultivars.map((c) => ({ cultivar_id: c.cultivar_id, name: c.name, is_active: c.is_active, version: c.version })), total: cultivars.length })
  }
  if (path === '/api/v1/admin/cultivars' && method === 'POST') {
    const err = requireRole(user, ['super_admin'], requestId)
    if (err) return err
    const id = String(body.cultivar_id ?? '')
    if (!/^[a-z][a-z0-9_]{1,31}$/.test(id)) return errorResp(422, 'VALIDATION_FAILED', '业务码不合法', { fields: [{ field: 'cultivar_id', reason: '格式不符' }] }, requestId)
    if (cultivars.some((c) => c.cultivar_id === id)) return errorResp(409, 'STATE_CONFLICT', '业务码已存在', { object: 'cultivar', current_state: 'exists' }, requestId)
    const name = String(body.name ?? '').trim()
    if (!name) return errorResp(422, 'VALIDATION_FAILED', '名称必填', { fields: [{ field: 'name', reason: 'required' }] }, requestId)
    const row = { cultivar_id: id, name, is_active: true, version: 1, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }
    cultivars.push(row)
    appendAudit(user, 'dict.create', 'cultivar', id, null, { name }, requestId)
    return json(201, { cultivar_id: row.cultivar_id, name: row.name, is_active: row.is_active, version: row.version })
  }
  const cultivarMatch = path.match(/^\/api\/v1\/admin\/cultivars\/([a-z0-9_]+)$/)
  if (cultivarMatch && method === 'PATCH') {
    const err = requireRole(user, ['super_admin'], requestId)
    if (err) return err
    const c = cultivars.find((x) => x.cultivar_id === cultivarMatch[1])
    if (!c) return errorResp(404, 'NOT_FOUND', '品种不存在', { resource: 'cultivar' }, requestId)
    if (body.expected_version !== c.version) return errorResp(409, 'VERSION_CONFLICT', '字典已被更新，请刷新后重试。', { object: 'cultivar', expected_version: body.expected_version, current_version: c.version }, requestId)
    if (c.cultivar_id === 'unknown' && body.is_active === false) return errorResp(422, 'VALIDATION_FAILED', 'unknown 不得停用', { fields: [{ field: 'is_active', reason: 'unknown 不得停用' }] }, requestId)
    const before = { name: c.name, is_active: c.is_active }
    if (body.name != null) c.name = String(body.name).trim()
    if (body.is_active != null) c.is_active = Boolean(body.is_active)
    c.version += 1
    c.updated_at = new Date().toISOString()
    appendAudit(user, 'dict.update', 'cultivar', c.cultivar_id, before, { name: c.name, is_active: c.is_active }, requestId)
    return json(200, { cultivar_id: c.cultivar_id, name: c.name, is_active: c.is_active, version: c.version })
  }

  if (path === '/api/v1/admin/classes' && method === 'GET') {
    const err = requireRole(user, ['super_admin'], requestId)
    if (err) return err
    return json(200, { items: classes.map((c) => ({ class_id: c.class_id, name: c.name, parent_id: c.parent_id, is_active: c.is_active, is_provisional: c.is_provisional, introduced_taxonomy_version: c.introduced_taxonomy_version, deprecated_taxonomy_version: c.deprecated_taxonomy_version, version: c.version })), total: classes.length })
  }
  if (path === '/api/v1/admin/classes' && method === 'POST') {
    const err = requireRole(user, ['super_admin'], requestId)
    if (err) return err
    const id = String(body.class_id ?? '')
    if (!/^[a-z][a-z0-9_]{1,31}$/.test(id)) return errorResp(422, 'VALIDATION_FAILED', '业务码不合法', { fields: [{ field: 'class_id', reason: '格式不符' }] }, requestId)
    if (classes.some((c) => c.class_id === id)) return errorResp(409, 'STATE_CONFLICT', '业务码已存在', { object: 'class', current_state: 'exists' }, requestId)
    const name = String(body.name ?? '').trim()
    if (!name) return errorResp(422, 'VALIDATION_FAILED', '名称必填', { fields: [{ field: 'name', reason: 'required' }] }, requestId)
    const row: MockClass = { class_id: id, name, parent_id: (body.parent_id as string) ?? null, is_active: true, is_provisional: Boolean(body.is_provisional), introduced_taxonomy_version: taxonomyVersion, deprecated_taxonomy_version: null, version: 1, created_at: new Date().toISOString(), updated_at: new Date().toISOString() }
    classes.push(row)
    appendAudit(user, 'dict.create', 'class', id, null, { name }, requestId)
    return json(201, { class_id: row.class_id, name: row.name, parent_id: row.parent_id, is_active: row.is_active, is_provisional: row.is_provisional, introduced_taxonomy_version: row.introduced_taxonomy_version, deprecated_taxonomy_version: row.deprecated_taxonomy_version, version: row.version })
  }
  const classMatch = path.match(/^\/api\/v1\/admin\/classes\/([a-z0-9_]+)$/)
  if (classMatch && method === 'PATCH') {
    const err = requireRole(user, ['super_admin'], requestId)
    if (err) return err
    const c = classes.find((x) => x.class_id === classMatch[1])
    if (!c) return errorResp(404, 'NOT_FOUND', '类别不存在', { resource: 'class' }, requestId)
    if (body.expected_version !== c.version) return errorResp(409, 'VERSION_CONFLICT', '字典已被更新，请刷新后重试。', { object: 'class', expected_version: body.expected_version, current_version: c.version }, requestId)
    if (c.class_id === 'unknown' && body.is_active === false) return errorResp(422, 'VALIDATION_FAILED', 'unknown 不得停用', { fields: [{ field: 'is_active', reason: 'unknown 不得停用' }] }, requestId)
    const before = { name: c.name, is_active: c.is_active, parent_id: c.parent_id }
    if (body.name != null) c.name = String(body.name).trim()
    if (body.parent_id !== undefined) c.parent_id = (body.parent_id as string | null)
    if (body.is_active != null) c.is_active = Boolean(body.is_active)
    if (body.is_provisional != null) c.is_provisional = Boolean(body.is_provisional)
    c.version += 1
    c.updated_at = new Date().toISOString()
    appendAudit(user, 'dict.update', 'class', c.class_id, before, { name: c.name, is_active: c.is_active, parent_id: c.parent_id }, requestId)
    return json(200, { class_id: c.class_id, name: c.name, parent_id: c.parent_id, is_active: c.is_active, is_provisional: c.is_provisional, introduced_taxonomy_version: c.introduced_taxonomy_version, deprecated_taxonomy_version: c.deprecated_taxonomy_version, version: c.version })
  }

  // 类别 CSV 导入（F1：类别导入；品种 CSV 隐藏）
  if (path === '/api/v1/admin/classes/import/preview' && method === 'POST') {
    const err = requireRole(user, ['super_admin'], requestId)
    if (err) return err
    // 模拟：预览从 form 文件计算 SHA-256（实际为文件名哈希，演示用）
    const fileHash = sha256Hex(encodeUtf8(JSON.stringify(body)))
    return json(200, { file_sha256: fileHash, baseline_taxonomy_version: taxonomyVersion, added: 1, changed: 0, unchanged: 3, rejected: 0, row_errors: [] })
  }
  if (path === '/api/v1/admin/classes/import' && method === 'POST') {
    const err = requireRole(user, ['super_admin'], requestId)
    if (err) return err
    if (body.baseline_taxonomy_version !== taxonomyVersion) {
      return errorResp(409, 'STATE_CONFLICT', '字典基线已变化，请重新预览', { object: 'taxonomy', current_state: String(taxonomyVersion), allowed_from: [String(body.baseline_taxonomy_version)] }, requestId)
    }
    taxonomyVersion += 1
    appendAudit(user, 'dict.import', 'class', 'import', null, { taxonomy_version: taxonomyVersion }, requestId)
    return json(200, { taxonomy_version: taxonomyVersion, added: 1, changed: 0, unchanged: 3 })
  }

  // 账号
  if (path === '/api/v1/admin/users' && method === 'GET') {
    const err = requireRole(user, ['super_admin'], requestId)
    if (err) return err
    const page = Math.max(1, parseInt(query.page || '1', 10) || 1)
    const pageSize = Math.min(100, Math.max(1, parseInt(query.page_size || '20', 10) || 20))
    const list = users.map((u) => ({ user_id: u.user_id, username: u.username, display_name: u.display_name, role: u.role, is_active: u.is_active, created_at: u.created_at, last_login_at: u.last_login_at }))
    const start = (page - 1) * pageSize
    return json(200, { items: list.slice(start, start + pageSize), page, page_size: pageSize, total: list.length })
  }
  if (path === '/api/v1/admin/users' && method === 'POST') {
    const err = requireRole(user, ['super_admin'], requestId)
    if (err) return err
    const username = String(body.username ?? '')
    if (!/^[a-z][a-z0-9_.-]{2,31}$/.test(username)) return errorResp(422, 'VALIDATION_FAILED', '登录名不合法', { fields: [{ field: 'username', reason: '格式不符' }] }, requestId)
    if (users.some((u) => u.username === username)) return errorResp(409, 'STATE_CONFLICT', '登录名已存在', { object: 'user', current_state: 'exists' }, requestId)
    const display_name = String(body.display_name ?? '').trim()
    if (!display_name) return errorResp(422, 'VALIDATION_FAILED', '显示名必填', { fields: [{ field: 'display_name', reason: 'required' }] }, requestId)
    const role = body.role as Role
    if (!['collector', 'admin', 'super_admin', 'expert'].includes(role)) return errorResp(422, 'VALIDATION_FAILED', '角色不合法', { fields: [{ field: 'role', reason: '未知值' }] }, requestId)
    const row: MockUser = { user_id: uuidv7(), username, display_name, role, is_active: true, password: 'Temp-' + Math.random().toString(36).slice(2, 8), created_at: new Date().toISOString(), last_login_at: null }
    users.push(row)
    const temporaryPassword = row.password
    appendAudit(user, 'user.create', 'user', row.user_id, null, { username, role }, requestId)
    return json(201, { user: { user_id: row.user_id, username: row.username, display_name: row.display_name, role: row.role, is_active: row.is_active, created_at: row.created_at, last_login_at: row.last_login_at }, temporary_password: temporaryPassword })
  }
  const userMatch = path.match(/^\/api\/v1\/admin\/users\/([0-9a-f-]{36})(\/reset-password)?$/)
  if (userMatch && method === 'PATCH' && !userMatch[2]) {
    const err = requireRole(user, ['super_admin'], requestId)
    if (err) return err
    const u = users.find((x) => x.user_id === userMatch[1])
    if (!u) return errorResp(404, 'NOT_FOUND', '账号不存在', { resource: 'user' }, requestId)
    if (u.user_id === user.user_id && body.is_active === false) return errorResp(409, 'STATE_CONFLICT', '不能停用当前登录账号', { object: 'user', current_state: 'self' }, requestId)
    const before = { display_name: u.display_name, role: u.role, is_active: u.is_active }
    if (body.display_name != null) u.display_name = String(body.display_name).trim()
    if (body.role != null) u.role = body.role as Role
    if (body.is_active != null) {
      u.is_active = Boolean(body.is_active)
      if (!u.is_active) {
        for (const [token, s] of sessions) {
          if (s.user_id === u.user_id) sessions.delete(token)
        }
      }
    }
    appendAudit(user, 'user.update', 'user', u.user_id, before, { display_name: u.display_name, role: u.role, is_active: u.is_active }, requestId)
    return json(200, { user_id: u.user_id, username: u.username, display_name: u.display_name, role: u.role, is_active: u.is_active, created_at: u.created_at, last_login_at: u.last_login_at })
  }
  if (userMatch && method === 'POST' && userMatch[2] === '/reset-password') {
    const err = requireRole(user, ['super_admin'], requestId)
    if (err) return err
    const u = users.find((x) => x.user_id === userMatch[1])
    if (!u) return errorResp(404, 'NOT_FOUND', '账号不存在', { resource: 'user' }, requestId)
    const temporaryPassword = 'Temp-' + Math.random().toString(36).slice(2, 8)
    u.password = temporaryPassword
    appendAudit(user, 'user.reset_password', 'user', u.user_id, null, null, requestId)
    return json(200, { temporary_password: temporaryPassword })
  }

  // 审计
  if (path === '/api/v1/admin/audit' && method === 'GET') {
    const err = requireRole(user, ['super_admin'], requestId)
    if (err) return err
    let list = [...audit]
    if (query.object_type) list = list.filter((a) => a.object_type === query.object_type)
    if (query.object_id) list = list.filter((a) => a.object_id === query.object_id)
    if (query.actor_id) list = list.filter((a) => a.actor_id === query.actor_id)
    if (query.action) list = list.filter((a) => a.action === query.action)
    if (query.from) list = list.filter((a) => a.at.slice(0, 10) >= query.from)
    if (query.to) list = list.filter((a) => a.at.slice(0, 10) <= query.to)
    const page = Math.max(1, parseInt(query.page || '1', 10) || 1)
    const pageSize = Math.min(100, Math.max(1, parseInt(query.page_size || '20', 10) || 20))
    const start = (page - 1) * pageSize
    return json(200, { items: list.slice(start, start + pageSize), page, page_size: pageSize, total: list.length })
  }

  // 专家工单（F2）
  if (path === '/api/v1/expert/tickets' && method === 'GET') {
    const err = requireRole(user, ['expert', 'super_admin'], requestId)
    if (err) return err
    let list = tickets
    if (query.status) list = list.filter((t) => t.status === query.status)
    if (query.assignee === 'me') list = list.filter((t) => t.assignee_id === user.user_id)
    else if (query.assignee === 'unassigned') list = list.filter((t) => t.assignee_id == null)
    const page = Math.max(1, parseInt(query.page || '1', 10) || 1)
    const pageSize = Math.min(100, Math.max(1, parseInt(query.page_size || '20', 10) || 20))
    const start = (page - 1) * pageSize
    const items = list.map((t) => ({ ticket_id: t.ticket_id, question_id: t.question_id, status: t.status, outcome: t.outcome, assignee_id: t.assignee_id, assignee_display_name: t.assignee_id ? displayName(users.find((u) => u.user_id === t.assignee_id)) : null, version: t.version, created_at: t.created_at, updated_at: t.updated_at, question_text: t.question.text, question_status: t.question.status }))
    return json(200, { items: items.slice(start, start + pageSize), page, page_size: pageSize, total: items.length })
  }
  const ticketMatch = path.match(/^\/api\/v1\/expert\/tickets\/([0-9a-f-]{36})(\/(claim|draft|request-info|answer|unresolve))?$/)
  if (ticketMatch && method === 'GET' && !ticketMatch[2]) {
    const err = requireRole(user, ['expert', 'super_admin'], requestId)
    if (err) return err
    const t = tickets.find((x) => x.ticket_id === ticketMatch[1])
    if (!t) return errorResp(404, 'NOT_FOUND', '工单不存在或不可见', { resource: 'ticket' }, requestId)
    return json(200, toTicketDetail(t))
  }
  if (ticketMatch && ticketMatch[2] && method === 'POST') {
    const err = requireRole(user, ['expert', 'super_admin'], requestId)
    if (err) return err
    const t = tickets.find((x) => x.ticket_id === ticketMatch[1])
    if (!t) return errorResp(404, 'NOT_FOUND', '工单不存在或不可见', { resource: 'ticket' }, requestId)
    const action = ticketMatch[2].slice(1)
    if (body.expected_version !== t.version) {
      return errorResp(409, 'VERSION_CONFLICT', '工单已被更新，请刷新后重试。', { object: 'ticket', expected_version: body.expected_version, current_version: t.version }, requestId)
    }
    if (action === 'claim') {
      if (t.status !== 'queued') return errorResp(409, 'STATE_CONFLICT', '仅排队工单可领取', { object: 'ticket', current_state: t.status, allowed_from: ['queued'] }, requestId)
      if (t.assignee_id && t.assignee_id !== user.user_id) return errorResp(409, 'STATE_CONFLICT', '工单已被他人领取', { object: 'ticket', current_state: 'assigned' }, requestId)
      t.status = 'reviewing'
      t.assignee_id = user.user_id
      t.claimed_at = new Date().toISOString()
      t.version += 1
      t.events.push({ event_id: uuidv7(), action: 'claim', actor_display_name: user.display_name, at: new Date().toISOString(), version: t.version, payload: null })
      appendAudit(user, 'ticket.claim', 'ticket', t.ticket_id, null, { status: t.status }, requestId)
      return json(200, toTicketDetail(t))
    }
    if (action === 'draft') {
      if (t.assignee_id !== user.user_id) return errorResp(403, 'FORBIDDEN', '仅领取者可操作', { required_role: 'expert' }, requestId)
      t.draft = String(body.draft ?? '')
      t.version += 1
      t.events.push({ event_id: uuidv7(), action: 'save_draft', actor_display_name: user.display_name, at: new Date().toISOString(), version: t.version, payload: { draft: t.draft } })
      appendAudit(user, 'ticket.draft', 'ticket', t.ticket_id, null, { draft: t.draft }, requestId)
      return json(200, toTicketDetail(t))
    }
    if (action === 'request-info') {
      if (t.assignee_id !== user.user_id) return errorResp(403, 'FORBIDDEN', '仅领取者可操作', { required_role: 'expert' }, requestId)
      if (t.status !== 'reviewing') return errorResp(409, 'STATE_CONFLICT', '当前状态不允许要求补充', { object: 'ticket', current_state: t.status, allowed_from: ['reviewing'] }, requestId)
      t.status = 'needs_info'
      t.question.status = 'needs_info'
      t.version += 1
      t.events.push({ event_id: uuidv7(), action: 'request_info', actor_display_name: user.display_name, at: new Date().toISOString(), version: t.version, payload: { request_text: body.request_text } })
      appendAudit(user, 'ticket.request_info', 'ticket', t.ticket_id, null, { status: t.status }, requestId)
      return json(200, toTicketDetail(t))
    }
    if (action === 'answer') {
      if (t.assignee_id !== user.user_id) return errorResp(403, 'FORBIDDEN', '仅领取者可操作', { required_role: 'expert' }, requestId)
      if (t.status === 'needs_info') return errorResp(409, 'STATE_CONFLICT', '等待补充期间不能直接答复', { object: 'ticket', current_state: t.status, allowed_from: ['reviewing'] }, requestId)
      if (t.status !== 'reviewing') return errorResp(409, 'STATE_CONFLICT', '当前状态不允许答复', { object: 'ticket', current_state: t.status, allowed_from: ['reviewing'] }, requestId)
      t.status = 'done'
      t.outcome = 'answered'
      t.closed_at = new Date().toISOString()
      t.question.status = 'expert_answered'
      t.version += 1
      t.events.push({ event_id: uuidv7(), action: 'answer', actor_display_name: user.display_name, at: new Date().toISOString(), version: t.version, payload: { answer_text: body.answer_text } })
      appendAudit(user, 'ticket.answer', 'ticket', t.ticket_id, null, { outcome: t.outcome }, requestId)
      return json(200, toTicketDetail(t))
    }
    if (action === 'unresolve') {
      if (t.assignee_id !== user.user_id) return errorResp(403, 'FORBIDDEN', '仅领取者可操作', { required_role: 'expert' }, requestId)
      if (t.status !== 'reviewing') return errorResp(409, 'STATE_CONFLICT', '当前状态不允许无法判断', { object: 'ticket', current_state: t.status, allowed_from: ['reviewing'] }, requestId)
      t.status = 'done'
      t.outcome = 'unresolved'
      t.closed_at = new Date().toISOString()
      t.question.status = 'expert_unresolved'
      t.version += 1
      t.events.push({ event_id: uuidv7(), action: 'unresolve', actor_display_name: user.display_name, at: new Date().toISOString(), version: t.version, payload: { outcome: t.outcome } })
      appendAudit(user, 'ticket.unresolve', 'ticket', t.ticket_id, null, { outcome: t.outcome }, requestId)
      return json(200, toTicketDetail(t))
    }
  }

  return errorResp(404, 'NOT_FOUND', '资源不存在或不可见', { resource: path }, requestId)
}

function toTicketDetail(t: TicketRecord): Record<string, unknown> {
  return {
    ticket_id: t.ticket_id,
    question_id: t.question_id,
    status: t.status,
    outcome: t.outcome,
    assignee_id: t.assignee_id,
    assignee_display_name: t.assignee_id ? displayName(users.find((u) => u.user_id === t.assignee_id)) : null,
    draft: t.draft,
    version: t.version,
    created_at: t.created_at,
    updated_at: t.updated_at,
    claimed_at: t.claimed_at,
    closed_at: t.closed_at,
    question: t.question,
    events: t.events,
  }
}

function getAccessTokenOf(headers: Record<string, string>): string {
  const auth = headers['authorization'] || ''
  return auth.replace(/^Bearer\s+/i, '')
}
