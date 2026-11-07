<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowDownRight, ArrowLeft, ArrowRight, ArrowUpRight, Banknote, BriefcaseBusiness,
  ChevronDown, ChevronUp, MapPin, Minus, RotateCcw, Search, SlidersHorizontal, Sparkles, Star, X,
} from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import { insightService } from '@/services/insightService'
import type { JobFilterOption, JobFilterOptions, JobSummary } from '@/types/domain'
import { useWorkspaceStore } from '@/stores/workspace'
import { useFavoritesStore } from '@/stores/favorites'
import EmergingRolesCatalog from '@/components/jobs/EmergingRolesCatalog.vue'
import { jobVisualTone } from '@/utils/jobVisualTone'

const route = useRoute()
const router = useRouter()
const workspace = useWorkspaceStore()
const favorites = useFavoritesStore()
const catalogMode = ref<'standard' | 'emerging'>('standard')
const emergingTotal = ref(0)
const keyword = ref('')
const searchText = ref('')
const fields = ref<string[]>([])
const skills = ref<string[]>([])
const trends = ref<string[]>([])
const lastSeenBucket = ref('')
const sort = ref('posting_desc')
const page = ref(1)
const pageSize = ref(20)
const jobs = ref<JobSummary[]>([])
const total = ref(0)
const loading = ref(false)
const error = ref('')
const filterError = ref('')
const advancedOpen = ref(false)
const emptyFilters: JobFilterOptions = { fields: [], skills: [], trends: [], postingBuckets: [], sourceCounts: [], lastSeenBuckets: [], sorts: [] }
const options = ref<JobFilterOptions>(emptyFilters)
let loadVersion = 0

function csvQuery(name: string) {
  return String(route.query[name] || '').split(',').map(value => value.trim()).filter(Boolean)
}
function positiveInt(value: unknown, fallback: number) {
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback
}
function hydrateFromRoute() {
  catalogMode.value = route.query.catalog === 'new' ? 'emerging' : 'standard'
  keyword.value = String(route.query.keyword || '').trim()
  searchText.value = keyword.value
  fields.value = csvQuery('fields')
  skills.value = csvQuery('skills')
  trends.value = csvQuery('trends')
  lastSeenBucket.value = String(route.query.lastSeenBucket || '')
  sort.value = String(route.query.sort || 'posting_desc')
  page.value = positiveInt(route.query.page, 1)
  pageSize.value = [20, 40, 80].includes(Number(route.query.pageSize)) ? Number(route.query.pageSize) : 20
  workspace.jobSearchKeyword = keyword.value
  advancedOpen.value ||= Boolean(fields.value.length || skills.value.length || trends.value.length || lastSeenBucket.value)
}
function requestParams() {
  return {
    keyword: keyword.value.trim(), fields: fields.value.join(','), skills: skills.value.join(','),
    trends: trends.value.join(','), lastSeenBucket: lastSeenBucket.value,
    sort: sort.value, page: page.value, pageSize: pageSize.value, location: workspace.location,
  }
}
function routeQuery() {
  const params = requestParams()
  return Object.fromEntries(Object.entries(params).filter(([key, value]) => {
    if (key === 'location' || value === '' || value === 1) return false
    if (key === 'pageSize' && value === 20) return false
    if (key === 'sort' && value === 'posting_desc') return false
    return true
  }).map(([key, value]) => [key, String(value)]))
}
async function setCatalog(mode: 'standard' | 'emerging') {
  catalogMode.value = mode
  if (mode === 'emerging') await router.replace({ path: '/jobs', query: { catalog: 'new' } })
  else await router.replace({ path: '/jobs', query: routeQuery() })
}
async function loadJobs() {
  const version = ++loadVersion
  loading.value = true
  error.value = ''
  try {
    const data = await insightService.getJobs(requestParams())
    if (version !== loadVersion) return
    jobs.value = data.items
    total.value = data.total
    if (page.value > 1 && !data.items.length && data.total > 0) {
      page.value = Math.max(1, Math.ceil(data.total / pageSize.value))
      await commit(false)
    }
  } catch (reason: any) {
    if (version !== loadVersion) return
    jobs.value = []
    total.value = 0
    error.value = reason?.message || '岗位查询失败'
  } finally {
    if (version === loadVersion) loading.value = false
  }
}
async function loadFilters() {
  filterError.value = ''
  try { options.value = await insightService.getJobFilters() }
  catch (reason: any) { filterError.value = reason?.message || '筛选选项加载失败' }
}
async function loadEmergingCount() {
  try {
    const data = await insightService.getForecastOverview(3, 'baseline', 'year', '', workspace.location)
    emergingTotal.value = data.emergingRoles.length
  } catch {
    emergingTotal.value = 0
  }
}
async function commit(resetPage = true) {
  if (resetPage) page.value = 1
  keyword.value = keyword.value.trim()
  workspace.jobSearchKeyword = keyword.value
  const before = route.fullPath
  await router.replace({ path: '/jobs', query: routeQuery() })
  if (route.fullPath === before) await loadJobs()
}
function submitSearch() { keyword.value = searchText.value.trim(); void commit() }
function clearFilters() {
  keyword.value = ''; searchText.value = ''; fields.value = []; skills.value = []; trends.value = []
  lastSeenBucket.value = ''; sort.value = 'posting_desc'
  page.value = 1; pageSize.value = 20
  void commit(false)
}
function optionLabel(group: JobFilterOption[], value: string) {
  return group.find(item => item.value === value)?.label || value
}
const activeFilters = computed(() => [
  ...(keyword.value ? [{ group: 'keyword', value: keyword.value, label: `关键词：${keyword.value}` }] : []),
  ...fields.value.map(value => ({ group: 'fields', value, label: `岗位族：${optionLabel(options.value.fields, value)}` })),
  ...skills.value.map(value => ({ group: 'skills', value, label: `技能：${optionLabel(options.value.skills, value)}` })),
  ...trends.value.map(value => ({ group: 'trends', value, label: optionLabel(options.value.trends, value) })),
  ...(lastSeenBucket.value ? [{ group: 'lastSeenBucket', value: lastSeenBucket.value, label: `活跃：${optionLabel(options.value.lastSeenBuckets, lastSeenBucket.value)}` }] : []),
])
function removeFilter(group: string, value: string) {
  if (group === 'keyword') { keyword.value = ''; searchText.value = '' }
  else if (group === 'lastSeenBucket') lastSeenBucket.value = ''
  else if (group === 'fields') fields.value = fields.value.filter(item => item !== value)
  else if (group === 'skills') skills.value = skills.value.filter(item => item !== value)
  else if (group === 'trends') trends.value = trends.value.filter(item => item !== value)
  void commit()
}
function changePage(next: number) { page.value = next; void commit(false) }
function changePageSize(next: number) { pageSize.value = next; page.value = 1; void commit(false) }
function trendIcon(direction?: string) { return direction === 'up' ? ArrowUpRight : direction === 'down' ? ArrowDownRight : direction === 'new' ? Sparkles : Minus }
function trendEvidenceTitle(job: JobSummary) {
  if (job.trendDirection === 'new') return '该岗位由治理管理员复核并发布为新岗位发现'
  if (job.trendDirection === 'insufficient') return '岗位与岗位族均缺少可比较的时间序列'
  const basis = job.trendBasis === 'role' ? '岗位自身招聘序列' : '同岗位族招聘序列'
  const change = `${Number(job.trendChangePp || 0) >= 0 ? '+' : ''}${Number(job.trendChangePp || 0).toFixed(3)}pp`
  return `${basis} · ${job.trendWindow || '最近两个完整周期'} · 市场份额变化 ${change}`
}
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize.value)))

async function toggleFavorite(job: JobSummary) {
  try { ElMessage.success(await favorites.toggle(job) ? '已加入我的收藏' : '已取消收藏') }
  catch (reason: any) { ElMessage.error(reason?.message || '收藏操作失败') }
}

onMounted(async () => { hydrateFromRoute(); await Promise.all([loadFilters(), loadJobs(), loadEmergingCount(), favorites.load()]) })
watch(() => route.fullPath, () => { hydrateFromRoute(); if (catalogMode.value === 'standard') void loadJobs() })
watch(() => workspace.location, () => { page.value = 1; void loadEmergingCount(); if (catalogMode.value === 'standard') void loadJobs() })
</script>

<template>
  <div class="stack-lg jobs-page">
    <section class="jobs-catalog-switch" aria-label="岗位目录类型">
      <button :class="{ active:catalogMode === 'standard' }" :aria-pressed="catalogMode === 'standard'" @click="setCatalog('standard')"><BriefcaseBusiness aria-hidden="true" /><span><strong>已有岗位</strong><small>浏览 {{ total || '全部' }} 个标准岗位</small></span><ArrowRight aria-hidden="true" /></button>
      <button :class="{ active:catalogMode === 'emerging' }" :aria-pressed="catalogMode === 'emerging'" @click="setCatalog('emerging')"><Sparkles aria-hidden="true" /><span><strong>新岗位发现</strong><small>查看 {{ emergingTotal }} 项岗位发现</small></span><ArrowRight aria-hidden="true" /></button>
    </section>

    <section v-if="catalogMode === 'standard'" class="jobs-filter-shell" aria-label="岗位筛选">
      <div class="jobs-filter-primary">
        <form class="inline-search jobs-search" role="search" @submit.prevent="submitSearch">
          <Search aria-hidden="true" :size="17" /><input v-model="searchText" aria-label="岗位名称或别名" placeholder="搜索岗位名称或别名"  name="searchText" autocomplete="off">
          <button class="primary-btn" type="submit"><Search aria-hidden="true" :size="15" />搜索</button>
        </form>
        <label class="compact-select"><span>排序</span><el-select v-model="sort" aria-label="岗位排序" @change="commit()"><el-option v-for="item in options.sorts" :key="item.value" :label="item.label" :value="item.value" /></el-select></label>
        <button class="secondary-btn advanced-toggle" :aria-expanded="advancedOpen" @click="advancedOpen=!advancedOpen"><SlidersHorizontal aria-hidden="true" :size="16" />高级筛选<ChevronUp aria-hidden="true" v-if="advancedOpen" :size="15" /><ChevronDown aria-hidden="true" v-else :size="15" /></button>
        <span class="result-count">{{ loading ? '查询中' : `${workspace.location || '全国'} · ${total} 个标准岗位` }}</span>
      </div>

      <div v-show="advancedOpen" class="jobs-filter-advanced">
        <label><span>岗位族</span><el-select v-model="fields" multiple filterable collapse-tags collapse-tags-tooltip placeholder="全部岗位族" @change="commit()"><el-option v-for="item in options.fields" :key="item.value" :label="`${item.label}（${item.count}）`" :value="item.value" /></el-select></label>
        <label><span>代表技能 <small>需全部具备</small></span><el-select v-model="skills" multiple filterable collapse-tags collapse-tags-tooltip placeholder="选择技能" @change="commit()"><el-option v-for="item in options.skills" :key="item.value" :label="`${item.label}（${item.count}）`" :value="item.value" /></el-select></label>
        <label><span>发展趋势</span><el-select v-model="trends" multiple collapse-tags placeholder="全部趋势" @change="commit()"><el-option v-for="item in options.trends" :key="item.value" :label="`${item.label}（${item.count}）`" :value="item.value" /></el-select></label>
        <label><span>最近活跃</span><el-select v-model="lastSeenBucket" clearable placeholder="不限" @change="commit()"><el-option v-for="item in options.lastSeenBuckets" :key="item.value" :label="`${item.label}（${item.count}）`" :value="item.value" /></el-select></label>
      </div>

      <div v-if="activeFilters.length" class="active-job-filters" aria-label="已选筛选条件">
        <small>已筛选</small><button v-for="item in activeFilters" :key="`${item.group}-${item.value}`" @click="removeFilter(item.group,item.value)">{{ item.label }}<X aria-hidden="true" :size="12" /></button>
        <button class="clear-job-filters" @click="clearFilters"><RotateCcw aria-hidden="true" :size="13" />清空全部</button>
      </div>
      <p v-if="filterError" class="filter-warning">{{ filterError }}，可重试加载筛选项。<button @click="loadFilters">重试</button></p>
    </section>

    <p v-if="catalogMode === 'standard' && error" class="error-text job-error">{{ error }}<button class="secondary-btn" @click="loadJobs">重新查询</button></p>
    <section v-if="catalogMode === 'standard'" class="job-results" :aria-busy="loading">
      <div v-if="loading" class="job-list-skeleton" aria-label="正在查询本地图谱"><i v-for="item in 7" :key="item"></i></div>
      <template v-else>
        <div v-if="jobs.length" class="job-card-list">
          <article v-for="job in jobs" :key="job.id" class="job-card" :data-job-tone="jobVisualTone(job.field, job.name)">
            <button class="job-card-open" :aria-label="`查看${job.name}岗位详情`" @click="router.push(`/jobs/${job.id}`)">
              <div class="job-card-main">
              <div class="job-card-heading">
                <div class="job-card-title">
                  <span>{{ job.field || '未分类' }}<em v-if="job.discoveryTitle" class="discovery-badge"><Sparkles aria-hidden="true" :size="11" />{{ job.discoveryTitle }}</em></span>
                  <h2>{{ job.name }}</h2>
                </div>
                <div class="job-card-salary"><Banknote aria-hidden="true" :size="18" /><span><strong>{{ job.salaryMedian ? `${Math.round(job.salaryMedian / 1000)}K` : '--' }}</strong><small>月薪中位数</small></span></div>
              </div>
              <div class="job-card-meta">
                <span><MapPin aria-hidden="true" :size="15" />{{ workspace.location || job.topCities?.slice(0, 3).map(item => item.city).join(' · ') || '全国' }}</span>
                <span><BriefcaseBusiness aria-hidden="true" :size="15" />{{ job.postingCount || 0 }} 条 JD</span>
                <span>{{ job.sourceCount || 0 }} 个数据来源</span>
              </div>
              <div class="job-card-skills"><span v-for="skill in job.skills?.slice(0, 4)" :key="skill.id">{{ skill.name }}</span><small v-if="!job.skills?.length">技能数据待补充</small></div>
              </div>
              <aside class="job-card-signal">
                <span v-if="job.trendDirection" :class="['trend-badge', job.trendDirection]" :title="trendEvidenceTitle(job)"><component :is="trendIcon(job.trendDirection)" :size="14" />{{ job.trendLabel }}</span>
                <small>{{ job.salaryRangeMin ? `${Math.round(job.salaryRangeMin / 1000)}K–${Math.round(Number(job.salaryRangeMax || job.salaryRangeMin) / 1000)}K` : '薪资区间待补充' }}</small>
                <ArrowUpRight aria-hidden="true" :size="19" />
              </aside>
            </button>
            <button class="job-favorite-button" :class="{ active:favorites.isFavorite(job.id) }" :aria-label="favorites.isFavorite(job.id) ? `取消收藏${job.name}` : `收藏${job.name}`" :title="favorites.isFavorite(job.id) ? '取消收藏' : '收藏岗位'" @click="toggleFavorite(job)"><Star aria-hidden="true" :size="18" :fill="favorites.isFavorite(job.id) ? 'currentColor' : 'none'" /></button>
          </article>
        </div>
        <div v-else class="job-results-empty empty-state"><Search aria-hidden="true" /><h2>没有匹配岗位</h2><p>减少筛选条件后再试。</p><button v-if="activeFilters.length" class="secondary-btn" @click="clearFilters"><RotateCcw aria-hidden="true" :size="15" />清空筛选</button></div>
      </template>
      <footer v-if="!loading && total" class="job-pagination">
        <span>第 {{page}} / {{pageCount}} 页，共 {{total}} 条</span>
        <label>每页<el-select :model-value="pageSize" aria-label="每页岗位数量" @change="changePageSize"><el-option v-for="size in [20,40,80]" :key="size" :label="`${size} 条`" :value="size" /></el-select></label>
        <nav aria-label="岗位分页"><button class="icon-btn" title="上一页" aria-label="上一页岗位" :disabled="page<=1" @click="changePage(page-1)"><ArrowLeft aria-hidden="true" :size="17" /></button><button class="icon-btn" title="下一页" aria-label="下一页岗位" :disabled="page>=pageCount" @click="changePage(page+1)"><ArrowRight aria-hidden="true" :size="17" /></button></nav>
      </footer>
    </section>
    <EmergingRolesCatalog v-else @count="emergingTotal = $event" />
  </div>
</template>
