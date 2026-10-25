// 轮询：2 秒起逐步退避到 30 秒；终态停止；卸载清理。不依赖固定两次 setTimeout 推定完成。
import { onUnmounted, ref } from 'vue'

export interface PollOptions<T> {
  initialDelayMs?: number
  maxDelayMs?: number
  backoff?: number
  immediate?: boolean
  stop: (result: T) => boolean
}

export function usePolling<T>(fn: () => Promise<T>, opts: PollOptions<T>) {
  const running = ref(false)
  const delay = ref(opts.initialDelayMs ?? 2000)
  let timer: ReturnType<typeof setTimeout> | null = null
  let disposed = false

  async function tick() {
    if (disposed) return
    running.value = true
    try {
      const result = await fn()
      if (opts.stop(result)) {
        running.value = false
        delay.value = opts.initialDelayMs ?? 2000
        return
      }
      delay.value = Math.min((opts.maxDelayMs ?? 30000), Math.round(delay.value * (opts.backoff ?? 2)))
      timer = setTimeout(tick, delay.value)
    } catch {
      delay.value = Math.min((opts.maxDelayMs ?? 30000), Math.round(delay.value * (opts.backoff ?? 2)))
      timer = setTimeout(tick, delay.value)
    } finally {
      running.value = false
    }
  }

  function start() {
    if (timer) clearTimeout(timer)
    delay.value = opts.initialDelayMs ?? 2000
    if (opts.immediate) void tick()
    else timer = setTimeout(tick, delay.value)
  }

  function stop() {
    if (timer) clearTimeout(timer)
    timer = null
    disposed = true
  }

  onUnmounted(stop)

  return { start, stop, running }
}
