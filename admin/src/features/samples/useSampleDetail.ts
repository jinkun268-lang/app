// 样本详情状态：加载（请求序号防串）、审核/单图质量/排除恢复（版本冲突保留草稿并重读最新）。
//
// 冲突与草稿的边界：
// - formSyncToken 只在「加载完成 / 审核保存成功 / 排除恢复成功」时递增，界面据此把表单重置为服务端状态；
// - 409 冲突只重读服务端最新状态（版本、历史、展示字段），不递增 formSyncToken，因此未保存的审核草稿与逐图质量草稿保留；
// - 提交时 expected_version 始终取自当前最新 detail，冲突后重新提交不会一直使用旧版本；
// - 样本切换后返回的慢请求结果直接丢弃，不污染另一个 sampleId 的详情与表单。
import { ref, watch, type Ref } from 'vue'
import { excludeSample, getSample, restoreSample, reviewSample, setImageQuality } from '../../api/samples'
import type { ExcludeRequest, ImageQualityRequest, RestoreRequest, SampleDetail, SampleImage, SampleReviewRequest } from '../../types'
import { errorMessage, isVersionConflict } from '../../util/error'

export interface ActionResult {
  ok: boolean
  message: string
  conflict?: boolean
}

export function useSampleDetail(sampleId: Ref<string>) {
  const detail = ref<SampleDetail | null>(null)
  const loading = ref(false)
  const error = ref('')
  // 版本冲突提示：只更新服务端展示，不重置调用方草稿。
  const conflictNotice = ref('')
  // 需要把表单重置为服务端状态的信号（加载完成/保存成功），冲突重读不触发。
  const formSyncToken = ref(0)
  let seq = 0

  async function load(): Promise<SampleDetail | null> {
    const mySeq = ++seq
    loading.value = true
    error.value = ''
    try {
      const d = await getSample(sampleId.value)
      if (mySeq !== seq) return d
      detail.value = d
      conflictNotice.value = ''
      formSyncToken.value += 1
      return d
    } catch (e) {
      if (mySeq !== seq) return null
      error.value = errorMessage(e)
      detail.value = null
      return null
    } finally {
      if (mySeq === seq) loading.value = false
    }
  }

  // 冲突后只重读服务端状态（版本与历史），不触碰调用方草稿；样本已切换则丢弃结果。
  async function reloadAfterConflict(targetId: string): Promise<void> {
    try {
      const d = await getSample(targetId)
      if (sampleId.value !== targetId) return
      detail.value = d
    } catch {
      // 保留原展示
    }
  }

  function conflictResult(targetId: string, e: unknown): ActionResult {
    if (sampleId.value === targetId) conflictNotice.value = errorMessage(e)
    return { ok: false, message: errorMessage(e), conflict: true }
  }

  async function submitReview(payload: SampleReviewRequest): Promise<ActionResult> {
    const targetId = sampleId.value
    try {
      const d = await reviewSample(targetId, payload)
      // 样本已切换：保存结果属于上一个样本，不写入当前详情。
      if (sampleId.value !== targetId) return { ok: true, message: '审核已保存' }
      detail.value = d
      conflictNotice.value = ''
      formSyncToken.value += 1
      return { ok: true, message: '审核已保存' }
    } catch (e) {
      if (isVersionConflict(e)) {
        await reloadAfterConflict(targetId)
        return conflictResult(targetId, e)
      }
      return { ok: false, message: errorMessage(e) }
    }
  }

  async function submitQuality(imageId: string, payload: ImageQualityRequest): Promise<ActionResult> {
    const targetId = sampleId.value
    try {
      const img: SampleImage = await setImageQuality(targetId, imageId, payload)
      if (sampleId.value === targetId && detail.value) {
        const idx = detail.value.images.findIndex((i) => i.image_id === imageId)
        if (idx >= 0) detail.value.images[idx] = img
      }
      return { ok: true, message: '图片质量已保存' }
    } catch (e) {
      if (isVersionConflict(e)) {
        await reloadAfterConflict(targetId)
        return conflictResult(targetId, e)
      }
      return { ok: false, message: errorMessage(e) }
    }
  }

  async function toggleExclude(payload: ExcludeRequest | RestoreRequest, action: 'exclude' | 'restore'): Promise<ActionResult> {
    const targetId = sampleId.value
    try {
      const d = action === 'exclude' ? await excludeSample(targetId, payload as ExcludeRequest) : await restoreSample(targetId, payload as RestoreRequest)
      if (sampleId.value !== targetId) return { ok: true, message: action === 'exclude' ? '已排除' : '已恢复' }
      detail.value = d
      conflictNotice.value = ''
      formSyncToken.value += 1
      return { ok: true, message: action === 'exclude' ? '已排除' : '已恢复' }
    } catch (e) {
      if (isVersionConflict(e)) {
        await reloadAfterConflict(targetId)
        return conflictResult(targetId, e)
      }
      return { ok: false, message: errorMessage(e) }
    }
  }

  watch(sampleId, () => void load(), { immediate: true })

  return { detail, loading, error, conflictNotice, formSyncToken, load, submitReview, submitQuality, toggleExclude }
}
