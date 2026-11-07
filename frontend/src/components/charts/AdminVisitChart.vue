<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{ points:Array<{ period:string; value:number }> }>()
const numberFormatter = new Intl.NumberFormat('zh-CN')

const option = computed(() => ({
  animationDuration: 520,
  animationEasing: 'quadraticOut' as const,
  grid: { top: 13, right: 17, bottom: 28, left: 39 },
  tooltip: {
    trigger: 'axis',
    confine: true,
    backgroundColor: '#FFFFFF',
    borderColor: '#E8EEEC',
    borderWidth: 1,
    padding: [8, 10],
    textStyle: { color:'#20312E', fontSize:11 },
    formatter: (items:any[]) => `${items[0]?.axisValue}<br/>访问 <strong>${numberFormatter.format(Number(items[0]?.value || 0))}</strong> 人次`,
  },
  xAxis: {
    type: 'category',
    boundaryGap: false,
    data: props.points.map(item => item.period),
    axisLine: { lineStyle:{ color:'#CBD5D1' } },
    axisTick: { show:false },
    axisLabel: { color:'#5F6F6B', fontSize:12, interval:'auto', hideOverlap:true, showMinLabel:true, showMaxLabel:true, margin:10 },
  },
  yAxis: {
    type: 'value',
    minInterval: 1,
    axisLine: { show:false },
    axisTick: { show:false },
    axisLabel: { color:'#5F6F6B', fontSize:12 },
    splitLine: { lineStyle:{ color:'#CBD5D1' } },
  },
  series: [{
    type: 'line',
    smooth: .32,
    smoothMonotone: 'x',
    showSymbol: false,
    symbol: 'circle',
    symbolSize: 6,
    lineStyle: { color:'#3B82F6', width:2 },
    itemStyle: { color:'#3B82F6', borderColor:'#FFFFFF', borderWidth:2 },
    areaStyle: {
      color: {
        type: 'linear',
        x: 0, y: 0, x2: 0, y2: 1,
        colorStops: [
          { offset: 0, color: 'rgba(59,130,246,.20)' },
          { offset: 1, color: 'rgba(59,130,246,0)' },
        ],
      },
    },
    emphasis: { focus:'series', scale:1.12 },
    data: props.points.map(item => item.value),
  }],
}))
</script>

<template><VChart class="admin-visit-chart" :option="option" autoresize /></template>
