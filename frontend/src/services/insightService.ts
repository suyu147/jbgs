import { apiClient } from '@/api/client'
import { createPreviewForecast, previewDashboard, previewJobs, previewLocations } from '@/demo/productPreview'
import { DEMO_ACCESS_TOKEN, readAuthSession } from '@/stores/auth'
import type { AdminDashboardSummary, AgentHistoryMessage, AgentSessionSummary, DashboardSummary, DatasetItem, DatasetRevision, EmergingRoleDetail, EnterpriseAssessmentBatch, EnterpriseJobSubmission, EnterpriseOverview, EnterpriseResume, EvolutionData, FavoriteJob, ForecastOverview, ForecastScenario, GraphData, GraphFilterOptions, InterviewAnswerResult, InterviewReport, InterviewSessionState, JobDetail, JobFilterOptions, JobLocationOption, JobSalaryBucket, JobSummary, LearningStage, MatchResult, PageData, ReportContext, ResumeResult, ReviewItem, WorkspaceProfileData } from '@/types/domain'

const data = <T>(request: Promise<any>): Promise<T> => request.then(response => response.data.data)
const isPreview = () => readAuthSession()?.accessToken === DEMO_ACCESS_TOKEN
const responseCache = new Map<string, { expiresAt: number; value: unknown }>()
const pendingRequests = new Map<string, Promise<unknown>>()
let cacheGeneration = 0

function cacheKey(scope: string, params: Record<string, unknown> = {}) {
  return `${scope}:${JSON.stringify(Object.fromEntries(Object.entries(params).sort(([a], [b]) => a.localeCompare(b))))}`
}

function cachedRequest<T>(key: string, request: () => Promise<T>, ttlMs = 60_000): Promise<T> {
  const now = Date.now()
  const cached = responseCache.get(key)
  if (cached && cached.expiresAt > now) return Promise.resolve(cached.value as T)
  const pending = pendingRequests.get(key)
  if (pending) return pending as Promise<T>
  const generation = cacheGeneration
  const task = request()
    .then(value => {
      if (generation === cacheGeneration) responseCache.set(key, { expiresAt: Date.now() + ttlMs, value })
      if (responseCache.size > 160) responseCache.delete(responseCache.keys().next().value as string)
      return value
    })
    .finally(() => pendingRequests.delete(key))
  pendingRequests.set(key, task)
  return task
}

function userCacheKey(scope: string, params: Record<string, unknown> = {}) {
  return cacheKey(`${scope}:user:${readAuthSession()?.user.id || 'anonymous'}`, params)
}

function invalidateReadCache() {
  cacheGeneration += 1
  responseCache.clear()
}

function previewJobPage(params: Record<string, string | number> = {}): PageData<JobSummary> {
  const keyword = String(params.keyword || '').trim().toLowerCase()
  const field = String(params.field || '')
  const location = String(params.location || '').trim()
  const page = Math.max(1, Number(params.page || 1))
  const pageSize = Math.max(1, Number(params.pageSize || 20))
  const sort = String(params.sort || 'posting_desc')
  const filtered = previewJobs
    .filter(item => (!keyword || `${item.name} ${item.field} ${item.skills.map(skill => skill.name).join(' ')}`.toLowerCase().includes(keyword)) && (!field || item.field === field))
    .filter(item => !location || item.topCities?.some(city => city.city === location))
    .map(item => {
      if (!location) return { ...item, marketScope: '全国' }
      const city = item.topCities?.find(metric => metric.city === location)
      return {
        ...item, marketScope: location, postingCount: city?.postingCount || 0,
        locationCount: 1, topCities: city ? [city] : [], salaryMedian: city?.salaryMedian,
        salaryRangeMin: city?.salaryRangeMin, salaryRangeMax: city?.salaryRangeMax,
        salarySampleCount: city?.salarySampleCount,
      }
    })
  const sorted = [...filtered].sort((a, b) => {
    if (sort === 'name_asc') return a.name.localeCompare(b.name, 'zh-CN')
    if (sort === 'last_seen_desc') return String(b.lastSeen || '').localeCompare(String(a.lastSeen || ''))
    if (sort === 'trend_change_desc') return Number(b.trendChangePp || 0) - Number(a.trendChangePp || 0)
    return b.postingCount - a.postingCount
  })
  return { items: sorted.slice((page - 1) * pageSize, page * pageSize), page, pageSize, total: sorted.length }
}

function previewSalaryBuckets(job: JobSummary, location = ''): JobSalaryBucket[] {
  const city = location ? job.topCities?.find(item => item.city === location) : undefined
  if (location && !city) return []
  const median = city?.salaryMedian || job.salaryMedian || 18000
  const sampleCount = city?.salarySampleCount || job.salarySampleCount || 0
  const shares = median >= 22000 ? [.04, .11, .24, .38, .23] : median >= 19000 ? [.07, .17, .29, .34, .13] : [.12, .26, .34, .22, .06]
  const labels = ['10K 以下', '10K–15K', '15K–20K', '20K–30K', '30K 以上']
  return labels.map((label, index) => ({ label, count: Math.round(sampleCount * shares[index]), share: shares[index] }))
}

function previewJobDetail(id: string, location = ''): JobDetail {
  const source = previewJobs.find(item => item.id === id) || previewJobs[0]
  const city = location ? source.topCities?.find(item => item.city === location) : undefined
  const scoped = !location ? { ...source, marketScope: '全国' } : {
    ...source, marketScope: location, postingCount: city?.postingCount || 0, locationCount: city ? 1 : 0,
    topCities: city ? [city] : [], salaryMedian: city?.salaryMedian, salaryRangeMin: city?.salaryRangeMin,
    salaryRangeMax: city?.salaryRangeMax, salarySampleCount: city?.salarySampleCount,
  }
  return {
    ...scoped, postings: [], aliases: [], assets: {}, cityMetrics: source.topCities || [],
    salaryBuckets: previewSalaryBuckets(source, location),
  }
}

const previewInterviewKey = () => `ci_interview_sessions_${readAuthSession()?.user.id || 'preview-user'}`
function readPreviewInterviews(): InterviewSessionState[] {
  try { return JSON.parse(localStorage.getItem(previewInterviewKey()) || '[]') as InterviewSessionState[] } catch { return [] }
}
function writePreviewInterviews(items: InterviewSessionState[]) { localStorage.setItem(previewInterviewKey(), JSON.stringify(items.slice(0, 50))) }
function previewInterviewQuestions(roleName: string, skills: string[], count: number): InterviewSessionState['questions'] {
  const focus = skills.length ? skills : ['问题分析', '沟通协作', '业务理解']
  const templates = ['请结合一个真实项目，说明你如何拆解并解决最具挑战的问题？', '在 {skill} 方面，你做过哪些具体工作？结果如何衡量？', '当需求频繁变化且时间有限时，你会如何安排优先级？', '请举例说明你如何与产品、研发或业务方协作推进工作。', '如果发现上线结果与预期不一致，你会如何定位原因并复盘？', '未来半年你希望在 {skill} 上达到什么水平，准备怎么做？', '面对一个你不熟悉的业务领域，你会如何快速建立判断？', '请介绍一个能体现你专业判断力的决策，并说明依据。']
  return Array.from({ length: Math.max(3, Math.min(count, 8)) }, (_, index) => ({ index, question: templates[index % templates.length].replace('{skill}', focus[index % focus.length]), focus: focus[index % focus.length], answered: false, answer: '', feedback: '', score: null, referencePoints: [`明确说明与${roleName}相关的背景`, '给出行动、结果或可验证证据', '反思并说明后续改进'] }))
}
function previewInterviewEvaluation(answer: string) {
  const score = Math.max(20, Math.min(92, 25 + Math.min(45, Math.floor(answer.length / 3)) + (/[因为因此结果负责通过]/.test(answer) ? 25 : 10) + (/[0-9一二三四五六七八九十]/.test(answer) ? 10 : 0)))
  return { score, feedback: score < 75 ? '回答已覆盖基本思路。建议补充你亲自采取的关键行动、量化结果，以及遇到阻碍时的取舍依据。' : '回答结构清晰，能够说明行动与结果。可以再补充复盘后的改进动作，让经验更具迁移性。' }
}
function previewInterviewReport(session: InterviewSessionState): InterviewReport {
  const scores = session.questions.map(item => item.score || 0); const overallScore = scores.length ? Math.round(scores.reduce((sum, item) => sum + item, 0) / scores.length) : 0
  return { overallScore, summary: `本场共回答 ${session.totalCount} 道问题，综合得分 ${overallScore} 分。建议结合岗位核心技能继续补强。`, dimensions: [{ name: '专业能力', score: Math.min(100, overallScore + 2), comment: '结合岗位技能要求评估专业实践' }, { name: '表达沟通', score: Math.max(0, overallScore - 3), comment: '关注背景、行动与结果是否完整' }, { name: '岗位匹配', score: Math.min(100, overallScore + 1), comment: '结合岗位技能要求评估匹配程度' }], strengths: ['能围绕岗位问题完成连续作答', '愿意结合经验进行复盘'], improvements: ['补充可量化的项目结果', '加强对业务背景和协作影响的说明'], suggestions: ['选择一个代表性项目整理 STAR 案例', '针对岗位核心技能安排一次实操练习'], provider: 'rules' }
}

const previewJobFilters: JobFilterOptions = {
  fields: Array.from(new Set(previewJobs.map(item => item.field))).map(value => ({ value, label: value, count: previewJobs.filter(item => item.field === value).length })),
  skills: Array.from(new Set(previewJobs.flatMap(item => item.skills.map(skill => skill.name)))).map(value => ({ value, label: value, count: previewJobs.filter(item => item.skills.some(skill => skill.name === value)).length })),
  trends: [], postingBuckets: [], sourceCounts: [], lastSeenBuckets: [],
  sorts: [
    { value: 'posting_desc', label: '招聘证据最多', count: previewJobs.length },
    { value: 'last_seen_desc', label: '最近活跃优先', count: previewJobs.length },
    { value: 'trend_change_desc', label: '趋势变化最大', count: previewJobs.length },
    { value: 'name_asc', label: '岗位名称升序', count: previewJobs.length },
  ],
}

export const insightService = {
  isProductPreview: isPreview,
  getDashboard: (): Promise<DashboardSummary> => isPreview() ? Promise.resolve(previewDashboard) : cachedRequest('overview', () => data(apiClient.get('/overview')), 300_000),
  getJobs: (params: Record<string, string | number> = {}): Promise<PageData<JobSummary>> => isPreview()
    ? Promise.resolve(previewJobPage(params))
    : cachedRequest(cacheKey('jobs', params), () => data(apiClient.get('/jobs', { params })), 300_000),
  getJobLocations: (): Promise<JobLocationOption[]> => isPreview()
    ? Promise.resolve(previewLocations)
    : cachedRequest('job-locations', () => data(apiClient.get('/jobs/locations')), 600_000),
  getJobFilters: (): Promise<JobFilterOptions> => isPreview()
    ? Promise.resolve(previewJobFilters)
    : cachedRequest('job-filters', () => data(apiClient.get('/jobs/filters')), 600_000),
  getJob: (id: string, location = ''): Promise<JobDetail> => isPreview()
    ? Promise.resolve(previewJobDetail(id, location))
    : cachedRequest(cacheKey('job-detail', { id, location }), () => data(apiClient.get(`/jobs/${id}`, { params: location ? { location } : {} })), 300_000),
  getGraph: (params: Record<string, string | number> = {}): Promise<GraphData> => cachedRequest(
    cacheKey('graph', params), () => data(apiClient.get('/graph', { params })), 300_000,
  ),
  getGraphNode: (id: string): Promise<{id:string;type:string;properties:Record<string,any>}> => cachedRequest(
    cacheKey('graph-node', { id }), () => data(apiClient.get(`/graph/nodes/${id}`)), 300_000,
  ),
  getGraphFilters: (): Promise<GraphFilterOptions> => cachedRequest('graph-filters', () => data(apiClient.get('/graph/filters')), 600_000),
  getTrends: (roleId: string, granularity = 'year'): Promise<EvolutionData> => cachedRequest(
    cacheKey('evolution-trends', { roleId, granularity }),
    () => data(apiClient.get('/evolution/trends', { params: { roleId, granularity } })),
    300_000,
  ),
  getForecastOverview: (horizon = 3, scenario: ForecastScenario = 'baseline', granularity: 'year' | 'month' = 'year', roleId = '', location = '', keyword = ''): Promise<ForecastOverview> => {
    if (isPreview()) return Promise.resolve(createPreviewForecast(horizon, scenario, granularity, roleId))
    const params = { horizon, scenario, granularity, roleId, location, keyword }
    return cachedRequest(cacheKey('forecast', params), () => data<ForecastOverview>(apiClient.get('/forecasts/overview', { params })), 300_000)
  },
  prefetchLocation: (location: string) => {
    if (!location) return
    void Promise.all([
      insightService.getJobs({ pageSize: 12, location }),
      insightService.getForecastOverview(3, 'baseline', 'year', '', location),
    ]).catch(() => undefined)
  },
  getEmergingRole: (id: string, horizon = 3): Promise<EmergingRoleDetail> => {
    if (isPreview()) {
      const role = createPreviewForecast(horizon, 'baseline', 'year').emergingRoles.find(item => item.id === id)
      if (!role) return Promise.reject(new Error('新岗位信号不存在'))
      return Promise.resolve({ ...role, responsibilities: [], requiredSkills: role.coreSkills, bonusSkills: [], applicationScenarios: [], evidence: [] })
    }
    return cachedRequest(cacheKey('emerging-role', { id, horizon }), () => data(apiClient.get(`/forecasts/emerging-roles/${id}`, { params: { horizon } })), 180_000)
  },
  downloadEvolutionReport: async (roleId: string, horizon = 3, scenario: ForecastScenario = 'baseline', granularity: 'year' | 'month' = 'year'): Promise<Blob> => {
    let reportRoleId = roleId
    if (isPreview()) {
      const previewRoleMap: Record<string, { keyword: string; preferredName: string }> = {
        'role-ai-app': { keyword: '大模型应用工程师', preferredName: '大模型应用工程师' },
        'role-data-governance': { keyword: '数据治理工程师', preferredName: '数据治理工程师' },
        'role-cloud-native': { keyword: '云计算工程师', preferredName: '云计算工程师' },
        'role-security': { keyword: '网络安全工程师', preferredName: '网络安全工程师' },
        'role-frontend': { keyword: '前端开发工程师', preferredName: '前端开发工程师' },
        'role-embedded-ai': { keyword: '嵌入式软件工程师', preferredName: '嵌入式软件工程师' },
      }
      const mapping = previewRoleMap[roleId]
      if (mapping) {
        const page = await data<PageData<JobSummary>>(apiClient.get('/jobs', { params: { keyword: mapping.keyword, pageSize: 20 } }))
        reportRoleId = page.items.find(item => item.name === mapping.preferredName)?.id || page.items[0]?.id || ''
      }
    }
    if (!reportRoleId) throw new Error('当前岗位暂时没有可导出的趋势数据')
    const response = await apiClient.get('/evolution/report', { params: { roleId: reportRoleId, format: 'pdf', horizon, scenario, granularity }, responseType: 'blob' })
    return response.data
  },
  getAgentSessions: (limit = 50): Promise<{items: AgentSessionSummary[]; total: number}> => data(apiClient.get('/agent/sessions', { params: { limit } })),
  getAgentSession: (id: string): Promise<AgentSessionSummary & {messages: AgentHistoryMessage[]}> => data(apiClient.get(`/agent/sessions/${id}`)),
  renameAgentSession: (id: string, title: string): Promise<AgentSessionSummary> => data(apiClient.patch(`/agent/sessions/${id}`, { title })),
  deleteAgentSession: (id: string) => data(apiClient.delete(`/agent/sessions/${id}`)),
  startInterview: async (payload: { roleId: string; resumeId?: string; selfIntro?: string; questionCount?: number }): Promise<InterviewSessionState> => {
    if (isPreview()) {
      const role = previewJobDetail(payload.roleId); const now = new Date().toISOString(); const questions = previewInterviewQuestions(role.name, role.skills.map(item => item.name), payload.questionCount || 6)
      const session: InterviewSessionState = { id: `itv_${Date.now()}_${Math.random().toString(16).slice(2)}`, roleId: payload.roleId, roleName: role.name, status: 'in_progress', currentIndex: 0, totalCount: questions.length, questions, report: null, selfIntro: payload.selfIntro || '', createdAt: now }
      writePreviewInterviews([session, ...readPreviewInterviews()]); return session
    }
    return data(apiClient.post('/interview/start', payload, { timeout: 120000 }))
  },
  getInterviewSession: (id: string): Promise<InterviewSessionState> => {
    if (isPreview()) { const session = readPreviewInterviews().find(item => item.id === id); return session ? Promise.resolve(session) : Promise.reject(new Error('面试会话不存在')) }
    return data(apiClient.get(`/interview/sessions/${id}`, { timeout: 120000 }))
  },
  listInterviewSessions: (limit = 20): Promise<{items: InterviewSessionState[]; total: number}> => isPreview()
    ? Promise.resolve({ items: readPreviewInterviews().slice(0, limit), total: readPreviewInterviews().length })
    : data(apiClient.get('/interview/sessions', { params: { limit }, timeout: 120000 })),
  sendInterviewAnswer: async (id: string, answer: string): Promise<InterviewAnswerResult> => {
    if (isPreview()) {
      const sessions = readPreviewInterviews(); const session = sessions.find(item => item.id === id); if (!session) throw new Error('面试会话不存在')
      const item = session.questions[session.currentIndex]; if (!item) throw new Error('本场面试已结束'); const evaluation = previewInterviewEvaluation(answer); Object.assign(item, { answered: true, answer, ...evaluation }); session.currentIndex += 1; session.status = session.currentIndex >= session.totalCount ? 'finished' : 'in_progress'; writePreviewInterviews(sessions)
      return { feedback: evaluation.feedback, score: evaluation.score, referencePoints: item.referencePoints, nextQuestion: session.questions[session.currentIndex] ? { index: session.currentIndex, question: session.questions[session.currentIndex].question, focus: session.questions[session.currentIndex].focus } : null, status: session.status }
    }
    return data(apiClient.post(`/interview/${id}/answer`, { answer }, { timeout: 120000 }))
  },
  uploadInterviewAudio: async (id: string, blob: Blob): Promise<InterviewAnswerResult> => {
    if (isPreview()) throw new Error('演示模式暂不支持语音识别，请改用文字作答')
    const body = new FormData()
    body.append('file', blob, 'answer.webm')
    return data(apiClient.post(`/interview/${id}/audio`, body, { timeout: 120000 }))
  },
  getInterviewReport: (id: string): Promise<InterviewReport> => {
    if (isPreview()) { const sessions = readPreviewInterviews(); const session = sessions.find(item => item.id === id); if (!session) return Promise.reject(new Error('面试会话不存在')); if (session.currentIndex < session.totalCount) return Promise.reject(new Error('请先完成全部面试问题')); session.report = session.report || previewInterviewReport(session); session.status = 'completed'; writePreviewInterviews(sessions); return Promise.resolve(session.report) }
    return data(apiClient.post(`/interview/${id}/report`, null, { timeout: 120000 }))
  },
  uploadResume: async (file: File): Promise<ResumeResult> => {
    const body = new FormData(); body.append('file', file)
    const task = await data<{taskId:string}>(apiClient.post('/resumes', body))
    for (let attempt = 0; attempt < 240; attempt += 1) {
      const state = await data<{status:string;progress:number;result?:Omit<ResumeResult,'taskId'>;error?:string}>(apiClient.get(`/tasks/${task.taskId}`))
      if (state.status === 'completed' && state.result) {
        invalidateReadCache()
        return { taskId: task.taskId, ...state.result }
      }
      if (state.status === 'failed') throw new Error(state.error || '简历解析失败')
      await new Promise(resolve => window.setTimeout(resolve, 500))
    }
    throw new Error('简历解析超时，请稍后重试')
  },
  confirmResume: async (resumeId: string, payload: Record<string, any>) => {
    const result = await data(apiClient.put(`/resumes/${resumeId}/confirmation`, payload)); invalidateReadCache(); return result
  },
  getWorkspaceProfile: (): Promise<WorkspaceProfileData> => cachedRequest(userCacheKey('workspace-profile'), () => data(apiClient.get('/me/workspace-profile')), 120_000),
  saveWorkspaceProfile: async (payload: Record<string, any>): Promise<WorkspaceProfileData> => {
    const result = await data<WorkspaceProfileData>(apiClient.put('/me/workspace-profile', payload)); invalidateReadCache(); return result
  },
  getMyResumes: (limit = 20): Promise<{items:ResumeResult[];total:number}> => cachedRequest(
    userCacheKey('my-resumes', { limit }), () => data(apiClient.get('/me/resumes', { params: { limit } })), 120_000,
  ),
  getMyResumeFile: async (resumeId: string): Promise<Blob> => (await apiClient.get(`/me/resumes/${resumeId}/file`, { responseType: 'blob' })).data,
  deleteMyResume: async (resumeId: string): Promise<{resumeId:string;deleted:boolean}> => {
    const result = await data<{resumeId:string;deleted:boolean}>(apiClient.delete(`/me/resumes/${resumeId}`)); invalidateReadCache(); return result
  },
  getEnterpriseOverview: (): Promise<EnterpriseOverview> => cachedRequest(userCacheKey('enterprise-overview'), () => data(apiClient.get('/enterprise/overview')), 30_000),
  uploadEnterpriseResumes: async (files: File[]): Promise<{items:EnterpriseResume[];rejected:Array<{fileName:string;error:string}>;accepted:number}> => {
    const body = new FormData()
    files.forEach(file => body.append('files', file))
    const result = await data<{items:EnterpriseResume[];rejected:Array<{fileName:string;error:string}>;accepted:number}>(apiClient.post('/enterprise/resumes', body, { timeout: 120000 }))
    invalidateReadCache()
    return result
  },
  getEnterpriseResumes: (limit = 200): Promise<{items:EnterpriseResume[];total:number}> => cachedRequest(userCacheKey('enterprise-resumes', { limit }), () => data(apiClient.get('/enterprise/resumes', { params: { limit } })), 30_000),
  getEnterpriseResumeFile: async (resumeId: string): Promise<Blob> => (await apiClient.get(`/enterprise/resumes/${resumeId}/file`, { responseType: 'blob' })).data,
  deleteEnterpriseResume: async (resumeId: string): Promise<{resumeId:string;deleted:boolean}> => {
    const result = await data<{resumeId:string;deleted:boolean}>(apiClient.delete(`/enterprise/resumes/${resumeId}`))
    invalidateReadCache()
    return result
  },
  createEnterpriseAssessment: async (payload: {roleId:string;resumeIds:string[]}): Promise<EnterpriseAssessmentBatch> => {
    const result = await data<EnterpriseAssessmentBatch>(apiClient.post('/enterprise/assessments', payload, { timeout: 120000 }))
    invalidateReadCache()
    return result
  },
  getEnterpriseAssessments: (limit = 50): Promise<{items:EnterpriseAssessmentBatch[];total:number}> => cachedRequest(userCacheKey('enterprise-assessments', { limit }), () => data(apiClient.get('/enterprise/assessments', { params: { limit } })), 30_000),
  getEnterpriseAssessment: (batchId: string): Promise<EnterpriseAssessmentBatch> => data(apiClient.get(`/enterprise/assessments/${batchId}`)),
  createEnterpriseJobSubmission: async (payload: Record<string, any>): Promise<EnterpriseJobSubmission> => {
    const result = await data<EnterpriseJobSubmission>(apiClient.post('/enterprise/job-submissions', payload))
    invalidateReadCache()
    return result
  },
  getEnterpriseJobSubmissions: (): Promise<{items:EnterpriseJobSubmission[];total:number}> => cachedRequest(userCacheKey('enterprise-job-submissions'), () => data(apiClient.get('/enterprise/job-submissions')), 30_000),
  getFavoriteJobs: (limit = 100): Promise<{items:FavoriteJob[];total:number}> => cachedRequest(
    userCacheKey('favorite-jobs', { limit }), () => data(apiClient.get('/me/favorites', { params: { limit } })), 60_000,
  ),
  saveFavoriteJob: async (roleId: string): Promise<FavoriteJob> => {
    const result = await data<FavoriteJob>(apiClient.post('/me/favorites', { roleId })); invalidateReadCache(); return result
  },
  deleteFavoriteJob: async (roleId: string): Promise<{roleId:string;deleted:boolean}> => {
    const result = await data<{roleId:string;deleted:boolean}>(apiClient.delete(`/me/favorites/${encodeURIComponent(roleId)}`)); invalidateReadCache(); return result
  },
  matchSkills: (payload: Record<string, any>): Promise<MatchResult> => data(apiClient.post('/matching/manual', payload)),
  recommendRoles: (skills: string[]): Promise<{items:Array<{roleId:string;roleName:string;score:number;topGaps:string[]}>}> => data(apiClient.post('/matching/recommendations', { skills, limit: 8 })),
  getLearningPath: (reportId: string): Promise<{id:string;reportId:string;stages:LearningStage[]}> => data(apiClient.post('/learning-paths', null, { params: { reportId } })),
  getReport: (reportId: string): Promise<MatchResult & ReportContext & {id:string}> => data(apiClient.get(`/reports/${reportId}`, { params: { format: 'json' } })),
  reportUrl: (reportId: string, format: 'pdf' | 'csv' | 'json') => `${apiClient.defaults.baseURL}/reports/${reportId}?format=${format}`,
  downloadReport: async (reportId: string, format: 'pdf' | 'csv'): Promise<Blob> => {
    const response = await apiClient.get(`/reports/${reportId}`, { params: { format }, responseType: 'blob' })
    return response.data
  },
  getDatasets: (page = 1, pageSize = 20): Promise<PageData<DatasetItem>> => cachedRequest(
    userCacheKey('datasets', { page, pageSize }), () => data(apiClient.get('/datasets', { params: { page, pageSize } })), 60_000,
  ),
  getAdminDashboard: (): Promise<AdminDashboardSummary> => cachedRequest(userCacheKey('admin-dashboard'), () => data(apiClient.get('/admin/dashboard')), 30_000),
  createDataset: async (body: FormData): Promise<DatasetItem> => {
    const result = await data<DatasetItem>(apiClient.post('/datasets', body)); invalidateReadCache(); return result
  },
  updateDataset: async (id: string, body: FormData): Promise<DatasetItem> => {
    const result = await data<DatasetItem>(apiClient.put(`/datasets/${id}`, body)); invalidateReadCache(); return result
  },
  syncDataset: async (id: string): Promise<DatasetItem> => {
    const result = await data<DatasetItem>(apiClient.post(`/datasets/${id}/sync`)); invalidateReadCache(); return result
  },
  getDatasetRevisions: (id: string): Promise<DatasetRevision[]> => cachedRequest(
    userCacheKey('dataset-revisions', { id }), () => data(apiClient.get(`/datasets/${id}/revisions`)), 60_000,
  ),
  getReviews: (status = 'pending'): Promise<ReviewItem[]> => cachedRequest(
    userCacheKey('reviews', { status }), () => data(apiClient.get('/reviews', { params: { status } })), 30_000,
  ),
  review: async (id: string, payload: Record<string, any>) => {
    const result = await data(apiClient.patch(`/reviews/${id}`, payload)); invalidateReadCache(); return result
  },
  getVersions: (): Promise<{items:Array<Record<string, any>>;total:number}> => cachedRequest(userCacheKey('versions'), () => data(apiClient.get('/admin/versions')), 30_000),
  getVersion: (id: string): Promise<Record<string, any>> => cachedRequest(userCacheKey('version', { id }), () => data(apiClient.get(`/admin/versions/${id}`)), 30_000),
  publishVersion: async (id: string) => {
    const result = await data(apiClient.post(`/admin/versions/${id}/publish`)); invalidateReadCache(); return result
  },
  unpublishVersion: async (id: string) => {
    const result = await data(apiClient.post(`/admin/versions/${id}/unpublish`)); invalidateReadCache(); return result
  },
  createVersionDraft: async (id: string): Promise<{draftId:string;roleId:string;roleName:string;created:boolean}> => {
    const result = await data<{draftId:string;roleId:string;roleName:string;created:boolean}>(apiClient.post(`/admin/versions/${id}/draft`)); invalidateReadCache(); return result
  },
  getQuality: (): Promise<any> => cachedRequest(userCacheKey('quality'), () => data(apiClient.get('/quality/summary')), 30_000),
  downloadQualityReport: async (format: 'pdf' | 'csv' | 'json'): Promise<Blob> => {
    const response = await apiClient.get('/quality/report', { params: { format }, responseType: 'blob' })
    return response.data
  },
  health: (): Promise<any> => cachedRequest('health', () => data(apiClient.get('/health')), 15_000),
  prefetchPersonalWorkspace: (options: { location?: string; roleId?: string } = {}) => {
    if (isPreview()) return
    const location = options.location || ''
    const tasks: Promise<unknown>[] = [
      insightService.getDashboard(), insightService.getJobLocations(), insightService.getJobFilters(),
      insightService.getJobs({ pageSize: 12, location }), insightService.getJobs({ pageSize: 100 }),
      insightService.getJobs({ pageSize: 100, location }),
      insightService.getJobs({
        keyword: '', fields: '', skills: '', trends: '', lastSeenBucket: '', sort: 'posting_desc', page: 1, pageSize: 20, location,
      }),
      insightService.getForecastOverview(3, 'baseline', 'year', '', location), insightService.getGraphFilters(),
      insightService.getWorkspaceProfile(), insightService.getMyResumes(4),
    ]
    if (options.roleId) tasks.push(insightService.getGraph({
      viewMode: 'role', roleId: options.roleId, techStack: '', skillTier: '', seniority: '', entityType: '', keyword: '', limit: 100,
    }))
    void Promise.allSettled(tasks)
  },
  prefetchTargetRole: (roleId: string, location = '') => {
    if (isPreview() || !roleId) return
    void Promise.allSettled([
      insightService.getGraph({
        viewMode: 'role', roleId, techStack: '', skillTier: '', seniority: '', entityType: '', keyword: '', limit: 100,
      }),
      insightService.getTrends(roleId, 'year'), insightService.getTrends(roleId, 'month'),
      insightService.getForecastOverview(3, 'baseline', 'year', roleId, location),
      insightService.getForecastOverview(3, 'baseline', 'month', roleId, location),
    ])
  },
  prefetchAdminWorkspace: () => {
    void Promise.allSettled([
      insightService.getAdminDashboard(), insightService.getDatasets(1, 20), insightService.getReviews('pending'),
      insightService.getVersions(), insightService.health(),
    ])
  },
}
