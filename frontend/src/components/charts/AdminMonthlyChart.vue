<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { escapeChartText } from '@/utils/chartTheme'

use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{ points: Array<{period:string;postingCount:number}> }>()
const numberFormatter = new Intl.NumberFormat('zh-CN')
const chart = ref<InstanceType<typeof VChart> | null>(null)
let resizeFrame = 0

function resizeChart() {
  window.cancelAnimationFrame(resizeFrame)
  resizeFrame = window.requestAnimationFrame(() => {
    resizeFrame = window.requestAnimationFrame(() => chart.value?.resize())
  })
}

onMounted(async () => {
  await nextTick()
  resizeChart()
  window.addEventListener('resize', resizeChart)
})
onBeforeUnmount(() => {
  window.cancelAnimationFrame(resizeFrame)
  window.removeEventListener('resize', resizeChart)
})

const option = computed(() => ({
  animation: false,
  animationEasing: 'quadraticOut' as const,
  grid: { top: 18, right: 18, bottom: 10, left: 14, containLabel: true },
  tooltip: {
    trigger: 'axis',
    confine: true,
    backgroundColor: '#FFFFFF',
    borderColor: '#E8EEEC',
    borderWidth: 1,
    padding: [9, 12],
    textStyle: { color: '#20312E', fontSize: 12 },
    formatter: (items: any[]) => `${escapeChartText(items[0]?.axisValue)}<br/>招聘证据 <strong>${numberFormatter.format(Number(items[0]?.value || 0))}</strong> 条`,
  },
  xAxis: {
    type: 'category',
    boundaryGap: false,
    data: props.points.map(item => item.period),
    axisLine: { lineStyle: { color: '#CBD5D1' } },
    axisTick: { show: false },
    axisLabel: {
      color: '#5F6F6B',
      fontSize: 12,
      margin: 12,
      hideOverlap: true,
      showMinLabel: true,
      showMaxLabel: true,
      formatter: (value: string) => value.replace(/^(\d{2})\d{2}-/, '$1/'),
    },
  },
  yAxis: {
    type: 'value',
    minInterval: 1,
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { color: '#5F6F6B', fontSize: 12 },
    splitLine: { lineStyle: { color: '#CBD5D1' } },
  },
  series: [{
    type: 'line',
    smooth: .32,
    smoothMonotone: 'x',
    showSymbol: false,
    symbol: 'circle',
    symbolSize: 7,
    lineStyle: { color: '#8b5cf6', width: 2.5 },
    itemStyle: { color: '#8b5cf6', borderColor: '#FFFFFF', borderWidth: 2 },
    areaStyle: {
      color: {
        type: 'linear',
        x: 0, y: 0, x2: 0, y2: 1,
        colorStops: [
          { offset: 0, color: 'rgba(139,92,246,.22)' },
          { offset: 1, color: 'rgba(139,92,246,.015)' },
        ],
      },
    },
    emphasis: { focus: 'series', scale: 1.15 },
    data: props.points.map(item => item.postingCount),
  }],
}))
</script>

<template><div><VChart ref="chart" class="admin-monthly-chart" :option="option" autoresize role="img" aria-label="有效招聘证据按月原始计数折线图，完整数据见下方表格"/><details class="chart-data"><summary>查看每月原始计数</summary><div tabindex="0" aria-label="每月招聘证据数据表"><table><thead><tr><th scope="col">月份</th><th scope="col">有效记录（条）</th></tr></thead><tbody><tr v-for="point in points" :key="point.period"><th scope="row">{{ point.period }}</th><td>{{ point.postingCount.toLocaleString() }}</td></tr></tbody></table></div></details></div></template>
