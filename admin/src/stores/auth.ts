// 认证 store：会话初始化先于路由决策（App 挂载前 await init()）。
// 访问令牌驻内存、刷新令牌在 sessionStorage（tokens.ts）；不持久信任本地 role。
// opSeq 是会话/操作代际：init、login、clearSession 各自开启一代；异步操作在每个
// await 后校验代际，迟到的旧结果（pending init/login 后退出或换账号）不得覆盖新会话。
import { defineStore } from 'pinia'
import { login as apiLogin, getMe, refresh as apiRefresh } from '../api/auth'
import { ApiError, request } from '../api/http'
import { beginSession, clearTokens, getAccessToken, getRefreshToken, onUnauthorized, setTokens } from '../auth/tokens'
import { clearMediaCache } from '../media/cache'
import type { AuthUser, MeResponse, Role } from '../types'

interface Account {
  user_id: string
  username: string
  display_name: string
  role: Role
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    account: null as Account | null,
    initialized: false,
    opSeq: 0,
  }),
  getters: {
    isAuthed: (s) => !!s.account,
    role: (s): Role | null => s.account?.role ?? null,
    isSuper: (s) => s.account?.role === 'super_admin',
    isAdmin: (s) => s.account?.role === 'admin',
    isExpert: (s) => s.account?.role === 'expert',
  },
  actions: {
    setAccount(user: AuthUser | MeResponse) {
      this.account = {
        user_id: user.user_id,
        username: user.username,
        display_name: user.display_name,
        role: user.role,
      }
    },
    clearSession() {
      this.opSeq += 1 // 使 pending 的 init/login 结果作废
      clearTokens()
      clearMediaCache()
      this.account = null
    },
    async init() {
      const seq = ++this.opSeq
      const rt = getRefreshToken()
      if (!rt) {
        this.initialized = true
        return
      }
      try {
        const resp = await apiRefresh({ refresh_token: rt })
        if (seq !== this.opSeq) return // 期间已退出或换账号：不恢复旧会话
        if (!resp || typeof resp.access_token !== 'string' || !resp.access_token.trim() || typeof resp.refresh_token !== 'string' || !resp.refresh_token.trim()) {
          throw new ApiError(502, 'INTERNAL', '刷新响应缺少有效令牌')
        }
        setTokens(resp.access_token, resp.refresh_token)
        const me = await getMe()
        if (seq !== this.opSeq) return
        this.setAccount(me)
      } catch (error) {
        // 暂时无法恢复时保留刷新令牌，后续仍可重试；只处理明确的认证失效。
        if (seq === this.opSeq && error instanceof ApiError &&
          (error.status === 401 || (error.status === 403 && error.code === 'ACCOUNT_DISABLED'))) {
          this.clearSession()
        }
      } finally {
        this.initialized = true
      }
    },
    async login(username: string, password: string) {
      const seq = ++this.opSeq
      const resp = await apiLogin({ username, password })
      if (seq !== this.opSeq) return // 已被退出或更新的登录取代：丢弃本次结果
      // 登录/换账号开启新会话代际，旧会话在途的刷新与请求不得写回或清空本会话
      beginSession(resp.access_token, resp.refresh_token)
      this.setAccount(resp.user)
    },
    async logout() {
      // 先同步失效本地会话：在途请求与刷新随即按旧会话丢弃，不等待网络
      const access = getAccessToken()
      this.clearSession()
      if (!access) return // 未持访问令牌：本地已清理，无需通知服务端
      // 用退出前捕获的旧访问令牌尽力通知服务端；skipAuth + 显式头，不借用新会话凭据
      try {
        await request<void>({
          path: '/auth/logout',
          method: 'POST',
          responseType: 'none',
          skipAuth: true,
          headers: { authorization: `Bearer ${access}` },
        })
      } catch {
        // 服务端退出尽力而为，失败不影响本地清理
      }
    },
  },
})

// 会话失效（刷新失败等）时清理本地状态；路由守卫据此跳转登录。
onUnauthorized(() => {
  try {
    useAuthStore().clearSession()
  } catch {
    // store 尚未初始化时忽略
  }
})
