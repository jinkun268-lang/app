// Mock 种子数据（仅开发态 / 测试态）。所有 ID 为有效 UUIDv7，字段 snake_case，时间为 UTC。
// 这里的账号、品种、类别为开发夹具：正式清单/账号待 E1/E3 外部输入；tmp_ 类别为占位，不进入导出。
// 首版无果园实体，样本不再携带 orchard_id / orchard_name。
import type { Role } from '../types'

export interface MockUser {
  user_id: string
  username: string
  display_name: string
  role: Role
  is_active: boolean
  password: string
  created_at: string
  last_login_at: string | null
}

export interface MockCultivar {
  cultivar_id: string
  name: string
  is_active: boolean
  version: number
  created_at: string
  updated_at: string
}

export interface MockClass {
  class_id: string
  name: string
  parent_id: string | null
  is_active: boolean
  is_provisional: boolean
  introduced_taxonomy_version: number
  deprecated_taxonomy_version: number | null
  version: number
  created_at: string
  updated_at: string
}

export interface MockImage {
  image_id: string
  view_type: 'close_up' | 'context' | 'other'
  captured_at: string
  device_timezone: string
  device_model: string | null
  mime_type: 'image/jpeg' | 'image/png' | 'image/webp'
  width: number
  height: number
  file_size: number
  quality_status: 'pending' | 'usable' | 'unusable'
  quality_reason_code: string | null
  quality_note: string | null
  quality_version: number
  quality_reviewed_by_display_name: string | null
  quality_reviewed_at: string | null
  clock_skew_suspected: boolean
  quality_events: { event_id: string; before_status: string; after_status: string; reason_code: string | null; note: string | null; actor_display_name: string; at: string; image_version: number }[]
}

export interface MockSample {
  owner_id: string
  sample_id: string
  tree_id: string | null
  original_cultivar_id: string
  original_part: string
  original_class_id: string
  symptoms: string | null
  note: string | null
  taxonomy_version: number
  upload_state: 'complete'
  upload_completed_at: string
  excluded: boolean
  review_status: 'unreviewed' | 'confirmed' | 'corrected' | 'unresolved'
  final_cultivar_id: string | null
  final_part: string | null
  final_class_id: string | null
  review_note: string | null
  review_version: number
  reviewed_by_display_name: string | null
  reviewed_at: string | null
  images: MockImage[]
  review_events: { review_id: string; action: string; actor_display_name: string; actor_role: string; at: string; note: string | null; sample_version: number; before_json: Record<string, unknown> | null; after_json: Record<string, unknown> | null }[]
}

export interface SeedState {
  users: MockUser[]
  cultivars: MockCultivar[]
  classes: MockClass[]
  samples: MockSample[]
}

const AT = '2026-10-20T00:00:00Z'

function img(
  n: number,
  view_type: MockImage['view_type'],
  quality_status: MockImage['quality_status'],
  reason: string | null = null,
): MockImage {
  return {
    image_id: `019a0001-0000-7001-8000-0000000000${String(n).padStart(2, '0')}`,
    view_type,
    captured_at: `2026-10-20T0${n}:12:33+08:00`,
    device_timezone: 'Asia/Shanghai',
    device_model: 'Pixel 8',
    mime_type: 'image/jpeg',
    width: 3000,
    height: 4000,
    file_size: 1843200,
    quality_status,
    quality_reason_code: reason,
    quality_note: null,
    quality_version: quality_status === 'pending' ? 0 : 1,
    quality_reviewed_by_display_name: quality_status === 'pending' ? null : '管理员',
    quality_reviewed_at: quality_status === 'pending' ? null : AT,
    clock_skew_suspected: false,
    quality_events: quality_status === 'pending' ? [] : [
      { event_id: `019a0001-0000-7001-9000-0000000000${String(n).padStart(2, '0')}`, before_status: 'pending', after_status: quality_status, reason_code: reason, note: null, actor_display_name: '管理员', at: AT, image_version: 1 },
    ],
  }
}

export function seedState(): SeedState {
  return {
    users: [
      { user_id: '019a0000-0000-7000-8000-000000000001', username: 'super', display_name: '超级管理员', role: 'super_admin', is_active: true, password: '12345678', created_at: AT, last_login_at: null },
      { user_id: '019a0000-0000-7000-8000-000000000002', username: 'admin', display_name: '管理员', role: 'admin', is_active: true, password: '12345678', created_at: AT, last_login_at: null },
      { user_id: '019a0000-0000-7000-8000-000000000003', username: 'expert', display_name: '专家', role: 'expert', is_active: true, password: '12345678', created_at: AT, last_login_at: null },
      { user_id: '019a0000-0000-7000-8000-000000000004', username: 'collector1', display_name: '采集员甲', role: 'collector', is_active: true, password: '12345678', created_at: AT, last_login_at: null },
      { user_id: '019a0000-0000-7000-8000-000000000005', username: 'collector2', display_name: '采集员乙', role: 'collector', is_active: true, password: '12345678', created_at: AT, last_login_at: null },
    ],
    cultivars: [
      { cultivar_id: 'huyou', name: '胡柚', is_active: true, version: 1, created_at: AT, updated_at: AT },
      { cultivar_id: 'xiangyou', name: '香柚', is_active: true, version: 1, created_at: AT, updated_at: AT },
      { cultivar_id: 'unknown', name: '不确定', is_active: true, version: 1, created_at: AT, updated_at: AT },
    ],
    classes: [
      { class_id: 'unknown', name: '不确定', parent_id: null, is_active: true, is_provisional: false, introduced_taxonomy_version: 1, deprecated_taxonomy_version: null, version: 1, created_at: AT, updated_at: AT },
      // 非占位开发夹具：仅用于导出演示；正式类别清单待 E1
      { class_id: 'citrus_canker', name: '溃疡病', parent_id: null, is_active: true, is_provisional: false, introduced_taxonomy_version: 1, deprecated_taxonomy_version: null, version: 1, created_at: AT, updated_at: AT },
      { class_id: 'tmp_citrus_hlb', name: '黄龙病（占位）', parent_id: null, is_active: true, is_provisional: true, introduced_taxonomy_version: 1, deprecated_taxonomy_version: null, version: 1, created_at: AT, updated_at: AT },
      { class_id: 'tmp_citrus_greasy_spot', name: '脂点黄斑病（占位）', parent_id: null, is_active: true, is_provisional: true, introduced_taxonomy_version: 1, deprecated_taxonomy_version: null, version: 1, created_at: AT, updated_at: AT },
    ],
    samples: [
      {
        sample_id: '019a0001-0000-7000-8000-000000000001',
        owner_id: '019a0000-0000-7000-8000-000000000004',
        tree_id: 'T-001',
        original_cultivar_id: 'huyou',
        original_part: 'leaf',
        original_class_id: 'unknown',
        symptoms: '叶片出现黄斑',
        note: null,
        taxonomy_version: 1,
        upload_state: 'complete',
        upload_completed_at: '2026-10-20T01:22:10Z',
        excluded: false,
        review_status: 'unreviewed',
        final_cultivar_id: null,
        final_part: null,
        final_class_id: null,
        review_note: null,
        review_version: 0,
        reviewed_by_display_name: null,
        reviewed_at: null,
        images: [img(1, 'close_up', 'pending'), img(2, 'context', 'pending')],
        review_events: [],
      },
      {
        sample_id: '019a0001-0000-7000-8000-000000000002',
        owner_id: '019a0000-0000-7000-8000-000000000004',
        tree_id: 'T-002',
        original_cultivar_id: 'xiangyou',
        original_part: 'fruit',
        original_class_id: 'unknown',
        symptoms: '果面褐色斑点',
        note: null,
        taxonomy_version: 1,
        upload_state: 'complete',
        upload_completed_at: '2026-10-19T08:40:02Z',
        excluded: false,
        review_status: 'corrected',
        final_cultivar_id: 'xiangyou',
        final_part: 'fruit',
        final_class_id: 'citrus_canker',
        review_note: '果面褐色斑点，按溃疡病修正',
        review_version: 1,
        reviewed_by_display_name: '管理员',
        reviewed_at: '2026-10-19T09:00:00Z',
        images: [img(3, 'close_up', 'usable'), img(4, 'context', 'usable'), img(5, 'other', 'pending')],
        review_events: [{
          review_id: '019a0001-0000-7002-8000-000000000001', action: 'review', actor_display_name: '管理员', actor_role: 'admin', at: '2026-10-19T09:00:00Z', note: '果面褐色斑点，按溃疡病修正', sample_version: 1,
          before_json: { review_status: 'unreviewed', final_class_id: null }, after_json: { review_status: 'corrected', final_class_id: 'citrus_canker' },
        }],
      },
      {
        sample_id: '019a0001-0000-7000-8000-000000000003',
        owner_id: '019a0000-0000-7000-8000-000000000005',
        tree_id: 'T-003',
        original_cultivar_id: 'huyou',
        original_part: 'leaf',
        original_class_id: 'citrus_canker',
        symptoms: null,
        note: null,
        taxonomy_version: 1,
        upload_state: 'complete',
        upload_completed_at: '2026-10-18T03:00:00Z',
        excluded: false,
        review_status: 'confirmed',
        final_cultivar_id: 'huyou',
        final_part: 'leaf',
        final_class_id: 'citrus_canker',
        review_note: '确认为溃疡病',
        review_version: 1,
        reviewed_by_display_name: '管理员',
        reviewed_at: '2026-10-18T04:00:00Z',
        images: [img(6, 'close_up', 'usable'), img(7, 'context', 'unusable', 'blur')],
        review_events: [{
          review_id: '019a0001-0000-7002-8000-000000000002', action: 'review', actor_display_name: '管理员', actor_role: 'admin', at: '2026-10-18T04:00:00Z', note: '确认为溃疡病', sample_version: 1,
          before_json: { review_status: 'unreviewed', final_class_id: null }, after_json: { review_status: 'confirmed', final_class_id: 'citrus_canker' },
        }],
      },
      {
        sample_id: '019a0001-0000-7000-8000-000000000004',
        owner_id: '019a0000-0000-7000-8000-000000000004',
        tree_id: 'T-004',
        original_cultivar_id: 'huyou',
        original_part: 'leaf',
        original_class_id: 'unknown',
        symptoms: '叶脉黄化',
        note: null,
        taxonomy_version: 1,
        upload_state: 'complete',
        upload_completed_at: '2026-10-17T02:00:00Z',
        excluded: true,
        review_status: 'corrected',
        final_cultivar_id: 'huyou',
        final_part: 'leaf',
        final_class_id: 'tmp_citrus_hlb',
        review_note: '按黄龙病占位修正，已排除',
        review_version: 1,
        reviewed_by_display_name: '管理员',
        reviewed_at: '2026-10-17T03:00:00Z',
        images: [img(8, 'close_up', 'usable')],
        review_events: [{
          review_id: '019a0001-0000-7002-8000-000000000003', action: 'review', actor_display_name: '管理员', actor_role: 'admin', at: '2026-10-17T03:00:00Z', note: '按黄龙病占位修正，已排除', sample_version: 1,
          before_json: { review_status: 'unreviewed', final_class_id: null }, after_json: { review_status: 'corrected', final_class_id: 'tmp_citrus_hlb' },
        }],
      },
      {
        sample_id: '019a0001-0000-7000-8000-000000000005',
        owner_id: '019a0000-0000-7000-8000-000000000004',
        tree_id: 'T-005',
        original_cultivar_id: 'xiangyou',
        original_part: 'branch',
        original_class_id: 'unknown',
        symptoms: null,
        note: null,
        taxonomy_version: 1,
        upload_state: 'complete',
        upload_completed_at: '2026-10-16T05:00:00Z',
        excluded: false,
        review_status: 'unresolved',
        final_cultivar_id: null,
        final_part: null,
        final_class_id: null,
        review_note: '图片不足，无法判断',
        review_version: 1,
        reviewed_by_display_name: '管理员',
        reviewed_at: '2026-10-16T06:00:00Z',
        images: [img(9, 'close_up', 'pending')],
        review_events: [{
          review_id: '019a0001-0000-7002-8000-000000000004', action: 'review', actor_display_name: '管理员', actor_role: 'admin', at: '2026-10-16T06:00:00Z', note: '图片不足，无法判断', sample_version: 1,
          before_json: { review_status: 'unreviewed', final_class_id: null }, after_json: { review_status: 'unresolved', final_class_id: null },
        }],
      },
    ],
  }
}
