// 鉴权图片加载：fetch → Object URL，处理 202 预览生成中（限次退避，超限手动重试）、401/404/解码失败。
import { onUnmounted, ref, toValue, type MaybeRefOrGetter } from 'vue'
import { fetchSampleImage, objectUrlFromBlob } from '../api/media'
import { getMediaUrl, mediaCacheKey, setMediaUrl } from '../media/cache'
import { errorMessage } from '../util/error'

export type MediaState = 'loading' | 'ready' | 'pending' | 'error'

const MAX_RETRIES = 5

export function useMediaImage(imageId: MaybeRefOrGetter<string>, variant: 'preview' | 'original' = 'preview', w?: 320 | 1024) {
  const url = ref('')
  const state = ref<MediaState>('loading')
  const error = ref('')
  let timer: ReturnType<typeof setTimeout> | null = null
  let retries = 0
  let disposed = false
  let loadSeq = 0
  let lastKey = ''

  async function load() {
    if (disposed) return
    const sequence = ++loadSeq
    if (timer) {
      clearTimeout(timer)
      timer = null
    }
    const id = toValue(imageId)
    const key = mediaCacheKey(id, variant, w)
    if (key !== lastKey) {
      retries = 0
      lastKey = key
    }
    url.value = ''
    state.value = 'loading'
    error.value = ''
    if (!id) return
    const cached = getMediaUrl(key)
    if (cached) {
      url.value = cached
      state.value = 'ready'
      return
    }
    try {
      const res = await fetchSampleImage(id, { variant, w })
      // 快速切图或卸载后，迟到的旧响应不能覆盖当前图片。
      if (disposed || sequence !== loadSeq) return
      if (res.status === 'ok') {
        const u = objectUrlFromBlob(res.blob)
        setMediaUrl(key, u)
        url.value = u
        state.value = 'ready'
      } else if (res.status === 'pending') {
        retries += 1
        if (retries <= MAX_RETRIES) {
          state.value = 'pending'
          timer = setTimeout(load, (res.retryAfter || 1) * 1000)
        } else {
          state.value = 'error'
          error.value = '预览生成超时，请点击重试'
        }
      }
    } catch (e) {
      if (disposed || sequence !== loadSeq) return
      state.value = 'error'
      error.value = errorMessage(e)
    }
  }

  function retry() {
    retries = 0
    void load()
  }

  onUnmounted(() => {
    disposed = true
    loadSeq += 1
    if (timer) clearTimeout(timer)
  })

  return { url, state, error, load, retry }
}
