<template>
  <div class="page">
    <div class="toolbar"><h2>专家咨询</h2><button class="btn" :disabled="loading" @click="load">刷新列表</button></div>
    <p class="muted">采集员提交的真实问题与关联图片；答复将回到采集端。</p>
    <p v-if="error" class="err-text" role="alert">{{ error }}</p>
    <div class="columns">
      <section class="card queue">
        <p v-if="loading">加载中…</p><p v-else-if="!items.length" class="muted">暂无咨询</p>
        <button v-for="question in items" :key="question.question_id" class="question-row" :class="{active: detail?.question_id === question.question_id}" @click="select(question.question_id)">
          <span class="tag" :class="question.status === 'answered' ? 'tag-green' : 'tag-amber'">{{ question.status === 'answered' ? '已答复' : '待答复' }}</span>
          <p>{{ question.text }}</p><small class="muted">{{ question.created_at }}</small>
        </button>
        <Pagination :page="page" :page-size="20" :total="total" @change="changePage" />
      </section>
      <section class="card answer">
        <p v-if="detailLoading">问题详情加载中…</p>
        <template v-else-if="detail">
          <h3>问题详情</h3><p class="pre-wrap">{{ detail.text }}</p>
          <router-link v-if="detail.sample_id" :to="`/reviews/${detail.sample_id}`">查看关联采集记录</router-link>
          <div class="photos"><SampleThumb v-for="photo in detail.images" :key="photo.image_id" :image-id="photo.image_id" alt="咨询关联采集图片" /></div>
          <p v-if="detail.answer" class="pre-wrap"><strong>已保存答复：</strong>{{ detail.answer }}</p>
          <label for="expert-answer">专家答复</label>
          <textarea id="expert-answer" v-model="draft" class="input" rows="7" maxlength="4000" :disabled="saving" placeholder="填写判断依据、处理建议或需要补充的信息" />
          <p class="muted">{{ draft.length }}/4000 字</p>
          <p v-if="saveError" class="err-text" role="alert">{{ saveError }}</p>
          <p v-if="message" role="status">{{ message }}</p>
          <button class="btn btn-primary" :disabled="saving || !draft.trim()" @click="save">{{ saving ? '保存中…' : '保存答复' }}</button>
        </template>
        <p v-else class="muted">选择一个问题查看图片并答复</p>
      </section>
    </div>
  </div>
</template>
<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { answerQuestion, getQuestion, listQuestions } from '../api/collection'
import type { CollectionQuestion } from '../types'
import Pagination from '../components/Pagination.vue'
import SampleThumb from '../features/samples/SampleThumb.vue'
import { errorMessage } from '../util/error'
const items = ref<CollectionQuestion[]>([]), detail = ref<CollectionQuestion | null>(null)
const page = ref(1), total = ref(0), loading = ref(false), detailLoading = ref(false), saving = ref(false)
const error = ref(''), saveError = ref(''), draft = ref(''), message = ref('')
let listSequence = 0, detailSequence = 0
async function load() {
  const sequence = ++listSequence
  loading.value = true; error.value = ''
  try { const result = await listQuestions(page.value); if (sequence === listSequence) { items.value = result.items; total.value = result.total } }
  catch (e) { if (sequence === listSequence) error.value = errorMessage(e) }
  finally { if (sequence === listSequence) loading.value = false }
}
async function select(id: string) {
  if (saving.value) return
  if (detail.value && draft.value !== (detail.value.answer || '') && !window.confirm('当前答复未保存，确定切换问题？')) return
  const sequence = ++detailSequence
  detailLoading.value = true; error.value = ''; saveError.value = ''; message.value = ''
  try { const result = await getQuestion(id); if (sequence === detailSequence) { detail.value = result; draft.value = result.answer || '' } }
  catch (e) { if (sequence === detailSequence) error.value = errorMessage(e) }
  finally { if (sequence === detailSequence) detailLoading.value = false }
}
async function save() {
  if (!detail.value || !draft.value.trim() || saving.value) return
  saving.value = true; saveError.value = ''; message.value = ''
  try { const result = await answerQuestion(detail.value.question_id, draft.value.trim()); detail.value = result; draft.value = result.answer || ''; message.value = '答复已保存，采集员刷新后可查看'; await load() }
  catch (e) { saveError.value = errorMessage(e) }
  finally { saving.value = false }
}
function changePage(value: number) { page.value = value; void load() }
onMounted(load)
</script>
<style scoped>
.page { padding: 20px; }.toolbar { display:flex; justify-content:space-between; align-items:center; }h2 { margin:0; font-size:18px; }.columns { display:grid; grid-template-columns:minmax(240px, 1fr) minmax(300px, 2fr); gap:16px; }.queue, .answer { padding:16px; min-width:0; }.question-row { text-align:left; display:block; width:100%; padding:12px; border:0; border-bottom:1px solid var(--border); background:transparent; }.question-row.active { background:#eaf3eb; }.question-row p { white-space:normal; overflow-wrap:anywhere; }.photos { display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:8px; margin:12px 0; }.pre-wrap { white-space:pre-wrap; overflow-wrap:anywhere; }textarea { display:block; width:100%; margin:8px 0; }@media(max-width:800px) { .columns { grid-template-columns:1fr; } }
</style>
