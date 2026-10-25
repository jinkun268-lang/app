import { request } from './http'
import type { AuditPage } from '../types'

export interface AuditQuery {
  object_type?: string
  object_id?: string
  actor_id?: string
  action?: string
  from?: string
  to?: string
  page?: number
  page_size?: number
}

export function listAudit(query: AuditQuery = {}): Promise<AuditPage> {
  return request<AuditPage>({ path: '/admin/audit', query: query as Record<string, string | number | undefined> })
}
