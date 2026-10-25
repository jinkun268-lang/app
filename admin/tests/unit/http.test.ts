import { describe, expect, it, vi } from 'vitest'
import { getBootstrap, getMe } from '../../src/api/auth'
import { ApiError, request } from '../../src/api/http'
import { errorMessage } from '../../src/util/error'
import { expireAccessTokens, setMockEnabled } from '../../src/mocks'
import { loginAs } from '../helpers'

describe('http 客户端', () => {
  it('错误按 code 映射中文提示', () => {
    expect(errorMessage(new ApiError(404, 'NOT_FOUND', 'x'))).toContain('不存在或不可见')
    expect(errorMessage(new ApiError(409, 'VERSION_CONFLICT', 'x'))).toContain('更新')
  })

  it('401 过期时共享刷新并重放成功', async () => {
    await loginAs('admin')
    expireAccessTokens()
    const [a, b, c] = await Promise.all([getMe(), getMe(), getMe()])
    expect(a.user_id).toBeTruthy()
    expect(b.user_id).toBe(a.user_id)
    expect(c.user_id).toBe(a.user_id)
  })

  it('模拟关闭时请求失败不回退为演示数据', async () => {
    setMockEnabled(false)
    const fetchStub = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
    vi.stubGlobal('fetch', fetchStub)
    try {
      await expect(request({ path: '/health', skipAuth: true })).rejects.toThrow()
    } finally {
      vi.unstubAllGlobals()
      setMockEnabled(true)
    }
  })

  it('未登录访问受保护接口返回 401 AUTH_REQUIRED', async () => {
    await expect(getBootstrap()).rejects.toMatchObject({ code: 'AUTH_REQUIRED', status: 401 })
  })
})
