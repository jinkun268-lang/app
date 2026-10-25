import { request, requestRaw, throwIfError } from './http'
import type { ExportCreateRequest, ExportJob, ExportJobPage } from '../types'

export interface ExportListQuery {
  page?: number
  page_size?: number
}

export function listExports(query: ExportListQuery = {}): Promise<ExportJobPage> {
  return request<ExportJobPage>({ path: '/exports', query: query as Record<string, string | number | undefined> })
}

export function getExport(exportId: string): Promise<ExportJob> {
  return request<ExportJob>({ path: `/exports/${exportId}` })
}

export function createExport(payload: ExportCreateRequest, idempotencyKey: string): Promise<ExportJob> {
  return request<ExportJob>({ path: '/exports', method: 'POST', body: payload, idempotencyKey })
}

export function retryExport(exportId: string, idempotencyKey: string): Promise<ExportJob> {
  return request<ExportJob>({ path: `/exports/${exportId}/retry`, method: 'POST', idempotencyKey })
}

export interface DownloadResult {
  blob: Blob
  filename: string
}

function filenameFromDisposition(disposition: string | undefined, fallback: string): string {
  if (!disposition) return fallback
  const m = disposition.match(/filename="?([^";]+)"?/)
  return m ? m[1] : fallback
}

export async function downloadExport(exportId: string): Promise<DownloadResult> {
  const res = await requestRaw({ path: `/exports/${exportId}/download`, responseType: 'blob' })
  throwIfError(res)
  // 校验 MIME：非 ZIP 视为服务端返回了错误/JSON，不能当作 ZIP 保存。
  const contentType = res.headers['content-type'] || ''
  if (!/application\/(zip|octet-stream)/.test(contentType)) {
    throw new Error(`导出下载返回了非 ZIP 内容（${contentType}）`)
  }
  const blob = res.body instanceof Blob ? res.body : new Blob([res.body ?? ''])
  return { blob, filename: filenameFromDisposition(res.headers['content-disposition'], `dataset-${exportId}.zip`) }
}
