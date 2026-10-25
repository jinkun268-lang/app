// 媒体 Object URL 缓存：按 image_id/variant/w 缓存，换账号/卸载后回收。
import { revokeObjectUrl } from '../api/media'

const cache = new Map<string, string>()

export function mediaCacheKey(imageId: string, variant: string, w?: number): string {
  return `${imageId}:${variant}:${w ?? ''}`
}

export function getMediaUrl(key: string): string | undefined {
  return cache.get(key)
}

export function setMediaUrl(key: string, url: string): void {
  cache.set(key, url)
}

export function clearMediaCache(): void {
  cache.forEach((url) => {
    try {
      revokeObjectUrl(url)
    } catch {
      // ignore
    }
  })
  cache.clear()
}
