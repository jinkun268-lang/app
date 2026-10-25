import { beforeEach } from 'vitest'
import { resetMock, setMockEnabled } from '../src/mocks'
import { clearTokens } from '../src/auth/tokens'

// 每个测试前重置模拟状态与本地令牌，保证测试间不共享可变状态。
beforeEach(() => {
  setMockEnabled(true)
  resetMock()
  clearTokens()
})
