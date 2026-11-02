<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Plus, Search, X } from 'lucide-vue-next'
import MultiSelect from '../components/MultiSelect.vue'
import ExportImagePicker from '../features/training/ExportImagePicker.vue'
import { batchState, dateOnly, loadBatches, loadImages, reviewed, timeText } from '../features/training/data'
import { createExport, downloadExport, listExports, retryExport } from '../api/exports'
import { ApiError } from '../api/http'
import { useBootstrapStore } from '../stores/bootstrap'
import { usePolling } from '../composables/usePolling'
import { errorMessage } from '../util/error'
import { uuidv7 } from '../util/uuid'
import { toast } from '../ui/toast'
import type { ExportCreateRequest, ExportJob, TrainingBatch, TrainingImage } from '../types'
import '../features/training/training.css'

const bootstrap = useBootstrapStore()
const jobs = ref<ExportJob[]>([]), loading = ref(false), error = ref(''), creating = ref(false), createError = ref('')
const modal = ref(false), jobFilter = ref('all'), detailJob = ref<ExportJob | null>(null)
const batches = ref<TrainingBatch[]>([]), batchLoading = ref(false), batchError = ref('')
const selected = ref<string[]>([]), imageMap = ref<Record<string, TrainingImage[]>>({})
const imageLoading = ref<Record<string, boolean>>({}), imageErrors = ref<Record<string, string>>({})
const overrides = ref<Record<string, boolean>>({}), pickerId = ref('')
const name = ref(''), classes = ref<string[]>([]), cultivars = ref<string[]>([])
const review = ref<'reviewed' | 'unreviewed' | 'all'>('reviewed'), quality = ref<'usable' | 'pending' | 'unusable' | 'all'>('usable')
const query = ref(''), state = ref('all'), from = ref(''), to = ref(''), draftFrom = ref(''), draftTo = ref('')
const datePanel = ref<HTMLDetailsElement | null>(null)
const statusNames: Record<string, string> = { queued: '排队中', running: '生成中', succeeded: '已完成', failed: '失败' }
const shownJobs = computed(() => jobs.value.filter(job => jobFilter.value === 'all' || (jobFilter.value === 'active' ? ['running', 'queued'].includes(job.status) : job.status === jobFilter.value)))
const dateError = computed(() => !!draftFrom.value && !!draftTo.value && draftFrom.value > draftTo.value)
const unappliedDates = computed(() => draftFrom.value !== from.value || draftTo.value !== to.value)
const inDate = (batch: TrainingBatch) => (!from.value || dateOnly(batch.created_at) >= from.value) && (!to.value || dateOnly(batch.created_at) <= to.value)
const listed = computed(() => batches.value.filter(batch => inDate(batch) && (!query.value || `${batch.name} ${batch.place} ${batch.batch_id}`.toLowerCase().includes(query.value.toLowerCase())) && (state.value === 'all' || (state.value === 'ready') === (batchState(batch) === '处理完成'))))
const selectedBatches = computed(() => batches.value.filter(batch => selected.value.includes(batch.batch_id)))
const dimensionsMatch = (image: TrainingImage) => (!classes.value.length || classes.value.includes(image.class_id || '')) && (!cultivars.value.length || cultivars.value.includes(image.cultivar_id || ''))
const imagesIn = (id: string) => (imageMap.value[id] || []).filter(dimensionsMatch)
const defaultsMatch = (image: TrainingImage) => (review.value === 'all' || (review.value === 'reviewed' ? reviewed(image) : image.review_status === 'unreviewed')) && (quality.value === 'all' || (reviewed(image) && image.quality_status === quality.value))
const picked = (image: TrainingImage) => overrides.value[image.image_id] ?? defaultsMatch(image)
const eligible = computed(() => selected.value.flatMap(id => imagesIn(id).filter(picked)))
const scopeCount = computed(() => selected.value.reduce((count, id) => count + imagesIn(id).length, 0))
const selectedCount = (id: string) => selected.value.includes(id) ? imagesIn(id).filter(picked).length : 0
const selectedLoading = computed(() => selected.value.some(id => imageLoading.value[id] || imageErrors.value[id] || !imageMap.value[id]))
const canCreate = computed(() => !!name.value.trim() && !!eligible.value.length && eligible.value.length <= 10000 && !selectedLoading.value && !unappliedDates.value && !batchLoading.value && !batchError.value && !creating.value && bootstrap.ready)
const pickerBatch = computed(() => batches.value.find(batch => batch.batch_id === pickerId.value))
let pending: { serialized: string; key: string } | null = null
watch(review, value => { if (value === 'unreviewed') quality.value = 'all' })
watch([review, quality, classes, cultivars], () => { if (Object.keys(overrides.value).length) toast('条件已更新，已按新条件重新选图'); overrides.value = {} })
async function loadJobs() {
  loading.value = true; error.value = ''
  try { jobs.value = (await listExports({ page: 1, page_size: 100 })).items }
  catch (e) { error.value = errorMessage(e) }
  finally { loading.value = false }
}
const poll = usePolling(async () => { jobs.value = (await listExports({ page: 1, page_size: 100 })).items; return jobs.value }, { initialDelayMs: 2000, stop: rows => !rows.some(job => ['queued', 'running'].includes(job.status)) })
function startPoll() { if (jobs.value.some(job => ['queued', 'running'].includes(job.status)) && !poll.running.value) poll.start() }
async function refreshBatches() {
  batchLoading.value = true; batchError.value = ''
  try { batches.value = await loadBatches(); selected.value = selected.value.filter(id => batches.value.some(batch => batch.batch_id === id && inDate(batch))) }
  catch (e) { batchError.value = errorMessage(e) }
  finally { batchLoading.value = false }
}
async function openCreate() {
  modal.value = true; createError.value = ''
  if (!name.value) name.value = `柑橘训练集_${dateOnly(new Date().toISOString()).replace(/-/g, '')}`
  await refreshBatches()
  await Promise.all(selected.value.map(id => ensureImages(id, true)))
}
async function ensureImages(id: string, force = false) {
  if (imageLoading.value[id] || (!force && imageMap.value[id])) return
  imageLoading.value[id] = true; imageErrors.value[id] = ''
  try { imageMap.value[id] = await loadImages(id) }
  catch (e) { imageErrors.value[id] = errorMessage(e) }
  finally { imageLoading.value[id] = false }
}
function removeBatch(id: string) { selected.value = selected.value.filter(value => value !== id); for (const image of imageMap.value[id] || []) delete overrides.value[image.image_id]; if (pickerId.value === id) pickerId.value = '' }
async function toggleBatch(batch: TrainingBatch) { if (selected.value.includes(batch.batch_id)) removeBatch(batch.batch_id); else { selected.value.push(batch.batch_id); await ensureImages(batch.batch_id) } }
async function openPicker(batch: TrainingBatch) { if (!selected.value.includes(batch.batch_id)) selected.value.push(batch.batch_id); pickerId.value = batch.batch_id; await ensureImages(batch.batch_id) }
function applyDates(clear = false) {
  if (!clear && dateError.value) return
  from.value = clear ? '' : draftFrom.value; to.value = clear ? '' : draftTo.value
  if (clear) { draftFrom.value = ''; draftTo.value = '' }
  let removed = 0
  for (const batch of selectedBatches.value) if (!inDate(batch)) { removeBatch(batch.batch_id); removed++ }
  if (removed) toast(`已移除 ${removed} 个日期范围外的批次`)
  if (datePanel.value) datePanel.value.open = false
}
function setImages(value: boolean) { for (const image of imagesIn(pickerId.value)) overrides.value[image.image_id] = value }
function restoreDefaults() { for (const image of imageMap.value[pickerId.value] || []) delete overrides.value[image.image_id] }
async function create() {
  if (!canCreate.value) return
  const payload: ExportCreateRequest = { format: 'dataset', name: name.value.trim(), batch_ids: [...selected.value].sort(), batch_created_from: from.value || null, batch_created_to: to.value || null, class_ids: [...classes.value].sort(), cultivar_ids: [...cultivars.value].sort(), review_status: review.value, quality_status: quality.value, image_ids: eligible.value.map(image => image.image_id).sort() }
  const serialized = JSON.stringify(payload), key = pending?.serialized === serialized ? pending.key : uuidv7()
  creating.value = true; createError.value = ''
  try { const job = await createExport(payload, key); pending = null; jobs.value.unshift(job); modal.value = false; selected.value = []; overrides.value = {}; pickerId.value = ''; name.value = ''; jobFilter.value = 'all'; startPoll() }
  catch (e) { pending = e instanceof ApiError ? null : { serialized, key }; createError.value = errorMessage(e) }
  finally { creating.value = false }
}
async function retry(job: ExportJob) { try { await retryExport(job.export_id, uuidv7()); await loadJobs(); startPoll() } catch (e) { toast(errorMessage(e), 'error') } }
async function download(job: ExportJob) {
  try { const { blob, filename } = await downloadExport(job.export_id); const url = URL.createObjectURL(blob), anchor = document.createElement('a'); anchor.href = url; anchor.download = filename; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000) }
  catch (e) { toast(errorMessage(e), 'error') }
}
onMounted(async () => { await Promise.all([bootstrap.load(), loadJobs()]); startPoll() })
</script>

<template>
  <div class="td-app td-integrated"><main class="td-content">
    <div class="td-page-heading"><h1>数据导出</h1><button class="td-btn primary" @click="openCreate"><Plus :size="16" />创建导出任务</button></div>
    <p v-if="error" class="td-error" role="alert">{{ error }} <button class="td-text-btn" @click="loadJobs">重试</button></p>
    <section class="td-jobs" aria-label="导出任务列表"><div class="td-tabs td-job-tabs"><button v-for="tab in [{ id: 'all', name: '全部任务' }, { id: 'active', name: '进行中' }, { id: 'succeeded', name: '已完成' }, { id: 'failed', name: '失败' }]" :key="tab.id" :class="{ active: jobFilter === tab.id }" @click="jobFilter = tab.id">{{ tab.name }}</button></div>
      <div class="td-table-wrap"><table class="td-table td-jobs-table"><thead><tr><th>任务名称 / 编号</th><th>来源批次</th><th>状态</th><th>图片数量</th><th>创建时间</th><th>操作</th></tr></thead><tbody><tr v-for="job in shownJobs" :key="job.export_id"><td><strong>{{ job.filters?.name || '训练数据导出' }}</strong><small>{{ job.export_id }}</small><div v-if="job.error_detail" class="td-job-error">{{ job.error_detail }}</div></td><td><span v-for="batch in job.filters?.batch_snapshots || []" :key="batch.batch_id" class="td-source-name">{{ batch.name }}<time>{{ dateOnly(batch.created_at) }}</time></span><span v-if="!job.filters?.batch_snapshots?.length" class="td-muted">按原筛选条件</span></td><td><span class="td-badge" :class="job.status">{{ statusNames[job.status] }}</span></td><td>{{ job.item_count }} 张</td><td class="td-muted">{{ timeText(job.created_at) }}</td><td><div class="td-row"><button v-if="job.status === 'succeeded'" class="td-text-btn" @click="download(job)">下载</button><button v-if="job.status === 'failed'" class="td-text-btn" @click="retry(job)">重试</button><button class="td-text-btn secondary" @click="detailJob = job">详情</button></div></td></tr></tbody></table></div><div v-if="!shownJobs.length" class="td-empty">{{ loading ? '加载中…' : '暂无任务' }}</div>
    </section>
  </main>
  <div v-if="modal" class="td-modal-backdrop" @click.self="!creating && (modal = false)"><form class="td-dialog td-create-dialog td-batch-create" role="dialog" aria-modal="true" aria-labelledby="export-title" @submit.prevent="create">
    <header class="td-dialog-head"><h2 id="export-title">创建导出任务</h2><button type="button" class="td-icon-btn" :disabled="creating" aria-label="关闭创建导出任务" @click="modal = false"><X :size="19" /></button></header>
    <fieldset class="td-form-body" :disabled="creating"><p v-if="bootstrap.error" class="td-error">字典加载失败：{{ bootstrap.error }} <button type="button" class="td-text-btn" @click="bootstrap.load(true)">重试</button></p><label class="td-field">任务名称<input v-model="name" maxlength="48" required /></label>
      <div class="td-field-grid td-export-filters"><MultiSelect v-model="classes" label="病虫害类别" placeholder="全部类别" :options="bootstrap.classes.map(item => ({ value: item.class_id, label: item.name }))" /><MultiSelect v-model="cultivars" label="品种" placeholder="全部品种" :options="bootstrap.cultivars.map(item => ({ value: item.cultivar_id, label: item.name }))" /><label class="td-field">核验状态<select v-model="review"><option value="reviewed">已核验</option><option value="unreviewed">未核验</option><option value="all">全部</option></select></label><label class="td-field">质量状态<select v-model="quality" :disabled="review === 'unreviewed'"><option value="usable">可用</option><option value="pending">未质检</option><option value="unusable">不可用</option><option value="all">不限</option></select></label></div>
      <div class="td-default-rule">核验、质量条件决定默认勾选，选中批次后可逐图调整。</div><div class="td-picker-heading"><strong>采集批次</strong><span>各状态批次均可选择</span></div>
      <div class="td-filter-row td-picker-filters"><label class="td-search"><Search :size="15" /><input v-model="query" aria-label="查找导出批次" placeholder="批次名称 / 地点" /></label><select v-model="state" aria-label="导出批次状态筛选"><option value="all">全部批次</option><option value="ready">处理完成</option><option value="pending">待处理</option></select><details ref="datePanel" class="td-date-filter"><summary @click="draftFrom = from; draftTo = to">批次创建日期<small v-if="from || to" class="td-applied-date">{{ from || '不限' }} 至 {{ to || '不限' }}</small></summary><div><label>从<input v-model="draftFrom" type="date" aria-label="导出批次创建日期从" /></label><label>至<input v-model="draftTo" type="date" aria-label="导出批次创建日期至" /></label><p v-if="dateError" class="td-date-error" role="alert">结束日期不能早于开始日期</p><div class="td-date-actions"><button type="button" class="td-text-btn" @click="applyDates(true)">清除日期</button><button type="button" class="td-btn primary" :disabled="dateError" @click="applyDates()">应用日期</button></div></div></details></div>
      <p v-if="batchError" class="td-error">{{ batchError }} <button type="button" class="td-text-btn" @click="refreshBatches">重试</button></p><div v-if="batchLoading" class="td-empty">加载批次中…</div>
      <div v-else class="td-picker-table-wrap"><table class="td-table td-picker-table"><thead><tr><th /><th>批次 / 创建日期</th><th>状态</th><th>本次选图</th><th /></tr></thead><tbody><tr v-for="batch in listed" :key="batch.batch_id" :data-batch="batch.batch_id"><td><input type="checkbox" :aria-label="'选择批次 ' + batch.batch_id" :checked="selected.includes(batch.batch_id)" @change="toggleBatch(batch)" /></td><td><strong>{{ batch.name }}</strong><small>{{ batch.batch_id }} · {{ dateOnly(batch.created_at) }}</small></td><td><span class="td-badge">{{ batchState(batch) }}</span></td><td><template v-if="imageLoading[batch.batch_id]">加载中…</template><template v-else>{{ selectedCount(batch.batch_id) }} / {{ imageMap[batch.batch_id] ? imagesIn(batch.batch_id).length : batch.image_count }}</template><small v-if="imageErrors[batch.batch_id]" class="td-error">加载失败 <button type="button" class="td-text-btn" @click="ensureImages(batch.batch_id, true)">重试</button></small></td><td><button type="button" class="td-text-btn" @click="openPicker(batch)">选图</button></td></tr></tbody></table><div v-if="!listed.length" class="td-empty">没有符合条件的批次</div></div>
      <div v-if="selectedBatches.length" class="td-selected-batches"><span>已选 {{ selectedBatches.length }} 个批次</span><div v-for="batch in selectedBatches" :key="batch.batch_id" class="td-selected-batch"><button type="button" @click="openPicker(batch)"><span>{{ batch.name }}</span><time>{{ dateOnly(batch.created_at) }}</time><strong>{{ selectedCount(batch.batch_id) }} 张</strong></button><button type="button" class="td-remove-batch" :aria-label="'移除批次 ' + batch.batch_id" @click="removeBatch(batch.batch_id)"><X :size="12" /></button></div></div>
      <div class="td-export-count"><strong>本次导出 {{ eligible.length }} 张</strong><span>未选 {{ scopeCount - eligible.length }} 张</span><span>{{ selected.length }} 个采集批次</span></div><p v-if="unappliedDates" class="td-no-data">日期已修改，请应用日期后创建任务。</p><p v-else-if="selected.length && !eligible.length && !selectedLoading" class="td-no-data">尚未选中图片，可调整默认条件或点击“选图”手动选择。</p><p v-if="eligible.length > 10000" class="td-error">一次最多选中 10000 张图片，请减少选择。</p><p v-if="createError" class="td-error" role="alert">{{ createError }}</p>
    </fieldset><footer class="td-dialog-footer"><button type="button" class="td-btn" :disabled="creating" @click="modal = false">取消</button><button type="submit" class="td-btn primary" :disabled="!canCreate">{{ creating ? '创建中…' : `创建任务（${eligible.length} 张）` }}</button></footer>
  </form></div>
  <ExportImagePicker v-if="pickerBatch && modal" :batch="pickerBatch" :images="imagesIn(pickerId)" :selected-ids="eligible.map(image => image.image_id)" :loading="!!imageLoading[pickerId]" :error="imageErrors[pickerId] || ''" @toggle="image => overrides[image.image_id] = !picked(image)" @select-all="setImages(true)" @clear="setImages(false)" @restore="restoreDefaults" @close="pickerId = ''" @retry="ensureImages(pickerId, true)" />
  <div v-if="detailJob" class="td-modal-backdrop" @click.self="detailJob = null"><section class="td-dialog td-small-dialog" role="dialog" aria-modal="true" aria-label="导出任务详情"><header class="td-dialog-head"><h2>任务详情</h2><button class="td-icon-btn" aria-label="关闭任务详情" @click="detailJob = null"><X :size="19" /></button></header><div class="td-dialog-body"><h3>{{ detailJob.filters?.name || '训练数据导出' }}</h3><p class="td-muted td-small">{{ detailJob.export_id }}</p><dl class="td-confirm-summary"><div><dt>图片</dt><dd>{{ detailJob.item_count }} 张</dd></div><div><dt>病虫害类别</dt><dd>{{ detailJob.filters?.class_ids?.map(id => bootstrap.className(id)).join('、') || '全部类别' }}</dd></div><div><dt>品种</dt><dd>{{ detailJob.filters?.cultivar_ids?.map(id => bootstrap.cultivarName(id)).join('、') || '全部品种' }}</dd></div><div><dt>创建时间</dt><dd>{{ timeText(detailJob.created_at) }}</dd></div></dl><div class="td-snapshot-list"><span v-for="id in detailJob.filters?.image_ids || []" :key="id">{{ id }}</span></div><p v-if="detailJob.error_detail" class="td-error">{{ detailJob.error_detail }}</p></div><footer class="td-dialog-footer"><button class="td-btn" @click="detailJob = null">关闭</button></footer></section></div>
  </div>
</template>
