<template>
  <div class="toasts">
    <div v-for="t in items" :key="t.id" class="toast" :class="t.type">
      {{ t.message }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { useToasts } from '../ui/toast'

const { items } = useToasts()
</script>

<style scoped>
.toasts { position: fixed; top: 16px; right: 16px; z-index: 1000; display: flex; flex-direction: column; gap: 8px; }
.toast {
  padding: 10px 14px; border-radius: 8px; background: #111827; color: #fff;
  font-size: 13px; box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  border-left: 3px solid #6b7280;
}
.toast.success { border-left-color: #22c55e; }
.toast.error { border-left-color: #ef4444; }
</style>
