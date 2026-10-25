import { request } from './http'
import type {
  ClassCreateRequest, ClassEntry, ClassImportConfirmRequest, ClassImportPreviewResponse, ClassImportResult,
  ClassPatchRequest, Cultivar, CultivarCreateRequest, CultivarPatchRequest,
} from '../types'

interface DictList<T> {
  items: T[]
  total: number
}

export function listCultivars(): Promise<DictList<Cultivar>> {
  return request<DictList<Cultivar>>({ path: '/admin/cultivars' })
}
export function createCultivar(payload: CultivarCreateRequest): Promise<Cultivar> {
  return request<Cultivar>({ path: '/admin/cultivars', method: 'POST', body: payload })
}
export function updateCultivar(cultivarId: string, payload: CultivarPatchRequest): Promise<Cultivar> {
  return request<Cultivar>({ path: `/admin/cultivars/${cultivarId}`, method: 'PATCH', body: payload })
}

export function listClasses(): Promise<DictList<ClassEntry>> {
  return request<DictList<ClassEntry>>({ path: '/admin/classes' })
}
export function createClass(payload: ClassCreateRequest): Promise<ClassEntry> {
  return request<ClassEntry>({ path: '/admin/classes', method: 'POST', body: payload })
}
export function updateClass(classId: string, payload: ClassPatchRequest): Promise<ClassEntry> {
  return request<ClassEntry>({ path: `/admin/classes/${classId}`, method: 'PATCH', body: payload })
}

export function previewClassImport(file: File, baselineTaxonomyVersion?: number): Promise<ClassImportPreviewResponse> {
  const form = new FormData()
  form.append('file', file)
  if (baselineTaxonomyVersion != null) form.append('baseline_taxonomy_version', String(baselineTaxonomyVersion))
  return request<ClassImportPreviewResponse>({ path: '/admin/classes/import/preview', method: 'POST', form })
}

export function confirmClassImport(payload: ClassImportConfirmRequest, idempotencyKey: string): Promise<ClassImportResult> {
  return request<ClassImportResult>({ path: '/admin/classes/import', method: 'POST', body: payload, idempotencyKey })
}
