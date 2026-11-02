<script setup lang="ts">
import { computed } from 'vue'

const model = defineModel<string[]>({ required: true })
const props = defineProps<{ label: string; options: { value: string; label: string }[]; placeholder?: string }>()
const selectedText = computed(() => model.value.length
  ? props.options.filter(item => model.value.includes(item.value)).map(item => item.label).join('、')
  : props.placeholder || '全部')
function toggle(value: string) {
  model.value = model.value.includes(value) ? model.value.filter(item => item !== value) : [...model.value, value]
}
</script>

<template>
  <div class="multi-field">
    <span>{{ label }}</span>
    <details class="multi-select">
      <summary :aria-label="label + '多选'" :title="selectedText"><span>{{ selectedText }}</span><small>{{ model.length ? model.length + ' 项' : '▾' }}</small></summary>
      <div class="multi-menu">
        <button type="button" class="multi-clear" @click="model = []">{{ placeholder || '全部' }}</button>
        <label v-for="option in options" :key="option.value"><input type="checkbox" :aria-label="label + '：' + option.label" :checked="model.includes(option.value)" @change="toggle(option.value)" />{{ option.label }}</label>
        <span v-if="!options.length" class="multi-empty">暂无可选项</span>
      </div>
    </details>
  </div>
</template>

<style scoped>
.multi-field { display:flex; flex-direction:column; gap:6px; min-width:0; }
.multi-select { position:relative; min-width:0; font-weight:400; }
summary { display:flex; align-items:center; gap:8px; list-style:none; cursor:pointer; padding:9px 11px; border:1px solid #dce4d7; border-radius:6px; background:white; color:#52644a; min-height:40px; }
summary::-webkit-details-marker { display:none; }
summary span { overflow:hidden; white-space:nowrap; text-overflow:ellipsis; flex:1; }
summary small { flex-shrink:0; color:#84917c; }
.multi-menu { position:absolute; z-index:25; top:calc(100% + 4px); left:0; min-width:100%; max-height:240px; overflow:auto; padding:5px; border:1px solid #dce4d7; border-radius:7px; box-shadow:0 8px 24px #24392a24; background:white; }
.multi-menu label { display:flex; align-items:center; gap:8px; padding:7px; white-space:nowrap; cursor:pointer; }
.multi-menu label:hover { background:#f0f5e9; }
.multi-menu input { accent-color:#285b43; }
.multi-clear { border:0; background:transparent; color:#285b43; padding:7px; width:100%; text-align:left; cursor:pointer; }
.multi-empty { display:block; padding:8px; color:#84917c; }
</style>
