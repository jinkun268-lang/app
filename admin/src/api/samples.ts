import { request } from './http'
import type {
  ExcludeRequest, ImageQualityRequest, RestoreRequest, SampleDetail, SampleImage,
  SampleReviewRequest, SampleSummaryPage,
} from '../types'

export interface SampleListQuery {
  batch_id?: string
  review_status?: string
  excluded?: boolean
  final_cultivar_id?: string
  final_class_id?: string
  uploaded_from?: string
  uploaded_to?: string
  q?: string
  page?: number
  page_size?: number
}

export function listSamples(query: SampleListQuery = {}): Promise<SampleSummaryPage> {
  return request<SampleSummaryPage>({ path: '/samples', query: query as Record<string, string | number | boolean | undefined> })
}

export function getSample(sampleId: string): Promise<SampleDetail> {
  return request<SampleDetail>({ path: `/samples/${sampleId}` })
}

export function reviewSample(sampleId: string, payload: SampleReviewRequest): Promise<SampleDetail> {
  return request<SampleDetail>({ path: `/samples/${sampleId}/review`, method: 'PATCH', body: payload })
}

export function setImageQuality(sampleId: string, imageId: string, payload: ImageQualityRequest): Promise<SampleImage> {
  return request<SampleImage>({ path: `/samples/${sampleId}/images/${imageId}/quality`, method: 'PATCH', body: payload })
}

export function excludeSample(sampleId: string, payload: ExcludeRequest): Promise<SampleDetail> {
  return request<SampleDetail>({ path: `/samples/${sampleId}/exclude`, method: 'POST', body: payload })
}

export function restoreSample(sampleId: string, payload: RestoreRequest): Promise<SampleDetail> {
  return request<SampleDetail>({ path: `/samples/${sampleId}/restore`, method: 'POST', body: payload })
}
