<template>
  <div class="page">
    <div class="toolbar"><h2>采集批次</h2><button class="btn" :disabled="loading" @click="load">刷新</button></div>
    <p class="muted">查看采集地点、采集人和批次状态，点击批次查看对应图片记录。</p>
    <p v-if="error" role="alert" class="err-text">{{ error }}</p>
    <p v-if="loading">加载中…</p>
    <div v-else class="card table-wrap">
      <table><thead><tr><th>批次名称</th><th>地点</th><th>采集人</th><th>状态</th><th>创建时间</th><th>记录</th></tr></thead>
        <tbody><tr v-for="batch in items" :key="batch.batch_id">
          <td>{{ batch.name }}<div class="muted">{{ batch.note }}</div></td><td>{{ batch.place || '未填写' }}</td><td>{{ batch.collector || '未填写' }}</td>
          <td><span class="tag" :class="batch.closed ? 'tag-gray' : 'tag-green'">{{ batch.closed ? '已关闭' : '采集中' }}</span></td>
          <td>{{ batch.created_at }}</td><td><router-link :to="{ path: '/samples', query: { batch_id: batch.batch_id } }">查看图片</router-link></td>
        </tr><tr v-if="!items.length"><td colspan="6" class="muted">暂无已同步的采集批次</td></tr></tbody>
      </table>
    </div>
    <Pagination :page="page" :page-size="20" :total="total" @change="changePage" />
  </div>
</template>
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { listBatches } from '../api/collection'
import type { Batch } from '../types'
import { errorMessage } from '../util/error'
import Pagination from '../components/Pagination.vue'
const items = ref<Batch[]>([])
const page = ref(1), total = ref(0), loading = ref(false), error = ref('')
let requestId = 0
async function load() {
  const current = ++requestId
  loading.value = true; error.value = ''
  try { const result = await listBatches(page.value); if (current === requestId) { items.value = result.items; total.value = result.total } }
  catch (e) { if (current === requestId) error.value = errorMessage(e) }
  finally { if (current === requestId) loading.value = false }
}
function changePage(value: number) { page.value = value; void load() }
onMounted(load)
</script>
<style scoped>
.page { padding: 20px; }.toolbar { display: flex; align-items: center; justify-content: space-between; }.table-wrap { overflow-x: auto; }table { width: 100%; border-collapse: collapse; }th, td { padding: 12px; text-align: left; border-bottom: 1px solid var(--border); }h2 { margin: 0; font-size: 18px; }
</style>
