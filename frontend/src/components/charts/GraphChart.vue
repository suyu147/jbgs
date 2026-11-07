<script setup lang="ts">
import { computed, ref } from 'vue'
import { Plus, Minus, Maximize2 } from 'lucide-vue-next'
import { chartTheme, escapeChartText } from '@/utils/chartTheme'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { GraphChart } from 'echarts/charts'
import { LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { GraphData } from '@/types/domain'
use([GraphChart, LegendComponent, TooltipComponent, CanvasRenderer])
const props = defineProps<{ data: GraphData }>()
const emit = defineEmits<{ select: [id: string] }>()
const zoomScale = ref(1)
const fitZoom = computed(() => props.data.nodes.length > 80 ? .65 : props.data.nodes.length > 40 ? .8 : 1)
const chart = ref<InstanceType<typeof VChart>>()
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
const nodeName = (id: string) => props.data.nodes.find(node => node.id === id)?.name || id
function zoomBy(factor: number) {
  zoomScale.value = Math.min(4, Math.max(.35, zoomScale.value * factor))
  chart.value?.setOption({series: [{zoom: zoomScale.value * fitZoom.value}]})
}
function resetView() { zoomScale.value = 1; chart.value?.setOption({series: [{zoom: fitZoom.value, center: ['50%', '50%']}]}) }
const labelsVisible = computed(() => zoomScale.value >= 1.15)
const alwaysShowLabel = (node: GraphData['nodes'][number]) => node.type === 'job' || node.level === '核心能力' || ['certificate', 'standard', 'report'].includes(node.type)
const categoryColors = [chartTheme.text, chartTheme.primary, chartTheme.neutral, chartTheme.comparison, chartTheme.neutral, chartTheme.warning, chartTheme.comparison, chartTheme.comparison, chartTheme.warning, chartTheme.neutral, chartTheme.comparison, chartTheme.primary, chartTheme.primary, chartTheme.neutral, chartTheme.neutral]
const categories = ['岗位', '核心能力', '进阶能力', '加分能力', '招聘记录', '证书', '课程', '专业', '职业标准', '职业要求', '趋势报告', '趋势信号', '趋势主题', '需求快照', '时间周期'].map((name, index) => ({ name, itemStyle: { color: categoryColors[index] } }))
const shortLabel = (name: string) => name.length > 12 ? `${name.slice(0, 11)}…` : name
function categoryOf(node: GraphData['nodes'][number]) {
  if (node.type === 'job') return 0
  if (node.type === 'skill') {
    const tier = String(node.properties?.tier || '')
    if (tier === 'core' || node.level === '核心能力') return 1
    if (tier === 'advanced' || node.level === '进阶能力') return 2
    return 3
  }
  return { posting: 4, certificate: 5, course: 6, major: 7, standard: 8, requirement: 9, report: 10, signal: 11, topic: 12, snapshot: 13, period: 14 }[node.type] ?? 3
}
function symbolOf(type: string) { return ({ job: 'roundRect', posting: 'rect', skill: 'circle', certificate: 'diamond', course: 'roundRect', major: 'triangle', standard: 'diamond', requirement: 'rect', report: 'roundRect', signal: 'pin', topic: 'circle', snapshot: 'triangle', period: 'roundRect' } as Record<string,string>)[type] || 'circle' }
const option = computed(() => ({
  color: chartTheme.palette, animation: false,
  tooltip: { confine: true, backgroundColor: '#143f3b', borderWidth: 0, textStyle: { color: '#fff' }, formatter: (p: any) => p.dataType === 'edge' ? `${escapeChartText(nodeName(p.data.source))} · ${escapeChartText(p.data.value)} · ${escapeChartText(nodeName(p.data.target))}` : `${escapeChartText(p.data.name)}<br/>${escapeChartText(p.data.level || categories[p.data.category].name)}` },
  legend: [{ type: 'scroll', data: [...new Set(props.data.nodes.map(node => categories[categoryOf(node)].name))], top: 10, left: 12, right: 12, pageIconSize: 10, textStyle: { fontSize: 12 } }],
  series: [{ type: 'graph', layout: 'force', zoom: zoomScale.value * fitZoom.value, roam: true, draggable: true, scaleLimit: { min: 0.35 * fitZoom.value, max: 4 * fitZoom.value },
    force: { repulsion: props.data.viewMode === 'stack' ? 470 : 390, edgeLength: props.data.viewMode === 'stack' ? [80, 150] : [90, 165], gravity: .08, layoutAnimation: !reducedMotion },
    label: { show: labelsVisible.value, position: 'right', color: chartTheme.text, fontSize: 12 }, labelLayout: { hideOverlap: true },
    edgeLabel: { show: false },
    lineStyle: { color: 'source', opacity: .42, curveness: .12 }, emphasis: { focus: 'adjacency', label: { show: true }, lineStyle: { width: 3, opacity: .9 } },
    categories,
    data: props.data.nodes.map(n => ({ id: n.id, name: n.name, value: n.value, level: n.level, category: categoryOf(n), itemStyle: { color: categoryColors[categoryOf(n)] }, symbol: symbolOf(n.type), symbolSize: n.type === 'job' ? Math.min(68, Math.max(46, Number(n.value || 50))) : Math.min(46, 25 + Number(n.value || 0) / 6), label: { show: alwaysShowLabel(n) || labelsVisible.value, formatter: shortLabel(n.name) } })),
    links: props.data.edges.map(e => ({ source: e.source, target: e.target, value: e.relation })),
  }],
}))
function onClick(params: any) { if (params.dataType === 'node') emit('select', params.data.id) }
function onGraphRoam(params: any) {
  if (typeof params?.zoom !== 'number' || !Number.isFinite(params.zoom)) return
  zoomScale.value = Math.min(4, Math.max(0.35, zoomScale.value * params.zoom))
}
</script>
<template><div class="graph-visualization"><div class="canvas-controls" aria-label="图谱画布缩放"><button class="icon-btn" aria-label="放大图谱" :disabled="zoomScale >= 4" @click="zoomBy(1.25)"><Plus aria-hidden="true" :size="18" /></button><output aria-live="polite">{{ Math.round(zoomScale * 100) }}%</output><button class="icon-btn" aria-label="缩小图谱" :disabled="zoomScale <= .35" @click="zoomBy(.8)"><Minus aria-hidden="true" :size="18" /></button><button class="icon-btn" aria-label="重置图谱缩放和位置" @click="resetView"><Maximize2 aria-hidden="true" :size="17" /></button></div><VChart ref="chart" class="graph-chart" :option="option" autoresize role="img" :aria-label="`能力关系网络，${data.nodes.length} 个节点。可用画布上方的节点选择控件查看详情。`" @click="onClick" @graphroam="onGraphRoam" /></div></template>
