import { request } from './http'
import type { BootstrapResponse, LoginRequest, LoginResponse, MeResponse, RefreshRequest, RefreshResponse } from '../types'

export function login(payload: LoginRequest): Promise<LoginResponse> {
  return request<LoginResponse>({ path: '/auth/login', method: 'POST', body: payload, skipAuth: true })
}

export function refresh(payload: RefreshRequest): Promise<RefreshResponse> {
  return request<RefreshResponse>({ path: '/auth/refresh', method: 'POST', body: payload, skipAuth: true })
}

export function logout(): Promise<void> {
  return request<void>({ path: '/auth/logout', method: 'POST', responseType: 'none' })
}

export function getMe(): Promise<MeResponse> {
  return request<MeResponse>({ path: '/me' })
}

export function getBootstrap(): Promise<BootstrapResponse> {
  return request<BootstrapResponse>({ path: '/config/bootstrap' })
}
