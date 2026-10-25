<template>
  <div class="thumb-wrap" :style="{ aspectRatio: '3/4' }">
    <img v-if="state === 'ready'" :src="url" class="thumb-img" :alt="alt" />
    <div v-else class="thumb-ph" :class="state">
      {{ state === 'error' ? '加载失败' : '加载中…' }}
      <button v-if="state === 'error'" class="btn btn-sm" @click="retry">重试</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useMediaImage } from '../../composables/useMediaImage'

const props = defineProps<{ imageId: string; alt?: string }>()

const { url, state, load, retry } = useMediaImage(props.imageId, 'preview', 320)

onMounted(() => {
  if (!props.imageId) return
  void load()
})
</script>

<style scoped>
.thumb-wrap { width: 100%; overflow: hidden; border-radius: 6px; background: #f3f4f6; }
.thumb-img { width: 100%; height: 100%; object-fit: cover; display: block; }
.thumb-ph { width: 100%; height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px; color: #6b7280; font-size: 12px; }
</style>
