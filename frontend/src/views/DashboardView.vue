<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  ArrowRight, BriefcaseBusiness, ChevronLeft, ChevronRight,
  Map as MapIcon, MapPin, MessageCircleQuestion, Search,
  SearchCheck, Telescope, TrendingUp,
} from 'lucide-vue-next'
import ForecastChart from '@/components/charts/ForecastChart.vue'
import AssistantRobot from '@/components/assistant/AssistantRobot.vue'
import { useAssistantPopup } from '@/components/assistant/useAssistantPopup'
import { insightService } from '@/services/insightService'
import { apiUrl } from '@/api/client'
import type { ForecastOverview, JobSummary } from '@/types/domain'
import { useAuthStore } from '@/stores/auth'
import { useWorkspaceStore } from '@/stores/workspace'
import { jobVisualTone } from '@/utils/jobVisualTone'

const router = useRouter()
const auth = useAuthStore()
const workspace = useWorkspaceStore()
const forecast = ref<ForecastOverview | null>(null)
const jobs = ref<JobSummary[]>([])
const keyword = ref('')
const selected = computed({
  get: () => workspace.targetRoleId,
  set: (id) => {
    const job = jobs.value.find(item => item.id === id)
    workspace.selectTarget(id, job?.name || id)
  },
})
const scopeLabel = computed(() => workspace.location || '全国')
const scopedIndustries = computed(() => forecast.value?.industries || [])
const scopedHotSkills = computed(() => forecast.value?.hotSkills || [])
const displayedHotSkills = computed(() => {
  const source = scopedHotSkills.value.map(item => ({
    ...item,
    heat: Math.max(0, Math.min(100, Number(item.heat || 0))),
  }))
  const maxHeat = Math.max(...source.map(item => item.heat), 1)
  const skills = source
    .map(item => ({
      ...item,
      demandIndex: item.heat > 0 ? Math.round(Math.sqrt(item.heat / maxHeat) * 100) : 0,
    }))
    .sort((a, b) => b.heat - a.heat || b.roleCount - a.roleCount || a.name.localeCompare(b.name))
    .slice(0, 12)
  const completeRowCount = Math.floor(skills.length / 3) * 3
  return completeRowCount ? skills.slice(0, completeRowCount) : skills
})
const leadingOccupation = computed(() => {
  const occupations = forecast.value?.occupations || []
  if (!workspace.location) return occupations[0]
  const demand = new Map(jobs.value.map(job => [job.id, job.postingCount]))
  return [...occupations].sort((a, b) => (demand.get(b.roleId) || 0) - (demand.get(a.roleId) || 0))[0]
})
const featuredEmergingRoles = computed(() => (forecast.value?.emergingRoles || []).slice(0, 3))
const maxIndustryHeat = computed(() => Math.max(...scopedIndustries.value.map(item => item.heat), 1))
const error = ref('')
const pageHidden = ref(false)
const heroSlide = ref(0)
let heroCarouselTimer: number | undefined
const heroSlides = [
  { key: 'target', title: '岗位匹配', description: '选一个目标岗位，看看还差哪些能力', icon: SearchCheck, className: 'hero-entry-target' },
  { key: 'explore', title: '岗位地图', description: '按城市、行业和技能寻找方向', icon: MapIcon, className: 'hero-entry-explore' },
  { key: 'trends', title: '趋势雷达', description: '看看哪些岗位升温，哪些技能更吃香', icon: TrendingUp, className: 'hero-entry-trends' },
  { key: 'assistant', title: '职业问答', description: '把困惑说出来，整理下一步行动', icon: MessageCircleQuestion, className: 'hero-entry-assistant' },
]
let locationLoadVersion = 0
let expandedRoleLocation = ''

type QuickAssistantMessage = { role: 'user' | 'assistant'; content: string }
const assistantLauncher = ref<HTMLElement | null>(null)
const assistantOpen = ref(false)
const assistantDraft = ref('')
const assistantSending = ref(false)
const assistantMessages = ref<QuickAssistantMessage[]>([
  { role: 'assistant', content: '我是岗位规划助手，帮你理清职业方向～' },
])
const assistantPosition = ref<{ left: number; top: number } | null>(null)
const assistantPopupStyle = useAssistantPopup(assistantLauncher, assistantPosition)
const assistantDrag = ref({ active: false, moved: false, startX: 0, startY: 0, left: 0, top: 0 })
const assistantStyle = computed(() => assistantPosition.value
  ? { left: `${assistantPosition.value.left}px`, top: `${assistantPosition.value.top}px`, right: 'auto', bottom: 'auto' }
  : {})
const assistantPopupPlacement = computed(() => assistantPosition.value && assistantPosition.value.top < 280 ? 'below' : '')
const assistantPopupSide = computed(() => assistantPosition.value && assistantPosition.value.left < 360 ? 'left' : '')
const quickPrompts = ['这个岗位未来几年的发展方向？', '我应该优先学习哪些技能？']

function onVisibilityChange() {
  pageHidden.value = document.hidden
}


function clampAssistantPosition(left: number, top: number) {
  const width = assistantLauncher.value?.offsetWidth || 64
  const height = assistantLauncher.value?.offsetHeight || 64
  return {
    left: Math.max(8, Math.min(window.innerWidth - width - 8, left)),
    top: Math.max(8, Math.min(window.innerHeight - height - 8, top)),
  }
}

function onAssistantPointerDown(event: PointerEvent) {
  if (event.pointerType === 'mouse' && event.button !== 0) return
  const target = event.currentTarget as HTMLElement
  const bounds = target.getBoundingClientRect()
  const position = assistantPosition.value || { left: bounds.left, top: bounds.top }
  assistantPosition.value = position
  assistantDrag.value = { active: true, moved: false, startX: event.clientX, startY: event.clientY, left: position.left, top: position.top }
  target.setPointerCapture?.(event.pointerId)
}

function onAssistantPointerMove(event: PointerEvent) {
  if (!assistantDrag.value.active) return
  const drag = assistantDrag.value
  const moved = Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) > 5
  assistantDrag.value = { ...drag, moved }
  assistantPosition.value = clampAssistantPosition(drag.left + event.clientX - drag.startX, drag.top + event.clientY - drag.startY)
}

function onAssistantPointerUp(event: PointerEvent) {
  if (!assistantDrag.value.active) return
  const { moved } = assistantDrag.value
  assistantDrag.value = { ...assistantDrag.value, active: false }
  const target = event.currentTarget as HTMLElement
  target.releasePointerCapture?.(event.pointerId)
  if (!moved) assistantOpen.value = !assistantOpen.value
}

async function sendQuickAssistant(prefill?: string) {
  const text = (prefill ?? assistantDraft.value).trim()
  if (!text || assistantSending.value) return
  assistantMessages.value.push({ role: 'user', content: text })
  assistantDraft.value = ''
  const assistantIndex = assistantMessages.value.push({ role: 'assistant', content: '' }) - 1
  assistantSending.value = true
  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => controller.abort(), 12000)
  try {
    const response = await fetch(apiUrl('/agent/chat'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(auth.session?.accessToken ? { Authorization: `Bearer ${auth.session.accessToken}` } : {}) },
      signal: controller.signal,
      body: JSON.stringify({ agentMode: 'career_planning', message: text, sessionId: '', reportId: workspace.matchResult?.reportId || '', roleId: workspace.targetRoleId, roleName: workspace.targetRoleName }),
    })
    if (!response.ok) throw new Error('智能体服务暂不可用')
    const reader = response.body?.getReader()
    if (!reader) throw new Error('浏览器不支持流式响应')
    const decoder = new TextDecoder()
    let buffer = ''
    let streamFinished = false
    const appendBlock = (block: string) => {
      const dataLine = block.split(/\r?\n/).find(line => line.startsWith('data:'))
      if (!dataLine) return
      try {
        const event = JSON.parse(dataLine.slice(5).trim())
        if (event.type === 'token' && typeof event.content === 'string') {
          assistantMessages.value[assistantIndex].content += event.content
        } else if (event.type === 'done') {
          streamFinished = true
        }
      } catch { /* Ignore incomplete SSE frames. */ }
    }
    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
      const blocks = buffer.split(/\r?\n\r?\n/)
      buffer = blocks.pop() || ''
      blocks.forEach(appendBlock)
      if (done || streamFinished) {
        if (streamFinished && !done) await reader.cancel()
        break
      }
    }
    if (buffer.trim()) appendBlock(buffer)
    if (!assistantMessages.value[assistantIndex].content) assistantMessages.value[assistantIndex].content = '我可以继续帮你梳理职业方向、技能差距和学习路径。'
  } catch {
    assistantMessages.value[assistantIndex].content = '暂时无法连接智能体，你可以进入职业助手页面继续咨询。'
  } finally {
    window.clearTimeout(timeoutId)
    assistantSending.value = false
  }
}

onMounted(async () => {
  document.addEventListener('visibilitychange', onVisibilityChange)
  if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    heroCarouselTimer = window.setInterval(() => {
      if (!pageHidden.value) heroSlide.value = (heroSlide.value + 1) % heroSlides.length
    }, 5600)
  }
  const version = ++locationLoadVersion
  try {
      const [jobPage, prediction] = await Promise.all([
      insightService.getJobs({ pageSize: 12, location: workspace.location }), insightService.getForecastOverview(3, 'baseline', 'year', '', workspace.location),
    ])
    if (version !== locationLoadVersion) return
    jobs.value = jobPage.items
    forecast.value = prediction
    if (!selected.value && jobPage.items.length) workspace.selectTarget(jobPage.items[0].id, jobPage.items[0].name)
  } catch (reason: any) {
    error.value = reason.message || '职业洞察数据暂时无法读取'
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('visibilitychange', onVisibilityChange)
  if (heroCarouselTimer) window.clearInterval(heroCarouselTimer)
})


watch(() => workspace.location, async location => {
  const version = ++locationLoadVersion
  expandedRoleLocation = ''
  try {
    const [jobPage, prediction] = await Promise.all([
      insightService.getJobs({ pageSize: 12, location }),
      insightService.getForecastOverview(3, 'baseline', 'year', '', location),
    ])
    if (version !== locationLoadVersion) return
    jobs.value = jobPage.items
    forecast.value = prediction
    if (jobPage.items.length && !jobPage.items.some(item => item.id === selected.value)) {
      workspace.selectTarget(jobPage.items[0].id, jobPage.items[0].name)
    }
  } catch (reason: any) {
    if (version !== locationLoadVersion) return
    error.value = reason.message || '地区岗位数据暂时无法读取'
  }
})

async function ensureRoleOptions(visible: boolean) {
  if (!visible || expandedRoleLocation === workspace.location) return
  const location = workspace.location
  try {
    const page = await insightService.getJobs({ pageSize: 100, location })
    if (location !== workspace.location) return
    jobs.value = page.items
    expandedRoleLocation = location
  } catch { /* The compact role list remains usable when expansion fails. */ }
}

function search() {
  workspace.jobSearchKeyword = keyword.value.trim()
  router.push({ path: '/jobs', query: { keyword: keyword.value.trim() || undefined } })
}
function browseSkill(name: string) {
  workspace.jobSearchKeyword = name
  router.push({ path: '/jobs', query: { keyword: name } })
}
function focusedAction() {
  router.push('/matching')
}
function activateHeroSlide(index: number) {
  heroSlide.value = (index + heroSlides.length) % heroSlides.length
}
function heroCardState(index: number) {
  const offset = (index - heroSlide.value + heroSlides.length) % heroSlides.length
  return {
    'is-active': offset === 0,
    'is-next': offset === 1,
    'is-back': offset === 2,
    'is-prev': offset === 3,
  }
}
function openHeroSlide() {
  const slide = heroSlides[heroSlide.value]
  if (slide.key === 'target') focusedAction()
  else if (slide.key === 'explore') router.push('/jobs')
  else if (slide.key === 'trends') router.push('/forecast')
  else router.push({ path: '/assistant', query: { mode: 'career_planning' } })
}
function salaryK(value?: number) { return value ? `${Math.round(value / 1000)}K` : '--' }
function formatInteger(value?: number) { return new Intl.NumberFormat('zh-CN').format(Math.round(value || 0)) }
function demandLevel(value?: number) {
  const score = Math.max(0, Math.min(100, Number(value || 0)))
  if (score <= 20) return '极低'
  if (score <= 40) return '较低'
  if (score <= 60) return '中等'
  if (score <= 80) return '较高'
  return '极高'
}
function demandTone(value?: number) {
  const score = Math.max(0, Math.min(100, Number(value || 0)))
  if (score <= 20) return 'very-low'
  if (score <= 40) return 'low'
  if (score <= 60) return 'medium'
  if (score <= 80) return 'high'
  return 'very-high'
}
</script>

<template>
  <div class="career-home">
    <section class="career-command">
      <div class="command-inner with-launchpad hero-inner">
        <div class="command-primary">
          <div class="command-copy">
            <h1>岗位观测站</h1>
            <p>不止找工作，更要<span class="hero-emphasis">看见趋势</span>，找到你的<span class="hero-emphasis">下一站</span></p>
          </div>
          <form class="career-search" @submit.prevent="search">
            <Search :size="21" aria-hidden="true" />
            <input v-model="keyword" placeholder="搜索岗位、技能、城市" aria-label="搜索岗位、技能、城市" autocomplete="off" />
            <button type="submit" aria-label="搜索"><ArrowRight :size="17" aria-hidden="true" /></button>
          </form>
          <div class="discovery-shortcuts">
            <span>正在升温：</span>
            <button v-for="skill in scopedHotSkills.slice(0, 5)" :key="skill.name" type="button" @click="browseSkill(skill.name)">{{ skill.name }} <small>{{ skill.change >= 0 ? '+' : '' }}{{ skill.change.toFixed(1) }}pp</small></button>
          </div>
        </div>

        <aside class="hero-scene" :class="{ 'is-paused': pageHidden }" aria-label="岗位分析入口">
          <div class="hero-scene-decor" aria-hidden="true">
            <svg class="hero-network" viewBox="0 0 520 360" preserveAspectRatio="none"><path d="M42 92L142 38L246 112L350 54L472 106M142 38L164 198L246 112L324 238L472 106M42 92L164 198L324 238L472 106" /><circle cx="42" cy="92" r="3" /><circle cx="142" cy="38" r="3" /><circle cx="246" cy="112" r="3" /><circle cx="350" cy="54" r="3" /><circle cx="472" cy="106" r="3" /><circle cx="164" cy="198" r="3" /><circle cx="324" cy="238" r="3" /></svg>
            <svg class="hero-orbit" viewBox="0 0 520 360" preserveAspectRatio="none"><ellipse cx="270" cy="180" rx="220" ry="92" /><ellipse cx="270" cy="180" rx="184" ry="64" transform="rotate(-22 270 180)" /></svg>
            <span class="hero-cube cube-a"></span><span class="hero-cube cube-b"></span><span class="hero-cube cube-c"></span><div class="hero-bars"><i></i><i></i><i></i><i></i></div>
          </div>
          <div class="hero-panels" aria-label="快速入口轮播" aria-live="polite">
            <button class="hero-carousel-arrow hero-carousel-prev" type="button" aria-label="上一个入口" @click.stop="activateHeroSlide(heroSlide - 1)"><ChevronLeft :size="20" aria-hidden="true" /></button>
            <article v-for="(slide, index) in heroSlides" :key="slide.key" :class="['hero-entry-card', slide.className, heroCardState(index)]" :aria-label="slide.title" role="button" :tabindex="heroSlide === index ? 0 : -1" @click="heroSlide === index ? openHeroSlide() : activateHeroSlide(index)" @keydown.enter.prevent="heroSlide === index ? openHeroSlide() : activateHeroSlide(index)">
              <div class="hero-entry-icon"><component :is="slide.icon" :size="28" aria-hidden="true" /></div>
              <div class="hero-entry-copy"><h2>{{ slide.title }}</h2><p>{{ slide.description }}</p></div>
              <el-select v-if="slide.key === 'target'" v-model="selected" class="hero-entry-role-select" filterable placeholder="选择岗位" @click.stop @visible-change="ensureRoleOptions"><el-option v-for="job in jobs" :key="job.id" :label="job.name" :value="job.id" /></el-select>
              <ArrowRight v-else class="hero-entry-arrow" :size="20" aria-hidden="true" />
            </article>
            <button class="hero-carousel-arrow hero-carousel-next" type="button" aria-label="下一个入口" @click.stop="activateHeroSlide(heroSlide + 1)"><ChevronRight :size="20" aria-hidden="true" /></button>
            <div class="hero-carousel-dots" role="tablist" aria-label="入口轮播页签"><button v-for="(_, index) in heroSlides" :key="index" type="button" :class="{ active: heroSlide === index }" :aria-label="`切换到第 ${index + 1} 个入口`" @click.stop="activateHeroSlide(index)"></button></div>
          </div>
        </aside>
      </div>
    </section>
    <div v-if="!forecast && !error" class="ui-loading" role="status">正在整理岗位趋势与招聘证据…</div>

    <section class="home-surface insight-overview">
      <header class="surface-heading">
        <div><h2>{{ scopeLabel }}职业洞察总览</h2></div>
        <div class="overview-heading-meta"><span class="overview-scope"><MapPin aria-hidden="true" :size="14" />{{ scopeLabel }}</span></div>
      </header>

      <div class="insight-matrix">
        <section class="market-pulse">
          <header><div><span>行业需求</span><h3>招聘证据与行业份额变化</h3></div><button @click="router.push('/forecast')">查看完整预测<ArrowRight aria-hidden="true" :size="15" /></button></header>
          <div class="industry-ranking">
            <article v-for="(industry, index) in scopedIndustries" :key="industry.name">
              <b>{{ index + 1 }}</b><strong>{{ industry.name }}</strong>
              <div><i :style="{ width: `${industry.heat / maxIndustryHeat * 100}%` }"></i></div>
              <em :title="`${formatInteger(industry.heat)} 条招聘 JD`"><b>{{ formatInteger(industry.heat) }}</b><small>条 JD</small></em><small class="industry-share-change" :class="{ down: industry.change < 0 }" title="行业招聘份额同比变化"><span>份额</span><b>{{ industry.change >= 0 ? '+' : '' }}{{ industry.change.toFixed(1) }}pp</b></small>
            </article>
          </div>
        </section>

        <section class="occupation-watch">
          <header><div><span>职业热度预测 · {{ scopeLabel }}</span><h3>{{ leadingOccupation?.roleName || '加载中' }}</h3></div><em>未来 {{ forecast?.horizon || 3 }} 年</em></header>
          <ForecastChart v-if="leadingOccupation" :points="leadingOccupation.points" compact />
          <footer><span><i class="observed"></i>历史观测</span><span><i class="projected"></i>预测区间</span></footer>
        </section>

        <aside class="emerging-watch">
          <header><div><span>{{ workspace.location ? '全国新岗位雷达' : '新岗位雷达' }}</span><h3>正在形成的职业信号</h3></div><Telescope aria-hidden="true" /></header>
          <button v-for="role in featuredEmergingRoles" :key="role.id" :data-job-tone="jobVisualTone(role.industry, role.name)" @click="router.push('/jobs?catalog=new')">
            <span :class="`stage-${role.stage}`"></span>
            <div><strong>{{ role.name }}</strong><small>{{ role.industry }} · 预计窗口 {{ role.expectedWindow }}</small></div>
            <ChevronRight aria-hidden="true" :size="16" />
          </button>
          <div class="emerging-watch-footer"><button @click="router.push('/jobs?catalog=new')">查看全部 {{ forecast?.emergingRoles.length || 0 }} 项<ArrowRight aria-hidden="true" :size="15" /></button></div>
        </aside>
      </div>

      <section class="skill-radar-strip">
        <header><div><span>技能需求指数</span><h3>岗位加权需求与趋势变化</h3></div><button @click="router.push('/forecast?tab=skill')">查看能力预测<ArrowRight aria-hidden="true" :size="15" /></button></header>
        <div><button v-for="skill in displayedHotSkills" :key="skill.name" @click="browseSkill(skill.name)"><span><strong>{{ skill.name }}</strong></span><i :title="`${skill.name}需求程度：${demandLevel(skill.demandIndex)}`"><b :style="{ width: `${skill.demandIndex}%` }"></b></i><em><span><small class="skill-index-unit">需求程度</small><b :class="`skill-level-${demandTone(skill.demandIndex)}`" :title="'相对需求程度'">{{ demandLevel(skill.demandIndex) }}</b></span><small class="skill-change" :class="{ up: skill.change > 0, down: skill.change < 0, flat: skill.change === 0 }" title="需求变化百分点">变化 {{ skill.change >= 0 ? '+' : '' }}{{ skill.change.toFixed(1) }}pp</small></em></button></div>
      </section>
    </section>

    <section class="home-surface role-board">
      <header class="surface-heading"><div><h2>值得继续了解的岗位</h2></div><button class="text-btn" @click="router.push('/jobs')">查看全部岗位<ArrowRight aria-hidden="true" :size="15" /></button></header>
      <div class="role-opportunity-list">
        <button v-for="job in jobs.slice(0, 6)" :key="job.id" :data-job-tone="jobVisualTone(job.field, job.name)" :class="{ active: selected === job.id }" @click="router.push(`/jobs/${job.id}`)">
          <div class="role-card-heading"><div><span class="role-field">{{ job.field }}</span><strong>{{ job.name }}</strong></div><span class="role-card-salary"><strong>{{ salaryK(job.salaryMedian) }}</strong><small>月薪中位数</small></span></div>
          <div class="role-market-summary">
            <span><MapPin aria-hidden="true" :size="15" /><small>{{ workspace.location ? '当前地区' : '热门城市' }}</small><strong>{{ workspace.location || job.topCities?.slice(0,3).map(item => item.city).join(' · ') || '地区待补充' }}</strong><em v-if="!workspace.location && job.locationCount">覆盖 {{ job.locationCount }} 城</em></span>
            <span><BriefcaseBusiness aria-hidden="true" :size="15" /><small>市场证据</small><strong>{{ job.postingCount }} 条 JD</strong><em>{{ job.sourceCount }} 个来源</em></span>
          </div>
          <div class="role-card-skills">
            <span v-for="(skill, index) in [...job.skills].sort((a,b) => b.weight-a.weight).slice(0,3)" :key="skill.id"><b><i>{{ index + 1 }}</i>{{ skill.name }}</b><em><i :style="{ width: `${Math.round(skill.weight * 100)}%` }"></i></em><small>{{ Math.round(skill.weight * 100) }}%</small></span>
          </div>
          <footer><span>{{ job.marketScope || '全国' }} · 薪资样本 {{ job.salarySampleCount || 0 }}</span><em :class="job.trendDirection">查看职业名片<ChevronRight aria-hidden="true" :size="13" /></em></footer>
        </button>
      </div>
    </section>

    <aside
      ref="assistantLauncher"
      class="home-ai-launcher"
      :class="{ 'is-dragging': assistantDrag.active, 'popup-below': assistantPopupPlacement, 'popup-left': assistantPopupSide }"
      :style="assistantStyle"
      aria-label="AI职业助手入口"
      @keydown.esc.stop.prevent="assistantOpen = false"
    >
      
      <section v-if="assistantOpen" class="home-ai-chat" :style="assistantPopupStyle" role="dialog" aria-label="快速咨询职业助手">
        <header class="home-ai-chat-header">
          <div><strong>AI职业助手</strong><small>轻量咨询 · 岗位规划助手</small></div>
          <button type="button" aria-label="关闭聊天框" @click="assistantOpen = false">×</button>
        </header>
        <div class="home-ai-chat-messages" aria-live="polite">
          <div v-for="(message, index) in assistantMessages" :key="`${message.role}-${index}`" class="home-ai-chat-message" :class="message.role">
            <span v-if="message.role === 'assistant'" class="home-ai-chat-avatar"><AssistantRobot compact aria-hidden="true" /></span>
            <p>{{ message.content || '正在整理岗位证据…' }}</p>
          </div>
        </div>
        <div class="home-ai-chat-prompts">
          <button v-for="prompt in quickPrompts" :key="prompt" type="button" :disabled="assistantSending" @click="sendQuickAssistant(prompt)">{{ prompt }}</button>
        </div>
        <form class="home-ai-chat-input" @submit.prevent="sendQuickAssistant()">
          <input v-model="assistantDraft" :disabled="assistantSending" placeholder="问问岗位、技能或学习路径" aria-label="输入咨询内容"  name="assistantDraft" autocomplete="off">
          <button type="submit" :disabled="assistantSending || !assistantDraft.trim()">发送</button>
        </form>
        <button class="home-ai-chat-full" type="button" @click="router.push({ path: '/assistant', query: { mode: 'career_planning' } })">进入完整职业助手 <ArrowRight aria-hidden="true" :size="14" /></button>
      </section>

      <button
        type="button"
        class="home-ai-launcher-button"
        :aria-expanded="assistantOpen"
        aria-label="打开AI职业助手"
        title="拖动机器人，单击打开聊天"
        @pointerdown="onAssistantPointerDown"
        @pointermove="onAssistantPointerMove"
        @pointerup="onAssistantPointerUp"
        @pointercancel="onAssistantPointerUp"
        @keydown.enter.prevent="assistantOpen = !assistantOpen"
        @keydown.space.prevent="assistantOpen = !assistantOpen"
      >
        <AssistantRobot compact :busy="assistantSending" :online="true" mode="career_planning" />
        <span class="home-ai-launcher-copy"><strong>AI职业助手</strong><small>单击聊天 · 拖动定位</small></span>
      </button>
    </aside>    <p v-if="error" class="error-text">{{ error }}</p>
  </div>
</template>
