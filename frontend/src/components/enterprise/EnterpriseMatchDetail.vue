<script setup lang="ts">
import { computed } from 'vue'
import { Check, CircleHelp, FileCheck2 } from 'lucide-vue-next'
import CapabilityRadarChart from '@/components/charts/CapabilityRadarChart.vue'
import type { EnterpriseAssessmentCandidate } from '@/types/domain'

const props = defineProps<{ candidate: EnterpriseAssessmentCandidate }>()
const result = computed(() => props.candidate.result)
const matched = computed(() => result.value.gaps?.filter(item => item.status === 'matched') || [])
const missing = computed(() => result.value.gaps?.filter(item => item.status !== 'matched') || [])
const workStyle = { adaptability: 70, collaboration: 70, resilience: 70, initiative: 70 }
const dimensionLabel = (value: string) => ({ skills: '岗位能力', education: '学历', experience: '经验', certificates: '证书' } as Record<string,string>)[value] || value
</script>

<template>
  <section class="enterprise-match-detail">
    <header class="candidate-result-head">
      <div class="candidate-score"><strong>{{ candidate.score == null ? '—' : candidate.score }}</strong><span>综合匹配度</span></div>
      <div><small>{{ candidate.candidateCode }} · {{ candidate.fileName }}</small><h2>{{ result.candidateName || candidate.fileName.replace(/\.[^.]+$/, '') }}</h2><p>目标岗位：{{ result.roleName }}</p></div>
      <div class="resume-confidence"><FileCheck2/><span>内容识别置信度</span><strong>{{ result.contentConfidence == null ? '—' : `${result.contentConfidence}%` }}</strong><el-tooltip content="识别置信度仅反映简历内容提取，不参与综合匹配分计算。" placement="bottom"><button class="icon-btn" aria-label="识别置信度说明"><CircleHelp/></button></el-tooltip></div>
    </header>
    <div class="enterprise-dimensions"><div v-for="item in result.dimensions || []" :key="item.name"><span>{{ dimensionLabel(item.name) }}</span><strong>{{ item.score }}%</strong><i><b :style="{ width: `${item.score}%` }"></b></i></div></div>
    <div class="enterprise-analysis-grid">
      <div class="enterprise-radar"><header><h3>岗位能力对比</h3><span>当前岗位动态基准</span></header><CapabilityRadarChart :result="result" :work-style="workStyle" subject="候选人当前能力" :include-work-style="false" /><p class="ui-note">未采集综合素养自评，雷达仅展示已有证据维度。</p></div>
      <div class="enterprise-gap-list">
        <section><header><h3>已匹配能力</h3><span>{{ matched.length }}</span></header><div><p v-for="item in matched" :key="item.skillId"><Check/><strong>{{ item.skill }}</strong></p><small v-if="!matched.length">暂无完全匹配项</small></div></section>
        <section><header><h3>待提升能力</h3><span>{{ missing.length }}</span></header><div><p v-for="item in missing" :key="item.skillId"><i></i><strong>{{ item.skill }}</strong><em>{{ item.status === 'partial' ? '部分匹配' : '待补充' }}</em></p><small v-if="!missing.length">岗位核心能力已覆盖</small></div></section>
      </div>
    </div>
    <p class="confidence-notice">{{ result.confidenceNotice || '识别置信度与人岗匹配分分别衡量内容提取和岗位契合，请结合原始简历核验。' }}</p>
  </section>
</template>

<style scoped>
.enterprise-match-detail{min-width:0}.candidate-result-head{padding:20px;display:grid;grid-template-columns:88px minmax(0,1fr) auto;align-items:center;gap:18px;border-bottom:1px solid #e2ebe9}.candidate-score{width:82px;height:82px;display:grid;place-content:center;text-align:center;border:6px solid #d8eeea;border-top-color:#0f9d8f;border-radius:50%}.candidate-score strong{font-size:25px;line-height:1;color:#173f39}.candidate-score span{margin-top:4px;color:#6d7b77;font-size:9px}.candidate-result-head h2{margin:3px 0;font-size:18px}.candidate-result-head small,.candidate-result-head p{margin:0;color:#73827e;font-size:11px}.resume-confidence{min-width:190px;padding:12px 14px;display:grid;grid-template-columns:24px 1fr auto 16px;align-items:center;gap:6px;background:#f3f9f7;border:1px solid #dbeae7;border-radius:6px}.resume-confidence>svg:first-child{width:20px;color:#0f8d81}.resume-confidence span{font-size:11px;color:#667671}.resume-confidence strong{font-size:18px;color:#e86a3f;font-variant-numeric:tabular-nums}.resume-confidence>svg:last-child{width:14px;color:#899793}.enterprise-dimensions{padding:16px 20px;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;border-bottom:1px solid #e5edeb}.enterprise-dimensions>div{display:grid;grid-template-columns:1fr auto;align-items:center;gap:5px}.enterprise-dimensions span{font-size:11px;color:#6f7e7a}.enterprise-dimensions strong{font-size:13px;color:#20312e}.enterprise-dimensions i{grid-column:1/-1;height:5px;overflow:hidden;background:#e8efed;border-radius:3px}.enterprise-dimensions b{display:block;height:100%;background:#0f9d8f}.enterprise-analysis-grid{display:grid;grid-template-columns:minmax(0,1.2fr) minmax(280px,.8fr);gap:0}.enterprise-radar{min-width:0;padding:18px;border-right:1px solid #e5edeb}.enterprise-radar>header{display:flex;justify-content:space-between}.enterprise-radar h3,.enterprise-gap-list h3{margin:0;font-size:14px}.enterprise-radar header span{color:#7b8985;font-size:10px}.enterprise-radar :deep(.radar-canvas){height:340px}.enterprise-gap-list{padding:18px;display:grid;gap:14px;align-content:start}.enterprise-gap-list section{border:1px solid #e1eae8;border-radius:6px}.enterprise-gap-list section>header{padding:10px 12px;display:flex;justify-content:space-between;background:#f7faf9;border-bottom:1px solid #e5edeb}.enterprise-gap-list section>header span{min-width:22px;height:22px;display:grid;place-items:center;background:#e3f3ef;color:#0b8177;border-radius:4px;font-size:10px}.enterprise-gap-list section>div{max-height:160px;padding:6px 12px;overflow:auto}.enterprise-gap-list p{min-height:32px;margin:0;display:flex;align-items:center;gap:7px;border-bottom:1px solid #edf1f0;font-size:11px}.enterprise-gap-list p svg{width:14px;color:#10a06e}.enterprise-gap-list p>i{width:8px;height:8px;border:2px solid #e86a3f;border-radius:50%}.enterprise-gap-list p em{margin-left:auto;color:#8a9692;font-size:9px;font-style:normal}.enterprise-gap-list small{display:block;padding:12px;color:#82908c;text-align:center}.confidence-notice{margin:0;padding:10px 18px;background:#fff8f3;border-top:1px solid #f2ded2;color:#7d665a;font-size:10px}
@media(max-width:1000px){.candidate-result-head{grid-template-columns:80px 1fr}.resume-confidence{grid-column:1/-1}.enterprise-analysis-grid{grid-template-columns:1fr}.enterprise-radar{border-right:0;border-bottom:1px solid #e5edeb}}
@media(max-width:620px){.enterprise-dimensions{grid-template-columns:1fr 1fr}.candidate-result-head{padding:15px}.enterprise-radar{padding:12px}.enterprise-radar :deep(.radar-canvas){height:300px}}
</style>
