<script setup lang="ts">
import { X } from 'lucide-vue-next'
import SampleThumb from '../samples/SampleThumb.vue'
import { dateOnly, exportQualityNames, reviewed } from './data'
import type { TrainingBatch, TrainingImage } from '../../types'

defineProps<{ batch: TrainingBatch; images: TrainingImage[]; selectedIds: string[]; loading: boolean; error: string }>()
const emit = defineEmits<{ toggle: [image: TrainingImage]; selectAll: []; clear: []; restore: []; close: []; retry: [] }>()
</script>

<template>
  <div class="td-modal-backdrop td-export-image-overlay" @click.self="emit('close')">
    <section class="td-dialog td-export-image-dialog" role="dialog" aria-modal="true" aria-labelledby="image-picker-title">
      <header class="td-dialog-head"><div><h2 id="image-picker-title">{{ batch.name }} · 选择图片</h2><p>{{ dateOnly(batch.created_at) }} · {{ batch.batch_id }}</p></div><button type="button" class="td-icon-btn" aria-label="关闭批次选图" @click="emit('close')"><X :size="19" /></button></header>
      <div class="td-export-image-body">
        <div v-if="loading" class="td-empty">加载图片中…</div>
        <div v-else-if="error" class="td-empty"><p class="td-error">{{ error }}</p><button type="button" class="td-btn" @click="emit('retry')">重试</button></div>
        <template v-else>
          <div class="td-export-image-toolbar"><span>已选 {{ images.filter(image => selectedIds.includes(image.image_id)).length }} / {{ images.length }} 张</span><button type="button" class="td-text-btn" @click="emit('selectAll')">全选当前图片</button><button type="button" class="td-text-btn" @click="emit('clear')">全部取消</button><button type="button" class="td-text-btn td-ml-auto" @click="emit('restore')">恢复默认选图</button></div>
          <div class="td-image-grid td-export-image-grid">
            <label v-for="image in images" :key="image.image_id" class="td-export-image-card" :class="{ selected: selectedIds.includes(image.image_id) }">
              <input type="checkbox" :aria-label="'导出图片 ' + image.image_id" :checked="selectedIds.includes(image.image_id)" @change="emit('toggle', image)" />
              <SampleThumb :image-id="image.image_id" :alt="image.class_name || '采集图片'" />
              <div><div class="td-row td-between"><strong :title="image.image_id">{{ image.image_id }}</strong><span class="td-badge" :class="reviewed(image) ? image.quality_status : 'review'">{{ reviewed(image) ? exportQualityNames[image.quality_status] : image.review_status === 'unresolved' ? '无法判断' : '未核验' }}</span></div><p>{{ image.class_name }} · {{ image.cultivar_name }}</p><small>{{ reviewed(image) ? '已核验' : '采集类别，尚未确认' }} · {{ image.view_type }}</small></div>
            </label>
          </div>
          <div v-if="!images.length" class="td-empty">此批次没有符合当前类别、品种条件的已上传图片</div>
          <p class="td-export-image-note">手动勾选仅影响本次导出，不修改核验或质量状态。</p>
        </template>
      </div>
      <footer class="td-dialog-footer"><button type="button" class="td-btn primary" @click="emit('close')">完成选图</button></footer>
    </section>
  </div>
</template>
