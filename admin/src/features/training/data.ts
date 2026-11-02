import { listTrainingBatches, listTrainingImages } from '../../api/training'
import type { TrainingBatch, TrainingImage } from '../../types'

export const reviewed = (image: TrainingImage) => ['confirmed', 'corrected'].includes(image.review_status)
export const qualityNames = { pending: '未质检', usable: '可用', unusable: '不可用' }
export const reviewNames = { reviewed: '已核验', unreviewed: '未核验', all: '全部' }
export const exportQualityNames = { ...qualityNames, all: '不限' }
export const reasonNames = { blur: '模糊', occluded: '遮挡', exposure: '曝光异常', duplicate: '重复图片', wrong_object: '拍摄对象错误', other: '其他' }
export function dateOnly(iso?: string | null) {
  return iso ? new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(iso)) : '—'
}
export function timeText(iso?: string | null) {
  return iso ? new Date(iso).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '—'
}
export function batchState(batch: TrainingBatch) {
  if (!batch.closed) return '采集中'
  if (!batch.image_count) return '暂无图片'
  if (batch.reviewed_count < batch.image_count) return '待核验'
  if (batch.pending_count) return '待质检'
  return '处理完成'
}
export async function loadBatches() {
  const rows: TrainingBatch[] = []
  for (let page = 1; ; page++) {
    const result = await listTrainingBatches(page)
    rows.push(...result.items)
    if (page * result.page_size >= result.total) return rows
  }
}
export async function loadImages(batchId: string, reviewedOnly = false) {
  const rows: TrainingImage[] = []
  for (let page = 1; ; page++) {
    const result = await listTrainingImages(batchId, page, reviewedOnly)
    rows.push(...result.items)
    if (page * result.page_size >= result.total) return rows
  }
}
