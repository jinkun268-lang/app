<template>
  <div class="shell">
    <div v-if="isMobile && drawerOpen" class="mask" aria-hidden="true" @click="closeDrawer" />

    <aside
      id="app-sidebar"
      class="sidebar"
      :class="{ collapsed: !isMobile && collapsed, open: isMobile && drawerOpen }"
      :inert="sidebarInert ? true : undefined"
      aria-label="主导航"
    >
      <div class="sidebar-inner">
        <div class="brand-row">
          <span class="brand-icon"><Sprout :size="18" /></span>
          <div class="brand-text">
            <div class="brand">柑橘病虫害管理端</div>
          </div>
        </div>

        <nav class="nav">
          <template v-for="g in groups" :key="g.key">
            <button class="group-title" :aria-expanded="open.has(g.key)" @click="toggle(g.key)">
              <span class="g-label">{{ g.label }}</span>
              <ChevronDown class="chevron" :class="{ open: open.has(g.key) }" :size="16" />
            </button>
            <div v-show="open.has(g.key)" class="group-items">
              <router-link
                v-for="item in g.items"
                :key="item.to"
                class="nav-item"
                :class="{ 'is-active': route.path === item.to || route.path.startsWith(item.to + '/') }"
                :aria-current="route.path === item.to || route.path.startsWith(item.to + '/') ? 'page' : undefined"
                :to="item.to"
              >
                <component :is="item.icon" :size="16" class="nav-icon" />
                <span>{{ item.label }}</span>
              </router-link>
            </div>
          </template>
        </nav>

        <div class="footer">
          <div class="user">
            <span class="username">{{ auth.account?.display_name || auth.account?.username }}</span>
            <span v-if="roleLabel" class="role-tag">{{ roleLabel }}</span>
          </div>
          <button class="logout-btn" @click="logout">
            <LogOut :size="14" />
            退出登录
          </button>
        </div>
      </div>
    </aside>

    <div class="main">
      <header class="topbar">
        <button
          class="toggle-btn"
          :title="toggleTitle"
          :aria-label="toggleTitle"
          aria-controls="app-sidebar"
          :aria-expanded="isMobile ? drawerOpen : !collapsed"
          @click="onToggle"
        >
          <PanelLeftOpen v-if="isMobile ? !drawerOpen : collapsed" :size="18" />
          <PanelLeftClose v-else :size="18" />
        </button>
        <div class="title">{{ route.meta.title || '' }}</div>
      </header>
      <section class="content">
        <div v-if="unopened" class="unopened">
          <p class="unopened-title">页面不可用</p>
          <button class="btn" @click="router.push('/')">返回首页</button>
        </div>
        <!-- 未开放页面不挂载：不发不存在接口的请求。 -->
        <router-view v-else />
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch, type Component } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  BookOpen,
  ChevronDown,
  ClipboardList,
  Images,
  LogOut,
  PackageOpen,
  PanelLeftClose,
  PanelLeftOpen,
  ScrollText,
  Sprout,
  Users,
} from 'lucide-vue-next'
import { useAuthStore } from '../stores/auth'
import { useBootstrapStore } from '../stores/bootstrap'
import { isMockEnabled } from '../mocks'
import { sampleCapabilities } from '../auth/capabilities'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()
const bootstrap = useBootstrapStore()

// 真实 HTTP 模式已接入：样本、批次、咨询、导出、账号管理。旧工单、基础字典、审计未接入，
// 菜单隐藏且不挂载页面；模拟模式保留这些页面，便于开发态联调。
const realMode = !isMockEnabled()
const UNOPENED = new Set(['tickets', 'dictionaries', 'audit'])
const unopened = computed(() => realMode && UNOPENED.has(String(route.name ?? '')))

const collapsed = ref(false)
const drawerOpen = ref(false)
const open = ref(new Set<string>(['collection']))

const isMobile = ref(false)
const mq = window.matchMedia('(max-width: 900px)')
function onMq(e: MediaQueryListEvent | MediaQueryList) {
  isMobile.value = e.matches
  if (!e.matches) drawerOpen.value = false
}

const sidebarInert = computed(() => (isMobile.value ? !drawerOpen.value : collapsed.value))

const toggleTitle = computed(() =>
  isMobile.value ? (drawerOpen.value ? '关闭菜单' : '打开菜单') : collapsed.value ? '展开菜单' : '收起菜单',
)

function onToggle() {
  if (isMobile.value) drawerOpen.value = !drawerOpen.value
  else collapsed.value = !collapsed.value
}
function closeDrawer() {
  drawerOpen.value = false
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && isMobile.value && drawerOpen.value) closeDrawer()
}

function toggle(key: string) {
  const next = new Set(open.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  open.value = next
}

async function logout() {
  await auth.logout()
  router.push('/login')
}

const roleLabel = computed(
  () =>
    ({ super_admin: '超级管理员', admin: '训练管理员', expert: '核验专家', collector: '采集员' } as Record<string, string>)[
      auth.role ?? ''
    ] || '',
)

interface NavItem {
  to: string
  label: string
  icon: Component
}

const groups = computed(() => {
  const g: { key: string; label: string; items: NavItem[] }[] = []
  const capabilities = sampleCapabilities(auth.role)
  if (capabilities.readCollection) {
    g.push({
      key: 'collection',
      label: '采集与核验',
      items: [
        { to: '/samples', label: auth.role === 'collector' ? '我的采集' : '采集记录', icon: Images },
        { to: '/batches', label: '采集批次', icon: ClipboardList },
        ...(capabilities.review ? [{ to: '/reviews', label: '样本核验', icon: ClipboardList }] : []),
      ],
    })
  }
  if (capabilities.prepareTraining) {
    g.push({ key: 'training', label: '训练数据', items: [
      { to: '/training/quality', label: '质量检查', icon: Images },
      { to: '/exports', label: '数据导出', icon: PackageOpen },
    ] })
  }
  if (auth.isExpert || auth.isSuper) {
    g.push({ key: 'questions', label: '专家咨询', items: [{ to: '/questions', label: '咨询答复', icon: ClipboardList }] })
  }
  if (!realMode && (auth.isExpert || auth.isSuper)) {
    g.push({ key: 'qa', label: '专家工单', items: [{ to: '/tickets', label: '工单队列', icon: ClipboardList }] })
  }
  if (auth.isSuper) {
    // 真实模式只开放账号管理；字典与审计仍为模拟态页面。
    const baseItems: NavItem[] = realMode
      ? [{ to: '/settings/users', label: '账号管理', icon: Users }]
      : [
          { to: '/settings/dictionaries', label: '基础字典', icon: BookOpen },
          { to: '/settings/users', label: '账号管理', icon: Users },
          { to: '/settings/audit', label: '审计', icon: ScrollText },
        ]
    g.push({ key: 'base', label: '系统管理', items: baseItems })
  }
  return g
})

// 当前路由所属分组保持展开，避免切换页面后导航项被收起看不见。
function ensureActiveGroupOpen() {
  const g = groups.value.find((g) => g.items.some((it) => route.path === it.to || route.path.startsWith(it.to + '/')))
  if (g && !open.value.has(g.key)) {
    const next = new Set(open.value)
    next.add(g.key)
    open.value = next
  }
}

watch(
  () => route.path,
  () => {
    ensureActiveGroupOpen()
    closeDrawer()
  },
)

onMounted(() => {
  onMq(mq)
  mq.addEventListener('change', onMq)
  document.addEventListener('keydown', onKeydown)
  ensureActiveGroupOpen()
  // 失败原因由 store 记录并在页面展示，不在这里静默吞掉。
  if (auth.isAuthed) void bootstrap.load()
})
onBeforeUnmount(() => {
  mq.removeEventListener('change', onMq)
  document.removeEventListener('keydown', onKeydown)
})
</script>

<style scoped>
.shell { display: flex; height: 100%; }

.mask { position: fixed; inset: 0; background: rgba(10, 20, 15, 0.45); z-index: 40; }

.sidebar {
  width: 240px;
  flex-shrink: 0;
  background: linear-gradient(180deg, #0e2a1e 0%, #0b2118 100%);
  overflow: hidden;
  transition: width 0.2s ease, transform 0.2s ease;
  z-index: 50;
}
.sidebar.collapsed { width: 0; }
.sidebar-inner {
  width: 240px;
  height: 100%;
  display: flex;
  flex-direction: column;
  color: #b9cdc2;
}

.brand-row {
  min-height: 56px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 14px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.brand-icon {
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(94, 197, 134, 0.16);
  color: #7fd6a4;
}
.brand-text { min-width: 0; }
.brand { font-size: 15px; font-weight: 600; color: #fff; white-space: nowrap; }

.nav { flex: 1; overflow-y: auto; overflow-x: hidden; padding: 8px; }
.group-title {
  display: flex; align-items: center; gap: 8px; width: 100%;
  background: transparent; border: none; color: #d7e5dc;
  font-size: 13px; font-weight: 600; padding: 8px 10px; border-radius: 8px; margin-top: 6px;
  cursor: pointer;
}
.group-title:hover { background: rgba(255, 255, 255, 0.06); }
.g-label { flex: 1; text-align: left; }
.chevron { color: #6e8a7c; flex-shrink: 0; transition: transform 0.15s ease; }
.chevron.open { transform: rotate(180deg); }

.group-items { overflow: hidden; }
.nav-item {
  display: flex; align-items: center; gap: 8px;
  padding: 8px 10px; font-size: 13px; color: #a7bdb1;
  border-radius: 8px; margin: 2px 0; cursor: pointer;
}
.nav-icon { flex-shrink: 0; opacity: 0.85; }
.nav-item:hover { background: rgba(255, 255, 255, 0.06); color: #fff; }
.nav-item.router-link-active, .nav-item.is-active { background: #166534; color: #fff; }
.nav-item.router-link-active .nav-icon, .nav-item.is-active .nav-icon { opacity: 1; }

.footer {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  padding: 12px 14px; border-top: 1px solid rgba(255, 255, 255, 0.08);
}
.user { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.username { font-size: 13px; color: #e5efe9; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.role-tag {
  align-self: flex-start;
  font-size: 11px; line-height: 1.4; padding: 1px 7px; border-radius: 999px;
  color: #8fd7ae; background: rgba(52, 211, 153, 0.12); border: 1px solid rgba(52, 211, 153, 0.28);
}
.logout-btn {
  display: inline-flex; align-items: center; gap: 4px;
  background: transparent; border: none; color: #9fb8ab;
  font-size: 13px; padding: 5px 7px; border-radius: 6px; white-space: nowrap;
}
.logout-btn:hover { background: rgba(255, 255, 255, 0.06); color: #fca5a5; }

.main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.topbar {
  height: 52px; flex-shrink: 0; background: #fff;
  border-bottom: 1px solid var(--border);
  display: flex; align-items: center; gap: 10px; padding: 0 16px;
}
.toggle-btn { background: transparent; border: none; color: #6b7280; display: flex; align-items: center; padding: 6px; border-radius: 6px; }
.toggle-btn:hover { background: #f3f6f4; color: #1d3529; }
.title { font-weight: 600; font-size: 15px; }
.content { flex: 1; overflow: auto; }
.unopened { padding: 48px 24px; text-align: center; }
.unopened-title { font-size: 16px; font-weight: 600; margin: 0 0 6px; }

@media (max-width: 900px) {
  .sidebar {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    height: 100%;
    transform: translateX(-102%);
  }
  .sidebar.open { transform: none; box-shadow: 0 8px 30px rgba(0, 0, 0, 0.35); }
}
</style>
