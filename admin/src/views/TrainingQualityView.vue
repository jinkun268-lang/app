<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Check, ChevronRight, Search } from 'lucide-vue-next'
import { getSample, setImageQuality } from '../api/samples'
import ImageViewer from '../components/ImageViewer.vue'
import SampleThumb from '../features/samples/SampleThumb.vue'
import QualityInspector from '../features/training/QualityInspector.vue'
import { batchState, dateOnly, loadBatches, loadImages, qualityNames } from '../features/training/data'
import { useBootstrapStore } from '../stores/bootstrap'
import { errorMessage } from '../util/error'
import type { QualityReasonCode, TrainingBatch, TrainingImage } from '../types'
import '../features/training/training.css'

const route = useRoute(), router = useRouter(), bootstrap = useBootstrapStore()
const batches = ref<TrainingBatch[]>([]), images = ref<TrainingImage[]>([]), loading = ref(false), error = ref(''), busy = ref(false)
const query = ref(''), from = ref(''), to = ref(''), state = ref('all')
const category = ref(''), cultivar = ref(''), imageQuery = ref(typeof route.query.record === 'string' ? route.query.record : ''), quality = ref(route.query.record ? 'all' : 'pending')
const checked = ref<string[]>([]), currentId = ref(''), drawer = ref(false), zoom = ref(false), zoomIndex = ref(0)
const batchId = computed(() => typeof route.query.batch === 'string' ? route.query.batch : '')
const detailMode = computed(() => !!batchId.value || typeof route.params.id === 'string')
const currentBatch = computed(() => batches.value.find(batch => batch.batch_id === batchId.value))
const dateError = computed(() => !!from.value && !!to.value && from.value > to.value)
const listed = computed(() => dateError.value ? [] : batches.value.filter(batch => (!query.value || `${batch.name} ${batch.place} ${batch.batch_id}`.includes(query.value)) && (!from.value || dateOnly(batch.created_at) >= from.value) && (!to.value || dateOnly(batch.created_at) <= to.value) && (state.value === 'all' || (state.value === 'ready') === (batchState(batch) === '处理完成'))))
const scope = computed(() => images.value.filter(image => (!category.value || image.class_id === category.value) && (!cultivar.value || image.cultivar_id === cultivar.value) && (!imageQuery.value || `${image.image_id} ${image.sample_id} ${image.tree_id || ''}`.includes(imageQuery.value))))
const visible = computed(() => scope.value.filter(image => quality.value === 'all' || image.quality_status === quality.value))
const tabs = computed(() => [{ id: 'pending', name: '待检查' }, { id: 'all', name: '全部' }, { id: 'usable', name: '可用' }, { id: 'unusable', name: '不可用' }].map(tab => ({ ...tab, count: scope.value.filter(image => tab.id === 'all' || image.quality_status === tab.id).length })))
const active = computed(() => visible.value.find(image => image.image_id === currentId.value) || visible.value[0])
const position = computed(() => `${visible.value.findIndex(image => image.image_id === active.value?.image_id) + 1} / ${visible.value.length}`)
watch([category, cultivar, imageQuery, quality, batchId], () => { checked.value = [] })
watch(visible, rows => { if (!rows.some(image => image.image_id === currentId.value)) currentId.value = rows[0]?.image_id || '' })
let loadSequence = 0
async function load() {
  const sequence = ++loadSequence, id = batchId.value
  loading.value = true; error.value = ''; images.value = []; checked.value = []; drawer.value = false
  try {
    const rows = await loadBatches()
    let data: TrainingImage[] = []
    if (!id && typeof route.params.id === 'string') {
      const sample = await getSample(route.params.id)
      if (sequence !== loadSequence) return
      if (sample.batch_id) {
        await router.replace({ path: '/training/quality', query: { batch: sample.batch_id, record: sample.sample_id } })
        return
      }
      if (!sample.excluded && ['confirmed', 'corrected'].includes(sample.review_status)) {
        data = sample.images.map(image => ({ ...image, sample_id: sample.sample_id, batch_id: null, tree_id: sample.tree_id,
          class_id: sample.final_class_id, class_name: sample.final_class_name, cultivar_id: sample.final_cultivar_id,
          cultivar_name: sample.final_cultivar_name, review_status: sample.review_status, uploaded_at: sample.upload_completed_at }))
        quality.value = 'all'
      }
    } else if (id) data = await loadImages(id, true)
    if (sequence !== loadSequence) return
    batches.value = rows; images.value = data
  } catch (e) { if (sequence === loadSequence) error.value = errorMessage(e) }
  finally { if (sequence === loadSequence) loading.value = false }
}
watch([batchId, () => route.params.id], () => { imageQuery.value = typeof route.query.record === 'string' ? route.query.record : ''; quality.value = route.query.record ? 'all' : 'pending'; void load() })
function openBatch(batch: TrainingBatch) { void router.push({ path: '/training/quality', query: { batch: batch.batch_id } }) }
function selectImage(image: TrainingImage) { currentId.value = image.image_id; drawer.value = true }
function move(direction: number) { const index = visible.value.findIndex(image => image.image_id === active.value?.image_id); if (visible.value.length) currentId.value = visible.value[(index + direction + visible.value.length) % visible.value.length].image_id }
function updateCounts(image: TrainingImage, old: TrainingImage['quality_status']) {
  const batch = batches.value.find(item => item.batch_id === image.batch_id)
  if (batch && image.quality_status !== old) { batch[`${old}_count`]--; batch[`${image.quality_status}_count`]++ }
}
async function save(image: TrainingImage, status: 'usable' | 'unusable', reason: QualityReasonCode | null) {
  const result = await setImageQuality(image.sample_id, image.image_id, { expected_version: image.quality_version, quality_status: status, quality_reason_code: reason })
  const old = image.quality_status
  Object.assign(image, result); updateCounts(image, old)
}
async function saveCurrent(status: 'usable' | 'unusable', reason: QualityReasonCode | null) {
  if (!active.value || busy.value) return
  const image = active.value, next = visible.value.find(item => item.image_id !== image.image_id && item.quality_status === 'pending')
  busy.value = true; error.value = ''
  try { await save(image, status, reason); if (next) currentId.value = next.image_id }
  catch (e) { error.value = errorMessage(e) }
  finally { busy.value = false }
}
async function markUsable() {
  if (busy.value) return
  busy.value = true; error.value = ''
  const failures: string[] = []
  for (const image of images.value.filter(item => checked.value.includes(item.image_id))) {
    try { await save(image, 'usable', null); checked.value = checked.value.filter(id => id !== image.image_id) }
    catch (e) { failures.push(`${image.image_id}：${errorMessage(e)}`) }
  }
  if (failures.length) error.value = `有 ${failures.length} 张未保存：${failures.join('；')}`
  busy.value = false
}
function openZoom() { zoomIndex.value = Math.max(0, visible.value.findIndex(image => image.image_id === active.value?.image_id)); zoom.value = true }
onMounted(() => { void bootstrap.load(); void load() })
</script>

<template>
  <div class="td-app td-integrated"><main class="td-content">
    <div class="td-page-heading"><div class="td-row"><button v-if="detailMode" class="td-icon-btn" aria-label="返回批次列表" :disabled="busy" @click="router.push('/training/quality')"><ArrowLeft :size="19" /></button><h1>{{ detailMode ? (currentBatch?.name || '采集记录质量') : '质量检查' }}</h1></div><span v-if="currentBatch" class="td-muted">{{ dateOnly(currentBatch.created_at) }} · {{ batchState(currentBatch) }}</span></div>
    <p v-if="error && !active" class="td-error" role="alert">{{ error }} <button class="td-text-btn" :disabled="busy" @click="load">刷新</button></p><p v-if="bootstrap.error" class="td-error">字典加载失败 <button class="td-text-btn" @click="bootstrap.load(true)">重试</button></p>
    <div v-if="loading" class="td-empty">加载中…</div>
    <template v-else-if="!detailMode">
      <section class="td-filter-bar"><div class="td-filter-row"><label class="td-search"><Search :size="15" /><input v-model="query" aria-label="查找质检批次" placeholder="批次名称 / 地点" /></label><select v-model="state" aria-label="质检批次状态"><option value="all">全部批次</option><option value="pending">待处理</option><option value="ready">处理完成</option></select><label class="td-row">批次创建日期<input v-model="from" type="date" aria-label="质检批次创建日期从" />至<input v-model="to" type="date" aria-label="质检批次创建日期至" /></label></div><p v-if="dateError" class="td-error">结束日期不能早于开始日期</p></section>
      <section class="td-jobs"><div class="td-table-wrap"><table class="td-table"><thead><tr><th>批次 / 创建日期</th><th>地点</th><th>状态</th><th>已核验图片</th><th>待质检</th><th>可用</th><th /></tr></thead><tbody><tr v-for="batch in listed" :key="batch.batch_id"><td><strong>{{ batch.name }}</strong><small>{{ dateOnly(batch.created_at) }} · {{ batch.batch_id }}</small></td><td>{{ batch.place || '—' }}</td><td><span class="td-badge">{{ batchState(batch) }}</span></td><td>{{ batch.reviewed_count }}</td><td>{{ batch.pending_count }}</td><td>{{ batch.usable_count }}</td><td><button class="td-text-btn" @click="openBatch(batch)">检查图片<ChevronRight :size="14" /></button></td></tr></tbody></table></div><div v-if="!listed.length" class="td-empty">暂无符合条件的批次</div></section>
    </template>
    <template v-else>
      <section class="td-filter-bar"><div class="td-filter-row"><label class="td-search"><Search :size="15" /><input v-model="imageQuery" aria-label="搜索图片或采集记录" placeholder="图片 ID / 采集记录 / 树号" /></label><select v-model="category" aria-label="质量检查病虫害类别"><option value="">全部类别</option><option v-for="item in bootstrap.classes" :key="item.class_id" :value="item.class_id">{{ item.name }}</option></select><select v-model="cultivar" aria-label="质量检查品种"><option value="">全部品种</option><option v-for="item in bootstrap.cultivars" :key="item.cultivar_id" :value="item.cultivar_id">{{ item.name }}</option></select></div></section>
      <div class="td-tabs td-quality-tabs"><button v-for="tab in tabs" :key="tab.id" :class="{ active: quality === tab.id }" :disabled="busy" @click="quality = tab.id">{{ tab.name }}<span>{{ tab.count }}</span></button></div>
      <div class="td-quality-layout"><section class="td-gallery"><div v-if="checked.length" class="td-bulk-bar"><span>已选 {{ checked.length }} 张</span><button class="td-btn primary" :disabled="busy" @click="markUsable"><Check :size="14" />标记可用</button><button class="td-text-btn" :disabled="busy" @click="checked = []">取消</button></div><div class="td-results-caption">{{ visible.length }} 张图片</div>
        <div class="td-image-grid"><article v-for="image in visible" :key="image.image_id" class="td-photo-card" :class="{ selected: active?.image_id === image.image_id }"><button class="td-photo-open" :aria-label="'检查 ' + image.image_id" :disabled="busy" @click="selectImage(image)"><SampleThumb :image-id="image.image_id" :alt="image.class_name || '采集图片'" /><span class="td-view-tag">{{ image.view_type === 'close_up' ? '近景' : image.view_type === 'context' ? '远景' : '其他' }}</span></button><input v-model="checked" type="checkbox" class="td-photo-checkbox" :value="image.image_id" :disabled="busy" :aria-label="'选择 ' + image.image_id" /><span class="td-badge td-photo-status" :class="image.quality_status">{{ qualityNames[image.quality_status] }}</span><button class="td-photo-info" :disabled="busy" @click="selectImage(image)"><span class="td-row td-between"><strong>{{ image.class_name }}</strong><span>{{ image.cultivar_name }}</span></span><small>{{ image.sample_id }}</small></button></article></div><div v-if="!visible.length" class="td-empty">{{ images.length ? '当前筛选下没有图片' : '本批次暂无已通过核验的图片' }} <button v-if="quality === 'pending' && scope.length" class="td-text-btn" @click="quality = 'all'">查看全部图片</button></div>
      </section><div v-if="active" class="td-inline-inspector"><QualityInspector :image="active" :position="position" :busy="busy" :error="error" @refresh="load" @save="saveCurrent" @move="move" @zoom="openZoom" /></div></div>
    </template>
  </main><div v-if="drawer && active" class="td-inspector-overlay" @click.self="!busy && (drawer = false)"><QualityInspector :image="active" :position="position" :busy="busy" :error="error" @refresh="load" @save="saveCurrent" @move="move" @zoom="openZoom" @close="drawer = false" /></div><ImageViewer v-model="zoom" v-model:index="zoomIndex" :images="visible.map(image => ({ image_id: image.image_id, caption: image.class_name || '' }))" /></div>
</template>
