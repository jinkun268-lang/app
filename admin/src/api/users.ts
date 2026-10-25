import { request } from './http'
import type { ResetPasswordResponse, UserCreateRequest, UserCreateResponse, UserPage, UserPatchRequest, UserRow } from '../types'

export function listUsers(query: { page?: number; page_size?: number } = {}): Promise<UserPage> {
  return request<UserPage>({ path: '/admin/users', query: query as Record<string, string | number | undefined> })
}

export function createUser(payload: UserCreateRequest): Promise<UserCreateResponse> {
  return request<UserCreateResponse>({ path: '/admin/users', method: 'POST', body: payload })
}

export function updateUser(userId: string, payload: UserPatchRequest): Promise<UserRow> {
  return request<UserRow>({ path: `/admin/users/${userId}`, method: 'PATCH', body: payload })
}

export function resetPassword(userId: string): Promise<ResetPasswordResponse> {
  return request<ResetPasswordResponse>({ path: `/admin/users/${userId}/reset-password`, method: 'POST' })
}
