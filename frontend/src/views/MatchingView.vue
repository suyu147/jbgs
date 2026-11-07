<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRoute, useRouter } from 'vue-router'
import { Bot, Brain, Check, CircleCheck, CircleHelp, Download, ExternalLink, FileText, GitBranch, LoaderCircle, Route, Target, TrendingUp, Upload, X } from 'lucide-vue-next'
import { insightService } from '@/services/insightService'
import type { EvolutionData, GraphData, JobSummary } from '@/types/domain'
import { useWorkspaceStore } from '@/stores/workspace'
import CapabilityRadarChart from '@/components/charts/CapabilityRadarChart.vue'

const route = useRoute(); const router = useRouter(); const workspace = useWorkspaceStore()
const { skills, education, experienceYears: experience, resume, resumeConfirmed, workStyleAssessment, matchResult: result, learningPath: path } = storeToRefs(workspace)
const jobs = ref<JobSummary[]>([])
const roleId = computed({get:()=>workspace.targetRoleId,set:id=>{const job=jobs.value.find(item=>item.id===id);workspace.selectTarget(id,job?.name||id)}})
const input = ref('')
const recommendations = ref<Array<{ roleId: string; roleName: string; score: number; topGaps: string[] }>>([])
const graphPreview = ref<GraphData | null>(null)
const evolutionPreview = ref<EvolutionData | null>(null)
const loading = ref(false)
const contextLoading = ref(false)
const exporting = ref<'' | 'pdf' | 'csv'>('')
const error = ref('')
const useMyResume = ref(Boolean(resume.value))
const diagnosisHint = computed(() => !roleId.value ? '先选择你想了解的目标岗位。' : !skills.value.length ? '上传简历，或手动添加至少一项已掌握技能。' : useMyResume.value && resume.value && !resumeConfirmed.value ? '请先核对并确认简历解析结果。' : '信息已准备好，可以开始诊断。')

const matched = computed(() => result.value?.gaps.filter(gap => gap.status === 'matched') || [])
const missing = computed(() => result.value?.gaps.filter(gap => gap.status !== 'matched') || [])
const graphSkills = computed(() => graphPreview.value?.nodes.filter(node=>node.type==='skill').slice(0,8) || [])
const workStyleScore = computed(() => Math.round(Object.values(workStyleAssessment.value).reduce((sum, value) => sum + Number(value), 0) / 4))
const workStyleItems = [
  { key: 'collaboration' as const, label: '沟通协作' },
  { key: 'adaptability' as const, label: '学习适应' },
  { key: 'resilience' as const, label: '抗压执行' },
  { key: 'initiative' as const, label: '主动推进' },
]
const radarMetricDefinitions = [
  { name:'技能', description:'按当前岗位要求的技能及其重要程度，衡量个人已掌握技能的匹配情况。' },
  { name:'经验', description:'将个人工作年限与当前岗位的典型经验要求放在统一量尺上比较。' },
  { name:'学历', description:'比较个人最高学历与当前岗位招聘证据中的学历要求。' },
  { name:'能力广度', description:'衡量当前岗位涉及的多项有效技能中，个人已经覆盖了多少，不等同于单项技能深度。' },
  { name:'综合素养', description:'结合沟通协作、学习适应、抗压执行和主动推进自评，与岗位综合要求进行比较。' },
]

let profileRefreshSequence = 0

function applyProfileDefaults(profile: { education?: string; experienceYears?: number }) {
  if (!education.value && profile.education) education.value = profile.education
  if (experience.value === undefined && profile.experienceYears !== undefined) experience.value = profile.experienceYears
}

watch([education, experience], (next, previous, onCleanup) => {
  if (next[0] === previous[0] && next[1] === previous[1]) return
  if (!result.value || !roleId.value) return
  if (useMyResume.value && resume.value && !resumeConfirmed.value) return
  const timer = window.setTimeout(() => { void refreshProfileMatch() }, 80)
  onCleanup(() => window.clearTimeout(timer))
})

watch(roleId, (next, previous, onCleanup) => {
  if (!next || next === previous || !result.value) return
  if (useMyResume.value && resume.value && !resumeConfirmed.value) return
  const timer = window.setTimeout(() => { void refreshProfileMatch(true) }, 60)
  onCleanup(() => window.clearTimeout(timer))
})

onMounted(async () => {
  applyProfileDefaults(workspace.profile)
  const [data, storedProfile] = await Promise.all([
    insightService.getJobs({ pageSize: 100, location: workspace.location }),
    insightService.isProductPreview()
      ? Promise.resolve(null)
      : insightService.getWorkspaceProfile().catch(() => null),
  ])
  if (storedProfile) {
    workspace.updateProfile(storedProfile.profile)
    applyProfileDefaults(storedProfile.profile)
  }
  jobs.value = data.items
  const requested = String(route.query.roleId || '')
  if (route.query.resume === 'mine' && resume.value) useMyResume.value = true
  if (requested) roleId.value = requested
  else if (!roleId.value && data.items.length) roleId.value = data.items[0].id
  if (result.value?.reportId && result.value.roleId === roleId.value) await loadContext()
})

function addSkill() {
  const value = input.value.trim()
  if (value && !skills.value.includes(value)) skills.value.push(value)
  input.value = ''
}

async function upload(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  loading.value = true; error.value = ''
  try {
    const parsed = await insightService.uploadResume(file)
    resume.value = { ...parsed, fileName: file.name, uploadedAt: new Date().toISOString() }
    resumeConfirmed.value = false
    useMyResume.value = true
    skills.value = resume.value.skills.map(skill => skill.skill_name)
    education.value = resume.value.education
    experience.value = resume.value.experienceYears
  } catch (reason: any) { error.value = reason.message } finally { loading.value = false }
}

async function confirmResume() {
  if (!resume.value) return
  loading.value = true; error.value = ''
  try {
    await insightService.confirmResume(resume.value.resumeId, { skills: skills.value, education: education.value, experienceYears: experience.value, certificates: resume.value.certificates || [] })
    resumeConfirmed.value = true
  } catch (reason: any) { error.value = reason.message } finally { loading.value = false }
}

async function recommend() {
  if (!skills.value.length) return
  loading.value = true; error.value = ''
  try { recommendations.value = (await insightService.recommendRoles(skills.value)).items }
  catch (reason: any) { error.value = reason.message }
  finally { loading.value = false }
}

function selectRecommendation(item: { roleId: string; roleName: string }) {
  if (!jobs.value.some(job => job.id === item.roleId)) jobs.value.push({id:item.roleId,name:item.roleName,field:'',postingCount:0,sourceCount:0,firstSeen:'',lastSeen:'',skills:[]})
  workspace.selectTarget(item.roleId, item.roleName)
  recommendations.value = []
}

async function loadContext() {
  if (!roleId.value) return
  contextLoading.value = true
  try {
    ;[graphPreview.value, evolutionPreview.value] = await Promise.all([
      insightService.getGraph({roleId:roleId.value,limit:40}),
      insightService.getTrends(roleId.value,'year'),
    ])
  } finally { contextLoading.value = false }
}

async function run() {
  if (useMyResume.value && resume.value && !resumeConfirmed.value) { error.value = '请先确认“我的简历”解析结果'; return }
  loading.value = true; error.value = ''
  try {
    const matchedResult = await insightService.matchSkills({targetRoleId:roleId.value,skills:skills.value,education:education.value,experienceYears:experience.value,resumeId:useMyResume.value?resume.value?.resumeId||'':'',workStyleScore:workStyleScore.value})
    workspace.setMatch(matchedResult)
    await loadContext()
  } catch (reason: any) { error.value = reason.message }
  finally { loading.value = false }
}

async function refreshProfileMatch(refreshContext = false) {
  const sequence = ++profileRefreshSequence
  error.value = ''
  try {
    const matchedResult = await insightService.matchSkills({targetRoleId:roleId.value,skills:skills.value,education:education.value,experienceYears:experience.value,resumeId:useMyResume.value?resume.value?.resumeId||'':'',workStyleScore:workStyleScore.value})
    if (sequence === profileRefreshSequence) {
      workspace.setMatch(matchedResult)
      if (refreshContext) await loadContext()
    }
  } catch (reason: any) {
    if (sequence === profileRefreshSequence) error.value = reason.message
  }
}

async function buildPath() {
  if (!result.value) return
  path.value = (await insightService.getLearningPath(result.value.reportId)).stages
}
function safeFileName(value: string) { return value.replace(/[\\/:*?"<>|]/g, '-').trim() || '当前岗位' }
async function exportReport(format: 'pdf' | 'csv') {
  if (!result.value || exporting.value) return
  exporting.value = format
  error.value = ''
  try {
    const blob = await insightService.downloadReport(result.value.reportId, format)
    const href = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = href
    anchor.download = `${safeFileName(result.value.roleName)}-个人能力诊断.${format}`
    anchor.click()
    window.setTimeout(() => URL.revokeObjectURL(href), 0)
  } catch (reason: any) {
    error.value = reason.message || '报告导出失败，请稍后重试'
  } finally {
    exporting.value = ''
  }
}
function dimensionLabel(value: string) { return ({ skills: '岗位能力', education: '学历', experience: '经验', certificates: '证书' } as Record<string,string>)[value] || value }
function courseName(course: string | Record<string, any>) { return typeof course === 'string' ? course : String(course.name || '') }
function courseUrl(course: string | Record<string, any>) { return typeof course === 'string' ? '' : String(course.url || '') }
function courseProvider(course: string | Record<string, any>) { return typeof course === 'string' ? '' : String(course.provider || '') }
function openAbilityAssistant() { router.push({ path: '/assistant', query: { mode: 'ability_analysis' } }) }
</script>

<template>
  <div class="diagnosis-layout">
    <section class="panel profile-input">
      <div class="panel-head"><div><h2>个人能力档案</h2><p>优先使用“我的简历”，也可以临时补充或重新上传</p></div></div>
      <div class="diagnosis-target"><label class="field-label" for="diagnosis-target">1. 选择目标岗位</label><el-select id="diagnosis-target" v-model="roleId" filterable aria-label="诊断目标岗位" placeholder="选择目标岗位"><el-option v-for="job in jobs" :key="job.id" :label="job.name" :value="job.id"/></el-select></div>
      <h3 class="profile-step">2. 补充你的能力</h3>
      <button v-if="resume" type="button" class="saved-resume-choice" :class="{ active: useMyResume }" @click="useMyResume = !useMyResume">
        <span class="resume-choice-icon"><FileText aria-hidden="true" /></span>
        <span><small>我的简历</small><strong>{{ resume.fileName || '已解析简历' }}</strong><em>{{ resume.skills.length }} 项能力 · {{ resumeConfirmed ? '解析已确认' : '等待确认' }}</em></span>
        <b><CircleCheck aria-hidden="true" />{{ useMyResume ? '已选用' : '选择此简历' }}</b>
      </button>
      <label class="upload-zone compact" :class="{ 'has-saved-resume': resume }"><input type="file" accept=".pdf,.docx,.txt" @change="upload" name="profile-file"><Upload aria-hidden="true" :size="22"/><strong>{{loading?'正在解析…':resume?'重新上传并替换':'上传 PDF 或 Word 简历'}}</strong><span>最大 10 MB；扫描 PDF 将调用本地 OCR</span><b><FileText aria-hidden="true" :size="15"/>选择文件</b></label>
      <div v-if="resume?.ocr?.engine&&resume.ocr.engine!=='digital-text'" class="ocr-status"><span></span><strong>本地 OCR 已完成</strong><small>{{resume.ocr.engine}} · {{resume.ocr.pages}} 页 · {{resume.ocr.language}}</small></div>
      <div v-if="resume?.warnings?.length" class="warning-inline">{{resume.warnings.join(' ')}}</div>
      <div class="divider"><span>{{ resume ? '补充或修正能力信息' : '或手动填写' }}</span></div>
      <label class="field-label" for="diagnosis-skill">已掌握技能</label>
      <div class="skill-editor"><span v-for="skill in skills" :key="skill">{{skill}}<button :aria-label="`移除技能 ${skill}`" @click="skills=skills.filter(item=>item!==skill)"><X aria-hidden="true" :size="12"/></button></span><input id="diagnosis-skill" v-model="input" aria-describedby="skill-entry-hint" placeholder="输入技能后回车" @keyup.enter="addSkill" name="input" autocomplete="off"></div>
      <p class="field-hint" id="skill-entry-hint">填写你已掌握的技能，如 Python、数据分析。按回车添加，可逐项移除。</p>
      <div class="two-fields"><label><span>学历</span><el-select v-model="education" clearable placeholder="未提供"><el-option v-for="item in ['大专','本科','硕士','博士']" :key="item" :label="item" :value="item"/></el-select></label><label><span>经验年限</span><el-input-number v-model="experience" aria-label="工作经验年限" name="experience-years" :min="0" :max="30"/></label></div>
      <details class="optional-assessment"><summary>补充工作方式自评 <span>可选 · 不计入匹配总分</span></summary><section class="workstyle-self-assessment">
        <header><span><Brain aria-hidden="true" /></span><div><strong>工作方式自评</strong><small>用于雷达图补充观察，不进入匹配总分</small></div><em>{{ workStyleScore }}</em></header>
        <div><label v-for="item in workStyleItems" :key="item.key"><span>{{ item.label }} <b>{{ workStyleAssessment[item.key] }}</b></span><input v-model.number="workStyleAssessment[item.key]" :aria-label="item.label" type="range" min="0" max="100" step="5"  name="workStyleAssessment[item-key]"></label></div>
      </section></details>
      <button v-if="resume&&!resumeConfirmed" class="confirm-btn full" :disabled="loading" @click="confirmResume"><Check aria-hidden="true" :size="16"/>确认解析结果</button>
      <button class="secondary-btn full" :disabled="loading||!skills.length" @click="recommend"><Target aria-hidden="true" :size="16"/>根据能力推荐岗位</button>
      <div v-if="recommendations.length" class="recommend-list"><button v-for="item in recommendations" :key="item.roleId" @click="selectRecommendation(item)"><strong>{{item.roleName}}</strong><span>{{item.score}}%</span><small>{{item.topGaps.join('、')}}</small></button></div>
      
      <p id="diagnosis-hint" class="diagnosis-hint" role="status">{{ diagnosisHint }}</p>
      <button aria-describedby="diagnosis-hint" class="primary-btn full large" :disabled="loading||!roleId||!skills.length||(useMyResume&&!!resume&&!resumeConfirmed)" @click="run"><LoaderCircle aria-hidden="true" v-if="loading" class="spin" :size="17"/><Target aria-hidden="true" v-else :size="17"/>{{loading?'正在分析':'运行能力诊断'}}</button>
      <p v-if="error" class="error-text" role="alert">{{error}}</p>
    </section>

    <section class="panel match-result">
      <div v-if="!result" class="empty-state diagnosis-empty"><Target aria-hidden="true"/><h2>把差距变成成长计划</h2><p>不用一次准备好所有信息，从一个目标和一项技能开始。</p><ol><li>选择感兴趣的岗位</li><li>上传简历或手动填写技能</li><li>查看能力差距，生成学习路径</li></ol><small>诊断用于辅助探索，不代表招聘录用判断。</small></div>
      <template v-else>
        <div class="score-head"><div class="score-summary"><strong>{{result.score}}</strong><span>综合匹配度</span></div><div><h2>{{result.roleName}}</h2><p>技能得分 {{result.skillScore}}% · {{matched.length}} 项命中 · {{missing.length}} 项待提升</p></div></div>
        <div class="dimension-row"><div v-for="item in result.dimensions" :key="item.name"><span>{{dimensionLabel(item.name)}}</span><b>{{item.score}}%</b><small>当前权重 {{item.weight}}%</small></div></div>
        <section class="capability-radar-section">
          <header><div><h3>岗位需求基准与我的当前能力</h3><p>技能要求、经验、学历、能力广度和综合素养均按当前岗位动态计算。</p></div><em>当前岗位动态计算</em></header>
          <div class="capability-analysis-body">
            <div class="capability-radar-wrap">
              <CapabilityRadarChart :result="result" :work-style="workStyleAssessment" :experience-years="experience" />
              <el-popover placement="bottom-end" trigger="click" :width="380" popper-class="capability-metric-popper">
                <template #reference><button type="button" class="capability-metric-help" aria-label="查看雷达图指标说明" title="指标说明"><CircleHelp aria-hidden="true" :size="17" /></button></template>
                <div class="capability-metric-guide"><header><strong>指标说明</strong><span>所有数值均为 0–100 的相对比较值</span></header><dl class="capability-line-guide"><div><dt><i class="target"></i>岗位需求基准</dt><dd>根据当前岗位的真实招聘要求、技能证据和岗位标准形成，不是统一满分线。</dd></div><div><dt><i class="current"></i>我的当前能力</dt><dd>根据简历或手工填写的信息计算，并随目标岗位、学历和经验变化。</dd></div></dl><div class="capability-metric-list"><section v-for="item in radarMetricDefinitions" :key="item.name"><strong>{{ item.name }}</strong><p>{{ item.description }}</p></section></div></div>
              </el-popover>
            </div>
            <div class="gap-columns"><div><h3>已匹配 <span>{{matched.length}}</span></h3><article v-for="gap in matched" :key="gap.skillId"><Check aria-hidden="true" :size="15"/><strong>{{gap.skill}}</strong></article></div><div><h3>待提升 <span>{{missing.length}}</span></h3><article v-for="gap in missing" :key="gap.skillId" class="missing"><span></span><strong>{{gap.skill}}</strong></article></div></div>
          </div>
        </section>
        <div class="result-context-grid" :class="{loading:contextLoading}">
          <article><header><GitBranch aria-hidden="true"/><div><span>岗位能力图谱</span><strong>{{graphPreview?.totalNodes||0}} 节点 · {{graphPreview?.totalEdges||0}} 关系</strong></div><button @click="router.push('/graph')">展开</button></header><div class="context-skills"><span v-for="node in graphSkills" :key="node.id">{{node.name}}<small>{{node.level}}</small></span></div></article>
          <article><header><TrendingUp aria-hidden="true"/><div><span>岗位能力演化</span><strong>{{evolutionPreview?.series.length||0}} 条技能趋势</strong></div><button @click="router.push('/forecast?tab=evolution')">展开</button></header><div class="context-events"><span v-for="event in evolutionPreview?.events.slice(0,4)" :key="`${event.skillId}-${event.period}`"><b>{{event.skill}}</b><small>{{event.period}} · {{Number(event.change||0)>0?'+':''}}{{Number(event.change||0).toFixed(1)}}pp</small></span><p v-if="!evolutionPreview?.events.length">暂无达到比较阈值的显著变化</p></div></article>
        </div>
        <div class="report-actions"><button class="primary-btn" @click="buildPath"><Route aria-hidden="true" :size="16"/>{{path.length?'刷新学习路径':'生成学习路径'}}</button><button class="secondary-btn" @click="openAbilityAssistant"><Bot aria-hidden="true" :size="16"/>智能解读诊断</button><button class="secondary-btn" :disabled="!!exporting" @click="exportReport('pdf')"><LoaderCircle aria-hidden="true" v-if="exporting==='pdf'" class="spin" :size="16"/><Download aria-hidden="true" v-else :size="16"/>导出 PDF</button><button class="secondary-btn" :disabled="!!exporting" @click="exportReport('csv')"><LoaderCircle aria-hidden="true" v-if="exporting==='csv'" class="spin" :size="16"/><Download aria-hidden="true" v-else :size="16"/>导出 CSV</button></div>
        <div v-if="path.length" class="learning-track">
          <article v-for="stage in path" :key="stage.stage">
            <span>{{stage.stage}}</span>
            <div class="learning-stage-body">
              <header><div><strong>{{stage.name}} · {{stage.duration}}</strong><small v-if="stage.estimatedHoursPerWeek">建议每周 {{stage.estimatedHoursPerWeek}} 小时</small></div><b>{{stage.skills.join('、')}}</b></header>
              <p v-if="stage.goal" class="learning-goal">{{stage.goal}}</p>
              <div v-if="stage.weeklyTasks?.length" class="weekly-task-list">
                <section v-for="task in stage.weeklyTasks" :key="task.period">
                  <time>{{task.period}}</time><div><strong>{{task.title}}</strong><p v-for="action in task.actions" :key="action">{{action}}</p><small>阶段产物：{{task.deliverable}}</small></div>
                </section>
              </div>
              <dl class="learning-resources">
                <div v-if="stage.prerequisites?.length"><dt>前置能力</dt><dd>{{stage.prerequisites.join('、')}}</dd></div>
                <div v-if="stage.courses?.length"><dt>参考课程</dt><dd class="learning-course-links"><template v-for="course in stage.courses" :key="courseName(course)"><a v-if="courseUrl(course)" :href="courseUrl(course)" target="_blank" rel="noopener noreferrer" :title="courseProvider(course) ? `${courseProvider(course)} · 打开课程网页` : '打开课程网页'">{{courseName(course)}}<ExternalLink aria-hidden="true" :size="13" /></a><span v-else>{{courseName(course)}}</span></template></dd></div>
                <div v-if="stage.certificates?.length"><dt>可选认证</dt><dd>{{stage.certificates.join('、')}}</dd></div>
                <div v-if="stage.practiceProject"><dt>实践项目</dt><dd>{{stage.practiceProject}}</dd></div>
              </dl>
              <div v-if="stage.acceptanceCriteria?.length" class="learning-criteria"><strong>阶段验收</strong><ul><li v-for="criterion in stage.acceptanceCriteria" :key="criterion">{{criterion}}</li></ul></div>
              <p class="learning-outcome">{{stage.outcome}}</p>
            </div>
          </article>
        </div>
      </template>
    </section>
  </div>
</template>
