<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { PieChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([PieChart, TitleComponent, TooltipComponent, CanvasRenderer])

interface DonutDatum {
  key: string
  label: string
  value: number
  color: string
}

const props = defineProps<{
  items: DonutDatum[]
  centerLabel: string
}>()

const emit = defineEmits<{ select: [key: string] }>()
const numberFormatter = new Intl.NumberFormat('zh-CN')
const visibleItems = computed(() => props.items.filter(item => item.value > 0))
const total = computed(() => visibleItems.value.reduce((sum, item) => sum + item.value, 0))

const option = computed(() => ({
  animationDuration: 520,
  animationEasing: 'quadraticOut' as const,
  tooltip: {
    trigger: 'item',
    confine: true,
    backgroundColor: '#FFFFFF',
    borderColor: '#E8EEEC',
    borderWidth: 1,
    padding: [9, 12],
    textStyle: { color: '#20312E', fontSize: 12 },
    formatter: (params: any) => `${params.marker}${params.name}<br/><strong>${numberFormatter.format(Number(params.value || 0))}</strong> · ${params.percent}%`,
  },
  title: {
    left: 'center',
    top: 'center',
    text: `{value|${numberFormatter.format(total.value)}}\n{label|${props.centerLabel}}`,
    textStyle: {
      rich: {
        value: { color: '#20312E', fontSize: 24, fontWeight: 700, lineHeight: 30 },
        label: { color: '#5F6F6B', fontSize: 10, fontWeight: 400, lineHeight: 18 },
      },
    },
  },
  series: [{
    type: 'pie',
    radius: ['58%', '82%'],
    center: ['50%', '50%'],
    avoidLabelOverlap: true,
    label: { show: false },
    labelLine: { show: false },
    itemStyle: { borderColor: '#FFFFFF', borderWidth: 2, borderRadius: 2 },
    emphasis: { scale: true, scaleSize: 4, itemStyle: { shadowBlur: 6, shadowColor: 'rgba(32,49,46,.16)' } },
    data: visibleItems.value.length
      ? visibleItems.value.map(item => ({ name: item.label, value: item.value, key: item.key, itemStyle: { color: item.color } }))
      : [{ name: '暂无数据', value: 1, key: 'empty', itemStyle: { color: '#CBD5D1' } }],
  }],
}))

function handleChartClick(params: any) {
  if (params?.data?.key && params.data.key !== 'empty') emit('select', params.data.key)
}
</script>

<template>
  <div class="admin-donut-layout">
    <VChart class="admin-donut-chart" :option="option" autoresize @click="handleChartClick" />
    <div class="admin-donut-legend" aria-label="数据构成明细">
      <button v-for="item in items" :key="item.key" type="button" @click="emit('select', item.key)">
        <i :style="{ backgroundColor:item.color }"></i>
        <span>{{ item.label }}</span>
        <strong>{{ numberFormatter.format(item.value) }}</strong>
      </button>
    </div>
  </div>
</template>
