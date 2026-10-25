<template>
  <div v-if="totalPages > 1" class="pagination" role="navigation" aria-label="分页">
    <button class="btn btn-sm" :disabled="page <= 1" aria-label="上一页" @click="$emit('change', page - 1)">上一页</button>
    <span class="muted" aria-live="polite">第 {{ page }} / {{ totalPages }} 页 · 共 {{ total }} 条</span>
    <button class="btn btn-sm" :disabled="page >= totalPages" aria-label="下一页" @click="$emit('change', page + 1)">下一页</button>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ page: number; pageSize: number; total: number }>()
defineEmits<{ (e: 'change', page: number): void }>()

const totalPages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)))
</script>

<style scoped>
.pagination { display: flex; align-items: center; gap: 12px; padding: 12px 16px; justify-content: flex-end; }
</style>
