<template>
  <div class="page">
    <div class="page-head head-row">
      <div>
        <h1 class="page-title">账号管理</h1>
      </div>
      <span class="spacer" />
      <button class="btn btn-primary" :disabled="submitting" @click="openCreate">
        <Plus :size="15" />
        新建账号
      </button>
    </div>

    <div class="card">
      <div v-if="loading" class="empty muted">加载中…</div>
      <div v-else-if="loadError" class="empty">
        <p class="err-text">{{ loadError }}</p>
        <button class="btn" @click="load()">重试</button>
      </div>
      <div v-else-if="rows.length === 0" class="empty muted">暂无账号</div>
      <div v-else class="table-wrap">
      <table class="table">
        <thead>
          <tr>
            <th>登录名</th>
            <th>显示名</th>
            <th>角色</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in rows" :key="u.user_id">
            <td class="muted">{{ u.username }}</td>
            <td>
              {{ u.display_name }}
              <span v-if="isSelf(u)" class="tag tag-gray">当前账号</span>
            </td>
            <td>
              <select
                class="select"
                :value="u.role"
                :disabled="isSelf(u) || !!roleBusy[u.user_id]"
                @change="changeRole(u, $event)"
              >
                <option v-for="r in roles" :key="r.value" :value="r.value">{{ r.label }}</option>
              </select>
            </td>
            <td><span class="tag" :class="u.is_active ? 'tag-green' : 'tag-red'">{{ u.is_active ? '启用' : '停用' }}</span></td>
            <td>
              <div class="flex">
                <button class="btn btn-sm" @click="openEdit(u)">编辑</button>
                <button class="btn btn-sm" :disabled="!!resetBusy[u.user_id]" @click="reset(u)">
                  {{ resetBusy[u.user_id] ? '重置中…' : '重置密码' }}
                </button>
                <button
                  class="btn btn-sm"
                  :disabled="isSelf(u) || !!toggleBusy[u.user_id]"
                  @click="toggle(u)"
                >
                  {{ toggleBusy[u.user_id] ? '处理中…' : (u.is_active ? '停用' : '启用') }}
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      </div>
      <Pagination v-if="!loading && !loadError" :page="page" :page-size="pageSize" :total="total" @change="setPage" />
    </div>

    <Modal v-model="showForm" :title="editing ? '编辑账号' : '新建账号'" :busy="submitting">
      <div class="field">
        <label class="form-label" for="user-username">登录名</label>
        <input id="user-username" v-model="form.username" class="input" :disabled="!!editing" placeholder="如 collector01" />
      </div>
      <div class="field">
        <label class="form-label" for="user-display-name">显示名</label>
        <input id="user-display-name" v-model="form.display_name" class="input" placeholder="请输入显示名" />
      </div>
      <div class="field">
        <label class="form-label" for="user-role">角色</label>
        <select id="user-role" v-model="form.role" class="select" :disabled="!!editing && isSelf(editing)">
          <option v-for="r in roles" :key="r.value" :value="r.value">{{ r.label }}</option>
        </select>
      </div>
      <p v-if="formError" class="err-text">{{ formError }}</p>
      <template #footer>
        <button class="btn" :disabled="submitting" @click="showForm = false">取消</button>
        <button class="btn btn-primary" :disabled="submitting" @click="submit">{{ submitting ? '提交中…' : '确定' }}</button>
      </template>
    </Modal>

    <Modal :model-value="showPassword" title="临时密码（仅显示一次）" @update:model-value="(v) => { if (!v) closePassword() }">
      <div class="pwd-box">
        <code>{{ tempPassword }}</code>
        <button class="btn btn-sm" @click="copyPwd">复制</button>
      </div>
      <template #footer>
        <button class="btn btn-primary" @click="closePassword">{{ selfReset ? '我已复制，重新登录' : '我已复制' }}</button>
      </template>
    </Modal>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Plus } from 'lucide-vue-next'
import Modal from '../components/Modal.vue'
import Pagination from '../components/Pagination.vue'
import { createUser, listUsers, resetPassword, updateUser } from '../api/users'
import { useAuthStore } from '../stores/auth'
import { errorMessage } from '../util/error'
import { toast } from '../ui/toast'
import type { Role, UserRow } from '../types'

const auth = useAuthStore()
const router = useRouter()

const PAGE_SIZE = 20
const roles: { value: Role; label: string }[] = [
  { value: 'collector', label: '采集员' },
  { value: 'admin', label: '管理员' },
  { value: 'super_admin', label: '超级管理员' },
  { value: 'expert', label: '专家' },
]

const rows = ref<UserRow[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = PAGE_SIZE
const loading = ref(false)
const loadError = ref('')

const showForm = ref(false)
const editing = ref<UserRow | null>(null)
const submitting = ref(false)
const formError = ref('')
const form = reactive({ username: '', display_name: '', role: 'collector' as Role })

// 按行记录的 busy 标记，避免重复提交；不用共享对象引用判断。
const roleBusy = reactive<Record<string, boolean>>({})
const toggleBusy = reactive<Record<string, boolean>>({})
const resetBusy = reactive<Record<string, boolean>>({})

const showPassword = ref(false)
const tempPassword = ref('')
const selfReset = ref(false)

function isSelf(u: { user_id: string } | null): boolean {
  return !!u && !!auth.account && u.user_id === auth.account.user_id
}

function syncSelfAccount(u: UserRow): void {
  auth.setAccount({
    user_id: u.user_id,
    username: u.username,
    display_name: u.display_name,
    role: u.role,
  })
}

async function load(target: number = page.value) {
  loading.value = true
  loadError.value = ''
  try {
    const res = await listUsers({ page: target, page_size: pageSize })
    rows.value = res.items
    total.value = res.total
    page.value = res.page
  } catch (e) {
    loadError.value = errorMessage(e)
  } finally {
    loading.value = false
  }
}

function setPage(p: number) {
  if (p === page.value) return
  void load(p)
}

function openCreate() {
  editing.value = null
  form.username = ''
  form.display_name = ''
  form.role = 'collector'
  formError.value = ''
  showForm.value = true
}

function openEdit(u: UserRow) {
  editing.value = u
  form.username = u.username
  form.display_name = u.display_name
  form.role = u.role
  formError.value = ''
  showForm.value = true
}

async function submit() {
  const username = form.username.trim()
  const displayName = form.display_name.trim()
  if (!editing.value && !/^[a-z][a-z0-9_.-]{2,31}$/.test(username)) {
    formError.value = '登录名不合法（小写字母开头，3–32 字符）'
    return
  }
  if (!displayName) {
    formError.value = '显示名必填'
    return
  }
  if (displayName.length > 64) {
    formError.value = '显示名最长 64 个字符'
    return
  }
  submitting.value = true
  formError.value = ''
  try {
    if (editing.value) {
      const target = editing.value
      const updated = await updateUser(target.user_id, { display_name: displayName, role: form.role })
      if (isSelf(target)) syncSelfAccount(updated)
      showForm.value = false
      await load()
    } else {
      const res = await createUser({ username, display_name: displayName, role: form.role })
      showForm.value = false
      selfReset.value = false
      tempPassword.value = res.temporary_password
      showPassword.value = true
      await load(1)
    }
  } catch (e) {
    formError.value = errorMessage(e)
  } finally {
    submitting.value = false
  }
}

async function changeRole(u: UserRow, event: Event) {
  const el = event.target as HTMLSelectElement
  const next = el.value as Role
  if (next === u.role) return
  roleBusy[u.user_id] = true
  try {
    const updated = await updateUser(u.user_id, { role: next })
    if (isSelf(updated)) syncSelfAccount(updated)
    await load()
  } catch (e) {
    el.value = u.role // 失败还原为服务端原值，不依赖本地共享引用
    toast(errorMessage(e), 'error')
  } finally {
    roleBusy[u.user_id] = false
  }
}

async function toggle(u: UserRow) {
  const next = !u.is_active
  if (!next && !window.confirm(`停用账号 ${u.username}？`)) return
  toggleBusy[u.user_id] = true
  try {
    await updateUser(u.user_id, { is_active: next })
    await load()
  } catch (e) {
    toast(errorMessage(e), 'error')
  } finally {
    toggleBusy[u.user_id] = false
  }
}

async function reset(u: UserRow) {
  if (!window.confirm(`重置 ${u.username} 的密码？`)) return
  resetBusy[u.user_id] = true
  try {
    const res = await resetPassword(u.user_id)
    selfReset.value = isSelf(u)
    tempPassword.value = res.temporary_password
    showPassword.value = true
  } catch (e) {
    toast(errorMessage(e), 'error')
  } finally {
    resetBusy[u.user_id] = false
  }
}

function closePassword() {
  showPassword.value = false
  tempPassword.value = ''
  if (selfReset.value) {
    selfReset.value = false
    auth.clearSession()
    void router.push('/login')
  }
}

async function copyPwd() {
  try {
    await navigator.clipboard.writeText(tempPassword.value)
  } catch {
    toast('复制失败，请手动复制', 'error')
  }
}

onMounted(async () => {
  await load()
})
</script>

<style scoped>
.head-row { display: flex; align-items: flex-start; gap: 12px; flex-wrap: wrap; }
.err-text { color: var(--danger); }
.small { font-size: 12px; }
.warn { color: var(--warn); }
.pwd-box { display: flex; align-items: center; gap: 8px; }
.pwd-box code { background: #f3f4f6; padding: 6px 10px; border-radius: 6px; font-size: 14px; }
</style>
