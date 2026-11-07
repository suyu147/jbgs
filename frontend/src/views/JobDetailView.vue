<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowDownRight, ArrowLeft, ArrowUpRight, Award, Banknote, BookOpen, Bot, CircleAlert, ExternalLink, GitBranch, GraduationCap, ListOrdered, MapPin, Mic, Minus, ScrollText, Sparkles, Star, Target, TrendingUp } from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import { insightService } from '@/services/insightService'
import type { JobDetail } from '@/types/domain'
import { useWorkspaceStore } from '@/stores/workspace'
import { useFavoritesStore } from '@/stores/favorites'

const route = useRoute(); const router = useRouter(); const workspace = useWorkspaceStore()
const favorites = useFavoritesStore()
const job = ref<JobDetail | null>(null); const error = ref('')
const rankedSkills = computed(() => [...(job.value?.skills || [])].sort((a, b) => b.weight - a.weight).slice(0, 12))
const maxCityPostings = computed(() => Math.max(...(job.value?.cityMetrics?.map(item => item.postingCount) || [1])))
const maxSalaryBucket = computed(() => Math.max(...(job.value?.salaryBuckets?.map(item => item.count) || [1])))
const assetGroups = computed(() => [
  { key: 'standards', label: '职业标准', icon: ScrollText, items: job.value?.assets?.standards || [] },
  { key: 'certificates', label: '能力证书', icon: Award, items: job.value?.assets?.certificates || [] },
  { key: 'courses', label: '学习课程', icon: BookOpen, items: job.value?.assets?.courses || [] },
  { key: 'majors', label: '相关专业', icon: GraduationCap, items: job.value?.assets?.majors || [] },
].filter(group => group.items.length))

async function loadJob() { try { job.value = await insightService.getJob(String(route.params.id), workspace.location) } catch (reason: any) { error.value = reason.message } }
onMounted(() => Promise.all([loadJob(), favorites.load()]))
watch(() => workspace.location, loadJob)
function analyze(path: string) { if (!job.value) return; workspace.selectTarget(job.value.id, job.value.name); router.push(path) }
function askAssistant() { if (!job.value) return; workspace.selectTarget(job.value.id, job.value.name); router.push({ path: '/assistant', query: { mode: 'career_planning' } }) }
function startInterview() { if (!job.value) return; router.push({ path: '/interview', query: { roleId: job.value.id, roleName: job.value.name } }) }
function back() { window.history.length > 1 ? router.back() : router.push('/jobs') }
function trendIcon(direction?: string) { return direction === 'up' ? ArrowUpRight : direction === 'down' ? ArrowDownRight : direction === 'new' ? Sparkles : Minus }
function demandTier(weight: number) { return weight >= .6 ? '高频核心' : weight >= .35 ? '重点能力' : '补充能力' }
function salaryK(value?: number) { return value ? `${Math.round(value / 1000)}K` : '--' }
async function toggleFavorite() {
  if (!job.value) return
  try { ElMessage.success(await favorites.toggle(job.value) ? '已加入我的收藏' : '已取消收藏') }
  catch (reason: any) { ElMessage.error(reason?.message || '收藏操作失败') }
}
</script>

<template>
  <div class="stack-lg">
    <button class="back-btn" @click="back"><ArrowLeft :size="16" />返回岗位库</button>
    <p v-if="error" class="error-text">{{ error }}</p>
    <template v-if="job">
      <section class="job-identity">
        <div>
          <div class="job-title-badges"><span class="status-chip approved">已治理岗位</span><span v-if="job.discoveryTitle" class="discovery-badge light"><Sparkles :size="12" />{{ job.discoveryTitle }}</span><span :class="['trend-badge', job.trendDirection || 'insufficient']"><component :is="trendIcon(job.trendDirection)" :size="14" />{{ job.trendLabel || '证据不足' }}</span></div>
          <h1>{{ job.name }}</h1>
          <p>{{ job.field || '岗位族待完善' }} · {{ job.marketScope || '全国' }} · {{ job.postingCount }} 条 JD · {{ job.sourceCount }} 个来源</p>
        </div>
        <div class="action-row"><button class="job-detail-favorite" :class="{ active:favorites.isFavorite(job.id) }" :aria-label="favorites.isFavorite(job.id) ? '取消收藏' : '收藏岗位'" @click="toggleFavorite"><Star :size="17" :fill="favorites.isFavorite(job.id) ? 'currentColor' : 'none'" />{{ favorites.isFavorite(job.id) ? '已收藏' : '收藏' }}</button><button class="job-analysis-action" @click="analyze('/graph')"><GitBranch :size="16" />查看完整图谱</button><button class="job-analysis-action" @click="analyze('/forecast?tab=evolution')"><TrendingUp :size="16" />查看演化</button><button class="job-analysis-action" @click="analyze('/matching')"><Target :size="16" />能力诊断</button><button class="job-analysis-action" @click="askAssistant"><Bot :size="16" />咨询此岗位</button><button class="job-analysis-action" @click="startInterview"><Mic :size="16" />模拟面试</button></div>
      </section>

      <section class="detail-grid">
        <div class="panel capability-rank-panel">
          <div class="panel-head"><div><span class="section-code">CAPABILITY DEMAND RANKING</span><h2>职业能力需求排名</h2><p>按招聘 JD 中的技能渗透率排序，先看岗位最常要求什么。</p></div><span class="evidence-count"><ListOrdered :size="14" />{{ job.skills.length }} 项已治理技能</span></div>
          <div class="capability-ranking">
            <article v-for="(skill,index) in rankedSkills" :key="skill.id">
              <b class="capability-rank">{{ String(index + 1).padStart(2,'0') }}</b>
              <div class="capability-name"><strong>{{ skill.name }}</strong><span :class="['demand-tier',skill.weight >= .6 ? 'core' : skill.weight >= .35 ? 'advanced' : 'bonus']">{{ demandTier(skill.weight) }}</span><small>{{ skill.sourceCount || 0 }} 个来源 · {{ skill.evidenceCount || 0 }} 条证据</small></div>
              <div class="capability-demand"><span><i :style="{width:`${Math.round(skill.weight*100)}%`}"></i></span><strong>{{ Math.round(skill.weight * 100) }}%</strong><small>岗位样本渗透率</small></div>
              <p>{{ skill.evidence || '已通过聚合岗位证据确认。' }}</p>
            </article>
          </div>
          <footer class="capability-guidance"><CircleAlert /><div><strong>如何理解努力方向</strong><p>高排名代表市场要求更普遍，不等于你的个人学习顺序。完成能力诊断后，系统会结合已掌握技能、岗位必备程度和趋势信号生成个人优先级。</p></div><button class="primary-btn" @click="analyze('/matching')"><Target :size="15" />生成个人努力清单</button></footer>
        </div>
        <aside class="panel source-panel"><span class="section-code">SOURCE JD</span><h2>正在招聘</h2><a v-for="posting in job.postings" :key="posting.id" :href="posting.url" target="_blank" rel="noreferrer"><div><strong>{{ posting.title }}</strong><small>{{ posting.company || '企业已脱敏' }} · {{ posting.city || '地区未知' }}</small></div><ExternalLink :size="15" /></a><div v-if="!job.postings.length" class="source-empty">该岗位由已发布定义进入正式图谱，暂无直接 JD 引用。</div></aside>
      </section>

      <section class="market-detail-grid">
        <article class="panel market-overview-panel">
          <div class="panel-head"><div><span class="section-code">LOCATION & SALARY</span><h2>{{ job.marketScope || '全国' }}就业市场概览</h2><p>基于有效招聘 JD 聚合，薪资统一为税前月薪口径。</p></div><span class="market-sample"><Banknote :size="15" />{{ job.salarySampleCount || 0 }} 条有效薪资样本</span></div>
          <div class="market-kpis">
            <span><small>月薪中位数</small><strong>{{ salaryK(job.salaryMedian) }}</strong><em>较平均值更抗极端样本</em></span>
            <span><small>主流薪资区间</small><strong>{{ job.salaryRangeMin ? `${salaryK(job.salaryRangeMin)}–${salaryK(job.salaryRangeMax)}` : '--' }}</strong><em>样本中间集中区间</em></span>
            <span><small>{{ workspace.location ? '当前地区' : '覆盖城市' }}</small><strong>{{ workspace.location || `${job.locationCount || 0} 城` }}</strong><em>{{ workspace.location ? `${job.postingCount} 条地区 JD` : '按需求量统计' }}</em></span>
          </div>
        </article>

        <article class="panel city-ranking-panel">
          <div class="panel-head"><div><span class="section-code">CITY DEMAND</span><h2>城市需求排行</h2><p>展示招聘需求量、占比与城市薪资中位数。</p></div><MapPin :size="20" /></div>
          <div class="city-ranking">
            <div v-for="(city,index) in job.cityMetrics?.slice(0,5)" :key="city.city" :class="{ active: workspace.location === city.city }">
              <b>{{ index + 1 }}</b><strong>{{ city.city }}</strong><span><i :style="{width:`${city.postingCount/maxCityPostings*100}%`}"></i></span><em>{{ city.postingCount }} 条</em><small>{{ salaryK(city.salaryMedian) }}</small>
            </div>
            <p v-if="!job.cityMetrics?.length">暂无可用城市样本。</p>
          </div>
        </article>

        <article class="panel salary-distribution-panel">
          <div class="panel-head"><div><span class="section-code">SALARY DISTRIBUTION</span><h2>薪资区间分布</h2><p>{{ job.marketScope || '全国' }}有效样本的税前月薪分布。</p></div></div>
          <div class="salary-distribution">
            <div v-for="bucket in job.salaryBuckets" :key="bucket.label"><span><i :style="{height:`${Math.max(6,bucket.count/maxSalaryBucket*100)}%`}"></i></span><strong>{{ Math.round(bucket.share*100) }}%</strong><small>{{ bucket.label }}</small></div>
            <p v-if="!job.salaryBuckets?.length">暂无可用薪资样本。</p>
          </div>
        </article>
      </section>

      <section v-if="assetGroups.length" class="panel related-assets">
        <div class="panel-head"><div><span class="section-code">CONNECTED KNOWLEDGE</span><h2>岗位关联知识资产</h2><p>以下内容来自个人端可查询的正式图谱关系。</p></div><button class="secondary-btn" @click="analyze('/graph')"><GitBranch :size="15" />在图谱中展开</button></div>
        <div class="asset-bands"><section v-for="group in assetGroups" :key="group.key"><header><component :is="group.icon" :size="18" /><strong>{{ group.label }}</strong><span>{{ group.items.length }}</span></header><div><span v-for="item in group.items" :key="item.id">{{ item.name }}</span></div></section></div>
      </section>
    </template>
  </div>
</template>
