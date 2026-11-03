<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { CalendarDays, ChevronDown, Search, SlidersHorizontal } from 'lucide-vue-next'
import { correctOffline, listOffline, offlineImage, subscribeOffline, type OfflineRecognition } from '../api/offlineRecognitions'
import { errorMessage } from '../util/error'
import Pagination from '../components/Pagination.vue'

const filters = reactive({ query: '', status: '', names: [] as string[], start: '', end: '' })
const search = ref(''), page = ref(1), total = ref(0), categories = ref<string[]>([])
const items = ref<OfflineRecognition[]>([]), detail = ref<OfflineRecognition | null>(null)
const loading = ref(false), error = ref(''), notice = ref(''), imageUrl = ref(''), imageError = ref('')
const popup = ref<'date' | 'category' | null>(null), filterBox = ref<HTMLElement>(), dateButton = ref<HTMLButtonElement>()
const dateStart = ref<HTMLInputElement>(), draftStart = ref(''), draftEnd = ref(''), dateError = ref('')
const editor = ref<HTMLDialogElement>(), name = ref(''), note = ref(''), saving = ref(false), saveError = ref('')
const historyExpanded = ref(false)
const corrections = computed(() => [...(detail.value?.correction_events || [])].sort((a, b) => b.version - a.version))
const visibleCorrections = computed(() => historyExpanded.value ? corrections.value : corrections.value.slice(0, 1))
const original = computed(() => detail.value?.recognition ? [...detail.value.recognition.candidates].sort((a, b) => b.score - a.score) : [])
const editTarget = ref<{ id: string; version: number; name: string } | null>(null)
const categoryOptions = computed(() => [...new Set([...categories.value, ...filters.names])].sort())
const dateText = computed(() => filters.start || filters.end ? `${filters.start || '不限'} 至 ${filters.end || '不限'}` : '选择时间')
const categoryText = computed(() => filters.names.length ? filters.names.length === 1 ? filters.names[0] : `已选 ${filters.names.length} 类` : '全部疾病')
let listSequence = 0, imageSequence = 0
let unsubscribe: (() => void) | undefined, liveTimer: ReturnType<typeof setTimeout> | undefined
function changed() { if (liveTimer) clearTimeout(liveTimer); liveTimer = setTimeout(() => void load(), 100) }
function statusLabel(row: OfflineRecognition) { return row.correction_version ? '已修正' : row.inference_status === 'processing' ? '识别中' : row.inference_status === 'failed' ? '识别失败' : '原始结果' }

function time(value: string | null) {
  return value ? new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(value)) : '—'
}
function context(key: string) {
  return ({ huyou: '胡柚', xiangyou: '香柚', citrus: '其他柑橘', leaf: '叶片', fruit: '果实', branch: '枝条', adult: '成年树', young: '幼树', unknown: '树龄未知' } as Record<string, string>)[key] || key
}
async function load(preferred = detail.value?.record_id) {
  const seq = ++listSequence
  loading.value = true; error.value = ''
  try {
    const result = await listOffline(filters, page.value)
    if (seq !== listSequence) return
    if (!result.items.length && page.value > 1) { page.value = Math.max(1, Math.ceil(result.total / 20)); return }
    items.value = result.items; total.value = result.total; categories.value = result.categories
    select(result.items.find(row => row.record_id === preferred) || result.items[0] || null)
  } catch (e) {
    if (seq === listSequence) { error.value = errorMessage(e); items.value = []; select(null) }
  } finally { if (seq === listSequence) loading.value = false }
}
function select(row: OfflineRecognition | null) {
  const changed = row?.record_id !== detail.value?.record_id
  detail.value = row
  if (changed) { historyExpanded.value = false; void loadImage() }
}
async function loadImage() {
  const seq = ++imageSequence, id = detail.value?.record_id
  if (imageUrl.value) URL.revokeObjectURL(imageUrl.value)
  imageUrl.value = ''; imageError.value = ''
  if (!id) return
  try {
    const blob = await offlineImage(id)
    if (seq === imageSequence) imageUrl.value = URL.createObjectURL(blob)
  } catch (e) { if (seq === imageSequence) imageError.value = errorMessage(e) }
}
async function download() {
  if (!detail.value) return
  const row = detail.value
  try {
    const blob = await offlineImage(row.record_id, false), url = URL.createObjectURL(blob)
    const a = document.createElement('a'); a.href = url; a.download = `${row.record_id}.${row.mime_type === 'image/jpeg' ? 'jpg' : row.mime_type === 'image/png' ? 'png' : 'webp'}`; a.click()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (e) { error.value = errorMessage(e) }
}
async function togglePopup(value: 'date' | 'category') {
  if (popup.value === value) { popup.value = null; return }
  popup.value = value
  if (value === 'date') {
    draftStart.value = filters.start; draftEnd.value = filters.end; dateError.value = ''
    await nextTick(); dateStart.value?.focus()
  }
}
function applyDate() {
  if (draftStart.value && draftEnd.value && draftStart.value > draftEnd.value) { dateError.value = '开始日期不能晚于结束日期'; return }
  filters.start = draftStart.value; filters.end = draftEnd.value; popup.value = null; dateButton.value?.focus()
}
function clearDate() {
  filters.start = ''; filters.end = ''; popup.value = null; dateButton.value?.focus()
}
function toggleCategory(value: string) {
  filters.names = filters.names.includes(value) ? filters.names.filter(name => name !== value) : [...filters.names, value]
}
function outside(event: PointerEvent) { if (!filterBox.value?.contains(event.target as Node)) popup.value = null }
function escape(event: KeyboardEvent) { if (event.key === 'Escape' && popup.value) { popup.value = null; dateButton.value?.focus() } }
function edit() { if (!detail.value) return; editTarget.value = { id: detail.value.record_id, version: detail.value.correction_version, name: detail.value.current_name }; name.value = detail.value.current_name; note.value = ''; saveError.value = ''; editor.value?.showModal() }
async function save() {
  if (!editTarget.value || saving.value || !name.value.trim()) return
  const target = editTarget.value
  saving.value = true; saveError.value = ''; notice.value = ''
  try {
    await correctOffline(target.id, target.version, name.value.trim(), note.value.trim())
    editor.value?.close(); historyExpanded.value = false; notice.value = '修正已保存'; await load(target.id)
  } catch (e) { saveError.value = errorMessage(e) }
  finally { saving.value = false }
}
watch(() => [filters.query, filters.status, [...filters.names], filters.start, filters.end], () => { if (page.value === 1) void load(); else page.value = 1 })
watch(page, () => void load())
onMounted(() => { void load(); unsubscribe = subscribeOffline(changed); document.addEventListener('pointerdown', outside); document.addEventListener('keydown', escape) })
onBeforeUnmount(() => { unsubscribe?.(); if (liveTimer) clearTimeout(liveTimer); ++listSequence; ++imageSequence; if (imageUrl.value) URL.revokeObjectURL(imageUrl.value); document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape) })
</script>

<template>
  <div class="offline-page">
    <div class="heading"><h2>离线识别</h2><span class="muted">{{ total }} 条记录</span></div>
    <div ref="filterBox" class="filters">
      <form class="search" @submit.prevent="filters.query = search.trim()"><Search :size="16" /><input v-model="search" aria-label="搜索记录" placeholder="搜索记录编号、上传人" /><button type="submit">搜索</button></form>
      <select v-model="filters.status" class="input status" aria-label="修正状态"><option value="">全部状态</option><option value="original">原始结果</option><option value="corrected">已修正</option></select>
      <div class="filter-anchor category-anchor">
        <button class="btn filter-button" :class="{ applied: filters.names.length }" aria-label="疾病类别多选" :aria-expanded="popup === 'category'" @click="togglePopup('category')"><SlidersHorizontal :size="15" /><span>{{ categoryText }}</span><ChevronDown :size="14" /></button>
        <div v-if="popup === 'category'" class="popover category-menu"><button class="text-button" @click="filters.names = []">全部疾病</button><label v-for="category in categoryOptions" :key="category"><input type="checkbox" :checked="filters.names.includes(category)" @change="toggleCategory(category)" />{{ category }}</label><p v-if="!categoryOptions.length" class="muted">暂无类别</p></div>
      </div>
      <div class="filter-anchor date-anchor">
        <button ref="dateButton" class="btn filter-button" :class="{ applied: filters.start || filters.end }" :aria-expanded="popup === 'date'" @click="togglePopup('date')"><CalendarDays :size="16" /><span>{{ dateText }}</span><ChevronDown :size="14" /></button>
        <div v-if="popup === 'date'" class="popover date-menu" role="dialog" aria-label="上传日期范围"><div class="date-inputs"><label>开始日期<input ref="dateStart" v-model="draftStart" class="input" type="date" aria-label="开始日期" /></label><span>至</span><label>结束日期<input v-model="draftEnd" class="input" type="date" aria-label="结束日期" /></label></div><p v-if="dateError" class="err-text" role="alert">{{ dateError }}</p><div class="date-actions"><button class="text-button" @click="clearDate">清除</button><button class="btn btn-primary" @click="applyDate">应用</button></div></div>
      </div>
      <button v-if="filters.query || filters.status || filters.names.length || filters.start || filters.end" class="text-button" @click="search = ''; Object.assign(filters, { query: '', status: '', names: [], start: '', end: '' })">重置</button>
    </div>
    <p v-if="error" class="err-text" role="alert">{{ error }} <button class="text-button" @click="load()">重试</button></p><p v-if="notice" class="notice" role="status">{{ notice }}</p>
    <div class="columns" :aria-busy="loading">
      <section class="card records" aria-label="识别记录列表"><div class="list-heading">识别记录<span class="muted">{{ loading ? '加载中…' : total + ' 条' }}</span></div>
        <div v-if="!items.length" class="empty">{{ loading ? '正在加载记录…' : '暂无符合条件的记录' }}</div>
        <button v-for="row in items" :key="row.record_id" class="record" :class="{ active: detail?.record_id === row.record_id }" :disabled="loading" @click="select(row)"><div class="row-main"><strong>{{ row.current_name }}</strong><span class="badge" :class="{ corrected: row.correction_version }">{{ statusLabel(row) }}</span></div><div class="row-meta"><span>{{ row.owner_display_name }}</span><span>{{ time(row.uploaded_at) }}</span></div><small class="muted record-id">{{ row.record_id }}</small></button>
        <Pagination :page="page" :page-size="20" :total="total" @change="page = $event" />
      </section>
      <section class="card detail" aria-label="识别详情">
        <template v-if="detail"><div class="detail-heading"><h3>识别详情</h3><button class="text-button" @click="download">下载原图</button></div>
          <div class="photo"><img v-if="imageUrl" :src="imageUrl" alt="上传的识别图片" /><div v-else>{{ imageError || '图片加载中…' }}<button v-if="imageError" class="text-button" @click="loadImage">重试</button></div></div>
          <div class="context"><span>{{ detail.owner_display_name }}</span><span>{{ context(detail.crop_id) }} · {{ context(detail.part) }} · {{ context(detail.tree_age) }}</span><span>拍摄 {{ time(detail.captured_at) }}</span><span>上传 {{ time(detail.uploaded_at) }}</span></div>
          <p v-if="detail.symptom" class="symptom">{{ detail.symptom }}</p>
          <div class="result-card"><div><span class="muted">{{ detail.correction_version ? '人工修正' : statusLabel(detail) }}</span><h3>{{ detail.current_name }}</h3></div><button class="btn" :disabled="loading || detail.inference_status === 'processing'" @click="edit">修正结果</button></div>
          <div class="original"><h4>原始识别</h4><template v-if="detail.recognition"><div v-for="candidate in original" :key="candidate.label" class="candidate"><span>{{ candidate.name }}</span><div class="score-bar"><span :style="{ width: candidate.score * 100 + '%' }" /></div><span class="score">{{ (candidate.score * 100).toFixed(1) }}%</span></div><p class="muted model">{{ detail.recognition.model }} · {{ detail.recognition.model_version }} · {{ detail.source === 'device' ? '端侧识别' : '服务端识别' }}</p></template><p v-else class="muted">{{ detail.inference_status === 'processing' ? '识别中…' : detail.inference_error || '系统识别错误' }}</p></div>
          <div v-if="corrections.length" class="history">
            <div class="history-heading"><h4>修正记录</h4><button v-if="corrections.length > 1" class="text-button" :aria-expanded="historyExpanded" aria-controls="offline-correction-history" @click="historyExpanded = !historyExpanded">{{ historyExpanded ? '收起历史记录' : `展开其余 ${corrections.length - 1} 条` }}</button></div>
            <div id="offline-correction-history"><div v-for="event in visibleCorrections" :key="event.version" class="event"><div><strong>{{ event.from_name }} → {{ event.name }}</strong><span class="muted">{{ event.operator }} · {{ time(event.corrected_at) }}</span></div><p v-if="event.note">{{ event.note }}</p></div></div>
          </div>
          <div class="reminder"><span>消息提醒</span><button class="btn btn-sm" disabled title="等待消息系统接入">暂未接入</button></div>
        </template><div v-else class="empty">选择一条记录查看详情</div>
      </section>
    </div>
    <dialog ref="editor" class="correction-dialog" @cancel="saving && $event.preventDefault()"><form @submit.prevent="save"><h3>修正识别结果</h3><label>疾病类型<input v-model="name" class="input" required maxlength="100" :disabled="saving" list="offline-category-options" /><datalist id="offline-category-options"><option v-for="category in categoryOptions" :key="category" :value="category" /></datalist></label><label>修正说明<textarea v-model="note" class="input" rows="3" maxlength="2000" :disabled="saving" placeholder="选填" /></label><p v-if="saveError" class="err-text" role="alert">{{ saveError }}</p><div class="dialog-actions"><button type="button" class="btn" :disabled="saving" @click="editor?.close()">取消</button><button type="submit" class="btn btn-primary" :disabled="saving || !name.trim() || name.trim() === editTarget?.name">{{ saving ? '保存中…' : '保存修正' }}</button></div></form></dialog>
  </div>
</template>

<style scoped>
.offline-page{padding:24px;max-width:1500px;margin:auto;color:#293f34}.heading{display:flex;align-items:center;gap:14px;margin-bottom:20px}.heading h2{font-size:21px;margin:0}.heading>span{font-size:13px}.filters{display:flex;align-items:center;gap:10px;margin-bottom:18px;flex-wrap:wrap}.search{height:40px;display:flex;align-items:center;gap:8px;border:1px solid var(--border);border-radius:6px;background:white;padding:0 10px;flex:1;min-width:230px;max-width:420px;color:#76877c}.search input{border:0;outline:0;min-width:0;flex:1;background:transparent;font:inherit;font-size:13px}.search button,.text-button{border:0;background:transparent;color:#356d51;cursor:pointer;font:inherit;font-size:13px;padding:6px;white-space:nowrap}.status{width:125px;height:40px;font-size:13px}.filter-anchor{position:relative}.filter-button{display:flex;align-items:center;gap:8px;height:40px;font-size:13px}.filter-button.applied{border-color:#95b3a0;color:#285b43;background:#f5faf6}.category-anchor{min-width:148px}.category-anchor .filter-button{width:100%}.filter-button>span{flex:1;text-align:left}.popover{position:absolute;z-index:30;top:calc(100% + 7px);padding:16px;background:#fff;border:1px solid #dce5dc;border-radius:9px;box-shadow:0 12px 35px #183c2622}.category-menu{left:0;min-width:220px;max-height:330px;overflow:auto;padding:8px}.category-menu label{display:flex;align-items:center;gap:9px;padding:10px;cursor:pointer;white-space:nowrap;font-size:13px}.category-menu label:hover{background:#f1f6ef}.category-menu input{accent-color:#285b43}.date-menu{right:0;width:400px}.date-inputs{display:flex;gap:10px;align-items:end}.date-inputs label{flex:1;min-width:0;font-size:12px;color:#687d6d}.date-inputs .input{display:block;width:100%;margin-top:8px;height:39px;font-size:13px}.date-inputs>span{padding-bottom:10px}.date-actions,.dialog-actions{display:flex;justify-content:flex-end;gap:10px;margin-top:18px}.date-actions{justify-content:space-between}.columns{display:grid;grid-template-columns:minmax(290px,.82fr) minmax(480px,1.7fr);gap:18px;align-items:start}.card{min-width:0;overflow:hidden;border-radius:10px;border:1px solid #dde6dd;box-shadow:0 2px 6px #1c332408;background:#fff}.list-heading{display:flex;justify-content:space-between;padding:18px;font-weight:600;border-bottom:1px solid #e5ece4}.list-heading span{font-weight:400;font-size:12px}.record{width:100%;display:block;text-align:left;cursor:pointer;border:0;border-bottom:1px solid #edf1eb;background:#fff;padding:17px 18px;line-height:1.6;color:inherit}.record.active{background:#edf5ee;box-shadow:inset 3px 0 #316a4b}.record:hover{background:#f4f8f2}.row-main{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:8px}.row-main strong{font-size:15px}.badge{border-radius:4px;background:#f0f3ef;color:#6b7d6c;font-size:11px;padding:2px 7px;white-space:nowrap}.badge.corrected{background:#dfefe4;color:#2a6848}.row-meta{display:flex;justify-content:space-between;color:#6f8073;font-size:12px}.record-id{font-family:monospace;font-size:10px;display:block;margin-top:5px;overflow-wrap:anywhere}.detail{padding:20px 24px}.detail-heading{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}.detail-heading h3{font-size:16px;margin:0}.photo{height:300px;background:#f1f4ef;display:flex;align-items:center;justify-content:center;border-radius:7px;overflow:hidden;color:#7a897c;font-size:13px}.photo img{width:100%;height:100%;object-fit:contain}.context{display:flex;gap:7px 20px;flex-wrap:wrap;font-size:12px;color:#718275;margin:15px 0}.symptom{font-size:13px;white-space:pre-wrap;overflow-wrap:anywhere}.result-card{display:flex;justify-content:space-between;align-items:center;padding:16px 18px;background:#f1f7ed;border:1px solid #dce8d5;border-radius:7px;margin:18px 0}.result-card .muted{font-size:12px}.result-card h3{font-size:20px;margin:6px 0 0}.original h4,.history h4{font-size:14px;margin:20px 0 13px}.candidate{display:flex;gap:12px;align-items:center;margin:12px 0;font-size:13px}.candidate>span:first-child{width:130px;overflow-wrap:anywhere}.score-bar{height:5px;background:#edf1e9;flex:1;border-radius:3px;overflow:hidden}.score-bar>span{display:block;height:100%;background:#89a881}.score{font-variant-numeric:tabular-nums;width:52px;text-align:right;color:#687e6a}.model{font-size:11px;margin:15px 0}.event{border-left:2px solid #d7e5d6;padding:2px 0 2px 12px;margin:12px 0;font-size:12px}.event>div{display:flex;gap:8px;flex-wrap:wrap;justify-content:space-between}.event p{white-space:pre-wrap;overflow-wrap:anywhere;margin:7px 0}.reminder{display:flex;align-items:center;justify-content:space-between;border-top:1px solid #e7ede5;padding-top:15px;margin-top:20px;font-size:13px;color:#768779}.empty{padding:60px 18px;text-align:center;color:#89968a;font-size:13px}.notice{font-size:13px;color:#356d51}.correction-dialog{padding:25px;border:1px solid #dce5dc;border-radius:12px;width:min(460px,90vw);color:#293f34;box-shadow:0 24px 80px #12361b33}.correction-dialog::backdrop{background:#102c2055}.correction-dialog h3{margin:0 0 22px;font-size:18px}.correction-dialog label{display:block;margin:16px 0;font-size:13px}.correction-dialog .input{display:block;width:100%;margin-top:8px}.muted{color:#849080}@media(max-width:1100px){.columns{grid-template-columns:minmax(265px,1fr) minmax(380px,1.6fr)}.offline-page{padding:18px}.detail{padding:18px}.photo{height:250px}}@media(max-width:760px){.columns{grid-template-columns:1fr}.search{max-width:none;flex-basis:100%}.date-menu{right:0;width:min(400px,calc(100vw - 36px))}.date-inputs{flex-wrap:wrap}.date-inputs label{min-width:125px}.detail{padding:18px}.photo{height:260px}.row-meta{gap:12px}}

@media(max-width:760px){
  .filters{position:relative}
  .date-anchor{position:static}
  .date-menu{left:0;right:auto;top:100%}
}
.history-heading{display:flex;align-items:center;justify-content:space-between;gap:12px}
.history-heading h4{margin:20px 0 13px}
.history-heading .text-button{margin-top:7px}
</style>
