<template>
  <div class="page">
    <div class="tabs">
      <button v-for="t in tabs" :key="t.key" class="tab" :class="{ active: active === t.key }" @click="active = t.key">{{ t.label }}</button>
      <span class="spacer" />
      <button v-if="active === 'class'" class="btn btn-sm" @click="openImport">CSV 导入</button>
      <button class="btn btn-primary btn-sm" @click="openAdd">新增</button>
    </div>

    <div class="card">
      <div v-if="loading" class="empty muted">加载中…</div>
      <table v-else class="table">
        <thead>
          <tr>
            <th>编码</th>
            <th>名称</th>
            <th v-if="active === 'class'">占位</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="rowKey(row)">
            <td class="muted">{{ rowKey(row) }}</td>
            <td>{{ row.name }}</td>
            <td v-if="active === 'class'">{{ (row as ClassEntry).is_provisional ? '是' : '否' }}</td>
            <td><span class="tag" :class="row.is_active ? 'tag-green' : 'tag-gray'">{{ row.is_active ? '启用' : '停用' }}</span></td>
            <td>
              <button class="btn btn-sm" @click="openEdit(row)">编辑</button>
              <button class="btn btn-sm" :disabled="isReserved(rowKey(row))" @click="toggleActive(row)">{{ row.is_active ? '停用' : '启用' }}</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <Modal v-model="showForm" :title="editing ? '编辑' : '新增'" :busy="submitting">
      <div class="field">
        <label class="form-label">编码</label>
        <input v-model="form.code" class="input" :disabled="!!editing" placeholder="如 huyou" />
      </div>
      <div class="field">
        <label class="form-label">名称</label>
        <input v-model="form.name" class="input" placeholder="请输入名称" />
      </div>
      <div v-if="active === 'class'" class="field">
        <label class="form-label">父类别</label>
        <select v-model="form.parentId" class="select">
          <option value="">无</option>
          <option v-for="c in classes" :key="c.class_id" :value="c.class_id" :disabled="c.class_id === form.code">{{ c.name }}</option>
        </select>
      </div>
      <p v-if="formError" class="err-text">{{ formError }}</p>
      <template #footer>
        <button class="btn" :disabled="submitting" @click="showForm = false">取消</button>
        <button class="btn btn-primary" :disabled="submitting" @click="submit">{{ submitting ? '提交中…' : '确定' }}</button>
      </template>
    </Modal>

    <Modal v-model="showImport" title="类别 CSV 导入" :busy="importing">
      <div class="field">
        <label class="form-label">CSV 文件</label>
        <input type="file" accept=".csv,text/csv" class="input" @change="onFile" />
      </div>
      <div v-if="preview" class="import-result">
        <p>新增 {{ preview.added }} · 变更 {{ preview.changed }} · 不变 {{ preview.unchanged }} · 拒绝 {{ preview.rejected }}</p>
        <ul v-if="preview.row_errors.length" class="errors">
          <li v-for="(e, i) in preview.row_errors" :key="i">第 {{ e.row }} 行：{{ e.message }}</li>
        </ul>
      </div>
      <p v-if="importError" class="err-text">{{ importError }}</p>
      <template #footer>
        <button class="btn" :disabled="importing" @click="showImport = false">取消</button>
        <button class="btn" :disabled="importing || !file" @click="doPreview">{{ preview ? '重新预览' : '预览' }}</button>
        <button class="btn btn-primary" :disabled="importing || !canConfirm" @click="doConfirm">确认导入</button>
      </template>
    </Modal>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import Modal from '../components/Modal.vue'
import {
  confirmClassImport, createClass, createCultivar, listClasses, listCultivars,
  previewClassImport, updateClass, updateCultivar,
} from '../api/dictionaries'
import { useBootstrapStore } from '../stores/bootstrap'
import { uuidv7 } from '../util/uuid'
import { errorMessage } from '../util/error'
import { toast } from '../ui/toast'
import type { ClassEntry, ClassImportPreviewResponse, Cultivar } from '../types'

type TabKey = 'cultivar' | 'class'
type Row = Cultivar | ClassEntry

const active = ref<TabKey>('cultivar')
const tabs: { key: TabKey; label: string }[] = [
  { key: 'cultivar', label: '品种' },
  { key: 'class', label: '类别' },
]

const cultivars = ref<Cultivar[]>([])
const classes = ref<ClassEntry[]>([])
const loading = ref(false)
const bootstrap = useBootstrapStore()

const rows = computed<Row[]>(() => {
  if (active.value === 'cultivar') return cultivars.value
  return classes.value
})

function rowKey(row: Row): string {
  if ('cultivar_id' in row) return row.cultivar_id
  return row.class_id
}
function isReserved(code: string): boolean {
  return code === 'unknown'
}

const showForm = ref(false)
const editing = ref<Row | null>(null)
const submitting = ref(false)
const formError = ref('')
const form = reactive({ code: '', name: '', parentId: '' })

function openAdd() {
  editing.value = null
  form.code = ''
  form.name = ''
  form.parentId = ''
  formError.value = ''
  showForm.value = true
}
function openEdit(row: Row) {
  editing.value = row
  form.code = rowKey(row)
  form.name = row.name
  form.parentId = 'parent_id' in row && row.parent_id ? row.parent_id : ''
  formError.value = ''
  showForm.value = true
}

async function submit() {
  const code = form.code.trim()
  const name = form.name.trim()
  if (!code) {
    formError.value = '业务编码必填'
    return
  }
  if (!/^[a-z][a-z0-9_]{1,31}$/.test(code)) {
    formError.value = '业务编码格式不合法（小写字母开头，2–32 字符）'
    return
  }
  if (!name) {
    formError.value = '名称必填'
    return
  }
  submitting.value = true
  formError.value = ''
  try {
    if (active.value === 'cultivar') {
      if (editing.value) await updateCultivar(code, { expected_version: (editing.value as Cultivar).version, name })
      else await createCultivar({ cultivar_id: code, name })
    } else {
      if (editing.value) await updateClass(code, { expected_version: (editing.value as ClassEntry).version, name, parent_id: form.parentId || null })
      else await createClass({ class_id: code, name, parent_id: form.parentId || null })
    }
    showForm.value = false
    await Promise.all([load(), bootstrap.load(true)])
  } catch (e) {
    formError.value = errorMessage(e)
  } finally {
    submitting.value = false
  }
}

async function toggleActive(row: Row) {
  try {
    const code = rowKey(row)
    if (active.value === 'cultivar') await updateCultivar(code, { expected_version: (row as Cultivar).version, is_active: !row.is_active })
    else await updateClass(code, { expected_version: (row as ClassEntry).version, is_active: !row.is_active })
    await Promise.all([load(), bootstrap.load(true)])
  } catch (e) {
    toast(errorMessage(e), 'error')
  }
}

// CSV 导入（仅类别）
const showImport = ref(false)
const file = ref<File | null>(null)
const preview = ref<ClassImportPreviewResponse | null>(null)
const importing = ref(false)
const importError = ref('')
const baseline = ref(0)

const canConfirm = computed(() => !!preview.value && preview.value.rejected === 0 && preview.value.row_errors.length === 0)

function openImport() {
  showImport.value = true
  file.value = null
  preview.value = null
  importError.value = ''
  baseline.value = bootstrap.taxonomyVersion
}
function onFile(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0]
  file.value = f ?? null
  preview.value = null
}
async function doPreview() {
  if (!file.value) return
  importing.value = true
  importError.value = ''
  try {
    preview.value = await previewClassImport(file.value, baseline.value)
  } catch (e) {
    importError.value = errorMessage(e)
  } finally {
    importing.value = false
  }
}
async function doConfirm() {
  if (!preview.value || !file.value) return
  importing.value = true
  importError.value = ''
  try {
    await confirmClassImport({ file_sha256: preview.value.file_sha256, baseline_taxonomy_version: preview.value.baseline_taxonomy_version }, uuidv7())
    showImport.value = false
    await Promise.all([load(), bootstrap.load(true)])
  } catch (e) {
    importError.value = errorMessage(e)
  } finally {
    importing.value = false
  }
}

async function load() {
  loading.value = true
  try {
    const [cu, cl] = await Promise.all([listCultivars(), listClasses()])
    cultivars.value = cu.items
    classes.value = cl.items
  } catch (e) {
    toast(errorMessage(e), 'error')
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  await bootstrap.load().catch(() => {})
  await load()
})
</script>

<style scoped>
.tabs { display: flex; gap: 6px; align-items: center; margin-bottom: 14px; }
.tab { border: 1px solid var(--border); background: #fff; padding: 7px 14px; border-radius: 8px; }
.tab.active { background: var(--primary); border-color: var(--primary); color: #fff; }
.err-text { color: var(--danger); }
.import-result { margin-top: 8px; font-size: 13px; }
.errors { color: var(--danger); margin: 6px 0 0; padding-left: 18px; }
</style>
