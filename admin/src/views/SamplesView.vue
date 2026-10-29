<template>
  <div class="samples" :class="{ narrow: isNarrow }">
    <aside v-show="!isNarrow || !selectedId" class="list-pane card">
      <div class="pane-head">
        <Images :size="16" class="pane-icon" />
        <span>{{ workspaceTitle }}</span>
        <span class="pane-count muted">共 {{ total }} 条</span>
      </div>
      <div v-if="bootstrap.error && !selectedId" class="config-error">
        <span class="config-error-text">基础配置加载失败</span>
        <button class="btn btn-sm" :disabled="bootstrap.loading" @click="retryConfig">{{ bootstrap.loading ? '重试中…' : '重试' }}</button>
      </div>
      <div v-if="filters.batch_id" class="toolbar"><span>当前按采集批次筛选</span><button class="btn btn-sm" @click="setFilter('batch_id', undefined)">取消批次筛选</button></div>
      <div class="toolbar filters">
        <select
          :value="filters.review_status"
          class="select"
          aria-label="审核状态筛选"
          @change="(e) => setFilter('review_status', (e.target as HTMLSelectElement).value || undefined)"
        >
          <option v-if="workspace !== 'quality'" value="">全部审核状态</option>
          <option v-else value="confirmed,corrected">已通过核验</option>
          <option value="unreviewed">未审核</option>
          <option value="confirmed">已确认</option>
          <option value="corrected">已修正</option>
          <option value="unresolved">无法判断</option>
        </select>
        <select
          :value="filters.final_class_id"
          class="select"
          aria-label="最终类别筛选"
          @change="(e) => setFilter('final_class_id', (e.target as HTMLSelectElement).value || undefined)"
        >
          <option value="">全部最终类别</option>
          <option v-for="c in bootstrap.activeClasses" :key="c.class_id" :value="c.class_id">{{ c.name }}</option>
        </select>
        <input
          :value="filters.q"
          class="input"
          placeholder="样本号 / 树号"
          aria-label="按样本号或树号搜索"
          @input="(e) => setFilter('q', (e.target as HTMLInputElement).value || undefined)"
        />
        <button class="btn btn-sm" @click="clearFilters">清空</button>
      </div>

      <div v-if="loading" class="empty muted">加载中…</div>
      <div v-else-if="error" class="empty">
        <p class="err-text">{{ error }}</p>
        <button class="btn" @click="load">重试</button>
      </div>
      <div v-else-if="items.length === 0" class="empty muted">暂无样本</div>
      <ul v-else class="list">
        <li v-for="s in items" :key="s.sample_id" class="list-row">
          <button
            class="item"
            :class="{ active: selectedId === s.sample_id }"
            :aria-current="selectedId === s.sample_id ? 'true' : undefined"
            @click="open(s.sample_id)"
          >
            <div class="item-top">
              <span class="muted">{{ s.tree_id || s.sample_id.slice(0, 8) }}</span>
              <span class="tag" :class="statusClass(s.review_status)">{{ statusText(s.review_status) }}</span>
            </div>
            <div class="item-title">{{ s.original_class_name }}{{ s.final_class_name && s.final_class_name !== s.original_class_name ? ' → ' + s.final_class_name : '' }}</div>
            <div class="muted item-meta">{{ s.original_cultivar_name }} · {{ s.image_count }} 图</div>
            <div v-if="s.batch_snapshot" class="muted item-meta">{{ s.batch_snapshot.name }} · {{ s.batch_snapshot.place }}</div>
          </button>
        </li>
      </ul>
      <div class="pane-foot">
        <Pagination :page="page" :page-size="pageSize" :total="total" @change="setPage" />
      </div>
    </aside>

    <section v-if="selectedId" class="detail-pane">
      <div v-if="isNarrow" class="narrow-back">
        <button class="btn btn-sm" @click="goBack">← 返回列表</button>
      </div>
      <SampleDetail :key="workspace + ':' + selectedId" ref="detailRef" :sample-id="selectedId" :workspace="workspace" @saved="load" />
    </section>
    <section v-else class="detail-pane card">
      <div class="empty">请在左侧选择样本</div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Images } from 'lucide-vue-next'
import { useSampleList } from '../features/samples/useSampleList'
import SampleDetail from '../features/samples/SampleDetail.vue'
import Pagination from '../components/Pagination.vue'
import { useBootstrapStore } from '../stores/bootstrap'
import type { SampleWorkspace } from '../auth/capabilities'

const route = useRoute()
const router = useRouter()
const bootstrap = useBootstrapStore()
const workspace = computed(() => (route.meta.workspace as SampleWorkspace | undefined) ?? 'collection')
const workspaceTitle = computed(() => ({ collection: '采集记录', review: '样本核验', quality: '质量检查' })[workspace.value])
const workspacePath = computed(() => ({ collection: '/samples', review: '/reviews', quality: '/training/quality' })[workspace.value])
const { items, total, loading, error, filters, page, pageSize, setFilter, setPage, clearFilters, load } = useSampleList()

const selectedId = computed(() => (typeof route.params.id === 'string' ? route.params.id : ''))
const detailRef = ref<InstanceType<typeof SampleDetail> | null>(null)

const isNarrow = ref(false)
const mq = window.matchMedia('(max-width: 900px)')
function onMq(e: MediaQueryListEvent | MediaQueryList) {
  isNarrow.value = e.matches
}
onMounted(() => {
  onMq(mq)
  mq.addEventListener('change', onMq)
  // 配置加载失败写入 bootstrap.error 并在页面上提示，不静默吞掉。
  void bootstrap.load()
  void load()
})
onBeforeUnmount(() => mq.removeEventListener('change', onMq))

function retryConfig() {
  void bootstrap.load(true)
}

function statusText(s: string) {
  return ({ unreviewed: '未审核', confirmed: '已确认', corrected: '已修正', unresolved: '无法判断' } as Record<string, string>)[s] || s
}
function statusClass(s: string) {
  return ({ unreviewed: 'tag-amber', confirmed: 'tag-green', corrected: 'tag-blue', unresolved: 'tag-gray' } as Record<string, string>)[s] || 'tag-gray'
}

function open(id: string) {
  if (id === selectedId.value) return
  if (detailRef.value?.isDirty()) {
    if (!window.confirm('当前有未保存的更改，切换样本将丢弃这些更改，确定继续？')) return
  }
  router.push({ path: `${workspacePath.value}/${id}`, query: route.query })
}
function goBack() {
  if (detailRef.value?.isDirty()) {
    if (!window.confirm('当前有未保存的更改，返回将丢弃这些更改，确定继续？')) return
  }
  router.push({ path: workspacePath.value, query: route.query })
}
</script>

<style scoped>
.samples { display: flex; gap: 12px; height: 100%; padding: 12px; }
.list-pane { width: 32%; min-width: 300px; display: flex; flex-direction: column; overflow: hidden; min-height: 0; }
.detail-pane { flex: 1; display: flex; flex-direction: column; overflow: hidden; min-width: 0; min-height: 0; }
.pane-head {
  padding: 13px 16px;
  font-weight: 600;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.pane-icon { color: var(--primary); flex-shrink: 0; }
.pane-count { margin-left: auto; font-size: 12px; font-weight: 400; }
.filters { padding: 12px; margin: 0; display: flex; flex-wrap: wrap; }
.config-error { display: flex; align-items: center; gap: 8px; padding: 8px 12px; margin: 8px 12px 0; border: 1px solid #fdba74; background: #fff7ed; color: #9a3412; border-radius: 8px; font-size: 12px; }
.config-error-text { flex: 1; }
.filters .input, .filters .select { flex: 1; min-width: 120px; }
.list { list-style: none; margin: 0; padding: 0; overflow: auto; flex: 1; }
.list-row { margin: 0; }
.item {
  display: block;
  width: 100%;
  text-align: left;
  background: transparent;
  border: none;
  border-bottom: 1px solid var(--border);
  padding: 12px 16px;
  cursor: pointer;
}
.item:hover { background: #f6f9f7; }
.item.active { background: var(--primary-weak); box-shadow: inset 3px 0 0 var(--primary); }
.item-top { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 4px; }
.item-title { font-weight: 500; margin-bottom: 2px; }
.item-meta { font-size: 12px; }
.pane-foot { border-top: 1px solid var(--border); flex-shrink: 0; }
.narrow-back { padding: 0 0 8px; flex-shrink: 0; }
.err-text { color: var(--danger); }
.samples.narrow { flex-direction: column; }
.samples.narrow .list-pane { width: 100%; min-width: 0; flex: 1; }
.samples.narrow .detail-pane { width: 100%; flex: 1; }
</style>
