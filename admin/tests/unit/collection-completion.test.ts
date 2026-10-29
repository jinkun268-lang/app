import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createMemoryHistory, createRouter } from 'vue-router'
import * as api from '../../src/api/collection'
import { request } from '../../src/api/http'
import { setMockEnabled } from '../../src/mocks'
import { setTokens } from '../../src/auth/tokens'
import QuestionsView from '../../src/views/QuestionsView.vue'
import BatchesView from '../../src/views/BatchesView.vue'

const question = { question_id: 'q1', text: '叶片有斑点，应如何处理？', sample_id: null, owner_id: 'collector', status: 'open' as const, answer: null, created_at: '2026-10-29T10:00:00Z', answered_at: null, images: [], sample: null }
async function mountPage(component: typeof QuestionsView | typeof BatchesView) {
  const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component }, { path: '/samples', component: { template: '<div />' } }] })
  await router.push('/'); await router.isReady()
  return mount(component, { global: { plugins: [router] } })
}
function button(wrapper: ReturnType<typeof mount>, label: string) {
  const found = wrapper.findAll('button').find(value => value.text() === label)
  if (!found) throw Error(`Missing button ${label}`)
  return found
}
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); setMockEnabled(true) })

describe('真实咨询闭环', () => {
  it('提交答复失败保留草稿，重试成功呈现服务端持久化答复', async () => {
    vi.spyOn(api, 'listQuestions').mockResolvedValue({ items: [question], page: 1, page_size: 20, total: 1 })
    vi.spyOn(api, 'getQuestion').mockResolvedValue(question)
    const answer = vi.spyOn(api, 'answerQuestion').mockRejectedValueOnce(Error('网络中断')).mockResolvedValueOnce({ ...question, status: 'answered', answer: '请补充叶背近照' })
    const wrapper = await mountPage(QuestionsView); await flushPromises()
    await wrapper.find('.question-row').trigger('click'); await flushPromises()
    await wrapper.find('textarea').setValue('请补充叶背近照')
    await button(wrapper, '保存答复').trigger('click'); await flushPromises()
    expect((wrapper.find('textarea').element as HTMLTextAreaElement).value).toBe('请补充叶背近照')
    expect(wrapper.text()).toContain('网络中断')
    await button(wrapper, '保存答复').trigger('click'); await flushPromises()
    expect(answer).toHaveBeenLastCalledWith('q1', '请补充叶背近照')
    expect(wrapper.text()).toContain('答复已保存')
    expect(wrapper.text()).toContain('已保存答复：请补充叶背近照')
  })
  it('新API经统一客户端发送Bearer、分页和真实答复内容', async () => {
    setMockEnabled(false); setTokens('access', 'refresh')
    const fetcher = vi.fn().mockImplementation(async () => new Response(JSON.stringify(question), { status: 200, headers: { 'content-type': 'application/json' } }))
    vi.stubGlobal('fetch', fetcher)
    await api.answerQuestion('q 1', '叶背补拍')
    expect(fetcher.mock.calls[0][0]).toBe('/api/v1/questions/q%201/answer')
    expect(fetcher.mock.calls[0][1]).toMatchObject({ method: 'PATCH', body: JSON.stringify({ answer: '叶背补拍' }), headers: expect.objectContaining({ authorization: 'Bearer access' }) })
    await api.listBatches(2, 20)
    expect(fetcher.mock.calls[1][0]).toBe('/api/v1/batches?page=2&page_size=20')
    await request({ path: '/samples', query: { batch_id: 'b1' } })
    expect(fetcher.mock.calls[2][0]).toBe('/api/v1/samples?batch_id=b1')
  })
  it('批次列表跳转携带服务端筛选ID并展示关闭状态', async () => {
    vi.spyOn(api, 'listBatches').mockResolvedValue({ items: [{ batch_id: 'batch1', owner_id: 'u1', name: '上午采集', place: 'A区', collector: '张三', default_cultivar_id: 'unknown', note: '', closed: true, created_at: '2026-10-29T00:00:00Z', updated_at: '2026-10-29T00:00:00Z' }], page: 1, page_size: 20, total: 1 })
    const wrapper = await mountPage(BatchesView); await flushPromises()
    expect(wrapper.text()).toContain('已关闭'); expect(wrapper.text()).toContain('A区')
    expect(wrapper.find('a').attributes('href')).toBe('/samples?batch_id=batch1')
  })
})
