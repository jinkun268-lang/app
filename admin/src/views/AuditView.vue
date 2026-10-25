<template>
  <div class="page">
    <div class="toolbar">
      <input v-model="filters.object_type" class="input search" placeholder="对象类型" @change="apply" />
      <input v-model="filters.object_id" class="input search" placeholder="对象 ID" @change="apply" />
      <input v-model="filters.actor_id" class="input search" placeholder="操作者 ID" @change="apply" />
      <input v-model="filters.action" class="input search" placeholder="动作" @change="apply" />
      <input v-model="filters.from" type="date" class="input search" @change="apply" />
      <input v-model="filters.to" type="date" class="input search" @change="apply" />
      <button class="btn btn-sm" @click="clearFilters">清空</button>
      <span class="spacer" />
    </div>

    <div class="card">
      <div v-if="loading" class="empty muted">加载中…</div>
      <div v-else-if="error" class="empty"><p class="err-text">{{ error }}</p><button class="btn" @click="load">重试</button></div>
      <div v-else-if="items.length === 0" class="empty muted">暂无审计记录</div>
      <table v-else class="table">
        <thead>
          <tr>
            <th>时间</th>
            <th>操作者</th>
            <th>动作</th>
            <th>对象</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="a in items" :key="a.audit_id">
            <td class="muted">{{ fmt(a.at) }}</td>
            <td>{{ a.actor_display_name || '—' }}</td>
            <td><code>{{ a.action }}</code></td>
            <td>{{ a.object_type }} / <span class="muted">{{ a.object_id }}</span></td>
            <td><button class="btn btn-sm" @click="showDiff(a)">查看差异</button></td>
          </tr>
        </tbody>
      </table>
      <Pagination :page="page" :page-size="pageSize" :total="total" @change="setPage" />
    </div>

    <Modal v-model="showDiffModal" title="变更差异">
      <div class="diff-col">
        <div class="diff-label">变更前</div>
        <pre class="diff-pre">{{ diffBefore }}</pre>
      </div>
      <div class="diff-col">
        <div class="diff-label">变更后</div>
        <pre class="diff-pre">{{ diffAfter }}</pre>
      </div>
      <template #footer>
        <button class="btn" @click="showDiffModal = false">关闭</button>
      </template>
    </Modal>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import Modal from '../components/Modal.vue'
import Pagination from '../components/Pagination.vue'
import { listAudit } from '../api/audit'
import { errorMessage } from '../util/error'
import type { AuditRow } from '../types'

const items = ref<AuditRow[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 20
const loading = ref(false)
const error = ref('')

const filters = reactive({ object_type: '', object_id: '', actor_id: '', action: '', from: '', to: '' })

const showDiffModal = ref(false)
const diffBefore = ref('')
const diffAfter = ref('')

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
    const res = await listAudit({
      object_type: filters.object_type || undefined,
      object_id: filters.object_id || undefined,
      actor_id: filters.actor_id || undefined,
      action: filters.action || undefined,
      from: filters.from || undefined,
      to: filters.to || undefined,
      page: page.value,
      page_size: pageSize,
    })
    items.value = res.items
    total.value = res.total
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}

function apply() {
  page.value = 1
  void load()
}
function setPage(p: number) {
  page.value = p
  void load()
}
function clearFilters() {
  filters.object_type = ''
  filters.object_id = ''
  filters.actor_id = ''
  filters.action = ''
  filters.from = ''
  filters.to = ''
  apply()
}

function showDiff(a: AuditRow) {
  diffBefore.value = a.before_json ? JSON.stringify(a.before_json, null, 2) : '—'
  diffAfter.value = a.after_json ? JSON.stringify(a.after_json, null, 2) : '—'
  showDiffModal.value = true
}

onMounted(load)
</script>

<style scoped>
.search { max-width: 150px; }
code { background: #f3f4f6; padding: 1px 6px; border-radius: 4px; font-size: 12px; }
.err-text { color: var(--danger); }
.diff-col { margin-bottom: 12px; }
.diff-label { font-size: 12px; color: var(--muted); margin-bottom: 4px; }
.diff-pre { background: #f9fafb; padding: 10px; border-radius: 6px; font-size: 12px; overflow: auto; max-height: 200px; white-space: pre-wrap; word-break: break-all; }
</style>
