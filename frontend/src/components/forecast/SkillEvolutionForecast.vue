<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowDownRight, ArrowRight, ArrowUpRight, Bot, Sparkles, TrendingUp } from 'lucide-vue-next'
import ForecastChart from '@/components/charts/ForecastChart.vue'
import TrendChart from '@/components/charts/TrendChart.vue'
import { insightService } from '@/services/insightService'
import type { EvolutionData, ForecastOverview, ForecastScenario, JobSummary, SkillForecast, SkillTrend } from '@/types/domain'
import { useWorkspaceStore } from '@/stores/workspace'

type Granularity = 'year' | 'month'
type TrendDirection = 'up' | 'down' | 'stable'
const props = defineProps<{
  active: boolean
  horizon: number
  scenario: ForecastScenario
  granularity: Granularity
}>()
interface HistoricalSignal {
  direction: TrendDirection
  delta: number
  available: boolean
  startPeriod: string
  endPeriod: string
  startValue: number
  endValue: number
}
const route = useRoute()
const workspace = useWorkspaceStore()
const jobs = ref<JobSummary[]>([])
const roleId = ref('')
const granularity = computed(() => props.granularity)
const horizon = computed(() => props.horizon)
const scenario = computed(() => props.scenario)
const trends = ref<EvolutionData>({ series: [], events: [], warning: '' })
const forecast = ref<ForecastOverview | null>(null)
const selectedSkillId = ref('')
const loading = ref(false)
const error = ref('')
let ready = false
let loadVersion = 0
let prefetchTimer: number | undefined

const roleName = computed(() => jobs.value.find(item => item.id === roleId.value)?.name || workspace.targetRoleName || '目标岗位')
const skillForecasts = computed(() => forecast.value?.skills.filter(item => item.roleId === roleId.value) || [])
const historicalSignals = computed(() => {
  const signals = new Map<string, HistoricalSignal>()
  trends.value.series.forEach((series) => {
    const points = series.points.filter(point => Number.isFinite(point.value)).sort((a, b) => a.period.localeCompare(b.period))
    const available = points.length >= 2
    const first = points[0]
    const last = points[points.length - 1]
    const delta = available ? Math.round((last.value - first.value) * 10) / 10 : 0
    const direction: TrendDirection = delta > 0 ? 'up' : delta < 0 ? 'down' : 'stable'
    const signal = {
      direction,
      delta,
      available,
      startPeriod: first?.period || '',
      endPeriod: last?.period || '',
      startValue: first?.value || 0,
      endValue: last?.value || 0,
    }
    if (series.skillId) signals.set(series.skillId, signal)
    signals.set(series.skill, signal)
  })
  return signals
})
const rankedSkills = computed(() => skillForecasts.value
  .filter(skill => historicalSignals.value.get(skill.skillId)?.available || historicalSignals.value.get(skill.skill)?.available)
  .sort((a, b) => {
    const aSignal = historicalSignals.value.get(a.skillId) || historicalSignals.value.get(a.skill)
    const bSignal = historicalSignals.value.get(b.skillId) || historicalSignals.value.get(b.skill)
    return Math.abs(bSignal?.delta || 0) - Math.abs(aSignal?.delta || 0) || b.currentDemand - a.currentDemand
  }))
const selectedSkill = computed<SkillForecast | undefined>(() => skillForecasts.value.find(item => item.skillId === selectedSkillId.value) || rankedSkills.value[0])
const combinedTrends = computed<SkillTrend[]>(() => trends.value.series.map((series) => {
  const projected = skillForecasts.value.find(item => item.skillId === series.skillId || item.skill === series.skill)
  if (!projected) return series
  const futurePoints = projected.points
    .filter(point => point.observed === false)
    .map(point => ({ period: point.period, value: point.value, sampleSize: 0, forecast: true }))
  return { ...series, points: [...series.points.map(point => ({ ...point, forecast: false })), ...futurePoints] }
}))
const displayedScenarioLabel = computed(() => ({ conservative: '保守情景', baseline: '基准情景', growth: '增长情景' }[forecast.value?.scenario || scenario.value]))
const displayedGranularityLabel = computed(() => (forecast.value?.granularity || granularity.value) === 'year' ? '年度' : '月度')
const displayedHorizon = computed(() => forecast.value?.horizon || horizon.value)

async function load() {
  if (!roleId.value) return
  const version = ++loadVersion
  const requestedRoleId = roleId.value
  const requestedGranularity = granularity.value
  const requestedHorizon = horizon.value
  const requestedScenario = scenario.value
  loading.value = true
  error.value = ''
  try {
    const [trendData, forecastData] = await Promise.all([
      insightService.getTrends(requestedRoleId, requestedGranularity),
      insightService.getForecastOverview(requestedHorizon, requestedScenario, requestedGranularity, requestedRoleId),
    ])
    if (version !== loadVersion) return
    trends.value = trendData
    forecast.value = forecastData
    if (!selectedSkillId.value || !skillForecasts.value.some(item => item.skillId === selectedSkillId.value)) {
      selectedSkillId.value = forecastData.skills[0]?.skillId || trendData.series[0]?.skillId || ''
    }
    schedulePrefetch(requestedRoleId, requestedHorizon, requestedScenario, requestedGranularity)
  } catch (reason: any) {
    if (version !== loadVersion) return
    if (!forecast.value) trends.value = { series: [], events: [], warning: '' }
    error.value = reason.message || '技能演化与预测数据暂时无法读取'
  } finally {
    if (version === loadVersion) loading.value = false
  }
}

function schedulePrefetch(currentRoleId: string, currentHorizon: number, currentScenario: ForecastScenario, currentGranularity: Granularity) {
  if (prefetchTimer) window.clearTimeout(prefetchTimer)
  prefetchTimer = window.setTimeout(() => {
    const oppositeGranularity: Granularity = currentGranularity === 'year' ? 'month' : 'year'
    void Promise.allSettled([
      insightService.getTrends(currentRoleId, oppositeGranularity),
      insightService.getForecastOverview(currentHorizon, currentScenario, oppositeGranularity, currentRoleId),
    ])
  }, 40)
}

async function loadJobs() {
  const data = await insightService.getJobs({ pageSize: 100 })
  jobs.value = data.items
  roleId.value = String(route.query.roleId || workspace.targetRoleId || data.items[0]?.id || '')
}

function chooseSkill(id: string) { selectedSkillId.value = id }
function chooseTrendSkill(id: string) { if (id) selectedSkillId.value = id }
function historicalSignal(skill: SkillForecast) {
  return historicalSignals.value.get(skill.skillId) || historicalSignals.value.get(skill.skill) || {
    direction: 'stable', delta: 0, available: false, startPeriod: '', endPeriod: '', startValue: 0, endValue: 0,
  }
}
function signalLabel(signal: HistoricalSignal) {
  if (!signal.available) return '历史数据不足'
  if (signal.direction === 'stable') return '历史曲线稳定 0.0pp'
  return `历史曲线${signal.direction === 'up' ? '上升' : '下降'} ${signed(signal.delta)}pp`
}
function signalSummary(signal: HistoricalSignal) {
  if (!signal.available) return '历史数据不足'
  return `${signal.startPeriod} ${signal.startValue.toFixed(1)}% · ${signal.endPeriod} ${signal.endValue.toFixed(1)}%`
}
function signed(value: number) { return `${value >= 0 ? '+' : ''}${value.toFixed(1)}` }
function confidence(value = 0) { return `${Math.round(value * 100)}%` }

onMounted(async () => {
  try {
    await loadJobs()
    ready = true
    await load()
  } catch (reason: any) {
    error.value = reason.message || '岗位数据暂时无法读取'
  }
})
watch([roleId, granularity, horizon, scenario], () => { if (ready) load() })
onBeforeUnmount(() => {
  loadVersion += 1
  if (prefetchTimer) window.clearTimeout(prefetchTimer)
})
</script>

<template>
  <div class="skill-evolution-workspace">
    <div v-if="loading && !forecast" class="loading-state">正在读取 {{ roleName }} 的技能演化与预测…</div>
    <p v-if="error" class="error-text">{{ error }} <button class="text-btn" @click="load">重新加载</button></p>

    <template v-if="forecast && active">
      <section class="skill-evolution-grid">
        <div class="skill-evolution-main">
          <div class="panel trend-panel"><div class="panel-head"><div><h2>{{ roleName }}技能需求</h2><p>实线为历史需求，虚线为未来 {{ displayedHorizon }} 年预测；点击曲线查看单项详情。</p></div><div class="trend-chart-summary"><span class="trend-series-count">{{ trends.series.length }} 条技能曲线</span><span class="trend-line-key"><i></i>历史<b></b>预测</span></div></div><div v-if="!trends.series.length" class="empty-state trend-empty"><p>当前岗位没有可用趋势快照。</p></div><TrendChart v-else :trends="combinedTrends" @select="chooseTrendSkill" /></div>

          <section v-if="selectedSkill" class="panel skill-forecast-detail">
            <header class="forecast-detail-head">
              <div><h2>{{ selectedSkill.skill }}需求预测</h2><p>{{ roleName }} · 未来 {{ displayedHorizon }} 年 · {{ displayedGranularityLabel }}预测</p></div>
              <div class="forecast-detail-actions">
                <el-select v-model="selectedSkillId" filterable aria-label="选择预测技能" class="skill-detail-select"><el-option v-for="skill in rankedSkills" :key="skill.skillId" :label="skill.skill" :value="skill.skillId" /></el-select>
                <button class="secondary-btn" @click="$router.push('/graph')">查看能力关系<ArrowRight aria-hidden="true" /></button>
                <button class="secondary-btn" @click="$router.push({ path: '/assistant', query: { mode: 'ability_analysis' } })"><Bot aria-hidden="true" :size="15" />解读趋势</button>
              </div>
            </header>
            <div class="forecast-metrics"><article><small>当前需求指数</small><strong>{{ selectedSkill.currentDemand.toFixed(1) }}</strong><span>岗位需求标准化指数（0-100）</span></article><article><small>预测需求指数</small><strong>{{ selectedSkill.futureDemand.toFixed(1) }}</strong><span>未来 {{ displayedHorizon }} 年末中值</span></article><article><small>预测置信度</small><strong>{{ confidence(selectedSkill.confidence) }}</strong><span>来自历史残差与样本量</span></article></div>
            <div class="forecast-chart-panel"><header><div><strong>{{ selectedSkill.skill }}需求预测</strong><small>历史观测与未来趋势</small></div><span>{{ displayedScenarioLabel }}</span></header><ForecastChart :points="selectedSkill.points" unit="%" /></div>
          </section>
          <section v-else class="panel empty-state skill-forecast-empty"><TrendingUp aria-hidden="true" /><h2>选择一条技能曲线</h2><p>从右侧能力排行或图中的曲线选择技能，查看对应预测。</p></section>
        </div>
        <aside class="panel skill-insight-rail">
          <header><h2>能力排行</h2></header>
          <div class="skill-ranking">
            <button v-for="(skill, index) in rankedSkills" :key="skill.skillId" :class="{ active: selectedSkill?.skillId === skill.skillId }" @click="chooseSkill(skill.skillId)">
              <b>{{ index + 1 }}</b>
              <span class="skill-rank-content">
                <i class="skill-trend-arrow" :class="historicalSignal(skill).direction" :title="signalLabel(historicalSignal(skill))" :aria-label="signalLabel(historicalSignal(skill))">
                  <ArrowUpRight aria-hidden="true" v-if="historicalSignal(skill).direction === 'up'" />
                  <ArrowDownRight aria-hidden="true" v-else-if="historicalSignal(skill).direction === 'down'" />
                  <ArrowRight aria-hidden="true" v-else />
                </i>
                <span><strong>{{ skill.skill }}</strong><small>{{ signalSummary(historicalSignal(skill)) }}</small></span>
              </span>
              <em :class="historicalSignal(skill).direction">{{ historicalSignal(skill).available ? `${signed(historicalSignal(skill).delta)}pp` : '--' }}</em>
            </button>
            <p v-if="!rankedSkills.length" class="empty-state compact">当前暂无满足样本条件的单技能预测。</p>
          </div>
          <section v-if="selectedSkill" class="forecast-drivers"><header><Sparkles aria-hidden="true" /><div><strong>主要驱动信号</strong><small>岗位文本、来源覆盖与技能关系</small></div></header><div><span v-for="driver in selectedSkill.drivers" :key="driver">{{ driver }}</span></div></section>
        </aside>
      </section>
    </template>
  </div>
</template>
