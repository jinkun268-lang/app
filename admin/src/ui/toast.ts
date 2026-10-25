import { reactive } from 'vue'

export type ToastType = 'info' | 'success' | 'error'

export interface Toast {
  id: number
  message: string
  type: ToastType
}

const state = reactive<{ items: Toast[] }>({ items: [] })
let seq = 0

export function toast(message: string, type: ToastType = 'info', duration = 2600) {
  const id = ++seq
  state.items.push({ id, message, type })
  setTimeout(() => {
    const i = state.items.findIndex((t) => t.id === id)
    if (i >= 0) state.items.splice(i, 1)
  }, duration)
}

export function useToasts() {
  return state
}
