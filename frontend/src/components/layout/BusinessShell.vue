<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { BarChart3, BriefcaseBusiness, ChevronRight, Database, LayoutDashboard, LogOut, Menu, PanelLeftClose, PanelLeftOpen, ShieldCheck, UserCheck, UsersRound, X } from 'lucide-vue-next'
import { useAuthStore } from '@/stores/auth'
import { prefetchRoute } from '@/router'
import BrandLogo from '@/components/BrandLogo.vue'

const props = defineProps<{ portal: 'enterprise' | 'admin' }>()
const route = useRoute(), router = useRouter(), auth = useAuthStore()
const governance = computed(() => props.portal === 'admin')
const scope = computed(() => governance.value ? '治理管理员后台' : '企业 HR 工作台')
const mobileOpen = ref(false), collapsed = ref(false)
const menuButton = ref<HTMLButtonElement>(), sidebar = ref<HTMLElement>()
const key = `ci-business-navigation-${props.portal}`
try { collapsed.value = localStorage.getItem(key) === 'collapsed' } catch { /* Storage is optional. */ }
const items = computed(() => governance.value ? [
  { path: '/admin/dashboard', label: '智能治理大屏', icon: LayoutDashboard, description: '任务与运行状态' },
  { path: '/admin/data', label: '数据资产', icon: Database, description: '来源、版本与同步' },
  { path: '/admin/reviews', label: '候选复核', icon: UserCheck, description: '核验证据与岗位定义' },
  { path: '/admin/quality', label: '质量与发布', icon: ShieldCheck, description: '验收与发布边界' },
] : [
  { path: '/enterprise/dashboard', label: '市场岗位洞察', icon: BarChart3, description: '市场变化与招聘决策' },
  { path: '/enterprise/talent', label: '人才库与批量诊断', icon: UsersRound, description: '简历与人岗匹配' },
  { path: '/enterprise/jobs', label: '岗位提交', icon: BriefcaseBusiness, description: '招聘需求与提交记录' },
])
watch(collapsed, value => { try { localStorage.setItem(key, value ? 'collapsed' : 'expanded') } catch { /* Optional preference. */ } })
watch(() => route.path, () => { mobileOpen.value = false })
watch(mobileOpen, async value => {
  document.body.style.overflow = value ? 'hidden' : ''
  await nextTick()
  await new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve())))
  if (value) sidebar.value?.querySelector<HTMLElement>('.business-nav-close')?.focus()
  else menuButton.value?.focus()
})
function navKey(event: KeyboardEvent) {
  if (!mobileOpen.value) return
  if (event.key === 'Escape') { event.preventDefault(); mobileOpen.value = false }
  if (event.key !== 'Tab') return
  const elements = [...(sidebar.value?.querySelectorAll<HTMLElement>('a[href],button:not([disabled])') || [])].filter(el => el.getClientRects().length)
  const first = elements[0], last = elements[elements.length - 1]
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
  if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
}
function logout() { auth.logout(); router.replace({ path: '/login', query: { portal: props.portal } }) }
onBeforeUnmount(() => { document.body.style.overflow = '' })
</script>
<template>
  <div class="business-shell" :class="[governance ? 'governance-portal' : 'hr-portal', { 'nav-collapsed': collapsed, 'nav-open': mobileOpen }]">
    <a class="business-skip" href="#business-content">跳转到主要内容</a>
    <button v-if="mobileOpen" class="business-nav-backdrop" aria-label="关闭导航菜单" @click="mobileOpen = false"></button>
    <aside id="business-navigation" ref="sidebar" class="business-sidebar" :role="mobileOpen ? 'dialog' : undefined" :aria-modal="mobileOpen || undefined" :aria-label="scope" @keydown="navKey">
      <RouterLink class="business-brand" :to="governance ? '/admin/dashboard' : '/enterprise/dashboard'" aria-label="职能洞察，返回工作台首页">
        <BrandLogo :compact="collapsed" aria-hidden="true" />
      </RouterLink>
      <button class="business-nav-close" aria-label="关闭导航菜单" @click="mobileOpen = false"><X :size="20"/></button>
      <div class="business-workspace"><component :is="governance ? ShieldCheck : BriefcaseBusiness" :size="18"/><span><strong>{{ scope }}</strong><small>{{ governance ? '复核 · 质量 · 发布' : '市场 · 人才 · 招聘' }}</small></span></div>
      <nav aria-label="主导航"><RouterLink v-for="item in items" :key="item.path" :to="item.path" :aria-label="item.label" :title="collapsed ? item.label : item.description" :aria-current="route.path === item.path ? 'page' : undefined" @pointerenter="prefetchRoute(item.path)" @focus="prefetchRoute(item.path)"><component :is="item.icon" :size="18" aria-hidden="true"/><span>{{ item.label }}</span><ChevronRight v-if="route.path === item.path" class="nav-indicator" :size="14"/></RouterLink></nav>
      <div class="business-nav-bottom"><p>{{ governance ? '证据可追溯，发布有边界。' : '让招聘决策有据可依。' }}</p><button class="business-collapse" :aria-expanded="!collapsed" aria-controls="business-navigation" :aria-label="collapsed ? '展开导航' : '收起导航'" :title="collapsed ? '展开导航' : '收起导航'" @click="collapsed = !collapsed"><PanelLeftOpen v-if="collapsed" :size="18"/><PanelLeftClose v-else :size="18"/><span>收起导航</span></button></div>
      <footer><div class="business-avatar" aria-hidden="true">{{ auth.user?.displayName?.slice(0, 1) }}</div><div class="business-account"><strong>{{ auth.user?.displayName }}</strong><small>{{ scope }}</small></div><button aria-label="退出登录" title="退出登录" @click="logout"><LogOut :size="18"/></button></footer>
    </aside>
    <main class="business-main" :inert="mobileOpen || undefined">
      <header class="business-topbar"><button ref="menuButton" class="business-menu" aria-label="打开导航菜单" :aria-expanded="mobileOpen" aria-controls="business-navigation" @click="mobileOpen = true"><Menu :size="20"/></button><span>{{ scope }}</span><ChevronRight :size="14"/><span>{{ route.meta.title }}</span><span class="business-role"><component :is="governance ? ShieldCheck : BriefcaseBusiness" :size="15"/>{{ governance ? '治理空间' : '企业空间' }}</span></header>
      <div id="business-content" class="business-sheet" tabindex="-1"><header class="business-heading"><div><h1>{{ route.meta.title }}</h1><p>{{ route.meta.subtitle }}</p></div></header><router-view v-slot="{ Component, route: currentRoute }"><KeepAlive :max="8"><component :is="Component" :key="currentRoute.path"/></KeepAlive></router-view></div>
    </main>
  </div>
</template>
