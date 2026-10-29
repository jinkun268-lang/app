// 核心交互收尾：真实服务下的冲突草稿保留、配置加载失败提示/重试、未开放功能入口隐藏。
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { h } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { flushPromises, mount, type DOMWrapper, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import * as authApi from '../../src/api/auth'
import { getSample, reviewSample } from '../../src/api/samples'
import { useBootstrapStore } from '../../src/stores/bootstrap'
import { useAuthStore } from '../../src/stores/auth'
import { setMockEnabled } from '../../src/mocks'
import SampleDetail from '../../src/features/samples/SampleDetail.vue'
import SamplesView from '../../src/views/SamplesView.vue'
import AppLayout from '../../src/layout/AppLayout.vue'
import { loginAs } from '../helpers'

const SAMPLE = '019a0001-0000-7000-8000-000000000001'

// 路由占位页用渲染函数，避免依赖运行时模板编译。
function pageStub(className: string) {
  return { name: 'PageStub', render: () => h('div', { class: className }) }
}

function buttonByText(wrapper: VueWrapper<any> | DOMWrapper<any>, text: string): DOMWrapper<HTMLButtonElement> {
  const found = wrapper.findAll('button').find((b) => b.text() === text)
  if (!found) throw new Error(`未找到按钮：${text}`)
  return found as DOMWrapper<HTMLButtonElement>
}

function mountSampleDetail(sampleId: string, workspace: 'collection' | 'review' | 'quality' = 'review') {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore().setAccount({ user_id: '019a0000-0000-7000-8000-000000000001', username: 'super', display_name: '超级管理员', role: 'super_admin' })
  return mount(SampleDetail, {
    props: { sampleId, workspace },
    global: { plugins: [pinia], stubs: { RouterLink: true } },
  })
}

beforeEach(async () => {
  // jsdom 不提供媒体查询；布局与样本页共用桌面尺寸替身。
  vi.stubGlobal('matchMedia', () => ({
    matches: false,
    addEventListener: () => {},
    removeEventListener: () => {},
  }))
  setActivePinia(createPinia())
  await loginAs('super')
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  setMockEnabled(true)
})

describe('样本详情冲突与草稿', () => {
  it('同样本 409 后保留未保存草稿，重新提交使用最新版本', async () => {
    const wrapper = mountSampleDetail(SAMPLE)
    await flushPromises()

    const bootstrapStore = useBootstrapStore()
    expect(bootstrapStore.ready).toBe(true)
    expect(wrapper.find('.pane-head').text()).toContain('T-001')

    // 填写专业核验草稿（修正 + 备注）。
    await buttonByText(wrapper, '修正').trigger('click')
    await wrapper.findAll('.correct-form select')[2].setValue('citrus_canker')
    await wrapper.find('.correct-form textarea').setValue('复核草稿：待核对')
    expect(wrapper.text()).toContain('有未保存更改')

    // 另一位审核者先更新了该样本，本页停留的版本落后。
    await reviewSample(SAMPLE, { expected_version: 0, review_status: 'unresolved', review_note: '他人更新' })

    // 第一次提交：409，应提示冲突并重读服务端最新状态，但不覆盖草稿。
    await buttonByText(wrapper, '保存审核').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('数据已被他人更新')
    expect(wrapper.text()).toContain('请重新保存')
    expect((wrapper.find('.correct-form textarea').element as HTMLTextAreaElement).value).toBe('复核草稿：待核对')
    expect((wrapper.findAll('.correct-form select')[2].element as HTMLSelectElement).value).toBe('citrus_canker')
    // 服务端最新版本与历史已展示
    expect(wrapper.text()).toContain('他人更新')
    expect(wrapper.findAll('.history-item').length).toBeGreaterThan(0)
    const latest = await getSample(SAMPLE)
    expect(latest.review_version).toBe(1)
    expect(latest.review_status).toBe('unresolved')

    // 第二次提交：使用重读后的最新版本，保存成功并同步表单。
    await buttonByText(wrapper, '保存审核').trigger('click')
    await flushPromises()
    const saved = await getSample(SAMPLE)
    expect(saved.review_version).toBe(2)
    expect(saved.review_status).toBe('corrected')
    expect(saved.final_class_id).toBe('citrus_canker')
    expect(saved.review_note).toBe('复核草稿：待核对')
    expect(wrapper.text()).not.toContain('数据已被他人更新')
    expect(wrapper.text()).not.toContain('有未保存更改')
    wrapper.unmount()
  })
})

describe('工作区操作边界', () => {
  it('采集详情只读，核验与训练质量分开提供操作', async () => {
    const collection = mountSampleDetail(SAMPLE, 'collection')
    await flushPromises()
    expect(collection.text()).not.toContain('保存审核')
    expect(collection.text()).not.toContain('保存质量')
    collection.unmount()
    const quality = mountSampleDetail(SAMPLE, 'quality')
    await flushPromises()
    expect(quality.text()).toContain('尚未通过专业核验')
    expect(quality.text()).not.toContain('保存审核')
    expect(quality.text()).not.toContain('保存质量')
    quality.unmount()
    const ready = mountSampleDetail('019a0001-0000-7000-8000-000000000002', 'quality')
    await flushPromises()
    expect(ready.text()).toContain('保存质量')
    expect(ready.text()).not.toContain('保存审核')
    ready.unmount()
  })
})

describe('配置加载', () => {
  it('样本页展示基础配置错误并在重试后恢复，共享并发加载', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const store = useBootstrapStore()
    const spy = vi.spyOn(authApi, 'getBootstrap').mockRejectedValueOnce(new Error('网络错误，请检查连接后重试'))

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/samples/:id?', name: 'samples', component: pageStub('samples-page') }],
    })
    await router.push('/samples')
    await router.isReady()

    const wrapper = mount(SamplesView, { global: { plugins: [pinia, router] } })
    await flushPromises()

    expect(wrapper.find('.config-error').exists()).toBe(true)
    expect(wrapper.text()).toContain('基础配置加载失败')
    expect(store.loaded).toBe(false)
    expect(store.ready).toBe(false)

    // 重试按钮走真实加载，成功后错误消失、类别选项来自 bootstrap。
    await buttonByText(wrapper.find('.config-error'), '重试').trigger('click')
    await flushPromises()
    expect(wrapper.find('.config-error').exists()).toBe(false)
    expect(store.loaded).toBe(true)
    expect(store.ready).toBe(true)
    const classFilter = wrapper.findAll('.filters select')[1]
    expect(classFilter.findAll('option').length).toBeGreaterThan(1)

    // 并发刷新共享同一个请求
    const callsBefore = spy.mock.calls.length
    await Promise.all([store.load(true), store.load(true)])
    expect(spy.mock.calls.length).toBe(callsBefore + 1)
    expect(store.loaded).toBe(true)
    wrapper.unmount()
  })

  it('真实 HTTP 模式开放账号管理，其余未实现入口隐藏且不挂载', async () => {
    setMockEnabled(false)
    vi.spyOn(authApi, 'getBootstrap').mockResolvedValue({
      cultivars: [],
      classes: [],
      taxonomy_version: 1,
      policy_version: 1,
      server_time: '2026-10-20T00:00:00Z',
    })
    const pinia = createPinia()
    setActivePinia(pinia)
    useAuthStore().setAccount({ user_id: '019a0000-0000-7000-8000-000000000001', username: 'super', display_name: '超级管理员', role: 'super_admin' })

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/samples', name: 'samples', component: pageStub('samples-page') },
        { path: '/reviews', component: pageStub('reviews-page') },
        { path: '/batches', component: pageStub('batches-page') },
        { path: '/questions', component: pageStub('questions-page') },
        { path: '/training/quality', component: pageStub('quality-page') },
        { path: '/exports', name: 'exports', component: pageStub('exports-page') },
        { path: '/settings/users', name: 'users', component: pageStub('users-page') },
        { path: '/settings/dictionaries', name: 'dictionaries', component: pageStub('dictionaries-page') },
        { path: '/tickets', name: 'tickets', component: pageStub('tickets-page') },
      ],
    })
    // 未实现的字典页仍显示占位，且不挂载页面
    await router.push('/settings/dictionaries')
    await router.isReady()

    const wrapper = mount(AppLayout, { global: { plugins: [pinia, router] } })
    await flushPromises()

    expect(wrapper.text()).toContain('页面不可用')
    expect(wrapper.find('.dictionaries-page').exists()).toBe(false)

    const menu = wrapper.findAll('.nav-item').map((n) => n.text())
    expect(menu).toContain('采集记录')
    expect(menu).toContain('采集批次')
    expect(menu).toContain('咨询答复')
    expect(menu).toContain('样本核验')
    expect(menu).toContain('质量检查')
    expect(menu).toContain('数据导出')
    // 账号管理在真实模式已开放，其余基础管理与工单入口隐藏
    expect(menu).toContain('账号管理')
    expect(menu).not.toContain('基础字典')
    expect(menu).not.toContain('审计')
    expect(menu).not.toContain('工单队列')

    // 超级管理员的账号管理入口可进入并渲染页面
    await router.push('/settings/users')
    await flushPromises()
    expect(wrapper.find('.users-page').exists()).toBe(true)
    expect(wrapper.text()).not.toContain('页面不可用')

    // 核心页面仍正常渲染
    await router.push('/samples')
    await flushPromises()
    expect(wrapper.find('.samples-page').exists()).toBe(true)
    wrapper.unmount()
  })
})
