import { login } from '../src/api/auth'
import { setTokens } from '../src/auth/tokens'

export async function loginAs(username: string, password = '12345678') {
  const resp = await login({ username, password })
  setTokens(resp.access_token, resp.refresh_token)
  return resp
}

export function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}

export async function waitFor<T>(fn: () => Promise<T>, predicate: (v: T) => boolean, timeout = 3000, interval = 10): Promise<T> {
  const start = Date.now()
  let last: T
  for (;;) {
    last = await fn()
    if (predicate(last)) return last
    if (Date.now() - start > timeout) throw new Error('waitFor 超时')
    await sleep(interval)
  }
}
