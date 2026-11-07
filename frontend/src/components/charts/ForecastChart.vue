<script setup lang="ts">
import { computed } from 'vue'
import { chartTheme, escapeChartText } from '@/utils/chartTheme'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, MarkAreaComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { ForecastPoint } from '@/types/domain'

use([LineChart, GridComponent, MarkAreaComponent, TooltipComponent, CanvasRenderer])

const props = withDefaults(defineProps<{ points: ForecastPoint[]; compact?: boolean; unit?: string }>(), { compact: false, unit: '' })

const option = computed(() => {
  const periods = props.points.map(point => point.period)
  const lastObserved = props.points.reduce((last, point, index) => point.observed ? index : last, 0)
  const firstForecast = Math.min(lastObserved + 1, props.points.length - 1)
  const actual = props.points.map((point, index) => index <= lastObserved ? point.value : null)
  const forecast = props.points.map((point, index) => index >= lastObserved ? point.value : null)
  const lower = props.points.map((point, index) => index >= firstForecast ? point.lower : null)
  const upper = props.points.map((point, index) => index >= firstForecast ? point.upper : null)
  return {
    animation: false,
    animationDuration: 0,
    animationDurationUpdate: 0,
    tooltip: {
      trigger: 'axis', confine: true, backgroundColor: '#102f2d', borderWidth: 0, textStyle: { color: '#fff' },
      formatter: (params: any[]) => {
        const index = params[0]?.dataIndex || 0
        const point = props.points[index]
        if (!point) return ''
        return point.observed
          ? `${escapeChartText(point.period)}<br/>历史观测 <b>${point.value}${escapeChartText(props.unit)}</b>`
          : `${escapeChartText(point.period)}<br/>预测中值 <b>${point.value}${escapeChartText(props.unit)}</b><br/>区间 ${point.lower}–${point.upper}${escapeChartText(props.unit)}`
      },
    },
    grid: props.compact ? { top: 18, left: 38, right: 18, bottom: 26, containLabel: true } : { top: 28, left: 42, right: 24, bottom: 28, containLabel: true },
    xAxis: { type: 'category', boundaryGap: false, data: periods, axisTick: { show: false }, axisLine: { lineStyle: { color: chartTheme.line } }, axisLabel: { color: chartTheme.muted, fontSize: 11, margin: 10, hideOverlap: true, showMinLabel: true, showMaxLabel: true } },
    yAxis: { type: 'value', min: (value: { min: number }) => Math.max(0, Math.floor(value.min / 10) * 10 - 5), max: (value: { max: number }) => Math.min(100, Math.ceil(value.max / 10) * 10 + 5), splitNumber: 4, axisLine: { show: false }, axisTick: { show: false }, axisLabel: { show: true, color: chartTheme.muted, fontSize: 10, margin: 10 }, splitLine: { lineStyle: { color: chartTheme.grid, type: 'dashed' } } },
    series: [
      { name: '历史观测', type: 'line', data: actual, smooth: .32, smoothMonotone: 'x', showSymbol: false, symbol: 'circle', symbolSize: 6, lineStyle: { width: 2.5, color: '#8b5cf6' }, itemStyle: { color: '#8b5cf6' }, areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(139,92,246,.22)' }, { offset: 1, color: 'rgba(139,92,246,.015)' }] } }, emphasis: { focus: 'series', scale: 1.12 } },
      { name: '预测中值', type: 'line', data: forecast, smooth: .32, smoothMonotone: 'x', showSymbol: false, symbol: 'circle', symbolSize: 6, lineStyle: { width: 2, color: '#8b5cf6', type: 'dashed' }, itemStyle: { color: '#8b5cf6' }, areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(139,92,246,.12)' }, { offset: 1, color: 'rgba(139,92,246,.01)' }] } }, emphasis: { focus: 'series', scale: 1.12 } },
      { name: '预测下界', type: 'line', data: lower, smooth: .24, symbol: 'none', lineStyle: { width: 1, color: '#a78bfa', opacity: .7, type: 'dotted' }, tooltip: { show: false } },
      { name: '预测上界', type: 'line', data: upper, smooth: .24, symbol: 'none', lineStyle: { width: 1, color: '#a78bfa', opacity: .7, type: 'dotted' }, tooltip: { show: false } },
    ],
  }
})
</script>

<template>
  <div class="forecast-visualization">
    <div v-if="!compact" class="chart-legend" aria-label="图例"><span><i></i>历史观测</span><span><i class="forecast-line"></i>预测中值</span><span><i class="range-line"></i>预测上下界</span></div>
    <VChart :class="['forecast-chart', { compact }]" :option="option" autoresize role="img" :aria-label="`岗位趋势图，共 ${points.length} 个时间点。实线为观测，虚线为预测。`" />
    <details v-if="!compact" class="chart-data"><summary>查看趋势数据与预测区间</summary><div tabindex="0" aria-label="可滚动的趋势数据表"><table><caption class="sr-only">岗位趋势观测与预测值</caption><thead><tr><th scope="col">时间</th><th scope="col">类型</th><th scope="col">数值{{ unit }}</th><th scope="col">预测区间</th></tr></thead><tbody><tr v-for="point in points" :key="point.period"><th scope="row">{{ point.period }}</th><td>{{ point.observed ? '历史观测' : '预测' }}</td><td>{{ point.value }}</td><td>{{ point.observed ? '—' : `${point.lower}–${point.upper}` }}</td></tr></tbody></table></div></details>
  </div>
</template>
