<script setup lang="ts">
import { onActivated, onBeforeUnmount, onDeactivated, onMounted, ref } from 'vue'
import { insightService } from '@/services/insightService'
import type { AgentPipelineStatus, AgentRun } from '@/types/domain'

const status = ref<AgentPipelineStatus | null>(null)
const runs = ref<AgentRun[]>([])
const batches = ref<Array<{id: string; sourceName: string}>>([])
const selectedBatch = ref(''), error = ref(''), submitting = ref(false), loading = ref(false)
let timer: ReturnType<typeof setTimeout> | undefined
let active = false
const stateLabels: Record<string, string> = { queued: '等待处理', running: '处理中', completed: '已完成', failed: '失败', skipped: '已跳过', interrupted: '已中断' }
const reasonLabels: Record<string, string> = { busy: '等待锁超时，请手动重跑', over_limit: '超出本次生成上限', no_signal: '本批无可用信号或候选', disabled: '功能未开启', frozen: '草稿已冻结', draft_edited: '草稿已人工编辑', draft_frozen: '草稿已冻结', draft_changed: '生成期间草稿发生变更', unchanged: '描述输入未变化', already_normalized: '已完成标准化', enterprise_scope: '企业直通草稿无需此阶段' }
const stageLabels: Record<string, string> = { normalize: '解析标准化', feature: '特征与信号', definition: '草稿生成', description: '岗位描述', pipeline: '编排' }
function stopTimer() { if (timer) clearTimeout(timer); timer = undefined }
function schedule() {
  stopTimer()
  if (active && !document.hidden && document.hasFocus() && runs.value.some(run => ['queued', 'running'].includes(run.status))) timer = setTimeout(() => void load(false), 4000)
}
async function load(withBatches = true) {
  if (loading.value) return
  loading.value = true; error.value = ''
  try {
    status.value = await insightService.getAgentPipelineStatus()
    if (status.value.enabled) {
      runs.value = (await insightService.getAgentRuns()).items
      if (withBatches) batches.value = (await insightService.getIngestBatches()).items
    }
  } catch (reason: any) { error.value = reason.message || '运行记录读取失败' }
  finally { loading.value = false; schedule() }
}
async function startRun() {
  if (!selectedBatch.value || submitting.value) return
  submitting.value = true; error.value = ''
  try { await insightService.startAgentRun(selectedBatch.value); await load(false) }
  catch (reason: any) { error.value = reason.message || '启动失败' }
  finally { submitting.value = false }
}
function visibilityChanged() { if (active && !document.hidden && document.hasFocus()) void load(false); else stopTimer() }
function activate() { if (!active) { active = true; void load() } }
function deactivate() { active = false; stopTimer() }
function failureText(value: string) { return value === 'no_draft_legacy_batch' ? '该批次产生于管道关闭期，请企业重新提交' : value }
function stageSummary(value: Record<string, any>) {
  const labels: Record<string, string> = { processed: '记录', parsed: '解析成功', links: '链接', created: '新建', updated: '更新', skipped: '跳过', feature_count: '特征', signal_count: '信号' }
  return Object.entries(labels).filter(([key]) => typeof value[key] === 'number').map(([key, label]) => `${label} ${value[key]}`).join(' · ')
}
onMounted(() => { window.addEventListener('focus', visibilityChanged); window.addEventListener('blur', stopTimer); document.addEventListener('visibilitychange', visibilityChanged); activate() })
onActivated(activate)
onDeactivated(deactivate)
onBeforeUnmount(() => { deactivate(); window.removeEventListener('focus', visibilityChanged); window.removeEventListener('blur', stopTimer); document.removeEventListener('visibilitychange', visibilityChanged) })
</script>

<template>
  <div class="agent-runs stack-lg">
    <p v-if="error" class="agent-error" role="alert">{{ error }} <button class="secondary-btn" @click="load()">重试</button></p>
    <section class="panel agent-status" aria-live="polite">
      <strong>{{ status?.enabled ? '自动编排已开启' : status ? '自动编排未开启' : '正在读取状态' }}</strong>
      <template v-if="status?.enabled"><span>描述生成：{{ status.descriptionEnabled ? '开启' : '关闭' }}</span><span>{{ status.llmConfigured ? 'DeepSeek 已配置' : '使用规则模板' }}</span><span>每次最多 {{ status.maxDrafts }} 条描述</span><span>{{ status.running ? '正在处理' : '空闲' }}</span></template>
    </section>
    <template v-if="status?.enabled">
      <section class="panel agent-controls"><label for="agent-batch">接入批次</label><select id="agent-batch" v-model="selectedBatch"><option value="">请选择批次</option><option v-for="batch in batches" :key="batch.id" :value="batch.id">{{ batch.sourceName }} · {{ batch.id }}</option></select><button class="primary-btn" :disabled="!selectedBatch || submitting" @click="startRun">{{ submitting ? '正在提交' : '手动运行' }}</button><button class="secondary-btn" :disabled="loading" @click="load()">刷新</button></section>
      <section class="panel agent-table"><table><thead><tr><th>批次 / 时间</th><th>状态</th><th>阶段统计</th><th>草稿 / 描述</th><th>跳过与失败原因</th></tr></thead><tbody><tr v-for="run in runs" :key="run.id"><td><strong>{{ run.batchId }}</strong><small>{{ run.startedAt.replace('T', ' ') }}</small><small>{{ run.scope === 'enterprise' ? '企业提交' : '批次处理' }}</small></td><td>{{ stateLabels[run.status] }}<small>{{ run.llmUsed ? '已调用模型' : '未调用模型' }}</small></td><td><details v-for="(stage, name) in run.stages" :key="name"><summary>{{ stageLabels[name] || name }} · {{ stateLabels[stage.status] || stage.status }}</summary><p>{{ stageSummary(stage) }}</p><p v-if="stage.reason">{{ reasonLabels[stage.reason] || stage.reason }}</p><p v-if="stage.parse_errors?.length">解析失败 {{ stage.parse_errors.length }} 条</p><pre v-if="stage.parse_errors?.length">{{ JSON.stringify(stage.parse_errors, null, 2) }}</pre></details></td><td>{{ run.draftCount }} / {{ run.descriptionCount }}</td><td><p v-for="(count, reason) in run.skip_reasons" :key="reason">{{ reasonLabels[reason] || reason }}（{{ count }}）</p><p v-if="run.error" class="agent-error">{{ failureText(run.error) }}</p><span v-if="!run.error && !Object.keys(run.skip_reasons).length">—</span></td></tr><tr v-if="!runs.length"><td colspan="5">{{ loading ? '正在加载运行记录…' : '暂无运行记录' }}</td></tr></tbody></table></section>
    </template>
  </div>
</template>

<style scoped>
.agent-status,.agent-controls{padding:18px;display:flex;align-items:center;gap:18px;flex-wrap:wrap}.agent-status span{color:#62736e;font-size:13px}.agent-controls select{min-width:0;flex:1;max-width:600px;padding:10px;border:1px solid #d8e3e0;border-radius:6px;background:#fff}.agent-table{overflow-x:auto}.agent-table table{width:100%;border-collapse:collapse;font-size:13px;text-align:left}.agent-table th,.agent-table td{padding:16px;border-bottom:1px solid #e3ebe9;vertical-align:top}.agent-table th{color:#62736e;white-space:nowrap}.agent-table td:first-child{max-width:280px;overflow-wrap:anywhere}.agent-table small{display:block;color:#75837f;margin-top:6px}.agent-table p{margin:6px 0}.agent-table details{min-width:150px;margin:0 0 8px}.agent-table summary{cursor:pointer}.agent-table pre{white-space:pre-wrap;overflow-wrap:anywhere;max-width:320px}.agent-error{color:#a4442c}.agent-controls button:disabled{opacity:.5;cursor:not-allowed}
</style>
