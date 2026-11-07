<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Bot, ChevronDown, GitBranch,
  FileText, Home, LocateFixed, LogOut, MapPin, ScanSearch, Search, Star, Target, Telescope, UserRound,
} from 'lucide-vue-next'
import { useAuthStore } from '@/stores/auth'
import { useWorkspaceStore } from '@/stores/workspace'
import { insightService } from '@/services/insightService'
import { prefetchPortalRoutes, prefetchRoute } from '@/router'
import type { JobLocationOption } from '@/types/domain'
import FloatingAssistant from '@/components/assistant/FloatingAssistant.vue'
import BrandLogo from '@/components/BrandLogo.vue'
import provinceRecords from '@/data/chinaProvinces.json'
import cityRecords from '@/data/chinaCities.json'

interface AdministrativeRecord { c: string; n: string; p: string }

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const workspace = useWorkspaceStore()
const pageThemeClass = computed(() => `page-theme-${String(route.name || 'workspace')}`)
const locations = ref<JobLocationOption[]>([])
const locationDialogOpen = ref(false)
const primaryNav = ref<HTMLElement | null>(null)
function revealActiveNavigation() {
  const nav = primaryNav.value
  const active = nav?.querySelector<HTMLElement>('[aria-current="page"]')
  if (!nav || !active || nav.scrollWidth <= nav.clientWidth) return
  const navBox = nav.getBoundingClientRect()
  const activeBox = active.getBoundingClientRect()
  nav.scrollLeft += activeBox.left - navBox.left - (nav.clientWidth - activeBox.width) / 2
}
watch(() => route.path, async () => { await nextTick(); revealActiveNavigation() })
const locationSearch = ref('')
const selectedProvince = ref('')
const selectedProvinceCity = ref('')
const locationError = ref('')
const locationIndexLoading = ref(false)
const pinyinFormatter = shallowRef<typeof import('pinyin-pro')['pinyin']>()
let workspacePrefetchTimer: number | undefined
let targetPrefetchTimer: number | undefined
const screenIntro = computed(() => ({
  '/jobs': [route.query.catalog === 'new' ? '新岗位发现' : '探索适合你的岗位', '从岗位要求和真实招聘证据出发，找到值得继续了解的方向。'],
  '/assistant': ['职业助手', '带着一个具体问题开始，把岗位信息转化为下一步行动。'],
  '/graph': ['看懂岗位与能力的关联', '选择岗位，探索技能要求，再查看每一条关系背后的证据。'],
  '/forecast': ['读懂变化，再做选择', '比较岗位与技能的变化趋势，结合样本与预测区间判断方向。'],
  '/matching': ['找到你的下一项成长重点', '选定目标、补充能力信息，获得差距分析和可执行的学习路径。'],
} as Record<string, string[]>)[route.path])
const pageTitle = computed(() => String(route.meta.title || '职能洞察'))
const pageSubtitle = computed(() => String(route.meta.subtitle || ''))
const suppressPageHeading = computed(() => ['/jobs', '/graph', '/forecast', '/matching', '/assistant']
  .some(path => route.path === path || route.path.startsWith(`${path}/`)))
const audienceLabel = '求职成长'
const pageCode = ''
const items = computed(() => [
  { path: '/', label: '职业首页', icon: Home },
  { path: '/jobs', label: '探索岗位', icon: ScanSearch },
  { path: '/graph', label: '能力图谱', icon: GitBranch },
  { path: '/forecast', label: '趋势预测', icon: Telescope },
  { path: '/matching', label: '能力诊断', icon: Target },
  { path: '/assistant', label: '职业助手', icon: Bot },
])
const contextItems = computed(() => items.value.filter(item => ['/graph', '/forecast', '/matching', '/assistant'].includes(item.path)))
const locationLabel = computed(() => workspace.location || '全国')
const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('')
const nonCityLabels = new Set(['全国', '海外', '广东', '海南', '四川', '湖北', '湖南', '辽宁', '陕西', '甘肃', '内蒙古', '云南省', '广东省', '浙江省', '安徽省', '省直辖行政单位', '越南', '老挝', '苏丹', '赞比亚', '沙特阿拉伯', '刚果(金)'])
const provinces = (provinceRecords as AdministrativeRecord[]).map(item => ({
  code: item.p,
  name: item.n,
  shortName: item.n.replace(/特别行政区|壮族自治区|回族自治区|维吾尔自治区|自治区|省|市$/g, ''),
}))
const municipalityProvinceCodes = new Map([['北京', '11'], ['天津', '12'], ['上海', '31'], ['重庆', '50']])
const locationProvinceAliases = new Map([
  ['雄安新区', '13'], ['辛集', '13'], ['高碑店', '13'], ['晋州', '13'],
  ['张家港', '32'], ['井冈山', '36'], ['共青城', '36'], ['济源', '41'],
  ['文昌', '46'], ['陵水', '46'], ['昌江', '46'], ['万宁', '46'], ['东方', '46'], ['乐东', '46'], ['五指山', '46'],
  ['凯里', '52'], ['楚雄州', '53'], ['伊犁', '65'], ['石河子', '65'], ['克孜勒苏', '65'], ['巴音郭楞', '65'], ['昌吉', '65'],
  ['肇东', '23'],
])
const standardCities = (cityRecords as AdministrativeRecord[])
  .map(item => ({ provinceCode: item.p, name: normalizeAdministrativeName(item.n) }))
  .sort((a, b) => b.name.length - a.name.length)

function normalizeAdministrativeName(value: string) {
  return value.trim().replace(/[·・\s]/g, '').replace(/特别行政区|壮族自治区|回族自治区|维吾尔自治区|自治区|自治州|地区|盟|省|市/g, '')
}

function provinceCodeForLocation(value: string) {
  const normalized = normalizeAdministrativeName(value)
  const explicitProvince = provinces.find(province => value.includes(province.name) || value.includes(province.shortName))
  if (explicitProvince) return explicitProvince.code
  const municipality = [...municipalityProvinceCodes.entries()].find(([name]) => normalized.startsWith(name))
  if (municipality) return municipality[1]
  const aliasedLocation = [...locationProvinceAliases.entries()].find(([name]) => normalized === name || normalized.endsWith(name))
  if (aliasedLocation) return aliasedLocation[1]
  const exactCity = standardCities.find(city => normalized === city.name)
  if (exactCity) return exactCity.provinceCode
  const parentCity = standardCities.find(city => normalized.startsWith(city.name))
  if (parentCity) return parentCity.provinceCode
  return standardCities.find(city => normalized.endsWith(city.name))?.provinceCode || ''
}

const indexedLocations = computed(() => locations.value
  .filter(item => item.value && !nonCityLabels.has(item.label))
  .map(item => {
    const syllables = pinyinFormatter.value
      ? pinyinFormatter.value(item.label, { toneType: 'none', type: 'array' }) as string[]
      : []
    const latinSyllables = syllables.filter(value => /^[a-z]/i.test(value))
    return {
      ...item,
      provinceCode: provinceCodeForLocation(item.label),
      initial: latinSyllables[0]?.charAt(0).toUpperCase() || '#',
      pinyin: latinSyllables.join('').toLowerCase(),
      initials: latinSyllables.map(value => value.charAt(0)).join('').toLowerCase(),
    }
  }))
const availableProvinces = computed(() => provinces
  .map(province => {
    const cityItems = indexedLocations.value.filter(item => item.provinceCode === province.code)
    return { ...province, cityCount: cityItems.length, postingCount: cityItems.reduce((total, item) => total + item.postingCount, 0) }
  })
  .filter(province => province.cityCount > 0)
  .sort((a, b) => b.postingCount - a.postingCount || a.name.localeCompare(b.name, 'zh-CN')))
const availableProvinceCityCount = computed(() => availableProvinces.value.reduce((total, province) => total + province.cityCount, 0))
const provinceCities = computed(() => selectedProvince.value
  ? indexedLocations.value
    .filter(item => item.provinceCode === selectedProvince.value)
    .sort((a, b) => b.postingCount - a.postingCount || a.label.localeCompare(b.label, 'zh-CN'))
  : [])
const popularLocations = computed(() => indexedLocations.value.slice(0, 12))
const filteredLocations = computed(() => {
  const keyword = locationSearch.value.trim().toLowerCase().replace(/\s+/g, '')
  if (!keyword) return indexedLocations.value
  return indexedLocations.value.filter(item => item.label.includes(keyword) || item.pinyin.includes(keyword) || item.initials.includes(keyword))
})
const locationGroups = computed(() => {
  const grouped = new Map<string, typeof indexedLocations.value>()
  filteredLocations.value.forEach(item => {
    const values = grouped.get(item.initial) || []
    values.push(item)
    grouped.set(item.initial, values)
  })
  return [...grouped.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([initial, items]) => ({ initial, items }))
})
const availableInitials = computed(() => new Set(locationGroups.value.map(group => group.initial)))

onMounted(async () => {
  revealActiveNavigation()
  prefetchPortalRoutes('personal')
  workspacePrefetchTimer = window.setTimeout(() => {
    if (auth.user?.role === 'personal') insightService.prefetchPersonalWorkspace({ location: workspace.location, roleId: workspace.targetRoleId })
  }, 450)
  try { locations.value = await insightService.getJobLocations() }
  catch {
    locations.value = []
    locationError.value = '城市数据暂时无法读取，请稍后重试。'
  }
})
onBeforeUnmount(() => {
  if (workspacePrefetchTimer !== undefined) window.clearTimeout(workspacePrefetchTimer)
  if (targetPrefetchTimer !== undefined) window.clearTimeout(targetPrefetchTimer)
})
watch(() => workspace.targetRoleId, roleId => {
  if (!roleId || auth.user?.role !== 'personal') return
  if (targetPrefetchTimer !== undefined) window.clearTimeout(targetPrefetchTimer)
  targetPrefetchTimer = window.setTimeout(() => insightService.prefetchTargetRole(roleId, workspace.location), 250)
})

function navigate(path: string) { router.push(path) }
function isActive(path: string) { return path === '/' ? route.path === '/' : route.path.startsWith(path) }
function selectLocation(value: string) {
  workspace.selectLocation(value)
  selectedProvince.value = value ? provinceCodeForLocation(value) : ''
  selectedProvinceCity.value = value
  locationDialogOpen.value = false
  locationSearch.value = ''
}
async function openLocationDialog() {
  locationSearch.value = ''
  selectedProvince.value = workspace.location ? provinceCodeForLocation(workspace.location) : ''
  selectedProvinceCity.value = workspace.location
  locationDialogOpen.value = true
  if (!pinyinFormatter.value) {
    locationIndexLoading.value = true
    try { pinyinFormatter.value = (await import('pinyin-pro')).pinyin }
    finally { locationIndexLoading.value = false }
  }
}
function selectProvince() {
  selectedProvinceCity.value = ''
}
function selectProvinceLocation() {
  if (selectedProvinceCity.value) selectLocation(selectedProvinceCity.value)
}
function jumpToInitial(initial: string) {
  document.getElementById(`city-group-${initial}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
function formatPostingCount(value: number) { return new Intl.NumberFormat('zh-CN').format(value || 0) }
function prefetchLocation(value: string) { insightService.prefetchLocation(value) }
function logout() {
  auth.logout()
  router.replace({ path: '/login', query: { portal: 'personal' } })
}
</script>

<template>
  <div class="app-shell personal-portal" :class="pageThemeClass">
    <a class="skip-link" href="#workspace-main">跳至主要内容</a>
    <header class="topbar">
      <div class="topbar-inner">
        <button class="brand" aria-label="职能洞察，返回首页" @click="navigate('/')">
          <BrandLogo aria-hidden="true" />
        </button>
        <button class="location-trigger" :class="{ active: locationDialogOpen }" :title="`当前地区：${locationLabel}`" @click="openLocationDialog"><MapPin aria-hidden="true" :size="16" /><span>{{ locationLabel }}</span><ChevronDown aria-hidden="true" :size="13" /></button>
        <nav ref="primaryNav" class="top-nav" :aria-label="`${audienceLabel}主导航`">
          <router-link v-for="item in items" :key="item.path" :to="item.path" :class="{ active: isActive(item.path) }" :aria-current="isActive(item.path) ? 'page' : undefined" @pointerenter="prefetchRoute(item.path)" @focus="prefetchRoute(item.path)">
            <component :is="item.icon" :size="16" aria-hidden="true" />{{ item.label }}
          </router-link>
        </nav>
        <el-dropdown class="user-menu" trigger="click">
          <button class="user-trigger" aria-label="个人中心菜单"><UserRound aria-hidden="true" :size="17" /><span>个人中心</span><ChevronDown aria-hidden="true" :size="14" /></button>
          <template #dropdown><el-dropdown-menu><el-dropdown-item disabled>{{ auth.user?.username }} · {{ audienceLabel }}</el-dropdown-item><el-dropdown-item @click="navigate('/me')"><UserRound aria-hidden="true" :size="15" />账号与资料</el-dropdown-item><el-dropdown-item @click="navigate('/me/favorites')"><Star aria-hidden="true" :size="15" />我的收藏</el-dropdown-item><el-dropdown-item @click="navigate('/me/resumes')"><FileText aria-hidden="true" :size="15" />个人简历</el-dropdown-item><el-dropdown-item divided @click="logout"><LogOut aria-hidden="true" :size="15" />退出登录</el-dropdown-item></el-dropdown-menu></template>
        </el-dropdown>
      </div>
    </header>
    <el-dialog v-model="locationDialogOpen" class="location-dialog" width="min(960px, calc(100vw - 32px))" align-center append-to-body>
      <template #header>
        <div class="location-dialog-heading">
          <span><LocateFixed aria-hidden="true" :size="19" /></span>
          <div><strong>选择关注地区</strong><small>切换后，首页、岗位和趋势数据同步更新</small></div>
          <em>当前：{{ locationLabel }}</em>
        </div>
      </template>
      <div class="location-dialog-body">
        <section class="province-city-picker" aria-labelledby="province-city-heading">
          <header>
            <div><strong id="province-city-heading">按省市选择</strong><small>仅展示当前数据中有招聘记录的城市</small></div>
            <span>{{ availableProvinces.length }} 个省级地区 · {{ availableProvinceCityCount }} 个可选城市</span>
          </header>
          <div>
            <label>
              <span>省份</span>
              <select v-model="selectedProvince" aria-label="选择省份" @change="selectProvince">
                <option value="">请选择省份</option>
                <option v-for="province in availableProvinces" :key="province.code" :value="province.code">{{ province.shortName }}（{{ province.cityCount }}）</option>
              </select>
              <ChevronDown aria-hidden="true" :size="15" />
            </label>
            <span class="province-city-divider" aria-hidden="true">→</span>
            <label :class="{ disabled: !selectedProvince }">
              <span>城市</span>
              <select v-model="selectedProvinceCity" :disabled="!selectedProvince" aria-label="选择城市" @change="selectProvinceLocation">
                <option value="">{{ selectedProvince ? '请选择城市' : '请先选择省份' }}</option>
                <option v-for="city in provinceCities" :key="city.value" :value="city.value">{{ city.label }}（{{ formatPostingCount(city.postingCount) }} 条 JD）</option>
              </select>
              <ChevronDown aria-hidden="true" :size="15" />
            </label>
          </div>
        </section>

        <div class="location-search-row">
          <label><Search aria-hidden="true" :size="18" /><input v-model="locationSearch" placeholder="搜索城市名称、拼音或首字母" aria-label="搜索城市"  name="locationSearch" autocomplete="off"></label>
          <button class="all-location-button" :class="{ selected: !workspace.location }" @click="selectLocation('')"><LocateFixed aria-hidden="true" :size="16" />全国</button>
        </div>

        <section v-if="!locationSearch" class="popular-city-section">
          <header><strong>热门城市</strong><small>按招聘证据数量排序</small></header>
          <div><button v-for="item in popularLocations" :key="item.value" :class="{ selected: workspace.location === item.value }" @pointerenter="prefetchLocation(item.value)" @focus="prefetchLocation(item.value)" @click="selectLocation(item.value)"><span>{{ item.label }}</span><small>{{ formatPostingCount(item.postingCount) }} 条 JD</small></button></div>
        </section>

        <nav v-if="!locationSearch" class="city-alphabet" aria-label="城市首字母索引">
          <span>按拼音</span>
          <button v-for="initial in alphabet" :key="initial" :disabled="!availableInitials.has(initial)" @click="jumpToInitial(initial)">{{ initial }}</button>
        </nav>

        <div v-loading="locationIndexLoading" class="city-directory">
          <section v-for="group in locationGroups" :id="`city-group-${group.initial}`" :key="group.initial" class="city-initial-group">
            <strong>{{ group.initial }}</strong>
            <div><button v-for="item in group.items" :key="item.value" :class="{ selected: workspace.location === item.value }" :title="`${item.label} · ${formatPostingCount(item.postingCount)} 条 JD`" @pointerenter="prefetchLocation(item.value)" @focus="prefetchLocation(item.value)" @click="selectLocation(item.value)"><span>{{ item.label }}</span><small>{{ formatPostingCount(item.postingCount) }}</small></button></div>
          </section>
          <div v-if="!locationGroups.length && !locationError" class="city-empty-state">没有匹配的城市，请更换关键词。</div>
          <div v-if="locationError" class="city-empty-state error">{{ locationError }}</div>
        </div>
      </div>
    </el-dialog>
    <main id="workspace-main" tabindex="-1">
      <header v-if="screenIntro" class="workspace-heading"><h1>{{ screenIntro[0] }}</h1><p>{{ screenIntro[1] }}</p></header>
      <section v-if="route.path !== '/' && !suppressPageHeading && !route.meta.hidePageHeading" class="page-heading">
        <div><span>{{ pageCode }}</span><h1>{{ pageTitle }}</h1><p>{{ pageSubtitle }}</p></div>
        <span v-if="workspace.location" class="page-location-scope"><MapPin aria-hidden="true" :size="14" />当前地区：{{ workspace.location }}</span>
        <aside v-if="workspace.targetRoleId && route.meta.showRoleContext !== false" class="active-role-context">
          <div><small>当前分析岗位</small><strong>{{ workspace.targetRoleName || workspace.targetRoleId }}</strong></div>
          <nav><button v-for="item in contextItems" :key="item.path" :class="{ active: route.path === item.path }" :title="item.label" @pointerenter="prefetchRoute(item.path)" @focus="prefetchRoute(item.path)" @click="navigate(item.path)"><component :is="item.icon" :size="15" />{{ item.label }}</button></nav>
        </aside>
      </section>
      <div class="page-content">
        <router-view v-slot="{ Component, route: activeRoute }">
          <KeepAlive :max="18"><component :is="Component" :key="activeRoute.path" /></KeepAlive>
        </router-view>
      </div>
    </main>
    <FloatingAssistant v-if="route.path !== '/' && route.path !== '/assistant'" />
  </div>
</template>
