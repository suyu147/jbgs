<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { Check, Eye, FilePlus2, LoaderCircle, Play, Search, Trash2, UploadCloud, UsersRound, X } from 'lucide-vue-next'
import EnterpriseMatchDetail from '@/components/enterprise/EnterpriseMatchDetail.vue'
import { useRoute } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import UiState from '@/components/ui/UiState.vue'
import { insightService } from '@/services/insightService'
import type { EnterpriseAssessmentBatch, EnterpriseAssessmentCandidate, EnterpriseResume, JobSummary } from '@/types/domain'

const route = useRoute()
const resumes = ref<EnterpriseResume[]>([])
const jobs = ref<JobSummary[]>([])
const selectedResumeIds = ref<string[]>([])
const roleId = ref('')
const batch = ref<EnterpriseAssessmentBatch | null>(null)
const activeCandidateId = ref('')
const keyword = ref('')
const loading = ref(true)
const uploading = ref(false)
const assessing = ref(false)
const status = ref('')
const error = ref('')
const fileInput = ref<HTMLInputElement | null>(null)

const filteredResumes = computed(() => resumes.value.filter(item => !keyword.value.trim() || `${item.candidateName}${item.fileName}${item.skills.map(skill => skill.skill_name).join('')}`.toLowerCase().includes(keyword.value.trim().toLowerCase())))
const candidates = computed(() => batch.value?.candidates || [])
const activeCandidate = computed<EnterpriseAssessmentCandidate | null>(() => candidates.value.find(item => item.id === activeCandidateId.value) || candidates.value[0] || null)
const allFilteredSelected = computed(() => filteredResumes.value.length > 0 && filteredResumes.value.every(item => selectedResumeIds.value.includes(item.resumeId)))

async function load() {
  loading.value = true; error.value = ''
  try {
    const [resumeData, jobData, batchData] = await Promise.all([insightService.getEnterpriseResumes(), insightService.getJobs({ pageSize: 100 }), insightService.getEnterpriseAssessments(10)])
    resumes.value = resumeData.items
    jobs.value = jobData.items
    const requestedRole = String(route.query.role || '')
    roleId.value = jobs.value.some(item => item.id === requestedRole) ? requestedRole : roleId.value || jobs.value[0]?.id || ''
    if (batchData.items[0]) {
      batch.value = await insightService.getEnterpriseAssessment(batchData.items[0].id)
      activeCandidateId.value = batch.value.candidates?.[0]?.id || ''
    }
  } catch (reason: any) { error.value = reason.message || '人才库读取失败' }
  finally { loading.value = false }
}

function toggleResume(id: string) { selectedResumeIds.value = selectedResumeIds.value.includes(id) ? selectedResumeIds.value.filter(item => item !== id) : [...selectedResumeIds.value, id] }
function toggleAll() {
  if (allFilteredSelected.value) selectedResumeIds.value = selectedResumeIds.value.filter(id => !filteredResumes.value.some(item => item.resumeId === id))
  else selectedResumeIds.value = [...new Set([...selectedResumeIds.value, ...filteredResumes.value.map(item => item.resumeId)])]
}
async function upload(event: Event) {
  const files = Array.from((event.target as HTMLInputElement).files || [])
  if (files.length > 30) { error.value = '每次最多导入 30 份，请减少文件后重新选择。'; if(fileInput.value) fileInput.value.value=''; return }
  if (files.some(file => !/\.(pdf|docx|txt|md)$/i.test(file.name))) { error.value = '请使用 PDF、DOCX、TXT 或 MD 简历。'; if(fileInput.value) fileInput.value.value=''; return }
  if (!files.length) return
  uploading.value = true; error.value = ''; status.value = ''
  try {
    const result = await insightService.uploadEnterpriseResumes(files)
    status.value = `已导入 ${result.accepted} 份简历${result.rejected.length ? `，${result.rejected.length} 份未通过格式检查` : ''}`
    const data = await insightService.getEnterpriseResumes()
    resumes.value = data.items
    selectedResumeIds.value = result.items.map(item => item.resumeId)
  } catch (reason: any) { error.value = reason.message || '批量导入失败' }
  finally { uploading.value = false; if (fileInput.value) fileInput.value.value = '' }
}
async function preview(item: EnterpriseResume) {
  try { const blob = await insightService.getEnterpriseResumeFile(item.resumeId); const url = URL.createObjectURL(blob); window.open(url, '_blank', 'noopener'); window.setTimeout(() => URL.revokeObjectURL(url), 60_000) }
  catch (reason: any) { error.value = reason.message || '简历预览失败' }
}
async function remove(item: EnterpriseResume) {
  try { await ElMessageBox.confirm(`确认删除“${item.fileName}”？该简历将从企业人才库移除。`, '删除企业简历', {confirmButtonText:'确认删除',cancelButtonText:'取消',type:'warning'}) } catch { return }
  error.value = ''; status.value = ''
  try { await insightService.deleteEnterpriseResume(item.resumeId); resumes.value = resumes.value.filter(row => row.resumeId !== item.resumeId); selectedResumeIds.value = selectedResumeIds.value.filter(id => id !== item.resumeId); status.value = `已删除 ${item.fileName}` }
  catch (reason: any) { error.value = reason.message || '删除失败' }
}
async function assess() {
  if (!roleId.value || !selectedResumeIds.value.length) return
  assessing.value = true; error.value = ''; status.value = ''
  try {
    batch.value = await insightService.createEnterpriseAssessment({ roleId: roleId.value, resumeIds: selectedResumeIds.value })
    activeCandidateId.value = batch.value.candidates?.[0]?.id || ''
    status.value = `已完成 ${batch.value.completedCount} 位候选人的岗位匹配诊断`
  } catch (reason: any) { error.value = reason.message || '批量诊断失败' }
  finally { assessing.value = false }
}

watch(() => route.query.role, value => { if (typeof value === 'string' && jobs.value.some(job => job.id === value)) roleId.value = value })
onMounted(load)
</script>

<template>
  <div class="enterprise-talent">
    <div class="ui-callout"><p>导入简历 → 勾选候选人 → 选择目标岗位 → 批量诊断</p><span>{{ resumes.length }} 份简历 · 已选 {{ selectedResumeIds.length }} 人</span></div>
    <section class="talent-commandbar">
      <div><h2>企业简历库</h2><p>支持 PDF、DOCX、TXT、MD，每次最多导入 30 份</p></div>
      <input ref="fileInput" class="sr-only" aria-label="批量选择简历文件" type="file" multiple accept=".pdf,.docx,.txt,.md" @change="upload" />
      <button class="enterprise-secondary" :disabled="uploading" @click="fileInput?.click()"><LoaderCircle v-if="uploading" class="spin"/><UploadCloud v-else/>{{ uploading ? '正在解析简历' : '批量导入简历' }}</button>
      <label><span>目标岗位</span><el-select aria-label="目标诊断岗位" v-model="roleId" filterable placeholder="选择岗位"><el-option v-for="job in jobs" :key="job.id" :label="job.name" :value="job.id"/></el-select></label>
      <button class="enterprise-primary" :disabled="assessing || !selectedResumeIds.length || !roleId" @click="assess"><LoaderCircle v-if="assessing" class="spin"/><Play v-else/>{{ assessing ? '正在批量诊断' : `诊断已选 ${selectedResumeIds.length} 人` }}</button>
    </section>
    <p v-if="status" class="enterprise-success" role="status"><Check/>{{ status }}<button aria-label="关闭提示" @click="status = ''"><X/></button></p>
    <p v-if="error" class="enterprise-error" role="alert">{{ error }}<button class="ui-link" @click="load">重新读取</button></p>
    <section class="talent-workspace">
      <aside class="resume-library">
        <header><label><Search/><span class="sr-only">搜索候选人、文件或技能</span><input type="search" v-model="keyword" placeholder="搜索候选人、文件或技能" /></label><button @click="toggleAll"><span :class="{ checked: allFilteredSelected }"><Check/></span>{{ allFilteredSelected ? '取消全选' : '全选结果' }}</button></header>
        <div class="resume-table-head"><span>候选人</span><span>识别置信度</span><span>操作</span></div>
        <div class="resume-list">
          <UiState v-if="loading" kind="loading"/>
          <article v-for="item in filteredResumes" :key="item.resumeId" :class="{ selected: selectedResumeIds.includes(item.resumeId) }">
            <button class="resume-check" :aria-label="`${selectedResumeIds.includes(item.resumeId) ? '取消选择' : '选择'} ${item.candidateName}`" :aria-pressed="selectedResumeIds.includes(item.resumeId)" @click="toggleResume(item.resumeId)"><Check/></button>
            <div><strong>{{ item.candidateName }}</strong><small>{{ item.fileName }} · {{ item.skills.length }} 项技能</small></div><b>识别 {{ item.contentConfidence ?? '—' }}%</b>
            <span><button :aria-label="`预览 ${item.candidateName} 的简历`" title="预览简历" @click.stop="preview(item)"><Eye/></button><button :aria-label="`删除 ${item.candidateName} 的简历`" title="删除简历" @click.stop="remove(item)"><Trash2/></button></span>
          </article>
          <div v-if="!loading && !filteredResumes.length" class="resume-empty"><FilePlus2/><strong>{{ resumes.length ? '没有匹配的候选人' : '还没有企业简历' }}</strong><p>{{ resumes.length ? '请调整搜索条件。' : '批量导入简历后即可建立人才库。' }}</p></div>
        </div>
      </aside>
      <main class="assessment-area">
        <template v-if="batch && candidates.length">
          <div class="assessment-summary"><div><small>最近诊断批次</small><strong>{{ batch.roleName }}</strong><span>{{ batch.completedCount }}/{{ batch.candidateCount }} 人已完成 · 平均匹配度 {{ batch.averageScore }}%</span></div><div class="candidate-tabs" aria-label="选择查看的候选人"><button v-for="candidate in candidates" :key="candidate.id" :class="{ active: activeCandidate?.id === candidate.id }" :aria-pressed="activeCandidate?.id === candidate.id" @click="activeCandidateId = candidate.id"><span>{{ candidate.candidateCode }}</span><strong>{{ candidate.result.candidateName || candidate.fileName.replace(/\.[^.]+$/, '') }}</strong><b>{{ candidate.score == null ? '—' : `${candidate.score}%` }}</b></button></div></div>
          <EnterpriseMatchDetail v-if="activeCandidate" :candidate="activeCandidate" />
        </template>
        <div v-else class="assessment-empty"><UsersRound/><h2>批量诊断结果显示在这里</h2><p>从左侧选择一份或多份简历，指定目标岗位后运行诊断。</p><small>结果将按综合匹配度排序，并逐人展示维度得分、能力雷达和技能差距。</small><button class="secondary-btn" style="margin-top:16px" @click="fileInput?.click()">导入第一批简历</button></div>
      </main>
    </section>
  </div>
</template>

<style scoped>
.enterprise-talent{display:grid;gap:14px}.talent-commandbar{min-height:82px;padding:15px 18px;display:flex;align-items:center;gap:12px;background:#fff;border:1px solid #dfeae7;border-radius:8px}.talent-commandbar>div{margin-right:auto}.talent-commandbar h2{margin:0;font-size:17px}.talent-commandbar p{margin:4px 0 0;color:#71807c;font-size:11px}.talent-commandbar label{width:260px;display:grid;gap:4px}.talent-commandbar label>span{font-size:10px;color:#72817d}.enterprise-primary,.enterprise-secondary{min-height:40px;padding:0 14px;display:flex;align-items:center;justify-content:center;gap:7px;border-radius:6px;font-weight:700}.enterprise-primary{background:#0f9d8f;color:#fff}.enterprise-primary:hover{background:#0b8177}.enterprise-primary:disabled,.enterprise-secondary:disabled{opacity:.5;cursor:not-allowed}.enterprise-secondary{background:#fff;color:#17665e;border:1px solid #a9cbc5}.enterprise-primary svg,.enterprise-secondary svg{width:16px}.enterprise-success,.enterprise-error{margin:0;padding:10px 13px;display:flex;align-items:center;gap:8px;font-size:12px}.enterprise-success{background:#eaf8f2;border-color:#10b981;color:#28684f}.enterprise-error{background:#fff1ec;border-color:#e86a3f;color:#8a3f28}.enterprise-success>svg{width:15px}.enterprise-success button{margin-left:auto;background:none;color:inherit}.enterprise-success button svg{width:14px}.talent-workspace{min-height:650px;display:grid;grid-template-columns:420px minmax(0,1fr);background:#fff;border:1px solid #dfeae7;border-radius:8px;overflow:hidden}.resume-library{min-width:0;border-right:1px solid #e2ebe9}.resume-library>header{padding:14px;display:flex;gap:8px;border-bottom:1px solid #e2ebe9}.resume-library>header label{height:36px;min-width:0;flex:1;padding:0 10px;display:flex;align-items:center;gap:6px;background:#f4f8f7;border:1px solid #e0e9e7;border-radius:6px}.resume-library>header label svg{width:14px;color:#71817d}.resume-library>header input{min-width:0;flex:1;border:0;outline:0;background:none;font-size:11px}.resume-library>header>button{display:flex;align-items:center;gap:5px;background:none;color:#526863;font-size:10px}.resume-library>header>button span,.resume-check{width:18px;height:18px;display:grid;place-items:center;border:1px solid #b9cbc7;border-radius:4px;background:#fff;color:transparent}.resume-library>header>button span.checked,.selected .resume-check{background:#0f9d8f;border-color:#0f9d8f;color:#fff}.resume-library>header>button svg,.resume-check svg{width:12px}.resume-table-head{height:34px;padding:0 14px 0 48px;display:grid;grid-template-columns:minmax(0,1fr) 72px 60px;align-items:center;background:#f8faf9;color:#80908b;font-size:9px}.resume-list{max-height:650px;overflow:auto}.resume-list article{min-height:70px;padding:10px 13px;display:grid;grid-template-columns:22px minmax(0,1fr) 58px 56px;align-items:center;gap:8px;border-top:1px solid #edf1f0;cursor:pointer}.resume-list article:hover{background:#f7faf9}.resume-list article.selected{background:#eef8f6;box-shadow:inset 3px 0 #0f9d8f}.resume-check{padding:0}.resume-list article>div{min-width:0;display:grid}.resume-list article strong,.resume-list article small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.resume-list article strong{font-size:12px}.resume-list article small{margin-top:3px;color:#82908c;font-size:9px}.resume-list article>b{color:#e86a3f;font-size:12px;font-variant-numeric:tabular-nums}.resume-list article>span{display:flex}.resume-list article>span button{width:27px;height:27px;display:grid;place-items:center;background:transparent;color:#70817d}.resume-list article>span button:hover{background:#e4f1ee;color:#0b8177}.resume-list article>span button:last-child:hover{background:#fff0ec;color:#b4553d}.resume-list article>span svg{width:13px}.resume-empty,.assessment-empty{display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;color:#74837f}.resume-empty{min-height:260px}.resume-empty svg{width:34px;color:#9fb3ae}.resume-empty strong{margin-top:12px}.resume-empty p{margin:5px 0;font-size:11px}.assessment-area{min-width:0}.assessment-summary{min-height:94px;padding:14px 18px;display:grid;grid-template-columns:220px minmax(0,1fr);gap:14px;background:#f7faf9;border-bottom:1px solid #e2ebe9}.assessment-summary>div:first-child{display:grid;align-content:center}.assessment-summary small{color:#788783;font-size:10px}.assessment-summary>div:first-child strong{font-size:14px}.assessment-summary>div:first-child span{color:#71807c;font-size:10px}.candidate-tabs{display:flex;gap:7px;overflow-x:auto}.candidate-tabs button{min-width:128px;padding:8px 10px;display:grid;grid-template-columns:1fr auto;text-align:left;background:#fff;border:1px solid #dfe8e6;border-radius:5px;color:#52645f}.candidate-tabs button.active{border-color:#0f9d8f;box-shadow:inset 0 -2px #0f9d8f}.candidate-tabs button span{grid-column:1/-1;color:#8b9794;font-size:8px}.candidate-tabs button strong{max-width:90px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:10px}.candidate-tabs button b{color:#0b8177;font-size:11px}.assessment-empty{min-height:640px}.assessment-empty svg{width:48px;color:#9cb4ae}.assessment-empty h2{margin:15px 0 4px;font-size:18px}.assessment-empty p{margin:0;font-size:12px}.assessment-empty small{margin-top:9px;color:#95a09d;font-size:10px}.sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)}.spin{animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
@media(max-width:1180px){.talent-workspace{grid-template-columns:350px minmax(0,1fr)}.talent-commandbar{flex-wrap:wrap}.talent-commandbar>div{width:100%}}
@media(max-width:820px){.talent-workspace{display:block}.resume-library{border-right:0;border-bottom:1px solid #e2ebe9}.resume-list{max-height:360px}.talent-commandbar label{width:min(100%,260px)}.assessment-summary{grid-template-columns:1fr}.assessment-empty{min-height:360px}}
</style>
