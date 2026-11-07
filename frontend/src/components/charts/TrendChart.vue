<script setup lang="ts">
import { computed } from 'vue'
import { chartTheme } from '@/utils/chartTheme'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { SkillTrend } from '@/types/domain'

use([LineChart, GridComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{ trends: SkillTrend[] }>()
const emit = defineEmits<{ select: [skillId: string] }>()

const periods = computed(() => Array.from(new Set(
  props.trends.flatMap(trend => trend.points.map(point => point.period)),
)).sort())

const palette = chartTheme.palette

function escapeHtml(value: unknown) {
  return String(value ?? '').replace(/[&<>"']/g, character => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[character] || character))
}

const option = computed(() => ({
  color: palette,
  animation: false,
  animationDuration: 0,
  animationDurationUpdate: 0,
  tooltip: {
    trigger: 'axis',
    confine: true,
    backgroundColor: '#1B3B32',
    borderWidth: 0,
    padding: [10, 12],
    textStyle: { color: '#fff' },
    formatter: (params: any[]) => {
      const period = escapeHtml(params[0]?.axisValue)
      const lines = params
        .filter(item => item.value !== null && item.value !== undefined && !item.data?.forecastAnchor)
        .map(item => `${item.marker}${escapeHtml(item.seriesName)}${String(item.seriesId || '').startsWith('forecast-') ? '（预测）' : ''} <strong>${Number(item.value).toFixed(1)}%</strong>`)
      return [period, ...lines].join('<br/>')
    },
  },
  legend: {
    type: 'scroll',
    top: 2,
    left: 50,
    right: 18,
    itemWidth: 22,
    itemHeight: 9,
    pageIconColor: '#1B3B32',
    pageIconInactiveColor: '#A8ADA9',
    pageTextStyle: { color: '#5B635F' },
    textStyle: { color: '#5B635F', fontSize: 12 },
    data: props.trends.map(trend => trend.skill),
  },
  grid: { top: 62, left: 52, right: 20, bottom: 40 },
  xAxis: {
    type: 'category',
    boundaryGap: false,
    data: periods.value,
    axisLine: { lineStyle: { color: '#E5E5E0' } },
    axisLabel: { color: '#5B635F', fontSize: 12, hideOverlap: true, margin: 12 },
    axisTick: { show: false },
  },
  yAxis: {
    type: 'value',
    min: 0,
    max: 100,
    name: '渗透率 %',
    nameTextStyle: { color: '#5B635F', padding: [0, 0, 8, 0] },
    axisLabel: { color: '#5B635F', fontSize: 12 },
    splitLine: { lineStyle: { color: '#F0F0EC', type: 'solid' } },
  },
  series: props.trends.flatMap((trend, index) => {
    const color = palette[index % palette.length]
    const historicalPoints = trend.points.filter(point => !point.forecast)
    const forecastPoints = trend.points.filter(point => point.forecast)
    const historicalValues = new Map(historicalPoints.map(point => [point.period, point.value]))
    const forecastValues = new Map(forecastPoints.map(point => [point.period, point.value]))
    const lastHistorical = [...historicalPoints].sort((a, b) => a.period.localeCompare(b.period)).at(-1)
    const historical = {
      id: `history-${trend.skillId || trend.skill}`,
      name: trend.skill,
      type: 'line',
      smooth: false,
      smoothMonotone: 'x',
      connectNulls: false,
      showSymbol: false,
      symbol: 'circle',
      symbolSize: 5,
      lineStyle: { width: 2, color },
      itemStyle: { color },
      emphasis: { focus: 'series', lineStyle: { width: 3.6 } },
      data: periods.value.map(period => historicalValues.get(period) ?? null),
    }
    if (!forecastPoints.length || !lastHistorical) return [historical]
    const projected = {
      id: `forecast-${trend.skillId || trend.skill}`,
      name: trend.skill,
      type: 'line',
      smooth: false,
      smoothMonotone: 'x',
      connectNulls: false,
      showSymbol: false,
      symbol: 'circle',
      symbolSize: 5,
      lineStyle: { width: 1.5, color, type: 'dashed', opacity: 0.95 },
      itemStyle: { color },
      emphasis: { focus: 'series', lineStyle: { width: 3.6 } },
      data: periods.value.map(period => {
        if (period === lastHistorical.period) return { value: lastHistorical.value, forecastAnchor: true }
        return forecastValues.get(period) ?? null
      }),
    }
    return [historical, projected]
  }),
}))

function selectSeries(payload: any) {
  const name = String(payload?.seriesName || '')
  const trend = props.trends.find(item => item.skill === name)
  if (trend?.skillId) emit('select', trend.skillId)
}
</script>

<template>
  <div class="trend-visualization"><VChart class="chart" :option="option" autoresize role="img" aria-label="技能渗透率趋势，实线为观测，虚线为预测。下方可查看数据表。" @click="selectSeries" /><details class="chart-data"><summary>查看技能趋势数据</summary><div tabindex="0" aria-label="可滚动的技能趋势数据表"><table><thead><tr><th scope="col">技能</th><th scope="col">时间</th><th scope="col">渗透率</th><th scope="col">类型</th></tr></thead><tbody><template v-for="trend in trends" :key="trend.skillId"><tr v-for="point in trend.points" :key="`${trend.skillId}-${point.period}`"><th scope="row">{{ trend.skill }}</th><td>{{ point.period }}</td><td>{{ point.value }}%</td><td>{{ point.forecast ? '预测' : '观测' }}</td></tr></template></tbody></table></div></details></div>
</template>
