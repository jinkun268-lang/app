// 写操作统一请求状态：submitting 防重复提交，失败保留表单并给出错误，成功后才关闭弹窗。
import { ref } from 'vue'

export function useAsyncAction<TArgs extends unknown[], TResult>(fn: (...args: TArgs) => Promise<TResult>) {
  const submitting = ref(false)
  const error = ref('')

  async function run(...args: TArgs): Promise<TResult | undefined> {
    if (submitting.value) return undefined
    submitting.value = true
    error.value = ''
    try {
      return await fn(...args)
    } catch (e) {
      error.value = (e as Error).message
      throw e
    } finally {
      submitting.value = false
    }
  }

  return { submitting, error, run }
}
