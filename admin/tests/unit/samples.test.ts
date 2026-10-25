import { describe, expect, it } from 'vitest'
import { excludeSample, getSample, listSamples, restoreSample, reviewSample, setImageQuality } from '../../src/api/samples'
import { getBootstrap } from '../../src/api/auth'
import { loginAs } from '../helpers'

describe('样本与审核', () => {
  it('super_admin 与 admin 都可见全部样本（无果园范围）', async () => {
    const all = await loginAs('super')
    const superList = await listSamples({ page: 1, page_size: 100 })
    expect(superList.total).toBe(5)
    expect(all.user.role).toBe('super_admin')

    await loginAs('admin')
    const adminList = await listSamples({ page: 1, page_size: 100 })
    expect(adminList.total).toBe(5)
    // 原先分属两个果园的样本现在都可见
    const ids = adminList.items.map((s) => s.sample_id)
    expect(ids).toContain('019a0001-0000-7000-8000-000000000003')
    expect(ids).toContain('019a0001-0000-7000-8000-000000000005')
    // 摘要不再携带果园字段
    expect(adminList.items.every((s) => !('orchard_id' in s) && !('orchard_name' in s))).toBe(true)
    // 且可打开详情并审核
    const detail = await getSample('019a0001-0000-7000-8000-000000000003')
    expect(detail.sample_id).toBe('019a0001-0000-7000-8000-000000000003')
  })

  it('bootstrap 不再返回 orchards，仍提供品种/类别/版本', async () => {
    await loginAs('admin')
    const data = await getBootstrap()
    expect('orchards' in data).toBe(false)
    expect(data.cultivars.length).toBeGreaterThan(0)
    expect(data.classes.length).toBeGreaterThan(0)
    expect(data.taxonomy_version).toBeGreaterThan(0)
    expect(data.server_time).toBeTruthy()
  })

  it('不存在的样本返回 404，不展示其他样本', async () => {
    await loginAs('super')
    await expect(getSample('019a0001-0000-7000-8000-000000000099')).rejects.toMatchObject({ code: 'NOT_FOUND', status: 404 })
  })

  it('修正必须至少一项变化，否则 422', async () => {
    await loginAs('super')
    const sampleId = '019a0001-0000-7000-8000-000000000001'
    await expect(
      reviewSample(sampleId, {
        expected_version: 0,
        review_status: 'corrected',
        final_cultivar_id: 'huyou',
        final_part: 'leaf',
        final_class_id: 'unknown',
        review_note: null,
      }),
    ).rejects.toMatchObject({ code: 'VALIDATION_FAILED', status: 422 })
  })

  it('审核成功递增版本，旧版本保存返回 409', async () => {
    await loginAs('super')
    const sampleId = '019a0001-0000-7000-8000-000000000001'
    const d = await reviewSample(sampleId, {
      expected_version: 0,
      review_status: 'corrected',
      final_cultivar_id: 'huyou',
      final_part: 'leaf',
      final_class_id: 'citrus_canker',
      review_note: '修正为溃疡病',
    })
    expect(d.review_version).toBe(1)
    expect(d.final_class_id).toBe('citrus_canker')
    await expect(
      reviewSample(sampleId, { expected_version: 0, review_status: 'corrected', final_cultivar_id: 'huyou', final_part: 'leaf', final_class_id: 'citrus_canker', review_note: null }),
    ).rejects.toMatchObject({ code: 'VERSION_CONFLICT', status: 409 })
  })

  it('unresolved 不带最终值，带值返回 422', async () => {
    await loginAs('super')
    const sampleId = '019a0001-0000-7000-8000-000000000001'
    await expect(
      reviewSample(sampleId, { expected_version: 0, review_status: 'unresolved', final_class_id: 'citrus_canker', review_note: null }),
    ).rejects.toMatchObject({ code: 'VALIDATION_FAILED', status: 422 })
    const d = await reviewSample(sampleId, { expected_version: 0, review_status: 'unresolved', review_note: '无法判断' })
    expect(d.review_status).toBe('unresolved')
    expect(d.final_class_id).toBeNull()
  })

  it('单图不可用必须给原因，每图独立版本', async () => {
    await loginAs('super')
    const sampleId = '019a0001-0000-7000-8000-000000000001'
    await reviewSample(sampleId, { expected_version: 0, review_status: 'corrected', final_cultivar_id: 'huyou', final_part: 'leaf', final_class_id: 'citrus_canker' })
    const imageId = '019a0001-0000-7001-8000-000000000001'
    await expect(setImageQuality(sampleId, imageId, { expected_version: 0, quality_status: 'unusable', quality_reason_code: null })).rejects.toMatchObject({
      code: 'VALIDATION_FAILED',
      status: 422,
    })
    const img = await setImageQuality(sampleId, imageId, { expected_version: 0, quality_status: 'unusable', quality_reason_code: 'blur' })
    expect(img.quality_status).toBe('unusable')
    expect(img.quality_version).toBe(1)
    await expect(setImageQuality(sampleId, imageId, { expected_version: 0, quality_status: 'usable', quality_reason_code: null })).rejects.toMatchObject({
      code: 'VERSION_CONFLICT',
      status: 409,
    })
  })

  it('排除与恢复携带版本，不删除记录', async () => {
    await loginAs('super')
    const sampleId = '019a0001-0000-7000-8000-000000000001'
    const d = await excludeSample(sampleId, { expected_version: 0, reason: '测试排除' })
    expect(d.excluded).toBe(true)
    expect(d.images.length).toBeGreaterThan(0)
    const r = await restoreSample(sampleId, { expected_version: d.review_version, reason: null })
    expect(r.excluded).toBe(false)
  })
})
