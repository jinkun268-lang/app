import { request } from './http'
import { isMockEnabled } from '../mocks'

export interface OfflineRecognition {
  record_id: string
  owner_display_name: string
  state: string
  uploaded_at: string | null
  captured_at: string
  source: 'device' | 'server'
  crop_id: string
  part: string
  tree_age: string
  symptom: string
  mime_type: string
  file_size: number
  device_model: string
  current_name: string
  current_class_id: string | null
  correction_version: number
  inference_status: 'awaiting_image' | 'processing' | 'succeeded' | 'failed' | null
  inference_error: string | null
  recognition: {
    model: string; model_version: string; warning: string; created_at: string
    candidates: { label: string; name: string; score: number; class_id: string | null }[]
  } | null
  correction_events: { version: number; from_name: string; name: string; note: string; operator: string; corrected_at: string }[]
}
export interface OfflinePage {
  items: OfflineRecognition[]; total: number; categories: string[]
}
export interface OfflineFilters {
  query: string; status: string; names: string[]; start: string; end: string
}

// Calendar days in Asia/Shanghai. End is exclusive at the following midnight.
export function uploadBounds(start: string, end: string) {
  return {
    uploaded_from: start ? new Date(`${start}T00:00:00+08:00`).toISOString() : undefined,
    uploaded_to: end ? new Date(Date.parse(`${end}T00:00:00+08:00`) + 86400000).toISOString() : undefined,
  }
}
export function listOffline(filters: OfflineFilters, page: number): Promise<OfflinePage> {
  const names = new URLSearchParams()
  filters.names.forEach(name => names.append('names', name))
  return request({ path: '/offline-recognitions' + (names.size ? '?' + names : ''),
    query: { query: filters.query, status: filters.status, page, page_size: 20, ...uploadBounds(filters.start, filters.end) } })
}
export function correctOffline(id: string, version: number, name: string, note: string): Promise<OfflineRecognition> {
  return request({ path: `/offline-recognitions/${encodeURIComponent(id)}/correction`, method: 'PATCH',
    body: { expected_version: version, name, note } })
}
export function offlineImage(id: string, preview = true): Promise<Blob> {
  return request({ path: `/offline-recognitions/${encodeURIComponent(id)}/image`, query: { preview }, responseType: 'blob' })
}

export function subscribeOffline(onChange: () => void): () => void {
  if (isMockEnabled()) return () => {}
  let stopped = false, timer: ReturnType<typeof setTimeout> | undefined
  let controller: AbortController | undefined
  async function connect() {
    controller = new AbortController()
    try {
      const stream = await request<ReadableStream<Uint8Array>>({ path: '/offline-recognitions/events', responseType: 'stream', signal: controller.signal })
      const reader = stream.getReader(), decoder = new TextDecoder()
      let buffer = ''
      try {
        while (!stopped) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
          if (buffer.length > 32768) throw new Error('实时更新数据无效')
          let end: number
          while ((end = buffer.indexOf('\n\n')) >= 0) {
            const event = buffer.slice(0, end); buffer = buffer.slice(end + 2)
            if (/^event: (ready|changed)$/m.test(event)) onChange()
          }
        }
      } finally { await reader.cancel().catch(() => {}); reader.releaseLock() }
    } catch { /* Preserve the displayed data while reconnecting. */ }
    if (!stopped) timer = setTimeout(() => void connect(), 2000)
  }
  void connect()
  return () => { stopped = true; if (timer) clearTimeout(timer); controller?.abort() }
}
