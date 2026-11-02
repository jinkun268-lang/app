import { request } from './http'
import type { TrainingBatchPage, TrainingImagePage } from '../types'

export function listTrainingBatches(page = 1): Promise<TrainingBatchPage> {
  return request({ path: '/training/batches', query: { page, page_size: 100 } })
}
export function listTrainingImages(batchId: string, page = 1, reviewedOnly = false): Promise<TrainingImagePage> {
  return request({ path: `/training/batches/${encodeURIComponent(batchId)}/images`, query: { page, page_size: 100, reviewed_only: reviewedOnly } })
}
