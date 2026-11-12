<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { Archive, Briefcase, Check, Edit3, ExternalLink, Eye, FilePenLine, RefreshCw, Rocket, Save, TrendingUp, X } from 'lucide-vue-next'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { useBusinessUnsaved } from '@/composables/useBusinessUnsaved'
import UiState from '@/components/ui/UiState.vue'
import { insightService } from '@/services/insightService'
import type { AgentDescriptionData, DescriptionMissing, ReviewItem } from '@/types/domain'

const items = ref<ReviewItem[]>([])
const versions = ref<Array<Record<string, any>>>([])
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const editing = ref<ReviewItem | null>(null)
const description = ref<AgentDescriptionData | DescriptionMissing | null>(null)
const descriptionLoading = ref(false), descriptionSaving = ref(false), pipelineEnabled = ref(false)
const descriptionError = ref('')
const descriptionReasons: Record<string, string> = { disabled: '岗位描述生成未开启', not_generated: '岗位描述尚未生成', draft_changed: '生成期间草稿发生变更，请重新生成', frozen: '草稿已冻结，无法生成描述' }
const availableDescription = computed(() => description.value && 'markdown' in description.value ? description.value : null)
const missingDescription = computed(() => description.value && 'reason' in description.value ? descriptionReasons[description.value.reason] : '')
async function loadDescription(id: string) {
  descriptionLoading.value = true; descriptionError.value = ''
  try {
    const result = await insightService.getDraftDescription(id)
    if (editing.value?.id === id) description.value = result
  } catch (reason: any) { if (editing.value?.id === id) descriptionError.value = reason.message || '描述读取失败' }
  finally { if (editing.value?.id === id) descriptionLoading.value = false }
}
async function regenerateDescription() {
  if (!editing.value || descriptionSaving.value) return
  if (editorDirty.value) { ElMessage.warning('请先保存草稿修改，再重新打开并生成描述'); return }
  const id = editing.value.id
  descriptionSaving.value = true
  try {
    const result = await insightService.regenerateDraftDescription(id)
    if (result.status === 'skipped') ElMessage.warning(descriptionReasons[result.reason || ''] || '本次生成已跳过，请稍后重试')
    await loadDescription(id)
  } catch (reason: any) { ElMessage.error(reason.message || '重生成失败') }
  finally { descriptionSaving.value = false }
}
async function downloadDescription(format: 'md' | 'docx') {
  if (!editing.value) return
  try {
    const blob = await insightService.downloadDraftDescription(editing.value.id, format)
    const url = URL.createObjectURL(blob), link = document.createElement('a')
    link.href = url; link.download = `${editing.value.roleName}.${format}`; link.click(); URL.revokeObjectURL(url)
  } catch (reason: any) { ElMessage.error(reason.message || '下载失败') }
}
const versionDetail = ref<Record<string, any> | null>(null)
const versionDetailLoading = ref(false)
type ReviewCategory = 'new_role' | 'definition_update' | 'skill_change'
const route = useRoute(), router = useRouter()
const activeCategory = ref<ReviewCategory>(['new_role','definition_update','skill_change'].includes(String(route.query.category)) ? route.query.category as ReviewCategory : 'new_role')
const reviewPage = ref(Math.max(1, Number(route.query.page) || 1))
watch([activeCategory, reviewPage], ([category],[oldCategory]) => {
  if(category !== oldCategory) reviewPage.value = 1
  void router.replace({query:{...route.query,category,page:String(reviewPage.value)}})
})
watch(() => [route.query.category, route.query.page], ([category,page]) => { if(['new_role','definition_update','skill_change'].includes(String(category))) activeCategory.value=category as ReviewCategory; reviewPage.value=Math.max(1, Number(page)||1) })
const form = reactive({ publicationTitle: '', responsibilities: '', requiredSkills: '', bonusSkills: '', scenarios: '', note: '' })
const editorBaseline = ref('')
const editorDirty = computed(() => Boolean(editing.value) && JSON.stringify(form) !== editorBaseline.value)
useBusinessUnsaved(editorDirty)
function confirmEditorClose(done?: () => void) {
 if(saving.value) return
 if(editorDirty.value && !window.confirm('有尚未保存的复核修改，确认关闭并放弃？')) return
 editing.value=null; done?.()
}
const editingIsRole = computed(() => ['new_role', 'definition_update'].includes(editing.value?.candidateType || ''))
const changeCandidates = computed(() => items.value.filter(item => item.candidateType === 'skill_change').length)
const evidenceTotal = computed(() => items.value.reduce((sum, item) => sum + item.evidence.length, 0))
const dataBackedCandidates = computed(() => items.value.filter(item => item.evidenceClass === 'data_backed').length)
const reviewCategories = computed(() => [
  { value: 'new_role' as const, label: '新岗位发现', icon: Briefcase, count: items.value.filter(item => item.candidateType === 'new_role').length },
  { value: 'definition_update' as const, label: '岗位定义更新', icon: FilePenLine, count: items.value.filter(item => item.candidateType === 'definition_update').length },
  { value: 'skill_change' as const, label: '能力变化', icon: TrendingUp, count: items.value.filter(item => item.candidateType === 'skill_change').length },
])
const activeCategoryMeta = computed(() => reviewCategories.value.find(item => item.value === activeCategory.value)!)
const filteredItems = computed(() => items.value.filter(item => item.candidateType === activeCategory.value))
const pagedItems = computed(() => filteredItems.value.slice((reviewPage.value-1)*6, reviewPage.value*6))
const reviewPageCount = computed(() => Math.max(1, Math.ceil(filteredItems.value.length/6)))
const displayVersions = computed(() => {
  const priority: Record<string, number> = { published: 3, approved: 2, withdrawn: 1 }
  const latest = new Map<string, Record<string, any>>()
  for (const version of versions.value) {
    const key = String(version.roleId || version.roleName || version.id)
    const current = latest.get(key)
    if (!current || (priority[version.status] || 0) > (priority[current.status] || 0)) latest.set(key, version)
  }
  return [...latest.values()].sort((a, b) => {
    const timestamp = (item: Record<string, any>) => Date.parse(item.publishedAt || item.updatedAt || '') || 0
    return timestamp(b) - timestamp(a) || String(a.roleName).localeCompare(String(b.roleName))
  })
})
async function load() {
  loading.value = true
  error.value = ''
  try {
    const [reviewItems, versionData] = await Promise.all([insightService.getReviews('pending'), insightService.getVersions()])
    items.value = reviewItems
    versions.value = versionData.items || []
  } catch (e: any) { error.value = e.message } finally { loading.value = false }
}

function names(values: any[] = []) { return values.map(item => typeof item === 'string' ? item : item.skill_name || item.scenario || '').filter(Boolean).join('\n') }
function openEditor(item: ReviewItem) {
  editing.value = item
  description.value = null
  if (pipelineEnabled.value) void loadDescription(item.id)
  form.publicationTitle = item.definition.publication_title || (item.candidateType === 'new_role' ? '新岗位发现' : item.candidateType === 'definition_update' ? '岗位定义更新' : '岗位能力变化')
  form.responsibilities = names(item.definition.core_responsibilities)
  form.requiredSkills = names(item.definition.required_skills)
  form.bonusSkills = names(item.definition.bonus_skills)
  form.scenarios = names(item.definition.application_scenarios)
  form.note = ''
  editorBaseline.value = JSON.stringify(form)
}
function lines(value: string) { return value.split(/\r?\n|[,，]/).map(item => item.trim()).filter(Boolean) }
function buildDefinition(item: ReviewItem) {
  const originalSkills = [...(item.definition.required_skills || []), ...(item.definition.bonus_skills || [])]
  const skill = (name: string) => originalSkills.find((entry: any) => entry.skill_name === name) || { skill_id: '', skill_name: name, evidence: '人工复核补充', evidence_count: 0, posting_penetration: 0 }
  const originalScenarios = item.definition.application_scenarios || []
  return {
    ...item.definition,
    publication_title: form.publicationTitle.trim(),
    core_responsibilities: lines(form.responsibilities),
    required_skills: lines(form.requiredSkills).map(skill),
    bonus_skills: lines(form.bonusSkills).map(skill),
    application_scenarios: lines(form.scenarios).map(name => originalScenarios.find((entry: any) => entry.scenario === name) || { scenario: name, evidence_count: 0 }),
    definition_status: 'human_reviewed',
  }
}
async function saveDefinition() {
  if (!editing.value || saving.value) return
  saving.value = true
  try {
    const definition = editingIsRole.value ? buildDefinition(editing.value) : editing.value.definition
    await insightService.review(editing.value.id, { action: 'update', note: form.note || '管理台人工修改岗位定义', definition })
    ElMessage.success('岗位定义已保存，候选仍处于待复核状态')
    editing.value = null
    await load()
  } catch (reason: any) { ElMessage.error(reason.message || '保存失败，请重试') } finally { saving.value = false }
}
async function act(item: ReviewItem, action: 'approve' | 'reject') {
  try {
    await ElMessageBox.confirm(`确认${action === 'approve' ? '批准' : '驳回'}“${item.roleName}”？操作会保留审计记录。`, '人工复核', { confirmButtonText: '确认', cancelButtonText: '取消', type: action === 'approve' ? 'success' : 'warning' })
  } catch { return }
  if (saving.value) return
  saving.value = true
  try {
  const definition = editing.value?.id === item.id && editingIsRole.value ? buildDefinition(item) : item.definition
  await insightService.review(item.id, { action, note: form.note || '本地管理台人工复核', definition })
  editing.value = null
  ElMessage.success(action === 'approve' ? '已批准并生成待发布版本' : '已驳回候选')
  await load()
  } catch (reason: any) { ElMessage.error(reason.message || '复核未完成，请重试') } finally { saving.value = false }
}
async function publish(versionId: string) {
  if (saving.value) return
  try { await ElMessageBox.confirm('确认发布此版本？发布后会更新正式岗位库与知识图谱，并保留审计记录。', '发布岗位版本', {confirmButtonText:'确认发布',cancelButtonText:'取消',type:'warning'}) } catch { return }
  saving.value = true
  try {
  await insightService.publishVersion(versionId)
  ElMessage.success('岗位定义版本已发布，岗位库与知识图谱已同步更新')
  await load()
  } catch (reason: any) { ElMessage.error(reason.message || '发布失败，请重试') } finally { saving.value = false }
}
async function unpublish(version: Record<string, any>) {
  if (saving.value) return
  try {
    await ElMessageBox.confirm(`确认下架“${version.roleName}”的当前版本？版本与审计历史会保留，可再次发布或生成更新草稿。`, '下架岗位定义', { confirmButtonText: '确认下架', cancelButtonText: '取消', type: 'warning' })
  } catch { return }
  saving.value = true
  try {
    await insightService.unpublishVersion(version.id)
    ElMessage.success('岗位定义版本已下架，历史记录仍可追溯')
    await load()
  } catch (reason: any) { ElMessage.error(reason.message || '下架失败，请重试') } finally { saving.value = false }
}
async function createUpdate(version: Record<string, any>) {
  if (saving.value) return
  saving.value = true
  try {
  const result = await insightService.createVersionDraft(version.id)
  await load()
  const draft = items.value.find(item => item.id === result.draftId)
  if (draft) openEditor(draft)
  ElMessage.success(result.created ? '已创建更新草稿，请修改后重新复核发布' : '已打开尚未提交的更新草稿')
  } catch (reason: any) { ElMessage.error(reason.message || '创建草稿失败，请重试') } finally { saving.value = false }
}
async function openVersionDetail(version: Record<string, any>) {
  versionDetail.value = version
  versionDetailLoading.value = true
  try { versionDetail.value = await insightService.getVersion(version.id) }
  catch (e: any) { ElMessage.error(e.message || '版本详情读取失败') }
  finally { versionDetailLoading.value = false }
}
function closeVersionDetail() { versionDetail.value = null }
function versionLabel(status: string) {
  return { published: '已发布', approved: '已批准待发布', withdrawn: '已下架' }[status] || status
}
const labelMap: Record<string, string> = { enterprise_name: '提交企业', enterprise_contact: '企业联系人', location: '招聘城市', job_category: '岗位族', first_seen: '首次出现', latest_seen: '最近出现', posting_count: '招聘名额', source_count: '数据来源', candidate_reason: '候选依据', core_responsibilities: '核心职责', required_skills: '必备技能', bonus_skills: '加分技能', application_scenarios: '应用场景', changes: '变化项' }
function preview(value: any) {
  if (Array.isArray(value)) return `${value.length} 项`
  if (value === 'human_review_required') return '待人工确认'
  if (typeof value === 'string' && value.startsWith('recent_first_seen')) return '近期首现并具有多来源招聘证据'
  if (value === 'recent_first_seen_multi_source_minimum_5_postings_plus_emerging_term') return '多来源、近期首现且含新兴技术词'
  return value
}
onMounted(async () => {
  void load()
  try { pipelineEnabled.value = (await insightService.getAgentPipelineStatus()).enabled } catch { pipelineEnabled.value = false }
})
</script>

<template>
  <div class="stack-lg">
    <section class="review-summary"><div><h2>人工复核与版本管理</h2><p>人工确认后才可形成版本并发布到正式图谱。</p></div><div class="review-summary-actions"><span class="pending-total">{{ items.length }} <small>待处理</small></span><button class="secondary-btn" @click="load"><RefreshCw :size="16" />刷新</button></div></section>
    <section class="admin-kpi-strip review-kpis" aria-label="候选复核概览">
      <article><span>待复核候选</span><strong>{{ items.length }}</strong><small>全部候选</small></article>
      <article><span>真实证据候选</span><strong>{{ dataBackedCandidates }}</strong><small>跨来源招聘记录</small></article>
      <article><span>能力变化类</span><strong>{{ changeCandidates }}</strong><small>技能需求变化</small></article>
      <article><span>证据记录</span><strong>{{ evidenceTotal }}</strong><small>可供人工核验</small></article>
    </section>
    <UiState v-if="error" kind="error" title="候选读取失败" :description="error" action="重新加载" @action="load"/><UiState v-if="loading && !items.length" kind="loading"/>
    <section v-if="versions.length" class="panel version-strip">
      <div><h2>岗位定义版本</h2></div>
      <div class="version-list"><article v-for="version in displayVersions" :key="version.id"><div><span class="release-kind">{{ version.displayTitle || '岗位定义发布' }}</span><strong>{{ version.roleName }}</strong><small>{{ version.sourceCount || 0 }} 个来源 · {{ version.evidenceCount || 0 }} 条证据</small></div><em :class="['status-chip', version.status]">{{ versionLabel(version.status) }}</em><div class="version-actions"><button class="secondary-btn" title="查看版本定义与来源证据" @click="openVersionDetail(version)"><Eye :size="15" />详情</button><button v-if="version.status !== 'approved'" class="secondary-btn" :disabled="saving" title="基于此版本创建更新草稿" @click="createUpdate(version)"><Edit3 :size="15" />更新</button><button v-if="version.status === 'published'" class="reject-btn" :disabled="saving" title="下架并保留历史" @click="unpublish(version)"><Archive :size="15" />下架</button><button v-if="version.status === 'approved' || version.status === 'withdrawn'" class="primary-btn" :disabled="saving" @click="publish(version.id)"><Rocket :size="15" />{{ version.status === 'withdrawn' ? '重新发布' : '发布' }}</button></div></article></div>
    </section>
    <section class="review-category-panel panel" aria-label="候选类型切换">
      <div class="review-category-tabs" role="group" aria-label="候选类型">
        <button v-for="category in reviewCategories" :key="category.value" :class="{ active: activeCategory === category.value }" type="button" :aria-pressed="activeCategory === category.value" @click="activeCategory = category.value">
          <component :is="category.icon" :size="18" />
          <span>{{ category.label }}</span>
          <b>{{ category.count }}</b>
        </button>
      </div>
    </section>
    <section class="review-grid" aria-label="待处理候选">
      <article v-for="item in pagedItems" :key="item.id" class="panel review-card"><div class="review-card-head"><small>{{ item.id.slice(-8) }}</small><span v-if="item.definition.source_type === 'enterprise_job_submission'" class="enterprise-source-label">企业 HR 提交</span></div><h2>{{ item.roleName }}</h2><p v-if="item.definition.source_type === 'enterprise_job_submission'" class="enterprise-review-summary">{{ item.definition.enterprise_name }} · {{ item.definition.location || '招聘城市待确认' }} · 招聘 {{ item.definition.posting_count || 1 }} 人</p><dl><div v-for="(value, key) in item.definition" v-show="labelMap[String(key)]" :key="key"><dt>{{ labelMap[String(key)] }}</dt><dd>{{ preview(value) }}</dd></div></dl><div class="review-actions"><button class="secondary-btn" @click="openEditor(item)"><Edit3 :size="16" />{{ ['new_role', 'definition_update'].includes(item.candidateType) ? '编辑定义' : '查看证据' }}</button><button class="reject-btn" :disabled="saving" @click="act(item, 'reject')"><X :size="16" />驳回</button><button class="primary-btn" :disabled="saving" @click="act(item, 'approve')"><Check :size="16" />批准</button></div></article>
      <div v-if="!loading && !filteredItems.length" class="empty-state panel"><Check /><h2>暂无{{ activeCategoryMeta.label }}候选</h2><p>新的候选会在完成规则识别后进入此分类。</p></div>
    </section>
    <div v-if="filteredItems.length" class="review-pagination"><span>共 {{ filteredItems.length }} 项候选 · 第 {{ reviewPage }} / {{ reviewPageCount }} 页</span><div class="ui-toolbar"><button class="secondary-btn" :disabled="reviewPage <= 1" @click="reviewPage--">上一页</button><button class="secondary-btn" :disabled="reviewPage >= reviewPageCount" @click="reviewPage++">下一页</button></div></div>
    <el-drawer :before-close="confirmEditorClose" :model-value="Boolean(editing)" size="min(620px, 92vw)" title="候选定义与来源证据" :with-header="false" @close="editing = null">
      <div v-if="editing" class="definition-editor">
        <header><div><h2>{{ editing.roleName }}</h2><p>{{ editingIsRole ? '逐项核对岗位定义，保存不会自动发布。' : '核对变化信号与统计限制后再作决定。' }}</p></div><button class="icon-btn" aria-label="关闭详情面板" title="关闭" @click="confirmEditorClose()"><X :size="18" /></button></header>
        <template v-if="editingIsRole"><label><span>版本发布标题</span><input v-model="form.publicationTitle" maxlength="24" placeholder="例如：新岗位发现" name="publicationTitle" autocomplete="off" /></label><label><span>核心职责</span><textarea v-model="form.responsibilities" rows="6" placeholder="每行一项核心职责" name="responsibilities" autocomplete="off" /></label><div class="editor-columns"><label><span>必备技能</span><textarea v-model="form.requiredSkills" rows="7" placeholder="每行一项技能" name="requiredSkills" autocomplete="off" /></label><label><span>加分技能</span><textarea v-model="form.bonusSkills" rows="7" placeholder="每行一项技能" name="bonusSkills" autocomplete="off" /></label></div><label><span>典型行业应用场景</span><textarea v-model="form.scenarios" rows="5" placeholder="每行一个场景" name="scenarios" autocomplete="off" /></label></template>
        <section v-else class="change-evidence"><article v-for="change in editing.definition.changes" :key="change.skill_id"><strong>{{ change.skill_name }}</strong><b>{{ change.change_pp > 0 ? '+' : '' }}{{ change.change_pp }} pp</b><small>{{ change.analysis_note }}</small></article></section>
        <label><span>复核备注</span><textarea v-model="form.note" rows="3" placeholder="记录修改依据或判断理由" name="note" autocomplete="off" /></label>
        <section class="evidence-records"><div><b>{{ editing.evidence.length }} 条</b></div><article v-for="record in editing.evidence.slice(0, 6)" :key="record.recordId || record.period"><strong>{{ record.source || record.type }}</strong><small>{{ record.period }} · {{ record.recordId || '聚合证据' }}</small><p>{{ record.excerpt }}</p></article></section>
        <section v-if="pipelineEnabled" class="agent-description">
          <header><h3>岗位描述</h3><button v-if="editing.status === 'pending'" class="secondary-btn" :disabled="descriptionSaving || descriptionLoading" @click="regenerateDescription">{{ descriptionSaving ? '正在生成…' : '重新生成' }}</button></header>
          <p v-if="descriptionLoading" role="status">正在读取描述…</p>
          <p v-if="descriptionError" role="alert">{{ descriptionError }} <button class="secondary-btn" @click="loadDescription(editing.id)">重试</button></p>
          <p v-if="missingDescription">{{ missingDescription }}</p>
          <template v-if="availableDescription"><p v-if="availableDescription.stale" class="description-stale">草稿已变更，描述可能过期</p><small>{{ availableDescription.provider === 'rules' ? '规则模板' : 'DeepSeek' }} · {{ availableDescription.generatedAt.replace('T', ' ') }}</small><pre>{{ availableDescription.markdown }}</pre><div class="description-downloads"><button class="secondary-btn" @click="downloadDescription('md')">下载 Markdown</button><button class="secondary-btn" @click="downloadDescription('docx')">下载 Word</button></div></template>
        </section>
        <footer><button class="reject-btn" @click="act(editing, 'reject')"><X :size="16" />驳回</button><button v-if="editingIsRole" class="secondary-btn" :disabled="saving" @click="saveDefinition"><Save :size="16" />保存草稿</button><button class="primary-btn" :disabled="saving" @click="act(editing, 'approve')"><Check :size="16" />批准并生成版本</button></footer>
      </div>
    </el-drawer>
    <el-drawer :model-value="Boolean(versionDetail)" size="min(680px, 94vw)" title="岗位版本详情" :with-header="false" @close="closeVersionDetail">
      <div v-if="versionDetail" class="definition-editor version-detail-drawer">
        <header><div><h2>{{ versionDetail.roleName }}</h2><p>{{ versionDetail.displayTitle }} · {{ versionLabel(versionDetail.status) }}</p></div><button class="icon-btn" aria-label="关闭详情面板" title="关闭" @click="closeVersionDetail"><X :size="18" /></button></header>
        <div v-if="versionDetailLoading" class="forecast-loading"><RefreshCw class="spin" />正在读取版本详情…</div>
        <template v-else>
          <section class="version-detail-metrics"><div><span>招聘记录</span><strong>{{ versionDetail.postingCount || 0 }}</strong></div><div><span>数据来源</span><strong>{{ versionDetail.sourceCount || 0 }}</strong></div><div><span>证据记录</span><strong>{{ versionDetail.evidenceCount || 0 }}</strong></div><div><span>版本状态</span><strong>{{ versionLabel(versionDetail.status) }}</strong></div></section>
          <section class="signal-detail-section"><h3>核心职责</h3><ul><li v-for="item in versionDetail.definition?.core_responsibilities || []" :key="typeof item === 'string' ? item : item.responsibility">{{ typeof item === 'string' ? item : item.responsibility }}</li></ul></section>
          <section class="signal-detail-section"><h3>岗位能力</h3><div class="signal-skill-groups"><div><span>必备技能</span><em v-for="item in versionDetail.definition?.required_skills || []" :key="typeof item === 'string' ? item : item.skill_name">{{ typeof item === 'string' ? item : item.skill_name }}</em></div><div><span>加分技能</span><em v-for="item in versionDetail.definition?.bonus_skills || []" :key="typeof item === 'string' ? item : item.skill_name">{{ typeof item === 'string' ? item : item.skill_name }}</em></div></div></section>
          <section class="signal-detail-section"><h3>来源证据</h3><article v-for="record in versionDetail.evidence || []" :key="record.recordId || `${record.source}-${record.period}`" class="signal-evidence-row"><div><strong>{{ record.source || record.type || '来源记录' }}</strong><small>{{ record.period || '时间未知' }} · {{ record.recordId || '聚合证据' }}</small></div><p>{{ record.excerpt || '该记录用于岗位定义复核。' }}</p><a v-if="record.url" :href="record.url" target="_blank" rel="noopener noreferrer">打开来源<ExternalLink /></a></article><p v-if="!versionDetail.evidence?.length" class="empty-note">该历史版本未关联明细来源，聚合证据数量仍保留在版本定义中。</p></section>
        </template>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.agent-description{padding:16px 0;border-top:1px solid #e3ebe9}.agent-description header,.description-downloads{display:flex;align-items:center;justify-content:space-between;gap:12px}.description-downloads{justify-content:flex-start;flex-wrap:wrap}.agent-description h3{margin:0;font-size:15px}.agent-description pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit;line-height:1.8;max-height:440px;overflow:auto;padding:12px;background:#f4f8f7}.agent-description small{color:#75837f}.description-stale{color:#a85b22;background:#fff4e9;padding:10px}
.review-card-head{display:flex;align-items:center;justify-content:space-between}.enterprise-source-label{padding:3px 7px;border-radius:4px;background:#e8f6f3;color:#0b8177;font-size:10px;font-weight:700}.enterprise-review-summary{margin:-4px 0 12px;padding:8px 10px;background:#f2f8f7;color:#5f6f6b;font-size:11px}
</style>
