import { requestRaw, throwIfError, parseJsonBody } from './http'
import type { MediaPendingResponse } from '../types'

export interface SampleImageVariant {
  variant: 'preview' | 'original'
  w?: 320 | 1024
}

export type MediaFetchResult =
  | { status: 'ok'; blob: Blob }
  | { status: 'pending'; retryAfter: number; imageId: string }
  | { status: 'error' }

// 鉴权媒体：通过 http 客户端携带 Bearer 拉取，不能只拼 <img src> 假设带 Authorization。
// 202 预览生成中由调用方按 Retry-After 重查同一 URL；401/404/解码失败抛 ApiError。
export async function fetchSampleImage(imageId: string, opts: SampleImageVariant = { variant: 'preview', w: 320 }): Promise<MediaFetchResult> {
  const query: Record<string, string | number> = { variant: opts.variant }
  if (opts.variant === 'preview' && opts.w) query.w = opts.w
  const res = await requestRaw({ path: `/media/sample-images/${imageId}`, query, responseType: 'blob' })
  if (res.status === 200) {
    return { status: 'ok', blob: res.body instanceof Blob ? res.body : new Blob([res.body ?? '']) }
  }
  if (res.status === 202) {
    const data = parseJsonBody<MediaPendingResponse>(res)
    return { status: 'pending', retryAfter: data.retry_after ?? 1, imageId: data.image_id }
  }
  throwIfError(res)
  return { status: 'error' }
}

export function objectUrlFromBlob(blob: Blob): string {
  return URL.createObjectURL(blob)
}

export function revokeObjectUrl(url: string): void {
  URL.revokeObjectURL(url)
}
