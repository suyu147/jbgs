<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  Activity, ArrowRight, BriefcaseBusiness, CircleAlert, CircleCheck, Clock3,
  CalendarRange, Check, ChevronDown, Database, Eye, FileStack, Flame, MapPin, MousePointerClick, Network,
  RefreshCw, Server, Sparkles, Users,
} from 'lucide-vue-next'
import AdminDonutChart from '@/components/charts/AdminDonutChart.vue'
import AdminMonthlyChart from '@/components/charts/AdminMonthlyChart.vue'
import AdminVisitChart from '@/components/charts/AdminVisitChart.vue'
import { insightService } from '@/services/insightService'
import type { AdminDashboardSummary } from '@/types/domain'

const router = useRouter()
const dashboard = ref<AdminDashboardSummary | null>(null)
const loading = ref(true)
const error = ref('')
const numberFormatter = new Intl.NumberFormat('zh-CN')
interface DonutDatum { key:string; label:string; value:number; color:string }
type EvidenceRange = '6m' | '12m' | '24m' | 'thisYear' | 'lastYear' | 'all' | 'custom'
type AccessRange = 'today' | 'yesterday' | '24h' | '7d' | '14d' | '30d' | 'thisMonth' | 'lastMonth' | 'custom'

const evidenceRange = ref<EvidenceRange>('12m')
const evidenceRangeMenu = ref<HTMLDetailsElement | null>(null)
const customStartMonth = ref('')
const customEndMonth = ref('')
const currentYear = new Date().getFullYear()
const evidenceRangePresets: Array<{value:Exclude<EvidenceRange, 'custom'>;label:string}> = [
  { value:'6m', label:'最近 6 个月' },
  { value:'12m', label:'最近 12 个月' },
  { value:'24m', label:'最近 24 个月' },
  { value:'thisYear', label:`${currentYear} 年` },
  { value:'lastYear', label:`${currentYear - 1} 年` },
  { value:'all', label:'全部周期' },
]
const accessRange = ref<AccessRange>('today')
const accessRangeMenu = ref<HTMLDetailsElement | null>(null)
const accessRangePlacement = ref<'up' | 'down'>('down')
const accessRangeAvailableHeight = ref(360)
const accessNow = ref(new Date())
let accessClockTimer: number | undefined
function toDateInput(value: Date) {
  const year = value.getFullYear()
  const month = String(value.getMonth() + 1).padStart(2, '0')
  const day = String(value.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}
const accessCustomStart = ref(toDateInput(new Date(accessNow.value.getFullYear(), accessNow.value.getMonth(), accessNow.value.getDate() - 6)))
const accessCustomEnd = ref(toDateInput(accessNow.value))
const accessRangePresets: Array<{value:Exclude<AccessRange, 'custom'>;label:string}> = [
  { value:'today', label:'今天' },
  { value:'yesterday', label:'昨天' },
  { value:'24h', label:'近 24 小时' },
  { value:'7d', label:'近 7 天' },
  { value:'14d', label:'近 14 天' },
  { value:'30d', label:'近 30 天' },
  { value:'thisMonth', label:'本月' },
  { value:'lastMonth', label:'上月' },
]

const entityMeta = [
  { key:'Course', label:'课程', color:'#8B5CF6' },
  { key:'TrendSignal', label:'趋势信号', color:'#3B82F6' },
  { key:'Requirement', label:'能力要求', color:'#06B6D4' },
  { key:'Certificate', label:'证书', color:'#10B981' },
  { key:'TrendReport', label:'趋势报告', color:'#F59E0B' },
  { key:'TimePeriod', label:'时间周期', color:'#F97316' },
  { key:'TrendTopic', label:'趋势主题', color:'#E86A3F' },
  { key:'Major', label:'专业', color:'#64748B' },
  { key:'OccupationStandard', label:'职业标准', color:'#94A3B8' },
]

// 运营观察数据与正式治理指标分层，后续可整体替换为访问日志接口。
const hourlyVisitPattern = [
  { period:'00:00', value:32 }, { period:'02:00', value:24 },
  { period:'04:00', value:18 }, { period:'06:00', value:46 },
  { period:'08:00', value:96 }, { period:'10:00', value:138 },
  { period:'12:00', value:121 }, { period:'14:00', value:164 },
  { period:'16:00', value:188 }, { period:'18:00', value:156 },
  { period:'20:00', value:117 }, { period:'22:00', value:84 },
]
const jobAttention = [
  { name:'数据分析师', family:'数字技术', score:92, change:'+18' },
  { name:'人工智能训练师', family:'人工智能', score:87, change:'+15' },
  { name:'Python 开发工程师', family:'软件工程', score:81, change:'+11' },
  { name:'机器学习工程师', family:'人工智能', score:76, change:'+9' },
  { name:'大数据工程师', family:'数据工程', score:69, change:'+7' },
  { name:'算法工程师', family:'人工智能', score:66, change:'+6' },
  { name:'数据产品经理', family:'产品管理', score:62, change:'+5' },
  { name:'云计算工程师', family:'基础架构', score:58, change:'+4' },
  { name:'网络安全工程师', family:'信息安全', score:54, change:'+4' },
  { name:'智能制造工程师', family:'智能制造', score:49, change:'+3' },
]
const featureUsage = [
  { label:'岗位库', value:34, color:'#8B5CF6' },
  { label:'趋势预测', value:27, color:'#3B82F6' },
  { label:'能力图谱', value:23, color:'#06B6D4' },
  { label:'能力诊断', value:16, color:'#10B981' },
]
const activeRegions = ['北京', '上海', '深圳', '杭州', '广州', '成都', '南京', '武汉', '苏州', '西安']

const kpis = computed(() => dashboard.value ? [
  { label:'招聘记录', value:dashboard.value.graph.postingCount, note:'真实 JD 证据', icon:BriefcaseBusiness, route:'/admin/data' },
  { label:'岗位角色', value:dashboard.value.graph.jobCount, note:'正式岗位定义', icon:FileStack, route:'/admin/reviews' },
  { label:'技能实体', value:dashboard.value.graph.skillCount, note:'已归一技能资产', icon:Sparkles, route:'/admin/data' },
  { label:'图谱关系', value:dashboard.value.graph.relationCount, note:'当前关系总量', icon:Network, route:'/admin/quality' },
  { label:'月度快照', value:dashboard.value.graph.snapshotCount || 0, note:'动态演化基础', icon:Activity, route:'/admin/quality' },
  { label:'待复核', value:dashboard.value.graph.pendingReviewCount, note:'需要人工处理', icon:CircleAlert, route:'/admin/reviews', attention:true },
] : [])
const funnelMax = computed(() => Math.max(...(dashboard.value?.governance.funnel.map(item => item.count) || [1]), 1))
const qualityStatus = computed(() => dashboard.value?.quality.score === 100 ? '全部质量规则通过' : '存在需要处理的质量项')
const entityChartItems = computed<DonutDatum[]>(() => entityMeta.map(item => ({ ...item, value:dashboard.value?.graph.entityCounts[item.key] || 0 })))
const linkedServiceCount = computed(() => {
  if (!dashboard.value) return 0
  return [dashboard.value.system.api, dashboard.value.system.mysql, dashboard.value.system.neo4j, Boolean(dashboard.value.graph.snapshotCount)].filter(Boolean).length
})
const riskItems = computed(() => {
  if (!dashboard.value) return []
  const governance = dashboard.value.governance
  return [
    ...dashboard.value.risks,
    { key:'draftDefinitions', label:'草稿岗位定义', count:governance.draftStatuses.draft || 0, route:'/admin/reviews' },
    { key:'approvedDefinitions', label:'已批准待发布', count:governance.draftStatuses.approved || 0, route:'/admin/reviews' },
    { key:'runningTasks', label:'运行中处理任务', count:governance.taskStatuses.running || 0, route:'/admin/quality' },
    { key:'pendingRevisions', label:'待同步数据修订', count:dashboard.value.dataAssets.revisionStatuses.pending || 0, route:'/admin/data' },
  ]
})
const filteredMonthlyEvidence = computed(() => {
  const points = dashboard.value?.monthlyEvidence || []
  if (evidenceRange.value === 'all') return points
  if (evidenceRange.value === 'thisYear') return points.filter(item => item.period.startsWith(`${currentYear}-`))
  if (evidenceRange.value === 'lastYear') return points.filter(item => item.period.startsWith(`${currentYear - 1}-`))
  if (evidenceRange.value === 'custom') {
    return points.filter(item => item.period >= customStartMonth.value && item.period <= customEndMonth.value)
  }
  const monthCount = Number.parseInt(evidenceRange.value, 10)
  return points.slice(-monthCount)
})
const evidenceRangeLabel = computed(() => {
  if (evidenceRange.value === 'custom') return `${customStartMonth.value} 至 ${customEndMonth.value}`
  return evidenceRangePresets.find(item => item.value === evidenceRange.value)?.label || '选择时间'
})
const customRangeValid = computed(() => Boolean(
  customStartMonth.value && customEndMonth.value && customStartMonth.value <= customEndMonth.value,
))
const accessCustomRangeValid = computed(() => Boolean(
  accessCustomStart.value && accessCustomEnd.value && accessCustomStart.value <= accessCustomEnd.value,
))
const accessRangeLabel = computed(() => {
  if (accessRange.value === 'custom') return `${accessCustomStart.value.slice(5)} 至 ${accessCustomEnd.value.slice(5)}`
  return accessRangePresets.find(item => item.value === accessRange.value)?.label || '选择时间'
})
const accessRangeDates = computed(() => {
  const today = accessNow.value
  const end = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  let start = new Date(end)
  if (accessRange.value === 'yesterday') { start.setDate(start.getDate() - 1); end.setDate(end.getDate() - 1) }
  else if (accessRange.value === '7d') start.setDate(start.getDate() - 6)
  else if (accessRange.value === '14d') start.setDate(start.getDate() - 13)
  else if (accessRange.value === '30d') start.setDate(start.getDate() - 29)
  else if (accessRange.value === 'thisMonth') start = new Date(end.getFullYear(), end.getMonth(), 1)
  else if (accessRange.value === 'lastMonth') {
    start = new Date(end.getFullYear(), end.getMonth() - 1, 1)
    end.setDate(0)
  } else if (accessRange.value === 'custom' && accessCustomRangeValid.value) {
    start = new Date(`${accessCustomStart.value}T00:00:00`)
    return { start, end:new Date(`${accessCustomEnd.value}T00:00:00`) }
  }
  return { start, end }
})
const accessRangeDays = computed(() => Math.max(1, Math.round(
  (accessRangeDates.value.end.getTime() - accessRangeDates.value.start.getTime()) / 86400000,
) + 1))
const accessTrend = computed(() => {
  const now = accessNow.value
  if (['today', 'yesterday', '24h'].includes(accessRange.value)) {
    const factor = accessRange.value === 'yesterday' ? .89 : accessRange.value === 'today' ? 1.04 : 1
    const rollingPattern = Array.from({ length:12 }, (_, index) => {
      const hour = (now.getHours() - 22 + index * 2 + 24) % 24
      const source = hourlyVisitPattern[Math.floor(hour / 2)]
      return { period:`${String(hour).padStart(2, '0')}:00`, value:source.value }
    })
    const visiblePattern = hourlyVisitPattern.filter(item => Number(item.period.slice(0, 2)) <= now.getHours())
    const pattern = accessRange.value === 'yesterday'
      ? hourlyVisitPattern
      : accessRange.value === '24h'
        ? rollingPattern
        : visiblePattern.length > 1 ? visiblePattern : hourlyVisitPattern.slice(0, 2)
    return pattern.map((item, index) => ({
      period:item.period,
      value:Math.round(item.value * factor * (1 + Math.sin(index * 1.7) * .025)),
    }))
  }
  const totalDays = accessRangeDays.value
  const pointCount = Math.min(totalDays, 30)
  const step = Math.max(1, Math.ceil(totalDays / pointCount))
  const points: Array<{period:string;value:number}> = []
  for (let offset = 0; offset < totalDays; offset += step) {
    const date = new Date(accessRangeDates.value.start)
    date.setDate(date.getDate() + offset)
    const weekdayFactor = [0.78, 1.06, 1.12, 1.09, 1.15, 1.02, 0.84][date.getDay()]
    const wave = 1 + Math.sin((offset + 2) * .72) * .09 + Math.cos(offset * .31) * .045
    points.push({ period:`${date.getMonth() + 1}/${date.getDate()}`, value:Math.round(1260 * weekdayFactor * wave) })
  }
  return points
})
const accessMetrics = computed(() => {
  if (['today', 'yesterday', '24h'].includes(accessRange.value)) {
    const visits = Math.round(accessTrend.value.reduce((sum, item) => sum + item.value, 0) * 1.084)
    const isYesterday = accessRange.value === 'yesterday'
    return [
      { label:isYesterday ? '昨日访问' : accessRange.value === 'today' ? '今日访问' : '24 小时访问', value:visits, note:isYesterday ? '较前日 +8.4%' : '较前期 +12.6%', icon:Eye },
      { label:'独立访客', value:Math.round(visits * .71), note:`人均 ${(visits / Math.max(1, Math.round(visits * .71))).toFixed(1)} 次`, icon:Users },
      { label:isYesterday ? '峰值在线' : '当前在线', value:isYesterday ? 181 : 86, note:`峰值 ${Math.round(Math.max(...accessTrend.value.map(item => item.value)) * 1.09)}`, icon:Activity },
    ]
  }
  const total = accessTrend.value.reduce((sum, item) => sum + item.value, 0)
  const daily = Math.round(total / Math.max(1, accessTrend.value.length))
  return [
    { label:'区间访问', value:total, note:`${accessRangeDays.value} 天汇总`, icon:Eye },
    { label:'日均访问', value:daily, note:'按日聚合', icon:Users },
    { label:'峰值在线', value:Math.round(Math.max(...accessTrend.value.map(item => item.value)) * .15), note:`高峰日 ${accessTrend.value.reduce((best, item) => item.value > best.value ? item : best, accessTrend.value[0]).period}`, icon:Activity },
  ]
})

function formatNumber(value: number) { return numberFormatter.format(value || 0) }
function formatTime(value: string) { return value ? new Date(value).toLocaleString('zh-CN', { hour12:false }) : '暂无记录' }
function navigate(path: string) { router.push(path) }
function selectEvidenceRange(range: Exclude<EvidenceRange, 'custom'>) {
  evidenceRange.value = range
  evidenceRangeMenu.value?.removeAttribute('open')
}
function applyCustomEvidenceRange() {
  if (!customRangeValid.value) return
  evidenceRange.value = 'custom'
  evidenceRangeMenu.value?.removeAttribute('open')
}
function selectAccessRange(range: Exclude<AccessRange, 'custom'>) {
  accessRange.value = range
  accessRangeMenu.value?.removeAttribute('open')
}
function applyCustomAccessRange() {
  if (!accessCustomRangeValid.value) return
  accessRange.value = 'custom'
  accessRangeMenu.value?.removeAttribute('open')
}
function updateAccessRangePlacement(event: Event) {
  const details = event.currentTarget as HTMLDetailsElement
  if (!details.open) return
  requestAnimationFrame(() => {
    const summary = details.querySelector('summary')
    const popover = details.querySelector<HTMLElement>('.access-range-popover')
    if (!summary || !popover) return
    const rect = summary.getBoundingClientRect()
    const spaceBelow = Math.max(0, window.innerHeight - rect.bottom - 12)
    const spaceAbove = Math.max(0, rect.top - 12)
    const desiredHeight = Math.min(popover.scrollHeight, 360)
    accessRangePlacement.value = spaceBelow >= desiredHeight || spaceBelow >= spaceAbove ? 'down' : 'up'
    accessRangeAvailableHeight.value = Math.max(160, Math.floor(accessRangePlacement.value === 'down' ? spaceBelow : spaceAbove))
  })
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    dashboard.value = await insightService.getAdminDashboard()
    if (!customStartMonth.value && dashboard.value.monthlyEvidence.length) {
      customStartMonth.value = dashboard.value.monthlyEvidence[0].period
      customEndMonth.value = dashboard.value.monthlyEvidence.at(-1)?.period || customStartMonth.value
    }
  }
  catch (reason) { error.value = reason instanceof Error ? reason.message : '数字大屏数据暂时无法读取' }
  finally { loading.value = false }
}

onMounted(() => {
  load()
  accessClockTimer = window.setInterval(() => { accessNow.value = new Date() }, 60_000)
})
onBeforeUnmount(() => {
  if (accessClockTimer) window.clearInterval(accessClockTimer)
})
</script>

<template>
  <div class="governance-dashboard">
    <section class="governance-toolbar" aria-label="数字大屏状态栏">
      <div class="toolbar-actions"><span><Clock3 :size="14" />{{ formatTime(dashboard?.generatedAt || '') }}</span><button class="secondary-btn" :disabled="loading" @click="load"><RefreshCw :size="16" :class="{ spinning:loading }" />刷新数据</button></div>
    </section>

    <div v-if="loading && !dashboard" class="governance-loading" aria-busy="true" aria-label="正在加载治理数据"><i v-for="item in 10" :key="item"></i></div>
    <section v-else-if="error && !dashboard" class="governance-error" role="alert"><CircleAlert /><div><strong>治理数据读取失败</strong><p>{{ error }}</p></div><button class="primary-btn" @click="load">重新加载</button></section>

    <template v-if="dashboard">
      <section class="governance-kpis" aria-label="核心数据资产">
        <button v-for="item in kpis" :key="item.label" :class="{ attention:item.attention }" @click="navigate(item.route)">
          <span><component :is="item.icon" :size="19" /></span><div><small>{{ item.label }}</small><strong>{{ formatNumber(item.value) }}</strong><em>{{ item.note }}</em></div><ArrowRight :size="15" />
        </button>
      </section>

      <section class="governance-operations" aria-label="运营观察">
        <div class="governance-operations-grid">
          <article class="governance-panel visit-observation-panel">
            <header>
              <div><h2>最近访问人数</h2><p>访问节奏与在线情况概览。<em class="live-clock">演示数据 · 非实时日志</em></p></div>
              <details
                ref="accessRangeMenu"
                class="access-range-menu"
                :class="{ 'drop-up':accessRangePlacement === 'up' }"
                :style="{ '--access-range-space':`${accessRangeAvailableHeight}px` }"
                @toggle="updateAccessRangePlacement"
              >
                <summary><CalendarRange :size="13" /><span>{{ accessRangeLabel }}</span><ChevronDown :size="12" /></summary>
                <div class="access-range-popover">
                  <strong>查询时间</strong>
                  <div class="access-range-presets"><button v-for="preset in accessRangePresets" :key="preset.value" type="button" :class="{ active:accessRange === preset.value }" @click="selectAccessRange(preset.value)"><Check v-if="accessRange === preset.value" :size="11" />{{ preset.label }}</button></div>
                  <div class="access-custom-range"><label><span>开始日期</span><input v-model="accessCustomStart" type="date" /></label><i>至</i><label><span>结束日期</span><input v-model="accessCustomEnd" type="date" /></label></div>
                  <button type="button" class="access-range-apply" :disabled="!accessCustomRangeValid" @click="applyCustomAccessRange">应用自定义时间</button>
                </div>
              </details>
            </header>
            <div class="access-metric-strip">
              <div v-for="item in accessMetrics" :key="item.label">
                <span><component :is="item.icon" :size="15" /></span>
                <div><small>{{ item.label }}</small><strong>{{ formatNumber(item.value) }}</strong><em>{{ item.note }}</em></div>
              </div>
            </div>
            <AdminVisitChart :points="accessTrend" />
          </article>

          <article class="governance-panel job-attention-panel">
            <header><div><h2>岗位关注度</h2><p>示意榜单 · 接入访问日志后更新。</p></div><Flame :size="19" /></header>
            <ol class="job-attention-list">
              <li v-for="(item,index) in jobAttention" :key="item.name">
                <span>{{ String(index + 1).padStart(2, '0') }}</span>
                <div><strong>{{ item.name }}</strong><small>{{ item.family }}</small><i><b :style="{ width:`${item.score}%` }"></b></i></div>
                <em>{{ item.score }}</em><small>{{ item.change }}</small>
              </li>
            </ol>
          </article>

          <article class="governance-panel feature-usage-panel">
            <header><div><h2>功能使用分布</h2><p>演示占比与地区样例 · 非实时统计。</p></div><MousePointerClick :size="19" /></header>
            <div class="feature-usage-body">
              <div class="feature-usage-ring" aria-label="功能访问占比"><strong>4</strong><small>核心模块</small></div>
              <div class="feature-usage-legend">
                <div v-for="item in featureUsage" :key="item.label">
                  <i :style="{ background:item.color }"></i><span>{{ item.label }}</span><strong>{{ item.value }}%</strong>
                </div>
              </div>
            </div>
            <footer class="active-region-strip"><span><MapPin :size="13" />活跃地区</span><div><i v-for="region in activeRegions" :key="region">{{ region }}</i></div></footer>
          </article>
        </div>
      </section>

      <section class="governance-cockpit-grid" aria-label="知识图谱治理驾驶舱">
        <article class="governance-panel quality-overview cockpit-quality">
          <header><div><h2>数据质量状态</h2></div><button @click="navigate('/admin/quality')">查看报告<ArrowRight :size="14" /></button></header>
          <div class="quality-gauge" :style="{ '--score': `${dashboard.quality.score * 3.6}deg` }"><strong>{{ dashboard.quality.score }}</strong><small>综合得分</small></div>
          <p><CircleCheck v-if="dashboard.quality.score === 100" :size="16" /><CircleAlert v-else :size="16" />{{ qualityStatus }}</p>
          <dl><div><dt>规则通过</dt><dd>{{ dashboard.quality.passedChecks }} / {{ dashboard.quality.totalChecks }}</dd></div><div><dt>算法评测</dt><dd>{{ dashboard.quality.evaluationPassed ? '通过' : '待检查' }}</dd></div><div><dt>测试覆盖</dt><dd>{{ dashboard.quality.coveragePassed ? '通过' : '待检查' }}</dd></div></dl>
        </article>

        <article class="governance-panel service-topology-panel">
          <header><div><h2>服务状态与图谱链路</h2><p>应用数据、接口、图谱与动态快照的实时连接状态。</p></div><em>{{ linkedServiceCount }} / 4 在线</em></header>
          <div class="service-topology" aria-label="MySQL、后端 API、Neo4j 和月度快照链路">
            <button :class="{ offline:!dashboard.system.mysql }" @click="navigate('/admin/data')"><span><Database :size="18" /></span><strong>MySQL</strong><small>应用数据</small><i></i></button>
            <b aria-hidden="true"></b>
            <button class="primary-node" :class="{ offline:!dashboard.system.api }" @click="navigate('/admin/quality')"><span><Server :size="19" /></span><strong>后端 API</strong><small>服务接口</small><i></i></button>
            <b aria-hidden="true"></b>
            <button :class="{ offline:!dashboard.system.neo4j }" @click="navigate('/admin/quality')"><span><Network :size="18" /></span><strong>Neo4j</strong><small>知识图谱</small><i></i></button>
            <b aria-hidden="true"></b>
            <button :class="{ offline:!dashboard.graph.snapshotCount }" @click="navigate('/admin/quality')"><span><Activity :size="18" /></span><strong>{{ formatNumber(dashboard.graph.snapshotCount || 0) }}</strong><small>月度快照</small><i></i></button>
          </div>
          <div class="service-topology-footer"><span><i></i>实时连接</span><strong>{{ dashboard.graphVersion }}</strong><button @click="navigate('/admin/quality')">链路详情<ArrowRight :size="13" /></button></div>
        </article>

        <article class="governance-panel evidence-panel cockpit-evidence">
          <header>
            <div><h2>招聘证据月度变化</h2><p>按有效招聘记录的规范月份统计。</p></div>
            <details ref="evidenceRangeMenu" class="evidence-range-menu">
              <summary><CalendarRange :size="13" /><span>{{ evidenceRangeLabel }}</span><ChevronDown :size="12" /></summary>
              <div class="evidence-range-popover">
                <strong>查询时间</strong>
                <div class="evidence-range-presets">
                  <button
                    v-for="preset in evidenceRangePresets"
                    :key="preset.value"
                    type="button"
                    :class="{ active:evidenceRange === preset.value }"
                    @click="selectEvidenceRange(preset.value)"
                  ><Check v-if="evidenceRange === preset.value" :size="11" />{{ preset.label }}</button>
                </div>
                <div class="evidence-custom-range">
                  <label><span>开始月份</span><input v-model="customStartMonth" type="month" /></label>
                  <i>至</i>
                  <label><span>结束月份</span><input v-model="customEndMonth" type="month" /></label>
                </div>
                <button type="button" class="evidence-range-apply" :disabled="!customRangeValid" @click="applyCustomEvidenceRange">应用自定义时间</button>
              </div>
            </details>
          </header>
          <AdminMonthlyChart :points="filteredMonthlyEvidence" />
        </article>

        <article class="governance-panel governance-risks cockpit-risks">
          <header><div><h2>治理待办任务</h2></div><CircleAlert :size="19" /></header>
          <div><button v-for="item in riskItems" :key="item.key" :class="{ clear:item.count === 0 }" @click="navigate(item.route)"><span>{{ item.count === 0 ? '已清零' : '待处理' }}</span><strong>{{ item.label }}</strong><em>{{ formatNumber(item.count) }}</em><ArrowRight :size="14" /></button></div>
        </article>

        <article class="governance-panel publish-funnel">
          <header><div><h2>复核发布流程</h2><p>候选发现进入正式图谱版本的治理闭环。</p></div><FileStack :size="19" /></header>
          <div><button v-for="(item,index) in dashboard.governance.funnel" :key="item.key" @click="navigate(item.route)"><span>{{ String(index+1).padStart(2,'0') }}</span><div><strong>{{ item.label }}</strong><i><b :style="{ width:`${Math.max(item.count ? 8 : 0,item.count/funnelMax*100)}%` }"></b></i></div><em>{{ formatNumber(item.count) }}</em><ArrowRight :size="14" /></button></div>
        </article>

        <article class="governance-panel donut-panel entity-composition cockpit-entities">
          <header><div><h2>图谱实体资产构成</h2><p>当前知识图谱中的治理类实体分布。</p></div><Network :size="19" /></header>
          <AdminDonutChart :items="entityChartItems" center-label="实体资产" @select="navigate('/admin/data')" />
        </article>
      </section>

    </template>
  </div>
</template>
