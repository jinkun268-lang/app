// 认证会话回归：同一会话并发刷新共用一次、迟到 401 复用已轮换令牌、
// 会话切换（登录/退出/换账号）后代际隔离——旧请求不重放、不清理新会话，
// 旧刷新结果不覆盖新会话令牌；刷新区分永久失效与临时故障；终态认证拒绝统一清理。
// 测试关闭模拟并用 fetch 桩精确控制响应时序（deferred 构造迟到响应与发出顺序）。
import { describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { getMe } from '../../src/api/auth'
import { request } from '../../src/api/http'
import { beginSession, getAccessToken, getRefreshToken, setTokens } from '../../src/auth/tokens'
import { useAuthStore } from '../../src/stores/auth'
import { setMockEnabled } from '../../src/mocks'

interface FakeResponse {
  status: number
  headers: Map<string, string>
  text: () => Promise<string>
}

function fakeJson(status: number, obj: unknown): FakeResponse {
  const body = JSON.stringify(obj)
  return {
    status,
    headers: new Map([['content-type', 'application/json; charset=utf-8']]),
    text: async () => body,
  }
}

function fakeHtml(status: number, html: string): FakeResponse {
  return {
    status,
    headers: new Map([['content-type', 'text/html; charset=utf-8']]),
    text: async () => html,
  }
}

function errorResp(status: number, code: string, message: string, details?: Record<string, unknown>): FakeResponse {
  return fakeJson(status, { error: { code, message, details, request_id: 'req-test' } })
}

function expired401(): FakeResponse {
  return errorResp(401, 'AUTH_INVALID', '访问令牌已过期', { reason: 'expired' })
}

function invalid401(): FakeResponse {
  return errorResp(401, 'AUTH_INVALID', '令牌无效或已撤销', { reason: 'invalid' })
}

function refreshOk(access: string, refresh: string): FakeResponse {
  return fakeJson(200, { access_token: access, refresh_token: refresh, token_type: 'Bearer', expires_in: 1800 })
}

function meOk(userId: string): FakeResponse {
  return fakeJson(200, { user_id: userId, username: 'u', display_name: 'U', role: 'admin' })
}

function loginOk(access: string, refresh: string, username: string, role: string): FakeResponse {
  return fakeJson(200, {
    access_token: access,
    refresh_token: refresh,
    token_type: 'Bearer',
    expires_in: 1800,
    user: { user_id: 'u-' + username, username, display_name: username, role },
  })
}

const ADMIN = { user_id: 'u1', username: 'admin1', display_name: '管理员', role: 'admin' as const }

function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((r) => {
    resolve = r
  })
  return { promise, resolve }
}

interface FetchCall {
  url: string
  method: string
  auth: string | undefined
}

// 接管全局 fetch：记录调用，响应由 handler 给出（可返回挂起 Promise 构造迟到响应）。
function stubFetch(handler: (call: FetchCall) => FakeResponse | Promise<FakeResponse>) {
  const calls: FetchCall[] = []
  const fetchStub = vi.fn(async (url: unknown, init?: { method?: string; headers?: Record<string, string> }) => {
    const call: FetchCall = {
      url: String(url),
      method: init?.method ?? 'GET',
      auth: init?.headers?.authorization,
    }
    calls.push(call)
    return handler(call)
  })
  vi.stubGlobal('fetch', fetchStub)
  return {
    calls,
    refreshCalls: () => calls.filter((c) => c.url.endsWith('/auth/refresh')),
  }
}

describe('认证会话与刷新', () => {
  it('启动恢复的临时错误和无效令牌响应保留凭据，账号停用才清理', async () => {
    setMockEnabled(false)
    setActivePinia(createPinia())
    try {
      setTokens('A', 'RT1')
      let response = errorResp(503, 'UNAVAILABLE', '服务暂不可用')
      stubFetch(() => response)
      const auth = useAuthStore()
      await auth.init()
      expect(getRefreshToken()).toBe('RT1')
      response = refreshOk(' ', '')
      await auth.init()
      expect(getAccessToken()).toBe('A')
      expect(getRefreshToken()).toBe('RT1')
      response = errorResp(403, 'ACCOUNT_DISABLED', '账号已停用')
      await auth.init()
      expect(getRefreshToken()).toBeNull()
    } finally {
      vi.unstubAllGlobals()
      setMockEnabled(true)
    }
  })

  it('刷新接口明确返回账号停用时清理会话', async () => {
    setMockEnabled(false)
    setActivePinia(createPinia())
    try {
      setTokens('A', 'RT1')
      const auth = useAuthStore()
      auth.setAccount(ADMIN)
      stubFetch((c) => c.url.endsWith('/auth/refresh')
        ? errorResp(403, 'ACCOUNT_DISABLED', '账号已停用') : expired401())
      await expect(getMe()).rejects.toMatchObject({ status: 401 })
      expect(getRefreshToken()).toBeNull()
      expect(auth.account).toBeNull()
    } finally {
      vi.unstubAllGlobals()
      setMockEnabled(true)
    }
  })

  it('同一会话并发 401 共用一次刷新并各自重放一次', async () => {
    setMockEnabled(false)
    try {
      setTokens('A', 'RT1')
      const { calls, refreshCalls } = stubFetch((c) => {
        if (c.url.endsWith('/auth/refresh')) return refreshOk('B', 'RT2')
        if (c.auth === 'Bearer A') return expired401()
        return meOk('u1')
      })
      const [m1, m2, m3] = await Promise.all([getMe(), getMe(), getMe()])
      expect([m1.user_id, m2.user_id, m3.user_id]).toEqual(['u1', 'u1', 'u1'])
      expect(refreshCalls()).toHaveLength(1)
      const replays = calls.filter((c) => c.url.endsWith('/me') && c.auth === 'Bearer B')
      expect(replays).toHaveLength(3)
    } finally {
      vi.unstubAllGlobals()
      setMockEnabled(true)
    }
  })

  it('迟到的旧 401 复用已轮换令牌重放，不再次刷新', async () => {
    setMockEnabled(false)
    try {
      setTokens('A', 'RT1')
      const stale = deferred<FakeResponse>()
      let staleInFlight = false
      const { calls, refreshCalls } = stubFetch((c) => {
        if (c.url.endsWith('/auth/refresh')) return refreshOk('B', 'RT2')
        if (c.auth === 'Bearer A') {
          if (!staleInFlight) {
            staleInFlight = true
            return stale.promise
          }
          return expired401()
        }
        return meOk('u1')
      })
      const first = getMe() // 携带 A 发出，响应被挂起（fetch 调用是同步发起的）
      const second = await getMe() // 同样携带 A：401 → 刷新轮换为 B → 用 B 重放成功
      expect(second.user_id).toBe('u1')
      stale.resolve(expired401()) // 第一请求此刻才收到对应 A 的过期 401
      const firstMe = await first
      expect(firstMe.user_id).toBe('u1')
      expect(refreshCalls()).toHaveLength(1) // 没有为迟到的 401 再次轮换刷新令牌
      const replays = calls.filter((c) => c.url.endsWith('/me') && c.auth === 'Bearer B')
      expect(replays).toHaveLength(2)
    } finally {
      vi.unstubAllGlobals()
      setMockEnabled(true)
    }
  })

  it('退出后返回的刷新结果不恢复旧登录', async () => {
    setMockEnabled(false)
    setActivePinia(createPinia())
    try {
      setTokens('A', 'RT1')
      const gate = deferred<FakeResponse>()
      const issued = deferred<void>()
      const { calls } = stubFetch((c) => {
        if (c.url.endsWith('/auth/refresh')) {
          issued.resolve()
          return gate.promise
        }
        return expired401()
      })
      const me = getMe() // 401 → 触发刷新（挂起）
      await issued.promise // 确认刷新已发出、尚未返回
      useAuthStore().clearSession() // 退出后的本地清理：清空令牌并进入新代际
      gate.resolve(refreshOk('X', 'RTX')) // 刷新此刻才返回
      await expect(me).rejects.toMatchObject({ status: 401, code: 'AUTH_INVALID' })
      expect(getAccessToken()).toBeNull()
      expect(getRefreshToken()).toBeNull()
      expect(calls).toHaveLength(2) // 原请求 + 刷新：无重放、无再次清理
    } finally {
      vi.unstubAllGlobals()
      setMockEnabled(true)
    }
  })

  it('刷新令牌被服务端拒绝（401）属永久失效，终结会话', async () => {
    setMockEnabled(false)
    setActivePinia(createPinia())
    try {
      setTokens('A', 'RT1')
      stubFetch((c) => (c.url.endsWith('/auth/refresh') ? errorResp(401, 'AUTH_INVALID', '刷新令牌无效或已轮换', { reason: 'invalid' }) : expired401()))
      const auth = useAuthStore()
      auth.setAccount(ADMIN)
      await expect(getMe()).rejects.toMatchObject({ status: 401, code: 'AUTH_INVALID' })
      expect(getAccessToken()).toBeNull()
      expect(getRefreshToken()).toBeNull()
      expect(auth.account).toBeNull() // emitUnauthorized → clearSession
    } finally {
      vi.unstubAllGlobals()
      setMockEnabled(true)
    }
  })

  it('刷新遇网络异常或 5xx 属临时故障：保留会话并向调用者报错', async () => {
    setMockEnabled(false)
    setActivePinia(createPinia())
    try {
      setTokens('A', 'RT1')
      const auth = useAuthStore()
      auth.setAccount(ADMIN)
      let refreshHandler: () => FakeResponse | Promise<FakeResponse> = () =>
        errorResp(503, 'UNAVAILABLE', '服务暂不可用，请稍后重试')
      stubFetch((c) => (c.url.endsWith('/auth/refresh') ? refreshHandler() : expired401()))
      await expect(getMe()).rejects.toMatchObject({ status: 503, code: 'UNAVAILABLE' })
      expect(getAccessToken()).toBe('A')
      expect(getRefreshToken()).toBe('RT1')
      expect(auth.account).not.toBeNull()
      refreshHandler = () => {
        throw new TypeError('Failed to fetch')
      }
      await expect(getMe()).rejects.toMatchObject({ status: 503, code: 'UNAVAILABLE' })
      expect(getAccessToken()).toBe('A')
      expect(getRefreshToken()).toBe('RT1')
      expect(auth.account).not.toBeNull()
    } finally {
      vi.unstubAllGlobals()
      setMockEnabled(true)
    }
  })

  it('普通 403 保留会话；账号停用与永久 401 统一终结会话', async () => {
    setMockEnabled(false)
    setActivePinia(createPinia())
    try {
      const auth = useAuthStore()
      setTokens('A', 'RT1')
      auth.setAccount(ADMIN)
      let meResp: FakeResponse = errorResp(403, 'FORBIDDEN', '无权限执行该操作')
      stubFetch((c) => (c.url.endsWith('/auth/refresh') ? refreshOk('B', 'RT2') : meResp))
      await expect(getMe()).rejects.toMatchObject({ status: 403, code: 'FORBIDDEN' })
      expect(getAccessToken()).toBe('A')
      expect(auth.account).not.toBeNull() // 权限不足不清会话
      meResp = errorResp(403, 'ACCOUNT_DISABLED', '账号已停用')
      await expect(getMe()).rejects.toMatchObject({ status: 403, code: 'ACCOUNT_DISABLED' })
      expect(getAccessToken()).toBeNull()
      expect(auth.account).toBeNull()
      setTokens('A2', 'RT2')
      auth.setAccount(ADMIN)
      meResp = invalid401()
      await expect(getMe()).rejects.toMatchObject({ status: 401, code: 'AUTH_INVALID' })
      expect(getAccessToken()).toBeNull()
      expect(auth.account).toBeNull()
    } finally {
      vi.unstubAllGlobals()
      setMockEnabled(true)
    }
  })

  it('刷新重放后仍被认证拒绝则终结会话', async () => {
    setMockEnabled(false)
    setActivePinia(createPinia())
    try {
      setTokens('A', 'RT1')
      const auth = useAuthStore()
      auth.setAccount(ADMIN)
      stubFetch((c) => {
        if (c.url.endsWith('/auth/refresh')) return refreshOk('B', 'RT2')
        if (c.auth === 'Bearer A') return expired401()
        return invalid401() // 重放携带 B 仍被拒
      })
      await expect(getMe()).rejects.toMatchObject({ status: 401, code: 'AUTH_INVALID' })
      expect(getAccessToken()).toBeNull()
      expect(getRefreshToken()).toBeNull()
      expect(auth.account).toBeNull()
    } finally {
      vi.unstubAllGlobals()
      setMockEnabled(true)
    }
  })

  it('换账号后旧请求的过期 401 不重放、不清理新会话', async () => {
    setMockEnabled(false)
    try {
      setTokens('A', 'RT1')
      const stale = deferred<FakeResponse>()
      const { calls } = stubFetch(() => stale.promise)
      const write = request({
        path: '/samples/00000000-0000-7000-8000-000000000000/exclude',
        method: 'POST',
        body: { expected_version: 1 },
      }) // 旧账号写请求，响应挂起（fetch 同步发起）
      beginSession('B', 'RT2') // 换账号登录（store.login 的本地效果）
      stale.resolve(expired401())
      await expect(write).rejects.toMatchObject({ status: 401 })
      expect(calls).toHaveLength(1) // 未刷新、未拿新账号令牌重放
      expect(getAccessToken()).toBe('B')
      expect(getRefreshToken()).toBe('RT2')
    } finally {
      vi.unstubAllGlobals()
      setMockEnabled(true)
    }
  })

  it('会话切换后各自刷新互不共用，旧刷新结果不覆盖新会话', async () => {
    setMockEnabled(false)
    try {
      setTokens('A', 'RT1')
      const oldGate = deferred<FakeResponse>()
      const newGate = deferred<FakeResponse>()
      const oldIssued = deferred<void>()
      const newIssued = deferred<void>()
      let refreshCount = 0
      const { refreshCalls } = stubFetch((c) => {
        if (c.url.endsWith('/auth/refresh')) {
          refreshCount += 1
          if (refreshCount === 1) {
            oldIssued.resolve()
            return oldGate.promise
          }
          newIssued.resolve()
          return newGate.promise
        }
        if (c.auth === 'Bearer C') return meOk('u2')
        return expired401()
      })
      const oldMe = getMe() // A 过期 → 旧会话刷新（挂起）
      await oldIssued.promise
      beginSession('B', 'RT2') // 换账号
      const newMe = getMe() // B 过期 → 新会话自己的刷新任务
      await newIssued.promise
      expect(refreshCalls()).toHaveLength(2) // 两个会话的刷新并存，不共用 Promise
      oldGate.resolve(refreshOk('OLD', 'OLD_RT'))
      await expect(oldMe).rejects.toMatchObject({ status: 401 }) // 旧请求按原 401 失败
      expect(getAccessToken()).toBe('B') // 旧会话的刷新结果被丢弃
      expect(getRefreshToken()).toBe('RT2')
      newGate.resolve(refreshOk('C', 'RT3'))
      await expect(newMe).resolves.toMatchObject({ user_id: 'u2' })
      expect(getAccessToken()).toBe('C')
      expect(getRefreshToken()).toBe('RT3')
    } finally {
      vi.unstubAllGlobals()
      setMockEnabled(true)
    }
  })

  it('换账号登录后，旧请求失败不清空新账号会话', async () => {
    setMockEnabled(false)
    setActivePinia(createPinia())
    try {
      setTokens('A', 'RT1')
      const stale = deferred<FakeResponse>()
      let staleSealed = false
      const { calls } = stubFetch((c) => {
        if (c.url.endsWith('/auth/login')) return loginOk('B', 'RT2', 'expert1', 'expert')
        if (!staleSealed) {
          staleSealed = true
          return stale.promise
        }
        return expired401()
      })
      const auth = useAuthStore()
      const oldMe = getMe() // 旧账号请求挂起
      await auth.login('expert1', '12345678') // 换账号登录（内部开启新会话代际）
      expect(auth.account?.username).toBe('expert1')
      expect(getAccessToken()).toBe('B')
      stale.resolve(expired401())
      await expect(oldMe).rejects.toMatchObject({ status: 401 })
      expect(calls).toHaveLength(2) // 原请求 + 登录：无刷新、无重放
      expect(auth.account?.username).toBe('expert1') // 新会话未被旧请求清空
      expect(getAccessToken()).toBe('B')
    } finally {
      vi.unstubAllGlobals()
      setMockEnabled(true)
    }
  })

  it('登录在途时退出：迟到的登录结果不恢复会话，服务端退出用旧令牌', async () => {
    setMockEnabled(false)
    setActivePinia(createPinia())
    try {
      setTokens('A', 'RT1')
      const gate = deferred<FakeResponse>()
      const { calls } = stubFetch((c) => {
        if (c.url.endsWith('/auth/login')) return gate.promise
        if (c.url.endsWith('/auth/logout')) return fakeJson(204, {})
        return expired401()
      })
      const auth = useAuthStore()
      const pending = auth.login('admin1', '12345678') // 登录挂起
      await auth.logout() // 期间退出：本地立即清理，并用旧令牌尽力通知服务端
      gate.resolve(loginOk('A2', 'RT1b', 'admin1', 'admin')) // 登录此刻才返回
      await pending
      expect(auth.account).toBeNull()
      expect(getAccessToken()).toBeNull()
      expect(getRefreshToken()).toBeNull()
      const logoutCall = calls.find((c) => c.url.endsWith('/auth/logout'))
      expect(logoutCall?.auth).toBe('Bearer A') // 捕获退出前旧令牌，不借用新会话凭据
    } finally {
      vi.unstubAllGlobals()
      setMockEnabled(true)
    }
  })

  it('并发两次登录：后发起的生效，迟到的先发起登录被丢弃', async () => {
    setMockEnabled(false)
    setActivePinia(createPinia())
    try {
      const firstGate = deferred<FakeResponse>()
      let loginCount = 0
      stubFetch((c) => {
        if (c.url.endsWith('/auth/login')) {
          loginCount += 1
          return loginCount === 1 ? firstGate.promise : loginOk('B', 'RT2', 'expert1', 'expert')
        }
        return expired401()
      })
      const auth = useAuthStore()
      const p1 = auth.login('admin1', '12345678') // 先发起，挂起
      const p2 = auth.login('expert1', '12345678') // 后发起，立即生效
      await p2
      firstGate.resolve(loginOk('A2', 'RT1b', 'admin1', 'admin')) // 先发起的登录此刻才返回
      await p1
      expect(auth.account?.username).toBe('expert1')
      expect(getAccessToken()).toBe('B')
      expect(getRefreshToken()).toBe('RT2')
    } finally {
      vi.unstubAllGlobals()
      setMockEnabled(true)
    }
  })

  it('init 恢复在途时换账号登录：旧 init 返回不覆盖新会话', async () => {
    setMockEnabled(false)
    setActivePinia(createPinia())
    try {
      setTokens('A', 'RT1') // 模拟 sessionStorage 中存留的刷新令牌
      const refreshGate = deferred<FakeResponse>()
      stubFetch((c) => {
        if (c.url.endsWith('/auth/refresh')) return refreshGate.promise
        if (c.url.endsWith('/auth/login')) return loginOk('B', 'RT2', 'expert1', 'expert')
        return expired401()
      })
      const auth = useAuthStore()
      const initP = auth.init() // 刷新挂起
      await auth.login('expert1', '12345678') // init 在途时换账号登录并生效
      refreshGate.resolve(refreshOk('X', 'RTX')) // 旧 init 的刷新此刻才返回
      await initP
      expect(auth.account?.username).toBe('expert1')
      expect(getAccessToken()).toBe('B')
      expect(getRefreshToken()).toBe('RT2')
      expect(auth.initialized).toBe(true)
    } finally {
      vi.unstubAllGlobals()
      setMockEnabled(true)
    }
  })

  it('成功响应为 HTML/非法 JSON 时抛结构化错误，无效刷新成功响应不覆盖令牌', async () => {
    setMockEnabled(false)
    try {
      setTokens('A', 'RT1')
      const refreshHandler: () => FakeResponse = () => fakeHtml(200, '<html>维护页</html>')
      let meHandler: () => FakeResponse = () => fakeHtml(200, '<html>维护页</html>')
      stubFetch((c) => (c.url.endsWith('/auth/refresh') ? refreshHandler() : meHandler()))
      await expect(getMe()).rejects.toMatchObject({ status: 502, code: 'INTERNAL' }) // 业务接口 200 返回 HTML：不伪装业务对象
      meHandler = () => expired401()
      await expect(getMe()).rejects.toMatchObject({ status: 502, code: 'INTERNAL' }) // 刷新 200 返回 HTML：按临时故障报错
      expect(getAccessToken()).toBe('A') // 无效成功响应未覆盖令牌
      expect(getRefreshToken()).toBe('RT1')
    } finally {
      vi.unstubAllGlobals()
      setMockEnabled(true)
    }
  })
})
