<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ArrowRight, RefreshCw, Search } from 'lucide-vue-next'
import ForecastChart from '@/components/charts/ForecastChart.vue'
import UiMetricStrip from '@/components/ui/UiMetricStrip.vue'
import UiState from '@/components/ui/UiState.vue'
import { insightService } from '@/services/insightService'
import type { EnterpriseOverview, ForecastOverview } from '@/types/domain'
const overview = ref<EnterpriseOverview | null>(null), forecast = ref<ForecastOverview | null>(null)
const selectedRole = ref(''), keyword = ref(''), sort = ref('heat'), loading = ref(true), error = ref('')
const occupations = computed(() => [...(forecast.value?.occupations || [])].filter(item => `${item.roleName}${item.industry}`.toLowerCase().includes(keyword.value.trim().toLowerCase())).sort((a,b) => sort.value === 'heat' ? b.currentIndex-a.currentIndex : b.changeRate-a.changeRate))
const selected = computed(() => forecast.value?.occupations.find(item => item.roleId === selectedRole.value) || occupations.value[0] || null)
const metrics = computed(() => [
  { label:'市场观测岗位', value:forecast.value ? forecast.value.occupations.length : null, unit:'类', note:'当前预测覆盖范围' },
  { label:'企业简历库', value:overview.value?.resumeCount, unit:'份', note:'已导入的招聘资产' },
  { label:'已诊断候选人', value:overview.value?.assessedCandidateCount, unit:'人次', note:`累计 ${overview.value?.assessmentBatchCount ?? '—'} 个批次` },
  { label:'平均岗位匹配度', value:overview.value?.averageMatchScore, unit:'%', note:'基于已完成的企业诊断' },
])
async function load() {
 loading.value = true; error.value = ''
 const results = await Promise.allSettled([insightService.getEnterpriseOverview(), insightService.getForecastOverview(3,'baseline','year')])
 if(results[0].status === 'fulfilled') overview.value = results[0].value
 if(results[1].status === 'fulfilled') forecast.value = results[1].value
 if(results.some(item => item.status === 'rejected')) error.value = '部分市场或企业数据读取失败，请重试。'
 loading.value = false
}
onMounted(load)
</script>
<template><div class="enterprise-dashboard">
  <div class="ui-toolbar"><p>{{ forecast ? `预测周期 3 年 · 基准情景 · ${forecast.source === 'prototype' ? '原型估计数据' : '模型预测'}` : '正在读取市场观测与企业诊断数据' }}</p><button class="secondary-btn" :disabled="loading" @click="load"><RefreshCw :size="15"/>{{ loading ? '正在更新…' : '刷新数据' }}</button></div>
  <UiState v-if="error" kind="error" title="部分数据暂时不可用" :description="error" action="重新读取" @action="load"/>
  <UiMetricStrip :items="metrics" :loading="loading && !forecast"/>
  <div class="hr-market-grid">
    <section class="ui-panel"><header class="ui-panel-head"><div><h2>岗位热度排行</h2><p>{{ occupations.length }} 类岗位 · 热度指数 0–100</p></div><select v-model="sort" class="ui-select" aria-label="岗位排序方式"><option value="heat">当前热度</option><option value="change">预测增幅</option></select></header><label class="ui-search"><Search/><span class="sr-only">搜索岗位名称或行业</span><input v-model="keyword" type="search" placeholder="搜索岗位名称或行业"/></label>
      <UiState v-if="loading && !forecast" kind="loading"/>
      <div v-else-if="occupations.length" class="hr-ranking-list"><button v-for="(item,index) in occupations" :key="item.roleId" :aria-pressed="selected?.roleId === item.roleId" @click="selectedRole = item.roleId"><b>{{ index+1 }}</b><span><strong>{{ item.roleName }}</strong><small>样本 {{ item.sampleSize.toLocaleString() }} 条</small><i class="ranking-track" aria-hidden="true"><b :style="{ width:`${Math.max(0,Math.min(100,item.currentIndex))}%` }"></b></i></span><em>{{ sort === 'heat' ? item.currentIndex : `${item.changeRate > 0 ? '+' : ''}${item.changeRate.toFixed(1)}%` }}</em></button></div>
      <UiState v-else title="未找到匹配岗位" description="调整搜索关键词，查看当前市场观测范围。" :action="keyword ? '清空搜索' : undefined" @action="keyword = ''"/>
    </section>
    <section class="ui-panel"><template v-if="selected"><header class="hr-trend-head"><div><h2>{{ selected.roleName }}</h2><p>{{ selected.industry }}</p><p>3 年预测变化 {{ selected.changeRate > 0 ? '+' : '' }}{{ selected.changeRate.toFixed(1) }}% · 置信度 {{ selected.confidence }}%</p></div><div class="hr-trend-value"><span>当前热度</span><strong>{{ selected.currentIndex }}</strong><small>指数</small></div></header><ForecastChart :points="selected.points" unit=" 指数"/><footer class="hr-trend-footer"><p>预测用于比较岗位变化方向，结合样本量与区间判断招聘节奏。</p><RouterLink class="primary-btn" :to="{path:'/enterprise/talent',query:{role:selected.roleId}}">诊断该岗位候选人<ArrowRight :size="15"/></RouterLink></footer></template><UiState v-else :kind="loading ? 'loading' : 'empty'" title="暂无岗位趋势" description="市场观测数据更新后，可在这里比较岗位变化。"/></section>
  </div>
  <section class="ui-panel"><header class="ui-panel-head"><div><h2>最近诊断批次</h2><p>招聘筛选进度与匹配度</p></div><RouterLink to="/enterprise/talent" class="ui-link">管理人才库<ArrowRight :size="14"/></RouterLink></header><div v-if="overview?.recentBatches.length" class="ui-table-scroll" tabindex="0" aria-label="可滚动的最近诊断批次"><table class="ui-table"><thead><tr><th scope="col">目标岗位</th><th scope="col" class="num">已完成 / 候选人数</th><th scope="col" class="num">平均匹配度</th><th scope="col" class="num">创建时间</th></tr></thead><tbody><tr v-for="batch in overview.recentBatches.slice(0,4)" :key="batch.id"><td>{{ batch.roleName }}</td><td class="num">{{ batch.completedCount }} / {{ batch.candidateCount }}</td><td class="num">{{ batch.averageScore }}%</td><td class="num">{{ new Date(batch.createdAt).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}) }}</td></tr></tbody></table></div><UiState v-else :kind="loading ? 'loading' : 'empty'" title="尚无诊断批次" description="导入简历并选择目标岗位，开始第一次批量诊断。"/></section>
</div></template>
