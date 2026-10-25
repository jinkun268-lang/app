// 关键 E2E：登录 → 列表 → 详情审核 → 单图质量 → 排除/恢复 → 导出 → 下载校验。
// 通过同一 HTTP 客户端 + 开发态模拟处理器驱动完整垂直切片（真实服务未验证，见 FRONTEND-VERIFICATION.md）。
import { describe, expect, it } from 'vitest'
import { getSample, listSamples, reviewSample, setImageQuality, excludeSample, restoreSample } from '../../src/api/samples'
import { createExport, downloadExport, getExport } from '../../src/api/exports'
import { sha256Hex } from '../../src/mocks/sha256'
import { uuidv7 } from '../../src/util/uuid'
import { loginAs, waitFor } from '../helpers'

const SAMPLE_ID = '019a0001-0000-7000-8000-000000000001'
const IMAGE_ID = '019a0001-0000-7001-8000-000000000001'

describe('F1 垂直切片（前端模拟）', () => {
  it('完整采集数据闭环', async () => {
    // 登录
    const login = await loginAs('super')
    expect(login.user.role).toBe('super_admin')

    // 列表
    const list = await listSamples({ page: 1, page_size: 20 })
    expect(list.total).toBe(5)

    // 详情
    const detail = await getSample(SAMPLE_ID)
    expect(detail.review_status).toBe('unreviewed')

    // 审核修正
    const reviewed = await reviewSample(SAMPLE_ID, {
      expected_version: 0,
      review_status: 'corrected',
      final_cultivar_id: 'huyou',
      final_part: 'leaf',
      final_class_id: 'citrus_canker',
      review_note: '按溃疡病修正',
    })
    expect(reviewed.review_version).toBe(1)
    expect(reviewed.final_class_id).toBe('citrus_canker')

    // 单图质量（不可用 + 原因）
    const img = await setImageQuality(SAMPLE_ID, IMAGE_ID, { expected_version: 0, quality_status: 'unusable', quality_reason_code: 'blur' })
    expect(img.quality_status).toBe('unusable')

    // 排除/恢复
    const excluded = await excludeSample(SAMPLE_ID, { expected_version: reviewed.review_version, reason: '演示排除' })
    expect(excluded.excluded).toBe(true)
    const restored = await restoreSample(SAMPLE_ID, { expected_version: excluded.review_version, reason: null })
    expect(restored.excluded).toBe(false)

    // 导出（此时 sample-1 已修正为溃疡病，但仅 1 张合格图？其 close_up 已废图，context pending → 0 张合格）
    const job = await createExport({ format: 'dataset' }, uuidv7())
    expect(job.export_id).toBeTruthy()

    // 轮询到成功并下载校验
    const done = await waitFor(() => getExport(job.export_id), (j) => j.status === 'succeeded')
    expect(done.zip_sha256).toBeTruthy()
    const { blob } = await downloadExport(job.export_id)
    const bytes = new Uint8Array(await blob.arrayBuffer())
    expect(sha256Hex(bytes)).toBe(done.zip_sha256)
  })
})
