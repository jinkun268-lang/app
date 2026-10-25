// 开发态模拟开关与出口。
// 默认连接真实服务；只有开发时显式 VITE_ENABLE_MOCK=true 才启用模拟。
// 测试夹具自行启用模拟，请求失败不会回退到模拟（见 http.ts）。
import { mockDispatch, resetMock, mockControl, expireAccessTokens } from './server'

let enabled = import.meta.env.DEV && import.meta.env.VITE_ENABLE_MOCK === 'true'

export function isMockEnabled(): boolean {
  return enabled
}

export function setMockEnabled(value: boolean): void {
  enabled = value
}

export { mockDispatch, resetMock, mockControl, expireAccessTokens }
export type { MockDispatchInput, MockDispatchResult } from './server'
