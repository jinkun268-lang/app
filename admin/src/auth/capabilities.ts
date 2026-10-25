// 角色能力判断：路由守卫与菜单渲染的唯一依据。
// 采集、专业核验、训练准备使用同一数据源，但按职责授权。
import type { Role } from '../types'

export type SampleWorkspace = 'collection' | 'review' | 'quality'
export const COLLECTION_ROLES: Role[] = ['collector', 'expert', 'admin', 'super_admin']
export const REVIEW_ROLES: Role[] = ['expert', 'super_admin']
export const TRAINING_ROLES: Role[] = ['admin', 'super_admin']

export function sampleCapabilities(role: Role | null) {
  return {
    readCollection: canAccess(role, COLLECTION_ROLES),
    review: canAccess(role, REVIEW_ROLES),
    prepareTraining: canAccess(role, TRAINING_ROLES),
  }
}

export function homeForRole(role: Role | null): string {
  if (role === 'expert' || role === 'super_admin') return '/reviews'
  if (role === 'admin') return '/training/quality'
  if (role === 'collector') return '/samples'
  return '/no-permission'
}

export function canAccess(role: Role | null, roles?: Role[]): boolean {
  if (!roles || roles.length === 0) return true
  if (!role) return false
  return roles.includes(role)
}

// 返回地址只接受站内合法路由（以 / 开头且非 //），防开放重定向。
export function isSafeRedirect(target: unknown): target is string {
  return typeof target === 'string' && target.startsWith('/') && !target.startsWith('//')
}
