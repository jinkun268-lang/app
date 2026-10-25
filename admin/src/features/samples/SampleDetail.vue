<template>
  <section v-if="detail" class="detail card">
    <div class="pane-head">
      <span class="head-title">{{ detail.tree_id || detail.sample_id.slice(0, 8) }}</span>
      <span class="tag" :class="statusClass(detail.review_status)">{{ statusText(detail.review_status) }}</span>
      <span class="tag" :class="detail.excluded ? 'tag-red' : 'tag-gray'">{{ detail.excluded ? '已排除' : '未排除' }}</span>
      <span class="spacer" />
      <span v-if="dirty" class="tag tag-amber">有未保存更改</span>
    </div>

    <div class="detail-body">
      <p v-if="conflictNotice" class="alert">
        数据已被他人更新，请重新保存。
      </p>

      <div class="grid2">
        <div class="info-block">
          <div class="info-label">树号</div>
          <div>{{ detail.tree_id || '—' }}</div>
        </div>
        <div class="info-block">
          <div class="info-label">完整上传时间</div>
          <div>{{ fmt(detail.upload_completed_at) }}</div>
        </div>
      </div>

      <div class="compare card">
        <div class="compare-col">
          <div class="info-label">初步（采集端填写）</div>
          <div class="big-name">{{ detail.original_class_name }}</div>
          <div class="muted small">
            品种：{{ detail.original_cultivar_name }} · 部位：{{ partText(detail.original_part) }}
          </div>
        </div>
        <div class="compare-col">
          <div class="info-label">审核（最终）</div>
          <div class="big-name" :class="{ empty: !detail.final_class_id }">{{ detail.final_class_name || '待审核' }}</div>
          <div class="muted small">
            品种：{{ detail.final_cultivar_name || '—' }} · 部位：{{ detail.final_part ? partText(detail.final_part) : '—' }}
          </div>
        </div>
      </div>

      <div v-if="canReview" class="section-title">专业核验</div>
      <div v-if="canReview" class="review-panel card">
        <div class="segmented">
          <button class="seg" :class="{ active: form.reviewStatus === 'confirmed' }" @click="chooseStatus('confirmed')">确认</button>
          <button class="seg" :class="{ active: form.reviewStatus === 'corrected' }" @click="chooseStatus('corrected')">修正</button>
          <button class="seg" :class="{ active: form.reviewStatus === 'unresolved' }" @click="chooseStatus('unresolved')">无法判断</button>
        </div>


        <div v-if="form.reviewStatus !== 'unresolved'" class="correct-form">
          <div class="field">
            <label class="form-label">最终品种</label>
            <select v-model="form.finalCultivarId" class="select" :disabled="form.reviewStatus === 'confirmed'">
              <option v-for="c in bootstrap.activeCultivars" :key="c.cultivar_id" :value="c.cultivar_id">{{ c.name }}</option>
            </select>
          </div>
          <div class="field">
            <label class="form-label">最终部位</label>
            <select v-model="form.finalPart" class="select" :disabled="form.reviewStatus === 'confirmed'">
              <option v-for="p in parts" :key="p.value" :value="p.value">{{ p.label }}</option>
            </select>
          </div>
          <div class="field">
            <label class="form-label">最终类别</label>
            <select v-model="form.finalClassId" class="select" :disabled="form.reviewStatus === 'confirmed'">
              <option v-for="c in bootstrap.activeClasses" :key="c.class_id" :value="c.class_id">{{ c.name }}</option>
            </select>
          </div>
          <div class="field">
            <label class="form-label">备注</label>
            <textarea v-model="form.note" class="input" rows="2" placeholder="可选" />
          </div>
        </div>

        <p v-if="bootstrap.error" class="warn">
          基础配置加载失败
          <button class="btn btn-sm" @click="retryConfig">重试</button>
        </p>
      </div>

      <div class="section-title">图片</div>
      <div class="img-grid">
        <div v-for="img in detail.images" :key="img.image_id" class="img-card">
          <button class="thumb-btn" @click="openViewer(img.image_id)">
            <SampleThumb :image-id="img.image_id" />
          </button>
          <div class="img-meta">
            <span>{{ viewText(img.view_type) }}</span>
            <span class="muted">{{ img.width }}×{{ img.height }}</span>
          </div>
          <div class="img-meta muted small">{{ fmt(img.captured_at) }}</div>
          <div v-if="canQuality && qualityReady" class="quality-row">
            <div class="segmented sm">
              <button class="seg" :class="{ active: drafts[img.image_id]?.status === 'usable' }" @click="setDraftStatus(img.image_id, 'usable')">可用</button>
              <button class="seg" :class="{ active: drafts[img.image_id]?.status === 'unusable' }" @click="setDraftStatus(img.image_id, 'unusable')">不可用</button>
            </div>
            <select v-if="drafts[img.image_id]?.status === 'unusable'" v-model="drafts[img.image_id].reason" class="select sm">
              <option value="" disabled>选择原因</option>
              <option v-for="r in reasons" :key="r.value" :value="r.value">{{ r.label }}</option>
            </select>
          </div>
          <button v-if="canQuality && qualityReady" class="btn btn-sm" :disabled="savingImg === img.image_id" @click="saveQuality(img.image_id)">
            {{ savingImg === img.image_id ? '保存中…' : '保存质量' }}
          </button>
          <span v-else class="muted small">训练质量：{{ qualityText(img.quality_status) }}</span>
        </div>
      </div>
      <p v-if="canQuality && !qualityReady" class="warn">尚未通过专业核验，核验完成后可保存训练质量。</p>

      <div class="section-title">审核历史</div>
      <div v-if="detail.review_events.length === 0" class="muted">暂无历史记录</div>
      <ul v-else class="history">
        <li v-for="ev in detail.review_events" :key="ev.review_id" class="history-item">
          <span class="tag tag-gray">{{ actionText(ev.action) }}</span>
          <span>{{ ev.actor_display_name }}</span>
          <span class="muted">{{ fmt(ev.at) }}</span>
          <span v-if="ev.note">{{ ev.note }}</span>
        </li>
      </ul>
    </div>

    <div class="pane-foot">
      <button class="btn" @click="reload">刷新</button>
      <span class="spacer" />
      <router-link v-if="workspace === 'collection' && capabilities.review" class="btn" :to="'/reviews/' + sampleId">进入核验</router-link>
      <router-link v-if="workspace === 'collection' && capabilities.prepareTraining" class="btn" :to="'/training/quality/' + sampleId">质量检查</router-link>
      <button v-if="canQuality" class="btn btn-danger" :disabled="saving" @click="toggleExcluded">{{ detail.excluded ? '恢复训练' : '排除训练' }}</button>
      <button v-if="canReview" class="btn btn-primary" :disabled="saving || !bootstrap.ready" @click="saveReview">
        {{ saving ? '保存中…' : '保存审核' }}
      </button>
    </div>

    <ImageViewer v-model="viewerOpen" :images="viewerImages" :index="viewerIndex" @update:index="viewerIndex = $event" />
  </section>

  <section v-else class="detail card">
    <div v-if="loading" class="empty muted">加载中…</div>
    <div v-else-if="error" class="empty">
      <p class="err-text">{{ error }}</p>
      <button class="btn" @click="reload">重试</button>
    </div>
    <div v-else class="empty muted">暂无数据</div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useSampleDetail } from './useSampleDetail'
import SampleThumb from './SampleThumb.vue'
import ImageViewer from '../../components/ImageViewer.vue'
import { useBootstrapStore } from '../../stores/bootstrap'
import { toast } from '../../ui/toast'
import { useAuthStore } from '../../stores/auth'
import { sampleCapabilities, type SampleWorkspace } from '../../auth/capabilities'
import type { ReviewStatus, SampleDetail as SampleDetailType } from '../../types'

const props = withDefaults(defineProps<{ sampleId: string; workspace?: SampleWorkspace }>(), { workspace: 'collection' })
const emit = defineEmits<{ (e: 'saved'): void }>()

const bootstrap = useBootstrapStore()
const auth = useAuthStore()
const capabilities = computed(() => sampleCapabilities(auth.role))
const canReview = computed(() => props.workspace === 'review' && capabilities.value.review)
const canQuality = computed(() => props.workspace === 'quality' && capabilities.value.prepareTraining)
const { detail, loading, error, conflictNotice, formSyncToken, load, submitReview, submitQuality, toggleExclude } = useSampleDetail(
  computed(() => props.sampleId),
)
const qualityReady = computed(() => detail.value?.review_status === 'confirmed' || detail.value?.review_status === 'corrected')

const parts = [
  { value: 'leaf', label: '叶' },
  { value: 'fruit', label: '果' },
  { value: 'branch', label: '枝' },
  { value: 'insect', label: '虫体' },
  { value: 'other', label: '其他' },
]
const reasons = [
  { value: 'blur', label: '模糊' },
  { value: 'occluded', label: '遮挡' },
  { value: 'exposure', label: '曝光异常' },
  { value: 'wrong_object', label: '拍错对象' },
  { value: 'duplicate', label: '重复' },
  { value: 'other', label: '其他' },
]

interface QualityDraft {
  status: 'usable' | 'unusable'
  reason: string
  note: string
}

const form = reactive<{ reviewStatus: ReviewStatus; finalCultivarId: string; finalPart: string; finalClassId: string; note: string }>({
  reviewStatus: 'confirmed',
  finalCultivarId: '',
  finalPart: 'leaf',
  finalClassId: 'unknown',
  note: '',
})

const drafts = reactive<Record<string, QualityDraft>>({})
const saving = ref(false)
const savingImg = ref('')
const dirty = ref(false)

const viewerOpen = ref(false)
const viewerIndex = ref(0)
const viewerImages = computed(() => (detail.value?.images ?? []).map((i) => ({ image_id: i.image_id, caption: viewText(i.view_type) })))

function statusText(s: ReviewStatus) {
  return ({ unreviewed: '未审核', confirmed: '已确认', corrected: '已修正', unresolved: '无法判断' } as Record<string, string>)[s] || s
}
function statusClass(s: ReviewStatus) {
  return ({ unreviewed: 'tag-amber', confirmed: 'tag-green', corrected: 'tag-blue', unresolved: 'tag-gray' } as Record<string, string>)[s] || 'tag-gray'
}
function viewText(v: string) {
  return ({ close_up: '近景', context: '环境图', other: '其他' } as Record<string, string>)[v] || v
}
function partText(p: string) {
  return ({ leaf: '叶', fruit: '果', branch: '枝', insect: '虫体', other: '其他' } as Record<string, string>)[p] || p
}
function qualityText(status: string) {
  return ({ pending: '待检查', usable: '可用', unusable: '不可用' } as Record<string, string>)[status] || status
}
function actionText(a: string) {
  return ({ review: '审核', exclude: '排除', restore: '恢复' } as Record<string, string>)[a] || a
}
function fmt(iso: string | null) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
  } catch {
    return iso
  }
}

function chooseStatus(s: ReviewStatus) {
  form.reviewStatus = s
  if (s === 'confirmed' && detail.value) {
    form.finalCultivarId = detail.value.original_cultivar_id
    form.finalPart = detail.value.original_part
    form.finalClassId = detail.value.original_class_id
  }
}

function setDraftStatus(imageId: string, s: 'usable' | 'unusable') {
  if (drafts[imageId]) drafts[imageId].status = s
}

function syncForm(d: SampleDetailType) {
  form.reviewStatus = d.review_status === 'unreviewed' ? 'confirmed' : d.review_status
  form.finalCultivarId = d.final_cultivar_id ?? d.original_cultivar_id
  form.finalPart = d.final_part ?? d.original_part
  form.finalClassId = d.final_class_id ?? d.original_class_id
  form.note = d.review_note ?? ''
  for (const img of d.images) {
    drafts[img.image_id] = {
      status: img.quality_status === 'pending' ? 'usable' : img.quality_status,
      reason: img.quality_reason_code ?? '',
      note: img.quality_note ?? '',
    }
  }
}

function clearDrafts() {
  for (const key of Object.keys(drafts)) delete drafts[key]
}

function recomputeDirty() {
  const d = detail.value
  if (!d) {
    dirty.value = false
    return
  }
  const baseStatus = d.review_status === 'unreviewed' ? 'confirmed' : d.review_status
  const baseCultivar = d.final_cultivar_id ?? d.original_cultivar_id
  const basePart = d.final_part ?? d.original_part
  const baseClass = d.final_class_id ?? d.original_class_id
  const baseNote = d.review_note ?? ''
  const formChanged = canReview.value && (
    form.reviewStatus !== baseStatus ||
    form.finalCultivarId !== baseCultivar ||
    form.finalPart !== basePart ||
    form.finalClassId !== baseClass ||
    form.note !== baseNote)
  const qualityChanged = canQuality.value && qualityReady.value && d.images.some((img) => {
    const dr = drafts[img.image_id]
    if (!dr) return false
    const baseQ = img.quality_status === 'pending' ? 'usable' : img.quality_status
    return dr.status !== baseQ || dr.reason !== (img.quality_reason_code ?? '')
  })
  dirty.value = formChanged || qualityChanged
}

// 切换样本：先清空上一个样本的草稿，等新详情到达后再统一初始化，避免旧草稿被带到新样本。
watch(
  () => props.sampleId,
  () => {
    clearDrafts()
    conflictNotice.value = ''
  },
)

// 只有「加载完成/保存成功」才把表单重置为服务端状态；409 冲突重读不重置，草稿保留。
watch(formSyncToken, () => {
  const d = detail.value
  if (!d || d.sample_id !== props.sampleId) return
  syncForm(d)
  recomputeDirty()
})

watch(
  () => [form.reviewStatus, form.finalCultivarId, form.finalPart, form.finalClassId, form.note, JSON.stringify(drafts)],
  recomputeDirty,
  { deep: true },
)

// 服务端展示更新（含冲突重读）后重新判断是否有未保存内容。
watch(detail, recomputeDirty)

onMounted(() => {
  // 与布局/列表共享同一加载：失败写入 bootstrap.error，不静默吞掉。
  void bootstrap.load()
})

function retryConfig() {
  void bootstrap.load(true)
}

function readyForReview(): boolean {
  const d = detail.value
  if (!d || d.sample_id !== props.sampleId) {
    toast('样本详情尚未加载完成，无法提交', 'error')
    return false
  }
  if (!bootstrap.ready) {
    toast(bootstrap.error ? '基础配置加载失败，无法提交审核' : '基础配置加载中，无法提交审核', 'error')
    return false
  }
  return true
}

async function saveReview() {
  if (!canReview.value) return
  if (!readyForReview()) return
  const d = detail.value as SampleDetailType
  saving.value = true
  try {
    let payload
    if (form.reviewStatus === 'confirmed') {
      payload = {
        // expected_version 取当前最新 detail：冲突重读后重新提交即使用服务端最新版本。
        expected_version: d.review_version,
        review_status: 'confirmed',
        final_cultivar_id: d.original_cultivar_id,
        final_part: d.original_part,
        final_class_id: d.original_class_id,
        review_note: form.note,
      }
    } else if (form.reviewStatus === 'corrected') {
      payload = {
        expected_version: d.review_version,
        review_status: 'corrected',
        final_cultivar_id: form.finalCultivarId,
        final_part: form.finalPart,
        final_class_id: form.finalClassId,
        review_note: form.note,
      }
    } else {
      payload = { expected_version: d.review_version, review_status: 'unresolved', review_note: form.note }
    }
    const res = await submitReview(payload as never)
    if (res.ok) {
      dirty.value = false
      emit('saved')
    } else {
      toast(res.message, 'error')
      // 冲突时只刷新列表/历史，不重置当前草稿。
      if (res.conflict) emit('saved')
    }
  } finally {
    saving.value = false
  }
}

async function saveQuality(imageId: string) {
  if (!canQuality.value || !qualityReady.value) return
  const dr = drafts[imageId]
  if (!dr) return
  if (dr.status === 'unusable' && !dr.reason) {
    toast('不可用必须选择原因', 'error')
    return
  }
  const d = detail.value
  if (!d || d.sample_id !== props.sampleId) {
    toast('样本详情尚未加载完成，无法提交', 'error')
    return
  }
  const img = d.images.find((i) => i.image_id === imageId)
  if (!img) return
  savingImg.value = imageId
  try {
    const res = await submitQuality(imageId, {
      // 逐图版本独立：同样取重读后的最新图片版本。
      expected_version: img.quality_version,
      quality_status: dr.status,
      quality_reason_code: dr.status === 'unusable' ? dr.reason : null,
      quality_note: dr.note,
    })
    if (res.ok) {
      // 该图为服务端最新值，重新判断是否还有未保存内容（不影响其他草稿）。
      recomputeDirty()
    } else toast(res.message, 'error')
  } finally {
    savingImg.value = ''
  }
}

async function toggleExcluded() {
  if (!canQuality.value) return
  const d = detail.value
  if (!d || d.sample_id !== props.sampleId) return
  const action = d.excluded ? 'restore' : 'exclude'
  const res = await toggleExclude({ expected_version: d.review_version } as never, action as 'exclude' | 'restore')
  if (res.ok) {
    emit('saved')
  } else {
    toast(res.message, 'error')
    if (res.conflict) emit('saved')
  }
}

function openViewer(imageId: string) {
  const idx = viewerImages.value.findIndex((i) => i.image_id === imageId)
  viewerIndex.value = Math.max(0, idx)
  viewerOpen.value = true
}

async function reload() {
  await load()
}

defineExpose({ isDirty: () => dirty.value })
</script>

<style scoped>
.detail { display: flex; flex-direction: column; height: 100%; overflow: hidden; }
.pane-head { padding: 13px 16px; font-weight: 600; border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 8px; flex-shrink: 0; flex-wrap: wrap; }
.head-title { font-weight: 600; }
.detail-body { padding: 16px; overflow: auto; flex: 1; }
.pane-foot {
  padding: 10px 16px;
  border-top: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  flex-shrink: 0;
  background: #fbfdfc;
}
.grid2 { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; margin-bottom: 12px; }
.info-block { background: #f9fafb; border-radius: 8px; padding: 10px; }
.info-label { color: var(--muted); font-size: 12px; margin-bottom: 4px; }
.compare { display: flex; gap: 20px; padding: 14px; margin-bottom: 14px; }
.compare-col { flex: 1; }
.big-name { font-size: 20px; font-weight: 600; margin: 4px 0; }
.big-name.empty { color: var(--muted); font-weight: 400; padding: 0; text-align: left; }
.small { font-size: 12px; }
.section-title { margin: 14px 0 8px; font-weight: 600; }
.review-panel { padding: 14px; }
.segmented { display: inline-flex; border: 1px solid var(--border); border-radius: 8px; overflow: hidden; }
.segmented.sm .seg { padding: 3px 10px; font-size: 12px; }
.seg { border: none; background: #fff; padding: 7px 18px; }
.seg + .seg { border-left: 1px solid var(--border); }
.seg.active { background: var(--primary); color: #fff; }
.correct-form { margin-top: 12px; display: grid; grid-template-columns: repeat(2, 1fr); gap: 0 16px; }
.warn { color: var(--warn); font-size: 13px; margin: 10px 0 0; }
.warn .btn { margin-left: 8px; }
.alert { background: #fff7ed; border: 1px solid #fdba74; color: #9a3412; border-radius: 8px; padding: 10px 12px; margin: 0 0 12px; font-size: 13px; line-height: 1.5; }
.img-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px; }
.img-card { border: 1px solid var(--border); border-radius: 8px; padding: 10px; display: flex; flex-direction: column; gap: 6px; }
.thumb-btn { border: none; background: transparent; padding: 0; cursor: pointer; }
.img-meta { display: flex; justify-content: space-between; font-size: 12px; }
.quality-row { display: flex; gap: 6px; align-items: center; }
.select.sm { flex: 1; min-width: 0; padding: 4px 6px; }
.history { list-style: none; margin: 0; padding: 0; }
.history-item { display: flex; gap: 8px; align-items: center; padding: 6px 0; border-bottom: 1px solid var(--border); font-size: 13px; flex-wrap: wrap; }

@media (max-width: 640px) {
  .detail-body { padding: 12px; }
  .grid2 { grid-template-columns: 1fr; }
  .compare { flex-direction: column; gap: 10px; }
  .correct-form { grid-template-columns: 1fr; }
  .img-grid { grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); }
}
</style>
