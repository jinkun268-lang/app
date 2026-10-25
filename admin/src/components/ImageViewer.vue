<template>
  <teleport to="body">
    <div v-if="modelValue" class="viewer-mask" @mousedown.self="close" @keydown="onKey">
      <div class="viewer-toolbar">
        <span class="viewer-count">{{ index + 1 }} / {{ images.length }}<template v-if="caption"> · {{ caption }}</template></span>
        <span class="spacer" />
        <button class="btn btn-sm" @click="zoomIn">放大</button>
        <button class="btn btn-sm" @click="zoomOut">缩小</button>
        <button class="btn btn-sm" :disabled="index <= 0" @click="prev">上一张</button>
        <button class="btn btn-sm" :disabled="index >= images.length - 1" @click="next">下一张</button>
        <button class="btn btn-sm" @click="close">关闭</button>
      </div>
      <div class="viewer-stage" tabindex="0" ref="stageEl">
        <div v-if="imgState === 'error'" class="viewer-msg">
          <p>{{ imgError }}</p>
          <button class="btn" @click="retry">重试</button>
        </div>
        <div v-else-if="imgState === 'loading' || imgState === 'pending'" class="viewer-msg muted">
          {{ imgState === 'pending' ? '预览生成中…' : '加载中…' }}
        </div>
        <img v-else :src="imgUrl" class="viewer-img" :style="{ transform: `scale(${scale})` }" alt="样本图片" />
      </div>
    </div>
  </teleport>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useMediaImage } from '../composables/useMediaImage'

export interface ViewerImage {
  image_id: string
  caption?: string
}

const props = defineProps<{ modelValue: boolean; images: ViewerImage[]; index: number }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void; (e: 'update:index', v: number): void }>()

const stageEl = ref<HTMLElement | null>(null)
const scale = ref(1)

const current = computed(() => props.images[props.index])
const media = useMediaImage(() => current.value?.image_id ?? '', 'original')
const imgUrl = computed(() => media.url.value)
const imgState = computed(() => media.state.value)
const imgError = computed(() => media.error.value)
const caption = computed(() => current.value?.caption)

watch(
  () => current.value?.image_id,
  (id) => {
    if (id) void media.load()
  },
  { immediate: true },
)

function close() {
  emit('update:modelValue', false)
  scale.value = 1
}
function prev() {
  if (props.index > 0) emit('update:index', props.index - 1)
}
function next() {
  if (props.index < props.images.length - 1) emit('update:index', props.index + 1)
}
function zoomIn() {
  scale.value = Math.min(3, scale.value + 0.5)
}
function zoomOut() {
  scale.value = Math.max(1, scale.value - 0.5)
}
function retry() {
  media.retry()
}
function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') close()
  else if (e.key === 'ArrowLeft') prev()
  else if (e.key === 'ArrowRight') next()
}
</script>

<style scoped>
.viewer-mask { position: fixed; inset: 0; background: rgba(0,0,0,0.85); z-index: 1200; display: flex; flex-direction: column; }
.viewer-toolbar { display: flex; align-items: center; gap: 8px; padding: 10px 16px; color: #fff; }
.viewer-count { font-size: 13px; }
.viewer-stage { flex: 1; display: flex; align-items: center; justify-content: center; overflow: auto; outline: none; }
.viewer-img { max-width: 96%; max-height: 96%; transition: transform 0.12s ease; background: #111; }
.viewer-msg { color: #fff; text-align: center; padding: 24px; }
</style>
