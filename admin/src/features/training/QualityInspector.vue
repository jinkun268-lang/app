<script setup lang="ts">
import { ref, watch } from 'vue'
import { Check, ChevronLeft, ChevronRight, Expand, X } from 'lucide-vue-next'
import SampleThumb from '../samples/SampleThumb.vue'
import { dateOnly, qualityNames, reasonNames } from './data'
import type { QualityReasonCode, TrainingImage } from '../../types'

const props = defineProps<{ image: TrainingImage; position: string; busy: boolean; error?: string }>()
const emit = defineEmits<{ save: [status: 'usable' | 'unusable', reason: QualityReasonCode | null]; move: [direction: number]; zoom: []; close: []; refresh: [] }>()
const draft = ref<'usable' | 'unusable'>('usable')
const reason = ref<QualityReasonCode | ''>('')
watch(() => [props.image.image_id, props.image.quality_version], () => {
  draft.value = props.image.quality_status === 'unusable' ? 'unusable' : 'usable'
  reason.value = (props.image.quality_reason_code as QualityReasonCode) || ''
}, { immediate: true })
</script>

<template>
  <aside class="td-inspector">
    <header class="td-inspector-head"><h3>图片检查</h3><div class="td-row td-gap-xs"><span class="td-muted td-small">{{ position }}</span><button class="td-icon-btn" aria-label="上一张图片" :disabled="busy" @click="emit('move', -1)"><ChevronLeft :size="16" /></button><button class="td-icon-btn" aria-label="下一张图片" :disabled="busy" @click="emit('move', 1)"><ChevronRight :size="16" /></button><button class="td-icon-btn td-inspector-close" aria-label="关闭图片检查" :disabled="busy" @click="emit('close')"><X :size="16" /></button></div></header>
    <div class="td-inspector-scroll">
      <button class="td-inspector-image" aria-label="放大查看图片" @click="emit('zoom')"><SampleThumb :key="image.image_id" :image-id="image.image_id" :alt="image.class_name || '采集图片'" /><span class="td-expand"><Expand :size="15" /></span></button>
      <div class="td-row td-between td-image-title"><strong>{{ image.tree_id || '采集图片' }}</strong><span class="td-badge" :class="image.quality_status">{{ qualityNames[image.quality_status] }}</span></div>
      <dl class="td-metadata"><div><dt>图片 ID</dt><dd>{{ image.image_id }}</dd></div><div><dt>采集记录</dt><dd>{{ image.sample_id }}</dd></div><div><dt>最终类别</dt><dd>{{ image.class_name }}</dd></div><div><dt>品种 / 上传日期</dt><dd>{{ image.cultivar_name }} · {{ dateOnly(image.uploaded_at) }}</dd></div></dl>
      <div class="td-rule" /><h4>质量判定</h4>
      <div class="td-verdict-options"><button :disabled="busy" :class="{ chosen: draft === 'usable' }" @click="draft = 'usable'">可用<Check v-if="draft === 'usable'" :size="15" /></button><button class="reject" :disabled="busy" :class="{ chosen: draft === 'unusable' }" @click="draft = 'unusable'">不可用<Check v-if="draft === 'unusable'" :size="15" /></button></div>
      <label v-if="draft === 'unusable'" class="td-field td-reason">不可用原因<select v-model="reason" :disabled="busy"><option value="">请选择原因</option><option v-for="(label, code) in reasonNames" :key="code" :value="code">{{ label }}</option></select></label>
    </div>
    <footer class="td-inspector-footer"><p v-if="error" class="td-error" role="alert">{{ error }} <button class="td-text-btn" :disabled="busy" @click="emit('refresh')">刷新图片</button></p><button class="td-btn primary td-full" :disabled="busy || (draft === 'unusable' && !reason)" @click="emit('save', draft, draft === 'unusable' ? reason as QualityReasonCode : null)">{{ busy ? '保存中…' : '保存并检查下一张' }}</button></footer>
  </aside>
</template>
