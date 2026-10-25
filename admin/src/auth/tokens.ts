// 令牌存储口径（docs/app/standards/06 第 4 节、admin-storage-design A1）：
// - 访问令牌仅驻内存（不持久化）；
// - 刷新令牌放 sessionStorage，关闭标签页失效，不做“记住我”；
// - 退出/切换账号清理全部令牌与派生状态。
// 本模块是 http 客户端与 auth store 之间唯一令牌读写通道。
//
// 会话代际（epoch）：登录、退出、换账号进入新代际；同一会话内的令牌轮换代际不变。
// http 客户端以“请求发出时的代际 + 访问令牌快照”区分迟到的旧 401 与会话切换。

const REFRESH_KEY = 'citrus_admin_refresh'

let accessToken: string | null = null
let sessionEpoch = 0

type UnauthorizedListener = () => void
const listeners = new Set<UnauthorizedListener>()

export function getAccessToken(): string | null {
  return accessToken
}

export function getRefreshToken(): string | null {
  try {
    return sessionStorage.getItem(REFRESH_KEY)
  } catch {
    return null
  }
}

// 同一会话内的令牌轮换（刷新）：代际不变。
export function setTokens(access: string, refresh: string): void {
  accessToken = access
  try {
    sessionStorage.setItem(REFRESH_KEY, refresh)
  } catch {
    // sessionStorage 不可用时仅保留内存访问令牌
  }
}

// 登录/换账号开启新会话：写入令牌并进入新代际。
export function beginSession(access: string, refresh: string): void {
  sessionEpoch += 1
  setTokens(access, refresh)
}

export function setAccessToken(access: string): void {
  accessToken = access
}

// 会话结束（退出、失效清理）：清空令牌并进入新代际，
// 旧会话在途的刷新与请求此后不得写回或清理本模块状态。
export function clearTokens(): void {
  sessionEpoch += 1
  accessToken = null
  try {
    sessionStorage.removeItem(REFRESH_KEY)
  } catch {
    // ignore
  }
}

export function getSessionEpoch(): number {
  return sessionEpoch
}

export function onUnauthorized(cb: UnauthorizedListener): () => void {
  listeners.add(cb)
  return () => listeners.delete(cb)
}

export function emitUnauthorized(): void {
  listeners.forEach((cb) => {
    try {
      cb()
    } catch {
      // ignore listener errors
    }
  })
}
