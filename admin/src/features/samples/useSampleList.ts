// 样本列表状态：筛选/分页进入 URL，刷新与返回保持；换页/换筛选走接口，不在浏览器本地过滤模拟分页。
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { listSamples } from '../../api/samples'
import type { SampleSummary } from '../../types'
import { errorMessage } from '../../util/error'

const PAGE_SIZE = 20

function asStr(v: unknown): string {
  return typeof v === 'string' ? v : ''
}

export function useSampleList() {
  const route = useRoute()
  const router = useRouter()

  const items = ref<SampleSummary[]>([])
  const total = ref(0)
  const loading = ref(false)
  const error = ref('')
  let seq = 0

  const filters = computed(() => {
    const excludedRaw = asStr(route.query.excluded)
    return {
      batch_id: asStr(route.query.batch_id) || undefined,
      review_status: asStr(route.query.review_status) || (route.meta.workspace === 'quality' ? 'confirmed,corrected' : undefined),
      final_cultivar_id: asStr(route.query.final_cultivar_id) || undefined,
      final_class_id: asStr(route.query.final_class_id) || undefined,
      q: asStr(route.query.q) || undefined,
      uploaded_from: asStr(route.query.uploaded_from) || undefined,
      uploaded_to: asStr(route.query.uploaded_to) || undefined,
      excluded: excludedRaw === 'true' ? true : excludedRaw === 'false' ? false : undefined,
    }
  })

  const page = computed(() => Math.max(1, parseInt(asStr(route.query.page) || '1', 10) || 1))
  const totalPages = computed(() => Math.max(1, Math.ceil(total.value / PAGE_SIZE)))

  function patchQuery(patch: Record<string, string | undefined>, resetPage = true) {
    const next: Record<string, string> = {}
    for (const [k, v] of Object.entries(route.query)) {
      if (typeof v === 'string') next[k] = v
    }
    for (const [k, v] of Object.entries(patch)) {
      if (v === undefined || v === '') delete next[k]
      else next[k] = v
    }
    if (resetPage) delete next.page
    router.replace({ query: next })
  }

  function setFilter(key: string, value: string | undefined) {
    patchQuery({ [key]: value })
  }

  function setPage(p: number) {
    patchQuery({ page: String(p) }, false)
  }

  function clearFilters() {
    router.replace({ query: {} })
  }

  async function load() {
    const mySeq = ++seq
    loading.value = true
    error.value = ''
    try {
      const res = await listSamples({
        batch_id: filters.value.batch_id,
        review_status: filters.value.review_status,
        excluded: filters.value.excluded,
        final_cultivar_id: filters.value.final_cultivar_id,
        final_class_id: filters.value.final_class_id,
        uploaded_from: filters.value.uploaded_from,
        uploaded_to: filters.value.uploaded_to,
        q: filters.value.q,
        page: page.value,
        page_size: PAGE_SIZE,
      })
      if (mySeq !== seq) return
      items.value = res.items
      total.value = res.total
    } catch (e) {
      if (mySeq !== seq) return
      error.value = errorMessage(e)
    } finally {
      if (mySeq === seq) loading.value = false
    }
  }

  watch(filters, () => void load())
  watch(page, () => void load())

  return {
    items,
    total,
    loading,
    error,
    filters,
    page,
    pageSize: PAGE_SIZE,
    totalPages,
    setFilter,
    setPage,
    clearFilters,
    load,
  }
}
