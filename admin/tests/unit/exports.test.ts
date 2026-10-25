import { describe, expect, it } from 'vitest'
import { createExport, downloadExport, getExport, listExports, retryExport } from '../../src/api/exports'
import { sha256Hex } from '../../src/mocks/sha256'
import { mockControl } from '../../src/mocks'
import { uuidv7 } from '../../src/util/uuid'
import { loginAs, waitFor } from '../helpers'

describe('导出', () => {
  it('创建快照、轮询成功、下载 ZIP 哈希与实际字节一致', async () => {
    await loginAs('super')
    const job = await createExport({ format: 'dataset', uploaded_from: null, uploaded_to: null, final_class_id: null }, uuidv7())
    expect(job.status).toBe('queued')
    expect(job.item_count).toBe(3) // 2 个合格图（sample-2）+ 1 个合格图（sample-3）

    const done = await waitFor(() => getExport(job.export_id), (j) => j.status === 'succeeded')
    expect(done.zip_sha256).toBeTruthy()

    const { blob, filename } = await downloadExport(job.export_id)
    expect(blob.type).toBe('application/zip')
    expect(filename).toBe(`dataset-${job.export_id}.zip`)
    const bytes = new Uint8Array(await blob.arrayBuffer())
    expect(sha256Hex(bytes)).toBe(done.zip_sha256)
  })

  it('同幂等键重复创建返回同一 export_id', async () => {
    await loginAs('super')
    const key = uuidv7()
    const a = await createExport({ format: 'dataset' }, key)
    const b = await createExport({ format: 'dataset' }, key)
    expect(a.export_id).toBe(b.export_id)
  })

  it('失败批次可重试，快照条目不变', async () => {
    await loginAs('super')
    mockControl.failNextExport = true
    const job = await createExport({ format: 'dataset' }, uuidv7())
    const failed = await waitFor(() => getExport(job.export_id), (j) => j.status === 'failed')
    expect(failed.error_code).toBe('FILE_MISMATCH')
    const snapshotCount = failed.item_count

    const retried = await retryExport(job.export_id, uuidv7())
    expect(retried.status).toBe('queued')
    const done = await waitFor(() => getExport(job.export_id), (j) => j.status === 'succeeded')
    expect(done.item_count).toBe(snapshotCount)
  })

  it('导出列表按创建时间倒序返回', async () => {
    await loginAs('super')
    await createExport({ format: 'dataset' }, uuidv7())
    await createExport({ format: 'dataset' }, uuidv7())
    const list = await listExports({ page: 1, page_size: 50 })
    expect(list.items.length).toBeGreaterThanOrEqual(2)
  })
})
