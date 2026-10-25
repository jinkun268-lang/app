// F2 专家工单。普通 admin 无权限（服务端 403）；F1 默认不开放此入口。
import { request } from './http'
import type {
  TicketActionRequest, TicketAnswerRequest, TicketDetail, TicketDraftRequest, TicketRequestInfoRequest,
  TicketSummaryPage, TicketUnresolveRequest,
} from '../types'

export interface TicketQuery {
  status?: string
  assignee?: 'me' | 'unassigned' | 'all'
  page?: number
  page_size?: number
}

export function listTickets(query: TicketQuery = {}): Promise<TicketSummaryPage> {
  return request<TicketSummaryPage>({ path: '/expert/tickets', query: query as Record<string, string | number | undefined> })
}

export function getTicket(ticketId: string): Promise<TicketDetail> {
  return request<TicketDetail>({ path: `/expert/tickets/${ticketId}` })
}

export function claimTicket(ticketId: string, payload: TicketActionRequest, idempotencyKey: string): Promise<TicketDetail> {
  return request<TicketDetail>({ path: `/expert/tickets/${ticketId}/claim`, method: 'POST', body: payload, idempotencyKey })
}

export function saveTicketDraft(ticketId: string, payload: TicketDraftRequest, idempotencyKey: string): Promise<TicketDetail> {
  return request<TicketDetail>({ path: `/expert/tickets/${ticketId}/draft`, method: 'POST', body: payload, idempotencyKey })
}

export function requestTicketInfo(ticketId: string, payload: TicketRequestInfoRequest, idempotencyKey: string): Promise<TicketDetail> {
  return request<TicketDetail>({ path: `/expert/tickets/${ticketId}/request-info`, method: 'POST', body: payload, idempotencyKey })
}

export function answerTicket(ticketId: string, payload: TicketAnswerRequest, idempotencyKey: string): Promise<TicketDetail> {
  return request<TicketDetail>({ path: `/expert/tickets/${ticketId}/answer`, method: 'POST', body: payload, idempotencyKey })
}

export function unresolveTicket(ticketId: string, payload: TicketUnresolveRequest, idempotencyKey: string): Promise<TicketDetail> {
  return request<TicketDetail>({ path: `/expert/tickets/${ticketId}/unresolve`, method: 'POST', body: payload, idempotencyKey })
}
