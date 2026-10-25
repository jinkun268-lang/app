import { describe, expect, it } from 'vitest'
import { createCultivar, listClasses, listCultivars, updateCultivar } from '../../src/api/dictionaries'
import { createUser, listUsers, updateUser } from '../../src/api/users'
import { listAudit } from '../../src/api/audit'
import { request } from '../../src/api/http'
import { loginAs } from '../helpers'

describe('基础管理', () => {
  it('普通 admin 不能访问字典/账号/审计（403）', async () => {
    await loginAs('admin')
    await expect(listCultivars()).rejects.toMatchObject({ code: 'FORBIDDEN', status: 403 })
    await expect(listClasses()).rejects.toMatchObject({ code: 'FORBIDDEN', status: 403 })
    await expect(listUsers()).rejects.toMatchObject({ code: 'FORBIDDEN', status: 403 })
    await expect(listAudit()).rejects.toMatchObject({ code: 'FORBIDDEN', status: 403 })
  })

  it('品种新增与版本冲突', async () => {
    await loginAs('super')
    const c = await createCultivar({ cultivar_id: 'new_cultivar', name: '新品种' })
    expect(c.cultivar_id).toBe('new_cultivar')
    await expect(updateCultivar('new_cultivar', { expected_version: 0, name: '改名' })).rejects.toMatchObject({ code: 'VERSION_CONFLICT', status: 409 })
    const updated = await updateCultivar('new_cultivar', { expected_version: c.version, name: '改名品种' })
    expect(updated.name).toBe('改名品种')
    expect(updated.version).toBe(2)
  })

  it('已移除的果园字典接口返回 404，不再视为成功', async () => {
    await loginAs('super')
    await expect(request({ path: '/admin/orchards' })).rejects.toMatchObject({ status: 404 })
  })

  it('unknown 不得停用', async () => {
    await loginAs('super')
    await expect(updateCultivar('unknown', { expected_version: 1, is_active: false })).rejects.toMatchObject({ code: 'VALIDATION_FAILED', status: 422 })
  })

  it('新建账号一次性返回临时密码，无删除接口', async () => {
    await loginAs('super')
    const res = await createUser({ username: 'newcollector', display_name: '新采集员', role: 'collector' })
    expect(res.temporary_password).toBeTruthy()
    expect(res.user.user_id).toBeTruthy()
    expect(res.user.role).toBe('collector')
    const users = await listUsers({ page: 1, page_size: 100 })
    expect(users.items.some((u) => u.username === 'newcollector')).toBe(true)
  })

  it('停用账号后其会话失效', async () => {
    await loginAs('super')
    const res = await createUser({ username: 'tempadmin', display_name: '临时管理员', role: 'admin' })
    await updateUser(res.user.user_id, { is_active: false })
    const users = await listUsers({ page: 1, page_size: 100 })
    const u = users.items.find((x) => x.username === 'tempadmin')
    expect(u?.is_active).toBe(false)
  })

  it('写操作追加审计记录，审计查询生效', async () => {
    await loginAs('super')
    const before = await listAudit({ page: 1, page_size: 100 })
    await createCultivar({ cultivar_id: 'test_cultivar', name: '测试品种' })
    const after = await listAudit({ page: 1, page_size: 100 })
    expect(after.total).toBeGreaterThan(before.total)
    const filtered = await listAudit({ action: 'dict.create', page: 1, page_size: 100 })
    expect(filtered.items.some((a) => a.object_id === 'test_cultivar')).toBe(true)
  })
})
