<template>
  <div class="tickets">
    <aside class="queue card">
      <div class="pane-head">专家工单</div>
      <div class="toolbar filters">
        <select v-model="filters.status" class="select">
          <option value="">全部状态</option>
          <option value="queued">排队</option>
          <option value="reviewing">处理中</option>
          <option value="needs_info">待补充</option>
          <option value="done">已关闭</option>
        </select>
        <select v-model="filters.assignee" class="select">
          <option value="all">全部</option>
          <option value="me">本人</option>
          <option value="unassigned">未分配</option>
        </select>
      </div>

      <div v-if="loading" class="empty muted">加载中…</div>
      <div v-else-if="error" class="empty"><p class="err-text">{{ error }}</p><button class="btn" @click="load">重试</button></div>
      <div v-else-if="items.length === 0" class="empty muted">暂无工单</div>
      <ul v-else class="list">
        <li v-for="t in items" :key="t.ticket_id" class="item" :class="{ active: selectedId === t.ticket_id }" @click="open(t.ticket_id)">
          <div class="item-top">
            <span class="tag" :class="statusClass(t.status)">{{ statusText(t.status) }}</span>
            <span class="muted small">{{ t.assignee_display_name || '未分配' }}</span>
          </div>
          <div class="item-title">{{ t.question_text || '(仅图片)' }}</div>
        </li>
      </ul>
    </aside>

    <section class="detail-pane card" v-if="detail">
      <div class="pane-head">
        <span>工单 {{ detail.ticket_id.slice(0, 13) }}…</span>
        <span class="tag" :class="statusClass(detail.status)">{{ statusText(detail.status) }}</span>
        <span class="spacer" />
        <button class="btn btn-sm" @click="reload">刷新</button>
      </div>

      <div class="detail-body">
        <div class="question-box card">
          <div class="info-label">问题原文</div>
          <p class="question-text">{{ detail.question.text || '(仅图片，无文字)' }}</p>
          <div v-if="detail.question.attachments.length" class="attachments">
            <span class="info-label">附件</span>
            <span v-for="a in detail.question.attachments" :key="a.attachment_id" class="tag tag-gray">{{ a.mime_type }}</span>
          </div>
        </div>

        <div v-if="detail.question.supplements.length" class="section">
          <div class="section-title">补充时间线</div>
          <ul class="timeline">
            <li v-for="s in detail.question.supplements" :key="s.supplement_id">
              <span>{{ s.author_display_name }}</span>
              <span class="muted">{{ fmt(s.created_at) }}</span>
              <div>{{ s.text }}</div>
            </li>
          </ul>
        </div>

        <div v-if="detail.status === 'queued' || detail.status === 'reviewing' || detail.status === 'needs_info'" class="review-panel card">
          <template v-if="detail.status === 'queued'">
            <button class="btn btn-primary" :disabled="acting" @click="claim">领取工单</button>
          </template>
          <template v-else-if="detail.status === 'needs_info'">
            <p class="muted">等待补充</p>
          </template>
          <template v-else>
            <div class="field">
              <label class="form-label">答复草稿</label>
              <textarea v-model="draft" class="input" rows="4" placeholder="草稿…" />
            </div>
            <div class="actions">
              <button class="btn" :disabled="acting" @click="saveDraft">保存草稿</button>
              <button class="btn" :disabled="acting" @click="requestInfo">要求补充</button>
              <button class="btn btn-primary" :disabled="acting || !draft.trim()" @click="answer">发布答复</button>
              <button class="btn btn-danger" :disabled="acting" @click="unresolve">无法判断</button>
            </div>
            <div v-if="actionError" class="err-text">{{ actionError }}</div>
          </template>
        </div>

        <div v-else class="done-box card">
          <p>已关闭 · {{ outcomeText(detail.outcome) }}</p>
        </div>

        <div class="section">
          <div class="section-title">处理历史</div>
          <ul class="timeline">
            <li v-for="ev in detail.events" :key="ev.event_id">
              <span class="tag tag-gray">{{ eventText(ev.action) }}</span>
              <span>{{ ev.actor_display_name || '系统' }}</span>
              <span class="muted">{{ fmt(ev.at) }}</span>
            </li>
          </ul>
        </div>
      </div>
    </section>

    <section v-else class="detail-pane card">
      <div class="empty">请在左侧选择工单</div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import {
  answerTicket, claimTicket, getTicket, listTickets, requestTicketInfo, saveTicketDraft, unresolveTicket,
} from '../api/tickets'
import { uuidv7 } from '../util/uuid'
import { errorMessage } from '../util/error'
import { toast } from '../ui/toast'
import type { TicketDetail, TicketSummary } from '../types'

const filters = reactive({ status: '', assignee: 'all' as 'me' | 'unassigned' | 'all' })
const items = ref<TicketSummary[]>([])
const loading = ref(false)
const error = ref('')
const selectedId = ref('')
const detail = ref<TicketDetail | null>(null)
const draft = ref('')
const acting = ref(false)
const actionError = ref('')

function statusText(s: string) {
  return ({ queued: '排队', reviewing: '处理中', needs_info: '待补充', done: '已关闭' } as Record<string, string>)[s] || s
}
function statusClass(s: string) {
  return ({ queued: 'tag-amber', reviewing: 'tag-blue', needs_info: 'tag-amber', done: 'tag-gray' } as Record<string, string>)[s] || 'tag-gray'
}
function eventText(a: string) {
  return ({ create: '创建', claim: '领取', save_draft: '草稿', request_info: '要求补充', answer: '答复', unresolve: '无法判断', reopen: '回流' } as Record<string, string>)[a] || a
}
function outcomeText(o: string | null) {
  return o === 'answered' ? '已答复' : o === 'unresolved' ? '无法判断' : '—'
}
function fmt(iso: string) {
  try {
    return new Date(iso).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
  } catch {
    return iso
  }
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await listTickets({ status: filters.status || undefined, assignee: filters.assignee, page: 1, page_size: 50 })
    items.value = res.items
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}

async function open(id: string) {
  selectedId.value = id
  await reloadDetail()
}
async function reloadDetail() {
  if (!selectedId.value) return
  try {
    detail.value = await getTicket(selectedId.value)
    draft.value = detail.value.draft ?? ''
    actionError.value = ''
  } catch (e) {
    toast(errorMessage(e), 'error')
  }
}
async function reload() {
  await reloadDetail()
}

async function act(fn: () => Promise<unknown>) {
  acting.value = true
  actionError.value = ''
  try {
    await fn()
    await Promise.all([reloadDetail(), load()])
  } catch (e) {
    actionError.value = errorMessage(e)
    // 版本冲突时重读最新
    await reloadDetail()
  } finally {
    acting.value = false
  }
}

async function claim() {
  await act(() => claimTicket(selectedId.value, { expected_version: detail.value!.version }, uuidv7()))
}
async function saveDraft() {
  await act(() => saveTicketDraft(selectedId.value, { expected_version: detail.value!.version, draft: draft.value }, uuidv7()))
}
async function requestInfo() {
  const text = window.prompt('请输入需要用户补充的说明：')
  if (text == null) return
  await act(() => requestTicketInfo(selectedId.value, { expected_version: detail.value!.version, request_text: text }, uuidv7()))
}
async function answer() {
  if (!draft.value.trim()) return
  await act(() => answerTicket(selectedId.value, { expected_version: detail.value!.version, answer_text: draft.value.trim() }, uuidv7()))
}
async function unresolve() {
  if (!window.confirm('确定标记为无法判断？')) return
  await act(() => unresolveTicket(selectedId.value, { expected_version: detail.value!.version, reason: '无法判断' }, uuidv7()))
}

onMounted(load)
</script>

<style scoped>
.tickets { display: flex; gap: 12px; height: 100%; padding: 12px; }
.queue { width: 32%; min-width: 300px; display: flex; flex-direction: column; overflow: hidden; }
.detail-pane { flex: 1; display: flex; flex-direction: column; overflow: hidden; min-width: 0; }
.pane-head { padding: 14px 16px; font-weight: 600; border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.filters { padding: 12px; margin: 0; display: flex; gap: 8px; }
.filters .select { flex: 1; }
.list { list-style: none; margin: 0; padding: 0; overflow: auto; flex: 1; }
.item { padding: 12px 16px; border-bottom: 1px solid var(--border); cursor: pointer; }
.item.active { background: var(--primary-weak); border-left: 3px solid var(--primary); }
.item-top { display: flex; justify-content: space-between; margin-bottom: 4px; }
.item-title { font-weight: 500; }
.detail-body { padding: 16px; overflow: auto; flex: 1; }
.question-box { padding: 12px; margin-bottom: 12px; }
.question-text { font-size: 15px; margin: 6px 0; }
.warn { color: var(--warn); font-size: 13px; }
.attachments { margin-top: 8px; }
.section { margin-top: 12px; }
.section-title { font-weight: 600; margin-bottom: 8px; }
.review-panel { padding: 14px; margin-bottom: 12px; }
.actions { display: flex; gap: 8px; margin-top: 12px; flex-wrap: wrap; }
.done-box { padding: 14px; margin-bottom: 12px; background: #f9fafb; }
.timeline { list-style: none; margin: 0; padding: 0; }
.timeline li { display: flex; gap: 8px; align-items: center; padding: 6px 0; border-bottom: 1px solid var(--border); font-size: 13px; flex-wrap: wrap; }
.info-label { color: var(--muted); font-size: 12px; margin-bottom: 4px; }
.err-text { color: var(--danger); font-size: 13px; }
</style>
