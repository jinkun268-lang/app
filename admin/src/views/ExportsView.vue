<template>
  <div class="page">
    <div class="page-head">
      <h1 class="page-title">数据导出</h1>
    </div>

    <div class="card filter-card">
      <div class="filter-grid">
        <div class="field">
          <label class="form-label" for="exp-from">上传日期从</label>
          <input id="exp-from" v-model="filters.uploaded_from" type="date" class="input" />
        </div>
        <div class="field">
          <label class="form-label" for="exp-to">上传日期至</label>
          <input id="exp-to" v-model="filters.uploaded_to" type="date" class="input" />
        </div>
        <div class="field">
          <label class="form-label" for="exp-class">最终类别</label>
          <select id="exp-class" v-model="filters.final_class_id" class="select">
            <option value="">全部</option>
            <option v-for="c in bootstrap.activeClasses" :key="c.class_id" :value="c.class_id">{{ c.name }}</option>
          </select>
        </div>
      </div>
      <div class="toolbar">
        <span class="spacer" />
        <button class="btn btn-primary" :disabled="creating" @click="create">
          <Plus :size="15" />
          {{ creating ? '创建中…' : '创建导出任务' }}
        </button>
      </div>
      <p v-if="createError" class="err-text">{{ createError }}</p>
    </div>

    <div class="card">
      <div v-if="loading && jobs.length === 0" class="empty muted">加载中…</div>
      <div v-else-if="error && jobs.length === 0" class="empty">
        <p class="err-text">{{ error }}</p>
        <button class="btn" @click="load">重试</button>
      </div>
      <div v-else-if="jobs.length === 0" class="empty muted">暂无导出任务</div>
      <div v-else class="table-wrap">
      <table class="table">
        <thead>
          <tr>
            <th>批次</th>
            <th>状态</th>
            <th>条目数</th>
            <th>创建时间</th>
            <th>完成时间</th>
            <th>文件大小</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="e in jobs" :key="e.export_id">
            <td class="muted" :title="e.export_id">{{ e.export_id.slice(0, 13) }}…</td>
            <td><span class="tag" :class="statusClass(e.status)">{{ statusText(e.status) }}</span></td>
            <td>{{ e.item_count }}</td>
            <td class="muted">{{ fmt(e.created_at) }}</td>
            <td class="muted">{{ e.finished_at ? fmt(e.finished_at) : '—' }}</td>
            <td class="muted">
              <template v-if="e.status === 'succeeded'">{{ formatSize(e.zip_size) }}</template>
              <template v-else>—</template>
            </td>
            <td>
              <div class="flex">
                <button class="btn btn-sm" :disabled="e.status !== 'succeeded'" @click="download(e.export_id)">
                  <Download :size="13" />
                  下载
                </button>
                <button v-if="e.status === 'failed'" class="btn btn-sm" @click="retry(e.export_id)">重试</button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { Download, Plus } from 'lucide-vue-next'
import { createExport, downloadExport, listExports, retryExport } from '../api/exports'
import { ApiError } from '../api/http'
import { useBootstrapStore } from '../stores/bootstrap'
import { uuidv7 } from '../util/uuid'
import { errorMessage } from '../util/error'
import { toast } from '../ui/toast'
import { usePolling } from '../composables/usePolling'
import type { ExportJob } from '../types'

const bootstrap = useBootstrapStore()
const jobs = ref<ExportJob[]>([])
const loading = ref(false)
const error = ref('')
const creating = ref(false)
const createError = ref('')

const filters = reactive({ uploaded_from: '', uploaded_to: '', final_class_id: '' })

let pendingKey = ''

function statusText(s: string) {
  return ({ queued: '排队中', running: '生成中', succeeded: '成功', failed: '失败' } as Record<string, string>)[s] || s
}
function statusClass(s: string) {
  return ({ queued: 'tag-amber', running: 'tag-blue', succeeded: 'tag-green', failed: 'tag-red' } as Record<string, string>)[s] || 'tag-gray'
}
function fmt(iso: string | null) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })
  } catch {
    return iso
  }
}
function formatSize(bytes: number | null | undefined) {
  if (bytes == null) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const res = await listExports({ page: 1, page_size: 50 })
    jobs.value = res.items
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}

// 轮询未终态任务（2 秒起退避到 30 秒），终态停止。
const hasActive = () => jobs.value.some((e) => e.status === 'queued' || e.status === 'running')
const poll = usePolling<{ items: ExportJob[] }>(async () => {
  const res = await listExports({ page: 1, page_size: 50 })
  jobs.value = res.items
  return res
}, {
  initialDelayMs: 2000,
  stop: (res) => !res.items.some((e) => e.status === 'queued' || e.status === 'running'),
})

async function refreshActive() {
  const res = await listExports({ page: 1, page_size: 50 })
  jobs.value = res.items
  if (hasActive() && !poll.running.value) poll.start()
}

async function create() {
  creating.value = true
  createError.value = ''
  const key = pendingKey || uuidv7()
  try {
    await createExport(
      {
        format: 'dataset',
        uploaded_from: filters.uploaded_from || null,
        uploaded_to: filters.uploaded_to || null,
        final_class_id: filters.final_class_id || null,
      },
      key,
    )
    pendingKey = ''
    await refreshActive()
  } catch (e) {
    if (e instanceof ApiError) {
      pendingKey = ''
      createError.value = errorMessage(e)
    } else {
      // 网络失败：结果不确定，保留幂等键供重试复用
      pendingKey = key
      createError.value = '网络连接失败，请重试'
    }
  } finally {
    creating.value = false
  }
}

async function retry(id: string) {
  try {
    await retryExport(id, uuidv7())
    await refreshActive()
  } catch (e) {
    toast(errorMessage(e), 'error')
  }
}

async function download(id: string) {
  try {
    const { blob, filename } = await downloadExport(id)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    document.body.appendChild(a)
    a.click()
    a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (e) {
    toast(errorMessage(e), 'error')
  }
}

onMounted(async () => {
  await bootstrap.load().catch(() => {})
  await load()
  if (hasActive()) poll.start()
})
</script>

<style scoped>
.filter-card { padding: 14px; margin-bottom: 14px; }
.filter-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 8px; }
.filter-grid .field { margin-bottom: 0; }
.err-text { color: var(--danger); }
@media (max-width: 640px) {
  .filter-grid { grid-template-columns: 1fr; }
}
</style>
