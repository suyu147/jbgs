import { createRouter, createWebHistory } from 'vue-router'
import { readAuthSession } from '@/stores/auth'

type ViewLoader = () => Promise<unknown>

const viewLoaders = {
  login: () => import('@/views/LoginView.vue'),
  workspace: () => import('@/views/DashboardView.vue'),
  jobs: () => import('@/views/JobsView.vue'),
  jobDetail: () => import('@/views/JobDetailView.vue'),
  graph: () => import('@/views/GraphView.vue'),
  forecast: () => import('@/views/ForecastView.vue'),
  matching: () => import('@/views/MatchingView.vue'),
  assistant: () => import('@/views/AssistantView.vue'),
  interview: () => import('@/views/InterviewView.vue'),
  interviewRoom: () => import('@/views/InterviewRoomView.vue'),
  profile: () => import('@/views/ProfileView.vue'),
  favorites: () => import('@/views/FavoritesView.vue'),
  resumes: () => import('@/views/ResumesView.vue'),
  adminDashboard: () => import('@/views/AdminDashboardView.vue'),
  data: () => import('@/views/DataView.vue'),
  reviews: () => import('@/views/ReviewsView.vue'),
  agentRuns: () => import('@/views/AgentRunsView.vue'),
  quality: () => import('@/views/QualityView.vue'),
  enterpriseDashboard: () => import('@/views/EnterpriseDashboardView.vue'),
  enterpriseTalent: () => import('@/views/EnterpriseTalentView.vue'),
  enterpriseJobs: () => import('@/views/EnterpriseJobsView.vue'),
} satisfies Record<string, ViewLoader>

const routeLoaders: Record<string, ViewLoader> = {
  '/login': viewLoaders.login,
  '/': viewLoaders.workspace,
  '/jobs': viewLoaders.jobs,
  '/graph': viewLoaders.graph,
  '/forecast': viewLoaders.forecast,
  '/matching': viewLoaders.matching,
  '/assistant': viewLoaders.assistant,
  '/interview': viewLoaders.interview,
  '/me': viewLoaders.profile,
  '/me/favorites': viewLoaders.favorites,
  '/me/resumes': viewLoaders.resumes,
  '/admin/dashboard': viewLoaders.adminDashboard,
  '/admin/data': viewLoaders.data,
  '/admin/reviews': viewLoaders.reviews,
  '/admin/agent': viewLoaders.agentRuns,
  '/admin/quality': viewLoaders.quality,
  '/enterprise/dashboard': viewLoaders.enterpriseDashboard,
  '/enterprise/talent': viewLoaders.enterpriseTalent,
  '/enterprise/jobs': viewLoaders.enterpriseJobs,
}

const personalPrefetchPaths = ['/', '/jobs', '/graph', '/forecast', '/matching', '/assistant', '/me', '/me/favorites', '/me/resumes']
const adminPrefetchPaths = ['/admin/dashboard', '/admin/data', '/admin/reviews', '/admin/quality']
const enterprisePrefetchPaths = ['/enterprise/dashboard', '/enterprise/talent', '/enterprise/jobs']
const prefetchedLoaders = new WeakSet<ViewLoader>()

function loaderForPath(path: string) {
  const cleanPath = path.split(/[?#]/, 1)[0] || '/'
  if (cleanPath.startsWith('/jobs/')) return viewLoaders.jobDetail
  if (cleanPath.startsWith('/interview/')) return viewLoaders.interviewRoom
  return routeLoaders[cleanPath]
}

export function prefetchRoute(path: string) {
  const loader = loaderForPath(path)
  if (!loader || prefetchedLoaders.has(loader)) return
  prefetchedLoaders.add(loader)
  void loader().catch(() => prefetchedLoaders.delete(loader))
}

export function prefetchPortalRoutes(portal: 'personal' | 'admin' | 'enterprise') {
  const paths = portal === 'admin' ? adminPrefetchPaths : portal === 'enterprise' ? enterprisePrefetchPaths : personalPrefetchPaths
  const schedule = window.requestIdleCallback
    ? (callback: () => void, timeout: number) => window.requestIdleCallback(callback, { timeout })
    : (callback: () => void, timeout: number) => window.setTimeout(callback, Math.min(timeout, 600))
  paths.forEach((path, index) => schedule(() => prefetchRoute(path), 350 + index * 120))
}

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', name: 'login', component: viewLoaders.login, meta: { title: '登录', layout: 'auth' } },
    { path: '/', name: 'workspace', component: viewLoaders.workspace, meta: { title: '职业洞察首页', subtitle: '从市场信号发现方向，从目标岗位开始行动', requiresAuth: true, portal: 'personal' } },
    { path: '/jobs', name: 'jobs', component: viewLoaders.jobs, meta: { title: '岗位库', subtitle: '', requiresAuth: true, portal: 'personal', showRoleContext: false } },
    { path: '/jobs/:id', name: 'job-detail', component: viewLoaders.jobDetail, meta: { title: '岗位档案', subtitle: '岗位定义、技能与来源', requiresAuth: true, portal: 'personal', showRoleContext: false } },
    { path: '/graph', name: 'graph', component: viewLoaders.graph, meta: { title: '能力图谱', subtitle: '探索岗位与技能的局部网络', requiresAuth: true, portal: 'personal' } },
    { path: '/forecast', name: 'forecast', component: viewLoaders.forecast, meta: { title: '趋势预测', subtitle: '岗位预测、技能预测与演化曲线', requiresAuth: true, portal: 'personal' } },
    { path: '/evolution', name: 'evolution-legacy', redirect: to => ({ path: '/forecast', query: { ...to.query, tab: 'evolution' } }) },
    { path: '/matching', name: 'matching', component: viewLoaders.matching, meta: { title: '能力诊断', subtitle: '简历解析、人岗匹配与学习路径', requiresAuth: true, portal: 'personal' } },
    { path: '/talent-assessment', redirect: '/matching' },
    { path: '/assistant', name: 'assistant', component: viewLoaders.assistant, meta: { title: '智能助理', subtitle: '基于本地图谱证据回答', requiresAuth: true, portal: 'personal' } },
    { path: '/interview', name: 'interview', component: viewLoaders.interview, meta: { title: '模拟面试准备', subtitle: '确认岗位、简历与自我介绍后开始 AI 模拟面试', requiresAuth: true, portal: 'personal', showRoleContext: false } },
    { path: '/interview/:id', name: 'interview-room', component: viewLoaders.interviewRoom, meta: { title: 'AI 模拟面试', subtitle: '逐题回答，结束后生成面试报告', requiresAuth: true, portal: 'personal', showRoleContext: false } },
    { path: '/me', name: 'me', component: viewLoaders.profile, meta: { title: '我的', subtitle: '管理个人资料、使用视角与简历资产', requiresAuth: true, portal: 'personal', showRoleContext: false, hidePageHeading: true } },
    { path: '/me/favorites', name: 'favorites', component: viewLoaders.favorites, meta: { title: '我的收藏', subtitle: '集中查看收藏的岗位', requiresAuth: true, portal: 'personal', showRoleContext: false } },
    { path: '/me/resumes', name: 'resumes', component: viewLoaders.resumes, meta: { title: '个人简历', subtitle: '上传、预览和管理多份简历', requiresAuth: true, portal: 'personal', showRoleContext: false } },
    { path: '/admin', redirect: '/admin/dashboard' },
    { path: '/admin/dashboard', name: 'admin-dashboard', component: viewLoaders.adminDashboard, meta: { title: '智能治理大屏', subtitle: '数据资产、图谱质量、复核发布与运行状态', requiresAuth: true, portal: 'admin' } },
    { path: '/admin/data', name: 'data', component: viewLoaders.data, meta: { title: '数据资产', subtitle: '正式数据、复核数据与使用边界', requiresAuth: true, portal: 'admin' } },
    { path: '/admin/reviews', name: 'reviews', component: viewLoaders.reviews, meta: { title: '候选复核', subtitle: '人工确认新岗位和能力变化', requiresAuth: true, portal: 'admin' } },
    { path: '/admin/agent', name: 'agent-runs', component: viewLoaders.agentRuns, meta: { title: '智能体编排', subtitle: '查看自动处理进度与草稿描述生成结果', requiresAuth: true, portal: 'admin' } },
    { path: '/admin/quality', name: 'quality', component: viewLoaders.quality, meta: { title: '质量与发布', subtitle: '图谱质量、验收指标和版本边界', requiresAuth: true, portal: 'admin' } },
    { path: '/enterprise', redirect: '/enterprise/dashboard' },
    { path: '/enterprise/dashboard', name: 'enterprise-dashboard', component: viewLoaders.enterpriseDashboard, meta: { title: '市场岗位洞察', subtitle: '识别招聘市场变化，校准人才引进优先级', requiresAuth: true, portal: 'enterprise' } },
    { path: '/enterprise/talent', name: 'enterprise-talent', component: viewLoaders.enterpriseTalent, meta: { title: '人才库与批量诊断', subtitle: '集中管理简历，并按目标岗位批量评估候选人', requiresAuth: true, portal: 'enterprise' } },
    { path: '/enterprise/jobs', name: 'enterprise-jobs', component: viewLoaders.enterpriseJobs, meta: { title: '岗位提交', subtitle: '提交企业招聘岗位，经治理管理员复核后发布', requiresAuth: true, portal: 'enterprise' } },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach(to => {
  const session = readAuthSession()
  if (to.meta.requiresAuth && !session) return { path: '/login', query: { portal: String(to.meta.portal || 'personal'), redirect: to.fullPath } }
  if (session && to.meta.portal && session.user.role !== to.meta.portal) {
    return session.user.role === 'admin' ? '/admin/dashboard' : session.user.role === 'enterprise' ? '/enterprise/dashboard' : '/'
  }
  if (to.path === '/login' && session) return session.user.role === 'admin' ? '/admin/dashboard' : session.user.role === 'enterprise' ? '/enterprise/dashboard' : '/'
})
router.afterEach(to => { document.title = `${String(to.meta.title)} - 职能洞察` })
export default router
