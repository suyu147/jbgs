import type { DashboardSummary, ForecastOverview, ForecastScenario, JobSummary } from '@/types/domain'

export const previewDashboard: DashboardSummary = {
  jobCount: 86,
  postingCount: 3695,
  skillCount: 3695,
  relationCount: 50610,
  nodeCount: 7814,
  datasetCount: 12,
  pendingReviewCount: 7,
  reportCount: 24,
  updatedAt: '2026-08-08T18:30:00+08:00',
  governanceVersion: '2026.08-preview',
}

export const previewJobs: JobSummary[] = [
  { id: 'role-ai-app', name: '人工智能应用开发工程师', field: '人工智能', postingCount: 486, sourceCount: 8, firstSeen: '2023-01', lastSeen: '2026-07', trendLabel: '持续升温', trendDirection: 'up', trendChangePp: 18.6, trendSamples: 486, locationCount: 12, salaryMedian: 22000, salaryRangeMin: 16000, salaryRangeMax: 30000, salarySampleCount: 368, topCities: [
    { city: '北京', postingCount: 126, share: .259, salaryMedian: 26000, salaryRangeMin: 20000, salaryRangeMax: 35000, salarySampleCount: 102 },
    { city: '上海', postingCount: 98, share: .202, salaryMedian: 24000, salaryRangeMin: 18000, salaryRangeMax: 32000, salarySampleCount: 76 },
    { city: '深圳', postingCount: 87, share: .179, salaryMedian: 25000, salaryRangeMin: 19000, salaryRangeMax: 33000, salarySampleCount: 69 },
    { city: '杭州', postingCount: 54, share: .111, salaryMedian: 22000, salaryRangeMin: 16000, salaryRangeMax: 29000, salarySampleCount: 43 },
    { city: '成都', postingCount: 31, share: .064, salaryMedian: 18000, salaryRangeMin: 13000, salaryRangeMax: 24000, salarySampleCount: 24 },
  ], skills: [
    { id: 'skill-python', name: 'Python', weight: .83 }, { id: 'skill-llm', name: '大模型应用', weight: .72 }, { id: 'skill-rag', name: 'RAG', weight: .61 },
  ] },
  { id: 'role-data-governance', name: '数据治理工程师', field: '大数据', postingCount: 392, sourceCount: 7, firstSeen: '2022-03', lastSeen: '2026-07', trendLabel: '稳健增长', trendDirection: 'up', trendChangePp: 12.4, trendSamples: 392, locationCount: 10, salaryMedian: 19000, salaryRangeMin: 14000, salaryRangeMax: 26000, salarySampleCount: 294, topCities: [
    { city: '北京', postingCount: 82, share: .209, salaryMedian: 22000, salaryRangeMin: 16000, salaryRangeMax: 30000, salarySampleCount: 65 },
    { city: '上海', postingCount: 71, share: .181, salaryMedian: 21000, salaryRangeMin: 15000, salaryRangeMax: 28000, salarySampleCount: 55 },
    { city: '杭州', postingCount: 58, share: .148, salaryMedian: 19000, salaryRangeMin: 14000, salaryRangeMax: 25000, salarySampleCount: 45 },
    { city: '深圳', postingCount: 49, share: .125, salaryMedian: 21000, salaryRangeMin: 15000, salaryRangeMax: 28000, salarySampleCount: 39 },
    { city: '成都', postingCount: 32, share: .082, salaryMedian: 16000, salaryRangeMin: 12000, salaryRangeMax: 21000, salarySampleCount: 24 },
  ], skills: [
    { id: 'skill-sql', name: 'SQL', weight: .88 }, { id: 'skill-quality', name: '数据质量', weight: .69 }, { id: 'skill-lineage', name: '数据血缘', weight: .58 },
  ] },
  { id: 'role-cloud-native', name: '云原生平台工程师', field: '云计算', postingCount: 337, sourceCount: 6, firstSeen: '2021-08', lastSeen: '2026-07', trendLabel: '需求稳定', trendDirection: 'stable', trendChangePp: 4.8, trendSamples: 337, locationCount: 9, salaryMedian: 21000, salaryRangeMin: 15000, salaryRangeMax: 29000, salarySampleCount: 251, topCities: [
    { city: '北京', postingCount: 76, share: .226, salaryMedian: 24000, salaryRangeMin: 18000, salaryRangeMax: 32000, salarySampleCount: 59 },
    { city: '深圳', postingCount: 62, share: .184, salaryMedian: 23000, salaryRangeMin: 17000, salaryRangeMax: 31000, salarySampleCount: 48 },
    { city: '上海', postingCount: 54, share: .160, salaryMedian: 23000, salaryRangeMin: 17000, salaryRangeMax: 30000, salarySampleCount: 42 },
    { city: '杭州', postingCount: 43, share: .128, salaryMedian: 21000, salaryRangeMin: 15000, salaryRangeMax: 28000, salarySampleCount: 33 },
    { city: '南京', postingCount: 29, share: .086, salaryMedian: 18000, salaryRangeMin: 13000, salaryRangeMax: 24000, salarySampleCount: 22 },
  ], skills: [
    { id: 'skill-k8s', name: 'Kubernetes', weight: .79 }, { id: 'skill-devops', name: 'DevOps', weight: .72 }, { id: 'skill-go', name: 'Go', weight: .54 },
  ] },
  { id: 'role-security', name: '网络安全运营工程师', field: '网络安全', postingCount: 301, sourceCount: 6, firstSeen: '2021-01', lastSeen: '2026-07', trendLabel: '需求上升', trendDirection: 'up', trendChangePp: 9.7, trendSamples: 301, locationCount: 11, salaryMedian: 18000, salaryRangeMin: 13000, salaryRangeMax: 25000, salarySampleCount: 216, topCities: [
    { city: '北京', postingCount: 69, share: .229, salaryMedian: 21000, salaryRangeMin: 15000, salaryRangeMax: 28000, salarySampleCount: 51 },
    { city: '深圳', postingCount: 52, share: .173, salaryMedian: 20000, salaryRangeMin: 15000, salaryRangeMax: 27000, salarySampleCount: 38 },
    { city: '上海', postingCount: 45, share: .150, salaryMedian: 19000, salaryRangeMin: 14000, salaryRangeMax: 26000, salarySampleCount: 33 },
    { city: '杭州', postingCount: 36, share: .120, salaryMedian: 18000, salaryRangeMin: 13000, salaryRangeMax: 24000, salarySampleCount: 26 },
    { city: '武汉', postingCount: 24, share: .080, salaryMedian: 15000, salaryRangeMin: 11000, salaryRangeMax: 20000, salarySampleCount: 17 },
  ], skills: [
    { id: 'skill-soc', name: '安全运营', weight: .77 }, { id: 'skill-response', name: '应急响应', weight: .68 }, { id: 'skill-python', name: 'Python', weight: .46 },
  ] },
  { id: 'role-frontend', name: '前端开发工程师', field: '软件开发', postingCount: 528, sourceCount: 9, firstSeen: '2020-01', lastSeen: '2026-07', trendLabel: '结构调整', trendDirection: 'stable', trendChangePp: 2.1, trendSamples: 528, locationCount: 14, salaryMedian: 17000, salaryRangeMin: 12000, salaryRangeMax: 24000, salarySampleCount: 417, topCities: [
    { city: '深圳', postingCount: 112, share: .212, salaryMedian: 19000, salaryRangeMin: 14000, salaryRangeMax: 26000, salarySampleCount: 89 },
    { city: '北京', postingCount: 101, share: .191, salaryMedian: 20000, salaryRangeMin: 15000, salaryRangeMax: 27000, salarySampleCount: 81 },
    { city: '上海', postingCount: 86, share: .163, salaryMedian: 19000, salaryRangeMin: 14000, salaryRangeMax: 25000, salarySampleCount: 68 },
    { city: '杭州', postingCount: 65, share: .123, salaryMedian: 17000, salaryRangeMin: 12000, salaryRangeMax: 23000, salarySampleCount: 51 },
    { city: '成都', postingCount: 44, share: .083, salaryMedian: 14000, salaryRangeMin: 10000, salaryRangeMax: 19000, salarySampleCount: 34 },
  ], skills: [
    { id: 'skill-ts', name: 'TypeScript', weight: .81 }, { id: 'skill-vue', name: 'Vue', weight: .66 }, { id: 'skill-ai-coding', name: 'AI 辅助开发', weight: .42 },
  ] },
  { id: 'role-embedded-ai', name: '智能终端算法工程师', field: '智能制造', postingCount: 214, sourceCount: 5, firstSeen: '2023-06', lastSeen: '2026-07', trendLabel: '新兴方向', trendDirection: 'new', trendChangePp: 15.2, trendSamples: 214, locationCount: 8, salaryMedian: 23000, salaryRangeMin: 17000, salaryRangeMax: 32000, salarySampleCount: 161, topCities: [
    { city: '深圳', postingCount: 61, share: .285, salaryMedian: 26000, salaryRangeMin: 19000, salaryRangeMax: 35000, salarySampleCount: 47 },
    { city: '上海', postingCount: 37, share: .173, salaryMedian: 25000, salaryRangeMin: 18000, salaryRangeMax: 34000, salarySampleCount: 28 },
    { city: '北京', postingCount: 32, share: .150, salaryMedian: 25000, salaryRangeMin: 18000, salaryRangeMax: 33000, salarySampleCount: 24 },
    { city: '苏州', postingCount: 29, share: .136, salaryMedian: 22000, salaryRangeMin: 16000, salaryRangeMax: 30000, salarySampleCount: 22 },
    { city: '杭州', postingCount: 21, share: .098, salaryMedian: 22000, salaryRangeMin: 16000, salaryRangeMax: 29000, salarySampleCount: 16 },
  ], skills: [
    { id: 'skill-cpp', name: 'C++', weight: .84 }, { id: 'skill-edge-ai', name: '边缘 AI', weight: .63 }, { id: 'skill-model-compression', name: '模型压缩', weight: .51 },
  ] },
]

export const previewLocations = Array.from(new Set(previewJobs.flatMap(job => job.topCities?.map(item => item.city) || [])))
  .map(city => ({
    value: city,
    label: city,
    postingCount: previewJobs.reduce((total, job) => total + (job.topCities?.find(item => item.city === city)?.postingCount || 0), 0),
    roleCount: previewJobs.filter(job => job.topCities?.some(item => item.city === city)).length,
  }))
  .sort((a, b) => b.postingCount - a.postingCount)

const scenarioFactor: Record<ForecastScenario, number> = { conservative: .72, baseline: 1, growth: 1.28 }

export function createPreviewForecast(horizon = 3, scenario: ForecastScenario = 'baseline', granularity: 'year' | 'month' = 'year', roleId = ''): ForecastOverview {
  const factor = scenarioFactor[scenario]
  const lastYear = 2026 + horizon
  const addMonths = (period: string, offset: number) => {
    const [year, month] = period.split('-').map(Number)
    const absolute = year * 12 + month - 1 + offset
    return `${Math.floor(absolute / 12)}-${String(absolute % 12 + 1).padStart(2, '0')}`
  }
  const observed = (values: number[]) => values.map((value, index) => ({
    period: granularity === 'month' ? addMonths('2026-01', index) : String(2023 + index), value, lower: value, upper: value, observed: true,
  }))
  const projected = (start: number, annualChange: number) => Array.from({ length: granularity === 'month' ? horizon * 12 : horizon }, (_, index) => {
    const step = granularity === 'month' ? (index + 1) / 12 : index + 1
    const value = Math.min(100, Math.max(0, start + annualChange * factor * step))
    const spread = 3.2 + index * 1.4
    return { period: granularity === 'month' ? addMonths('2026-04', index + 1) : String(2027 + index), value: Number(value.toFixed(1)), lower: Number(Math.max(0, value - spread).toFixed(1)), upper: Number(Math.min(100, value + spread).toFixed(1)), observed: false }
  })
  const curve = (history: number[], annualChange: number) => [...observed(history), ...projected(history.at(-1) || 0, annualChange)]

  const result: ForecastOverview = {
    generatedAt: '2026-08-08T18:30:00+08:00', horizon, scenario, granularity, source: 'prototype',
    modelVersion: 'UI-PROTOTYPE-0.1', trainingWindow: '2023-01 至 2026-07',
    occupations: [
      { roleId: 'role-ai-app', roleName: '人工智能应用开发工程师', industry: '人工智能', currentIndex: 82, changeRate: 23.8, confidence: .86, sampleSize: 486, points: curve([44, 57, 71, 82], 5.4) },
      { roleId: 'role-data-governance', roleName: '数据治理工程师', industry: '大数据', currentIndex: 74, changeRate: 16.5, confidence: .83, sampleSize: 392, points: curve([51, 59, 67, 74], 3.7) },
      { roleId: 'role-security', roleName: '网络安全运营工程师', industry: '网络安全', currentIndex: 69, changeRate: 13.1, confidence: .81, sampleSize: 301, points: curve([48, 56, 63, 69], 3.2) },
      { roleId: 'role-cloud-native', roleName: '云原生平台工程师', industry: '云计算', currentIndex: 66, changeRate: 8.6, confidence: .79, sampleSize: 337, points: curve([50, 57, 63, 66], 2.1) },
    ],
    skills: [
      { skillId: 'skill-rag', skill: 'RAG 工程', roleId: 'role-ai-app', roleName: '人工智能应用开发工程师', currentDemand: 61, futureDemand: Math.min(96, 61 + 7.2 * factor * horizon), changePp: 21.6 * factor, confidence: .84, drivers: ['企业知识库落地', '智能体应用增长'], points: curve([18, 31, 48, 61], 7.2) },
      { skillId: 'skill-agent', skill: '智能体编排', roleId: 'role-ai-app', roleName: '人工智能应用开发工程师', currentDemand: 47, futureDemand: Math.min(92, 47 + 8.1 * factor * horizon), changePp: 24.3 * factor, confidence: .78, drivers: ['工作流自动化', '多智能体协同'], points: curve([5, 14, 29, 47], 8.1) },
      { skillId: 'skill-quality', skill: '数据质量管理', roleId: 'role-data-governance', roleName: '数据治理工程师', currentDemand: 69, futureDemand: Math.min(94, 69 + 4.1 * factor * horizon), changePp: 12.3 * factor, confidence: .86, drivers: ['监管合规', 'AI 数据工程'], points: curve([46, 54, 62, 69], 4.1) },
      { skillId: 'skill-ai-coding', skill: 'AI 辅助开发', roleId: 'role-frontend', roleName: '前端开发工程师', currentDemand: 42, futureDemand: Math.min(88, 42 + 6.8 * factor * horizon), changePp: 20.4 * factor, confidence: .76, drivers: ['研发提效', '前端智能交互'], points: curve([4, 12, 26, 42], 6.8) },
    ].map(item => ({ ...item, futureDemand: Number(item.futureDemand.toFixed(1)), changePp: Number(item.changePp.toFixed(1)) })),
    emergingRoles: [
      { id: 'emerging-agent-ops', name: '智能体运营工程师', industry: '人工智能', signalStrength: 88, confidence: .76, expectedWindow: `2027-${Math.min(lastYear, 2029)}`, stage: 'accelerating', coreSkills: ['智能体编排', '业务流程建模', '效果评测'], evidenceCount: 128, postingCount: 128, sourceCount: 4, reviewStatus: 'pending', statusLabel: '产品预览', canOpenJob: false, rationale: '智能体从原型进入业务流程后，运营、评测和治理职责开始形成稳定技能组合。' },
      { id: 'emerging-ai-governance', name: 'AI 治理与合规工程师', industry: '人工智能安全', signalStrength: 81, confidence: .72, expectedWindow: `2027-${Math.min(lastYear, 2030)}`, stage: 'forming', coreSkills: ['模型风险评估', '数据合规', '算法审计'], evidenceCount: 94, postingCount: 94, sourceCount: 4, reviewStatus: 'pending', statusLabel: '产品预览', canOpenJob: false, rationale: '政策、行业标准和招聘技能共同出现治理类职责聚合信号。' },
      { id: 'emerging-synthetic-data', name: '合成数据工程师', industry: '数据工程', signalStrength: 73, confidence: .64, expectedWindow: `2028-${Math.min(lastYear + 1, 2031)}`, stage: 'early', coreSkills: ['生成模型', '隐私计算', '数据质量评估'], evidenceCount: 61, postingCount: 61, sourceCount: 3, reviewStatus: 'pending', statusLabel: '产品预览', canOpenJob: false, rationale: '隐私约束与高质量训练数据需求推动独立技能簇形成，目前仍属早期候选。' },
    ],
    industries: [
      { name: '人工智能', heat: 92, change: 18.6, roleCount: 18 }, { name: '大数据', heat: 84, change: 12.4, roleCount: 14 },
      { name: '网络安全', heat: 78, change: 9.7, roleCount: 11 }, { name: '智能制造', heat: 72, change: 8.8, roleCount: 13 },
      { name: '云计算', heat: 68, change: 5.3, roleCount: 12 },
    ],
    hotSkills: [
      { name: '大模型应用', heat: 94, change: 26.2, roleCount: 21 }, { name: 'Python', heat: 89, change: 11.8, roleCount: 38 },
      { name: '数据治理', heat: 83, change: 15.6, roleCount: 17 }, { name: 'RAG', heat: 79, change: 31.4, roleCount: 12 },
      { name: '网络安全', heat: 75, change: 9.1, roleCount: 19 }, { name: 'AI 辅助开发', heat: 72, change: 28.7, roleCount: 16 },
    ],
    notice: '当前为前端产品原型数据，用于验证信息架构与交互。正式预测必须接入经评测的时序模型，并显示样本量、误差区间和回测结果。', scopeRoleId: roleId,
  }
  if (roleId) {
    const scoped = result.skills.filter(item => item.roleId === roleId)
    if (scoped.length) result.skills = scoped
  }
  return result
}
