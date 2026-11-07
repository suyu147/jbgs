<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight, Bot, BriefcaseBusiness, CalendarRange, CircleAlert, Download, Layers3, LoaderCircle, Search, TrendingUp } from 'lucide-vue-next'
import ForecastChart from '@/components/charts/ForecastChart.vue'
import SkillEvolutionForecast from '@/components/forecast/SkillEvolutionForecast.vue'
import { insightService } from '@/services/insightService'
import type { ForecastOverview, ForecastScenario, OccupationForecast } from '@/types/domain'
import { useWorkspaceStore } from '@/stores/workspace'

type ForecastTab = 'occupation' | 'evolution'
type Granularity = 'year' | 'month'
const route = useRoute()
const router = useRouter()
const workspace = useWorkspaceStore()
const requestedTab = String(route.query.tab || '')
const initialTab: ForecastTab = requestedTab === 'skill' || requestedTab === 'evolution' ? 'evolution' : 'occupation'
const activeTab = ref<ForecastTab>(initialTab)
const horizon = ref(3)
const scenario = ref<ForecastScenario>('baseline')
const forecastGranularity = ref<Granularity>('year')
const result = ref<ForecastOverview | null>(null)
const selectedOccupationId = ref('')
const occupationKeyword = ref('')
const loading = ref(false)
const exportingPdf = ref(false)
const error = ref('')
const exportError = ref('')
let forecastLoadVersion = 0
let occupationSearchTimer: number | undefined
const selectedOccupation = computed(() => result.value?.occupations.find(item => item.roleId === selectedOccupationId.value))
const displayedScenarioLabel = computed(() => ({ conservative: '保守情景', baseline: '基准情景', growth: '增长情景' }[result.value?.scenario || scenario.value]))
const displayedGranularityLabel = computed(() => (result.value?.granularity || forecastGranularity.value) === 'year' ? '年度' : '月度')
const displayedHorizon = computed(() => result.value?.horizon || horizon.value)
const exportRole = computed(() => {
  if (activeTab.value === 'occupation' && selectedOccupation.value) {
    return { id: selectedOccupation.value.roleId, name: selectedOccupation.value.roleName }
  }
  return { id: workspace.targetRoleId, name: workspace.targetRoleName }
})

async function loadForecast() {
  const version = ++forecastLoadVersion
  const requestedHorizon = horizon.value
  const requestedScenario = scenario.value
  const requestedGranularity = forecastGranularity.value
  const requestedLocation = workspace.location
  const requestedKeyword = occupationKeyword.value.trim()
  loading.value = true
  error.value = ''
  try {
    const nextResult = await insightService.getForecastOverview(requestedHorizon, requestedScenario, requestedGranularity, '', requestedLocation, requestedKeyword)
    if (version !== forecastLoadVersion) return
    let occupations = [...nextResult.occupations]
    if (workspace.targetRoleId && !occupations.some(item => item.roleId === workspace.targetRoleId) && workspace.targetRoleName) {
      const targetResult = await insightService.getForecastOverview(requestedHorizon, requestedScenario, requestedGranularity, '', requestedLocation, workspace.targetRoleName)
      if (version !== forecastLoadVersion) return
      const target = targetResult.occupations.find(item => item.roleId === workspace.targetRoleId)
        || targetResult.occupations.find(item => item.roleName === workspace.targetRoleName)
      if (target) occupations = [target, ...occupations.filter(item => item.roleId !== target.roleId)]
    }
    nextResult.occupations = occupations
    result.value = nextResult
    const preferred = result.value.occupations.find(item => item.roleId === workspace.targetRoleId) || result.value.occupations[0]
    selectedOccupationId.value = preferred?.roleId || ''
    if (preferred && preferred.roleId !== workspace.targetRoleId) workspace.selectTarget(preferred.roleId, preferred.roleName)
  } catch (reason: any) {
    if (version !== forecastLoadVersion) return
    error.value = reason.message || '预测数据暂时无法读取'
  } finally {
    if (version === forecastLoadVersion) loading.value = false
  }
}
function setTab(tab: ForecastTab) {
  activeTab.value = tab
  router.replace({ query: { ...route.query, tab: tab === 'occupation' ? undefined : tab } })
  if (tab === 'occupation') void loadForecast()
}
function chooseOccupation(id: string) {
  selectedOccupationId.value = id
  const role = result.value?.occupations.find(item => item.roleId === id)
  if (role) workspace.selectTarget(role.roleId, role.roleName)
}
async function syncOccupationFromWorkspace() {
  if (!workspace.targetRoleId || selectedOccupationId.value === workspace.targetRoleId) return
  const local = result.value?.occupations.find(item => item.roleId === workspace.targetRoleId)
  if (local) {
    selectedOccupationId.value = local.roleId
    return
  }
  const version = ++forecastLoadVersion
  loading.value = true
  error.value = ''
  try {
    const targetResult = await insightService.getForecastOverview(horizon.value, scenario.value, forecastGranularity.value, '', workspace.location, workspace.targetRoleName)
    if (version !== forecastLoadVersion) return
    const target: OccupationForecast | undefined = targetResult.occupations.find(item => item.roleId === workspace.targetRoleId)
      || targetResult.occupations.find(item => item.roleName === workspace.targetRoleName)
    if (!target) throw new Error('当前分析岗位缺少可用的月度趋势样本')
    result.value = result.value
      ? { ...result.value, occupations: [target, ...result.value.occupations.filter(item => item.roleId !== target.roleId)] }
      : targetResult
    selectedOccupationId.value = target.roleId
  } catch (reason: any) {
    if (version === forecastLoadVersion) error.value = reason.message || '当前分析岗位预测数据暂时无法读取'
  } finally {
    if (version === forecastLoadVersion) loading.value = false
  }
}
function actOnOccupation() {
  const role = selectedOccupation.value
  if (role) workspace.selectTarget(role.roleId, role.roleName)
  router.push('/matching')
}
function askOccupation() {
  const role = selectedOccupation.value
  if (role) workspace.selectTarget(role.roleId, role.roleName)
  router.push({ path: '/assistant', query: { mode: 'career_planning' } })
}
function safeFileName(value: string) {
  return value.replace(/[\\/:*?"<>|]/g, '-').trim() || '当前岗位'
}
async function exportForecastPdf() {
  if (!exportRole.value.id || exportingPdf.value) return
  exportingPdf.value = true
  exportError.value = ''
  try {
    const blob = await insightService.downloadEvolutionReport(
      exportRole.value.id,
      horizon.value,
      scenario.value,
      forecastGranularity.value,
    )
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${safeFileName(exportRole.value.name)}-岗位趋势预测.pdf`
    document.body.appendChild(anchor)
    anchor.click()
    anchor.remove()
    window.setTimeout(() => URL.revokeObjectURL(url), 1000)
  } catch (reason: any) {
    exportError.value = reason.message || 'PDF 导出失败，请稍后重试'
  } finally {
    exportingPdf.value = false
  }
}
function confidence(value = 0) { return `${Math.round(value * 100)}%` }
function signedNumber(value?: number, digits = 1) { const number = Number(value || 0); return `${number >= 0 ? '+' : ''}${number.toFixed(digits)}` }
onMounted(async () => {
  if (requestedTab === 'emerging') {
    await router.replace({ path: '/jobs', query: { catalog: 'new' } })
    return
  }
  if (requestedTab === 'skill') await router.replace({ query: { ...route.query, tab: 'evolution' } })
  await loadForecast()
})
watch([horizon, scenario, forecastGranularity, () => workspace.location], () => {
  if (activeTab.value === 'occupation') void loadForecast()
})
watch(() => workspace.targetRoleId, () => {
  if (activeTab.value === 'occupation') void syncOccupationFromWorkspace()
})
watch(occupationKeyword, () => {
  if (occupationSearchTimer) window.clearTimeout(occupationSearchTimer)
  occupationSearchTimer = window.setTimeout(() => {
    selectedOccupationId.value = ''
    loadForecast()
  }, 250)
})
onBeforeUnmount(() => {
  if (occupationSearchTimer) window.clearTimeout(occupationSearchTimer)
})
</script>

<template>
  <div class="forecast-workspace">
    <section class="forecast-commandbar">
      <div class="forecast-tabs" role="group" aria-label="趋势预测功能">
        <button :class="{ active: activeTab === 'occupation' }" :aria-pressed="activeTab === 'occupation'" @click="setTab('occupation')"><BriefcaseBusiness aria-hidden="true" /><span>职业热度</span></button>
        <button :class="{ active: activeTab === 'evolution' }" :aria-pressed="activeTab === 'evolution'" @click="setTab('evolution')"><TrendingUp aria-hidden="true" /><span>技能演化</span></button>
      </div>
      <div class="forecast-parameters">
        <label><span><CalendarRange aria-hidden="true" />预测周期</span><el-select v-model="horizon" popper-class="forecast-filter-popper"><el-option label="未来 1 年" :value="1" /><el-option label="未来 3 年" :value="3" /><el-option label="未来 5 年" :value="5" /></el-select></label>
        <label><span><Layers3 aria-hidden="true" />预测情景</span><el-select v-model="scenario" popper-class="forecast-filter-popper"><el-option label="保守情景" value="conservative" /><el-option label="基准情景" value="baseline" /><el-option label="增长情景" value="growth" /></el-select></label>
        <label><span><CalendarRange aria-hidden="true" />数据粒度</span><div class="segmented"><button :class="{ active: forecastGranularity === 'year' }" @click="forecastGranularity = 'year'">年度</button><button :class="{ active: forecastGranularity === 'month' }" @click="forecastGranularity = 'month'">月度</button></div></label>
        <div class="forecast-export-action">
          <span>趋势报告</span>
          <button class="secondary-btn" :disabled="!exportRole.id || exportingPdf" @click="exportForecastPdf">
            <LoaderCircle aria-hidden="true" v-if="exportingPdf" class="spin" :size="15" />
            <Download aria-hidden="true" v-else :size="15" />
            {{ exportingPdf ? '正在导出' : '导出 PDF' }}
          </button>
        </div>
      </div>
    </section>

    <div v-if="exportError" class="forecast-export-error" role="alert"><CircleAlert aria-hidden="true" :size="15" />{{ exportError }}<button @click="exportError = ''">关闭</button></div>
    <div v-if="error && activeTab !== 'evolution'" class="forecast-error"><CircleAlert aria-hidden="true" /><div><strong>预测数据暂时无法读取</strong><p>{{ error }}</p></div><button class="secondary-btn" @click="loadForecast">重新加载</button></div>

    <div v-if="loading && !result && activeTab === 'occupation'" class="ui-loading" role="status">正在读取岗位排行与预测走势…</div>
    <template v-if="result && activeTab === 'occupation'">
      <section v-if="activeTab === 'occupation'" class="forecast-layout">
        <aside class="forecast-selector"><details class="mobile-forecast-picker"><summary>选择岗位 · {{ selectedOccupation?.roleName || '查看排行' }}</summary></details><header><h2>职业热度排行</h2><p>综合招聘规模、增长速度与跨来源覆盖。</p><el-input v-model="occupationKeyword" class="occupation-forecast-search" clearable placeholder="搜索岗位名称或别名" aria-label="搜索职业热度岗位"><template #prefix><Search aria-hidden="true" /></template></el-input></header><button v-for="(role, index) in result.occupations" :key="role.roleId" :class="{ active: selectedOccupation?.roleId === role.roleId }" @click="chooseOccupation(role.roleId)"><b>{{ index + 1 }}</b><div><strong>{{ role.roleName }}</strong><small>{{ role.industry }} · {{ role.sampleSize }} 条样本</small></div><em>{{ signedNumber(role.changeRate) }}%</em></button><div v-if="!result.occupations.length" class="occupation-search-empty"><Search aria-hidden="true" /><strong>没有匹配的可预测岗位</strong><span>尝试缩短关键词或使用岗位别名。</span></div></aside>
        <main v-if="selectedOccupation" class="forecast-detail"><header class="forecast-detail-head"><div><h2>{{ selectedOccupation.roleName }}</h2><p>{{ selectedOccupation.industry }} · {{ displayedScenarioLabel }} · 未来 {{ displayedHorizon }} 年 · {{ displayedGranularityLabel }}</p></div><div class="forecast-detail-actions"><button class="secondary-btn" @click="askOccupation"><Bot aria-hidden="true" :size="15" />咨询岗位</button><button class="primary-btn" @click="actOnOccupation">以此为目标做诊断<ArrowRight aria-hidden="true" /></button></div></header><div class="forecast-metrics"><article><small>当前热度指数</small><strong>{{ selectedOccupation.currentIndex }}</strong><span>满分 100</span></article><article><small>历史变化速度</small><strong>{{ signedNumber(selectedOccupation.changeRate) }}%</strong><span>历史序列变化</span></article><article><small>预测置信度</small><strong>{{ confidence(selectedOccupation.confidence) }}</strong><span>{{ selectedOccupation.sampleSize }} 条样本支撑</span></article></div><div class="forecast-chart-panel"><header><div><strong>岗位需求走势</strong><small>历史观测与未来趋势</small></div><span>{{ displayedScenarioLabel }}</span></header><ForecastChart :points="selectedOccupation.points" /></div><footer class="forecast-interpretation"><TrendingUp aria-hidden="true" /><div><strong>使用建议</strong><p>结合岗位能力结构和个人差距，安排学习与求职投入顺序。</p></div></footer></main>
        <main v-else class="forecast-detail occupation-detail-empty"><Search aria-hidden="true" /><h2>未找到可预测岗位</h2><p>左侧修改搜索词后即可查看岗位热度与未来走势。</p></main>
      </section>

    </template>

    <SkillEvolutionForecast
      :active="activeTab === 'evolution'"
      :horizon="horizon"
      :scenario="scenario"
      :granularity="forecastGranularity"
    />
  </div>
</template>
