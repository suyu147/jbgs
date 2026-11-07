<script setup lang="ts">
import { computed } from 'vue'
import { chartTheme } from '@/utils/chartTheme'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { RadarChart } from 'echarts/charts'
import { LegendComponent, RadarComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { MatchResult } from '@/types/domain'
import type { WorkStyleAssessment } from '@/stores/workspace'

use([RadarChart, RadarComponent, LegendComponent, TooltipComponent, CanvasRenderer])

const props = withDefaults(defineProps<{ result: MatchResult; workStyle: WorkStyleAssessment; experienceYears?: number; subject?: string; includeWorkStyle?: boolean }>(), { subject: '我的当前能力', includeWorkStyle: true })

const dimensionMap = computed(() => new Map(props.result.dimensions.map(item => [item.name, item.score])))
const educationProfile = computed(() => props.result.educationProfile)
const roleTargets = computed(() => props.result.radarTargets || {})
const skillTargetFallback = computed(() => Math.max(...props.result.gaps.map(item => Number(item.importance) || 0), 0))
const experienceScore = computed(() => props.experienceYears === undefined
  ? Math.round(props.result.experienceProfile?.current ?? dimensionMap.value.get('experience') ?? 0)
  : Math.round(Math.min(Math.max(props.experienceYears, 0) / 8, 1) * 100))
const workStyleScore = computed(() => Math.round(Object.values(props.workStyle).reduce((sum, value) => sum + Number(value), 0) / 4))
function targetValue(key: 'skills' | 'experience' | 'education' | 'breadth' | 'workStyle', fallback = 0) {
  return Math.max(0, Math.min(Number(roleTargets.value[key] ?? fallback) || 0, 100))
}

const axes = computed(() => [
  { name: '技能', target: targetValue('skills', skillTargetFallback.value), current: Math.round(dimensionMap.value.get('skills') ?? props.result.skillScore ?? 0) },
  { name: '经验', target: targetValue('experience'), current: experienceScore.value },
  {
    name: '学历',
    target: targetValue('education', educationProfile.value?.target || 0),
    current: Math.round(educationProfile.value?.current ?? dimensionMap.value.get('education') ?? 0),
  },
  { name: '能力广度', target: targetValue('breadth'), current: Math.round(props.result.breadthScore || 0) },
  { name: '综合素养', target: targetValue('workStyle'), current: workStyleScore.value },
].filter(axis => props.includeWorkStyle || axis.name !== '综合素养'))

const option = computed(() => ({
  animation: false,
  color: [chartTheme.neutral, chartTheme.primary],
  tooltip: { trigger: 'item', confine: true, backgroundColor: '#143f3b', borderWidth: 0, textStyle: { color: '#fff' } },
  legend: { top: 4, left: 'center', itemWidth: 20, itemHeight: 9, textStyle: { color: '#526c68', fontSize: 12 } },
  radar: {
    center: ['50%', '52%'], radius: '58%', startAngle: 90,
    indicator: axes.value.map(item => ({ name: item.name, max: 100 })),
    axisName: { color: '#45635f', fontSize: 12, lineHeight: 18 },
    splitNumber: 5,
    axisLine: { lineStyle: { color: '#cbdad7' } },
    splitLine: { lineStyle: { color: '#dce6e4' } },
    splitArea: { areaStyle: { color: ['#fbfdfd', '#f4f8f7'] } },
  },
  series: [{
    type: 'radar', symbolSize: 5,
    data: [
      { name: '岗位需求基准', value: axes.value.map(item => item.target), lineStyle: { width: 2, type: 'dashed' }, areaStyle: { opacity: .08 } },
      { name: props.subject, value: axes.value.map(item => item.current), lineStyle: { width: 2.5 }, areaStyle: { opacity: .18 } },
    ],
  }],
}))
</script>

<template>
  <div class="capability-radar-chart">
    <VChart class="radar-canvas" :option="option" autoresize role="img" :aria-label="`岗位需求与${subject}比较雷达图，数值在图下方列出`" /><dl class="radar-values"><div v-for="axis in axes" :key="axis.name"><dt>{{ axis.name }}</dt><dd>要求 {{ Math.round(axis.target) }} · 当前 {{ axis.current }}</dd></div></dl>
  </div>
</template>

<style scoped>
.capability-radar-chart{min-width:0}.radar-canvas{width:100%;height:380px}.capability-radar-chart p{margin:0;padding:10px 14px;background:#f6f9f8;color:#70837f;font-size:10px;line-height:1.6}.capability-radar-chart p strong{color:#466a66}
</style>
