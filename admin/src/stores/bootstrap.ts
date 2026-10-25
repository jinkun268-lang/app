// 配置 store：品种/类别及版本。选项来自 bootstrap，不维护第二份病种列表。
// 停用项保留历史展示，新增选择只允许当前有效项。
//
// 加载状态显式化：loading 表示请求进行中（含共享并发），error 保存失败原因并可重试，
// loaded 仅在成功后为 true；失败不写入空字典，页面据此禁止用空选项提交审核。
import { defineStore } from 'pinia'
import { getBootstrap } from '../api/auth'
import { errorMessage } from '../util/error'
import type { BootstrapResponse, ClassEntry, Cultivar } from '../types'

// 并发共享任务：同一次加载只发一个请求，后到的调用等待同一 Promise。
let inflight: Promise<void> | null = null

export const useBootstrapStore = defineStore('bootstrap', {
  state: () => ({
    loaded: false,
    loading: false,
    error: '' as string,
    cultivars: [] as Cultivar[],
    classes: [] as ClassEntry[],
    taxonomyVersion: 0,
    policyVersion: 0,
    serverTime: null as string | null,
  }),
  getters: {
    activeCultivars: (s) => s.cultivars.filter((c) => c.is_active),
    activeClasses: (s) => s.classes.filter((c) => c.is_active),
    // 只有加载成功且无错误时才允许使用字典提交审核（刷新期间沿用已加载的字典）。
    ready: (s): boolean => s.loaded && !s.error,
  },
  actions: {
    async load(force = false): Promise<void> {
      if (this.loaded && !force) return
      if (inflight) return inflight
      this.loading = true
      this.error = ''
      const task = (async () => {
        try {
          const data: BootstrapResponse = await getBootstrap()
          this.cultivars = data.cultivars
          this.classes = data.classes
          this.taxonomyVersion = data.taxonomy_version
          this.policyVersion = data.policy_version
          this.serverTime = data.server_time
          this.loaded = true
        } catch (e) {
          // 失败保留错误供页面展示与重试，不假装已加载。
          this.loaded = false
          this.error = errorMessage(e)
        } finally {
          this.loading = false
          inflight = null
        }
      })()
      inflight = task
      return task
    },
    reset() {
      this.loaded = false
      this.loading = false
      this.error = ''
      this.cultivars = []
      this.classes = []
      this.taxonomyVersion = 0
      this.policyVersion = 0
      this.serverTime = null
    },
    cultivarName(id: string | null): string {
      if (id == null) return '—'
      return this.cultivars.find((c) => c.cultivar_id === id)?.name ?? id
    },
    className(id: string | null): string {
      if (id == null) return '—'
      return this.classes.find((c) => c.class_id === id)?.name ?? id
    },
  },
})
