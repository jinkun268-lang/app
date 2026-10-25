<template>
  <teleport to="body">
    <div v-if="modelValue" class="modal-mask" @mousedown.self="onBackdrop">
      <div
        class="modal-card"
        role="dialog"
        aria-modal="true"
        :aria-labelledby="titleId"
        tabindex="-1"
        ref="cardEl"
        @keydown="onKeydown"
      >
        <div class="modal-head">
          <span class="modal-title" :id="titleId">{{ title }}</span>
          <button class="modal-close" aria-label="关闭" :disabled="busy" @click="close">×</button>
        </div>
        <div class="modal-body">
          <slot />
        </div>
        <div class="modal-foot">
          <slot name="footer" />
        </div>
      </div>
    </div>
  </teleport>
</template>

<script setup lang="ts">
import { nextTick, onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps<{ modelValue: boolean; title: string; busy?: boolean }>()
const emit = defineEmits<{ (e: 'update:modelValue', v: boolean): void }>()

const cardEl = ref<HTMLElement | null>(null)
const titleId = `modal-title-${Math.random().toString(36).slice(2, 9)}`
let lastFocused: HTMLElement | null = null

function close() {
  if (props.busy) return
  emit('update:modelValue', false)
}

function onBackdrop() {
  close()
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    e.stopPropagation()
    close()
    return
  }
  if (e.key === 'Tab') {
    trapFocus(e)
  }
}

function trapFocus(e: KeyboardEvent) {
  const el = cardEl.value
  if (!el) return
  const focusables = Array.from(
    el.querySelectorAll<HTMLElement>('button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'),
  )
  if (focusables.length === 0) return
  const first = focusables[0]
  const last = focusables[focusables.length - 1]
  if (e.shiftKey && document.activeElement === first) {
    e.preventDefault()
    last.focus()
  } else if (!e.shiftKey && document.activeElement === last) {
    e.preventDefault()
    first.focus()
  }
}

function onDocumentKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && props.modelValue) close()
}

watch(
  () => props.modelValue,
  async (open) => {
    if (open) {
      lastFocused = document.activeElement as HTMLElement | null
      await nextTick()
      const el = cardEl.value
      const focusables = el?.querySelectorAll<HTMLElement>('button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])')
      ;(focusables?.[0] ?? el)?.focus()
    } else if (lastFocused) {
      lastFocused.focus()
      lastFocused = null
    }
  },
)

watch(
  () => props.modelValue,
  (open) => {
    if (open) document.addEventListener('keydown', onDocumentKeydown)
    else document.removeEventListener('keydown', onDocumentKeydown)
  },
)

onBeforeUnmount(() => document.removeEventListener('keydown', onDocumentKeydown))
</script>

<style scoped>
.modal-mask {
  position: fixed; inset: 0; background: rgba(17, 24, 39, 0.45);
  display: flex; align-items: center; justify-content: center; z-index: 900;
}
.modal-card {
  width: 440px; max-width: 92vw; max-height: 90vh; background: #fff; border-radius: 12px;
  box-shadow: 0 10px 30px rgba(0,0,0,0.2); display: flex; flex-direction: column; outline: none;
}
.modal-head { display: flex; align-items: center; justify-content: space-between; padding: 14px 16px; border-bottom: 1px solid var(--border); }
.modal-title { font-weight: 600; }
.modal-close { background: transparent; border: none; font-size: 20px; color: #6b7280; line-height: 1; cursor: pointer; }
.modal-close:disabled { opacity: 0.4; cursor: not-allowed; }
.modal-body { padding: 16px; overflow: auto; }
.modal-foot { display: flex; justify-content: flex-end; gap: 8px; padding: 12px 16px; border-top: 1px solid var(--border); }
</style>
