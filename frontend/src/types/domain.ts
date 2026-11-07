export interface ApiEnvelope<T> { code: number; message: string; data: T; requestId?: string }

export type EntityType = 'job' | 'posting' | 'skill' | 'certificate' | 'course' | 'major' | 'standard' | 'requirement' | 'report' | 'signal' | 'topic' | 'snapshot'
export interface GraphNode { id: string; name: string; type: EntityType; level?: string; value?: number; properties?: Record<string, unknown> }
export interface GraphEdge { id: string; source: string; target: string; relation: string; weight?: number; tier?: string }
export interface GraphFilterOption { value: string; label: string; count?: number }
export interface GraphFilterOptions {
  viewModes: GraphFilterOption[]
  techStacks: GraphFilterOption[]
  skillTiers: GraphFilterOption[]
  seniorityLevels: GraphFilterOption[]
  entityTypes: GraphFilterOption[]
  method: { techStack: string; skillTier: string; seniority: string }
}
export interface GraphData {
  viewMode?: 'role' | 'stack' | 'entity'
  nodes: GraphNode[]
  edges: GraphEdge[]
  totalNodes: number
  totalEdges: number
  truncated: boolean
  appliedFilters?: Record<string, string>
  statistics?: { roleCount: number; skillCount: number; relationCount: number; typeCounts?: Record<string, number> }
}

export interface DashboardSummary {
  jobCount: number; postingCount: number; skillCount: number; relationCount: number; nodeCount: number
  datasetCount: number; pendingReviewCount: number; reportCount: number; updatedAt: string; governanceVersion: string
}

export interface AdminDashboardSummary {
  generatedAt: string
  governanceVersion: string
  graphVersion: string
  graph: DashboardSummary & { snapshotCount?: number; timePeriodCount?: number; entityCounts: Record<string, number> }
  dataAssets: {
    datasetCount: number; totalRecords: number; boundaries: Record<string, number>
    revisionStatuses: Record<string, number>; latestUpdatedAt: string
  }
  governance: {
    draftStatuses: Record<string, number>; candidateTypes: Record<string, number>
    versionStatuses: Record<string, number>; taskStatuses: Record<string, number>
    funnel: Array<{key:string;label:string;count:number;route:string}>
  }
  quality: {
    score: number; status: string; passedChecks: number; totalChecks: number
    evaluationPassed: boolean; coveragePassed: boolean
  }
  monthlyEvidence: Array<{period:string;postingCount:number}>
  locations: JobLocationOption[]
  risks: Array<{key:string;label:string;count:number;route:string}>
  recentActions: Array<{
    id:string;action:string;targetType:string;targetId:string
    detail:Record<string,unknown>;createdAt:string
  }>
  system: {api:boolean;neo4j:boolean;mysql:boolean;agentProvider:string;agentConfigured:boolean}
}

export interface JobSkill { id: string; name: string; weight: number; confidence?: string; sourceCount?: number; evidenceCount?: number; evidence?: string; urls?: string }
export interface JobCityMetric {
  city: string; postingCount: number; share: number; salaryMedian?: number
  salaryRangeMin?: number; salaryRangeMax?: number; salarySampleCount?: number
}
export interface JobSalaryBucket { label: string; count: number; share: number }
export interface JobSummary {
  id: string; name: string; field: string; postingCount: number; sourceCount: number; firstSeen: string; lastSeen: string; skills: JobSkill[]
  trendLabel?: string; trendDirection?: 'up'|'down'|'stable'|'new'|'insufficient'; trendChangePp?: number; trendSamples?: number
  trendBasis?: 'role'|'family'|'review'|'insufficient'; trendWindow?: string
  discoveryType?: string; discoveryTitle?: string; publishedAt?: string
  marketScope?: string; topCities?: JobCityMetric[]; locationCount?: number
  salaryMedian?: number; salaryRangeMin?: number; salaryRangeMax?: number; salarySampleCount?: number
}
export interface JobDetail extends JobSummary {
  categories?: string; industries?: string; aliases?: string[]; postings: Array<Record<string, string>>
  cityMetrics?: JobCityMetric[]; salaryBuckets?: JobSalaryBucket[]
  assets?: Record<string,Array<{id:string;name:string}>>
}
export interface FavoriteJob { id: string; roleId: string; roleName: string; field: string; createdAt: string }
export interface JobLocationOption { value: string; label: string; postingCount: number; roleCount: number; skillCount?: number }
export interface PageData<T> { items: T[]; page: number; pageSize: number; total: number }
export interface JobFilterOption { value: string; label: string; count: number }
export interface JobFilterOptions {
  fields: JobFilterOption[]; skills: JobFilterOption[]; trends: JobFilterOption[]
  postingBuckets: JobFilterOption[]; sourceCounts: JobFilterOption[]
  lastSeenBuckets: JobFilterOption[]; sorts: JobFilterOption[]
}

export interface TrendPoint { period: string; value: number; sampleSize: number; estimated?: boolean; forecast?: boolean }
export interface SkillTrend { skillId?: string; skill: string; points: TrendPoint[] }
export interface EvolutionData { series: SkillTrend[]; events: Array<Record<string, any>>; warning: string; continuityNote?: string; estimatedPointCount?: number; seriesLimit?: number; availableSeries?: number; availablePeriods?: number }

export type ForecastScenario = 'conservative' | 'baseline' | 'growth'
export interface ForecastPoint { period: string; value: number; lower: number; upper: number; observed?: boolean }
export interface OccupationForecast {
  roleId: string; roleName: string; industry: string; currentIndex: number; changeRate: number
  confidence: number; sampleSize: number; points: ForecastPoint[]
}
export interface SkillForecast {
  skillId: string; skill: string; roleId: string; roleName: string; currentDemand: number
  futureDemand: number; changePp: number; confidence: number; drivers: string[]; points: ForecastPoint[]
}
export interface EmergingRoleSignal {
  id: string; name: string; industry: string; signalStrength: number; confidence: number
  expectedWindow: string; stage: 'early' | 'forming' | 'accelerating'; coreSkills: string[]; evidenceCount: number; rationale: string
  roleId?: string; versionId?: string; publicationTitle?: string
  reviewStatus: 'pending' | 'approved' | 'published' | 'withdrawn'; statusLabel: string; publishedAt?: string
  postingCount: number; sourceCount: number; firstSeen?: string; latestSeen?: string; canOpenJob: boolean
}
export interface EmergingRoleDetail extends EmergingRoleSignal {
  responsibilities: Array<string | Record<string, any>>
  requiredSkills: Array<string | Record<string, any>>
  bonusSkills: Array<string | Record<string, any>>
  applicationScenarios: Array<string | Record<string, any>>
  evidence: Array<Record<string, any>>
}
export interface IndustryPulse { name: string; heat: number; change: number; roleCount: number }
export interface SkillPulse { name: string; heat: number; change: number; roleCount: number }
export interface ForecastOverview {
  generatedAt: string; horizon: number; scenario: ForecastScenario; granularity?: 'year' | 'month'; source: 'model' | 'prototype'
  modelVersion: string; trainingWindow: string; occupations: OccupationForecast[]; skills: SkillForecast[]
  emergingRoles: EmergingRoleSignal[]; industries: IndustryPulse[]; hotSkills: SkillPulse[]; notice: string; scopeRoleId?: string; scopeKeyword?: string
}

export interface AgentSessionSummary { id: string; title: string; createdAt: string; updatedAt: string; messageCount: number; lastMessage: string }
export interface AgentHistoryMessage { id: string; role: 'user' | 'assistant'; content: string; evidence?: Array<Record<string, any>>; createdAt: string }

export interface InterviewQuestionState { index: number; question: string; focus: string; answered: boolean; answer: string; feedback: string; score: number | null; referencePoints: string[] }
export interface InterviewDimension { name: string; score: number; comment: string }
export interface InterviewReport { overallScore: number; summary: string; dimensions: InterviewDimension[]; strengths: string[]; improvements: string[]; suggestions: string[]; provider?: string }
export interface InterviewSessionState { id: string; roleId: string; roleName: string; status: string; currentIndex: number; totalCount: number; questions: InterviewQuestionState[]; report: InterviewReport | null; selfIntro: string; createdAt: string }
export interface InterviewAnswerResult { feedback: string; score: number | null; referencePoints: string[]; nextQuestion: { index: number; question: string; focus: string } | null; status: string; transcript?: string }

export interface SkillGap { skillId: string; skill: string; status: 'matched' | 'partial' | 'missing'; level: string; importance: number; jobEvidence?: string; sourceUrls?: string[] }
export interface MatchResult { reportId: string; roleId: string; roleName: string; score: number; skillScore: number; breadthScore?: number; workStyleScore?: number; experienceRequirementMinYears?: number; radarVersion?: string; radarTargets?: { skills?: number; experience?: number; education?: number; breadth?: number; workStyle?: number }; dimensions: Array<{name:string;weight:number;score:number}>; gaps: SkillGap[]; notice: string; educationProfile?: { provided:string; providedRank:number; required:string; requiredRank:number; current:number; target:number; matchScore:number; evidenceCount:number }; experienceProfile?: { providedYears:number; requiredYears:number; current:number; target:number } }
export interface ReportContext {
  graphSummary: { roleId:string; roleName:string; nodeCount:number; relationCount:number; skills:Array<{id:string;name:string;level:string;weight:number}> }
  evolutionSummary: { granularity:string; seriesCount:number; events:Array<{skillId:string;skill:string;period:string;changePp:number;sampleSize:number}>; warning:string }
}
export interface LearningTask { period: string; title: string; actions: string[]; deliverable: string }
export interface LearningCourse { name: string; url?: string; provider?: string }
export interface LearningStage {
  stage: number; name: string; duration: string; estimatedHoursPerWeek?: number; goal?: string; skills: string[]
  prerequisites?: string[]; courses?: Array<LearningCourse | string>; certificates?: string[]; weeklyTasks?: LearningTask[]
  practiceProject?: string; acceptanceCriteria?: string[]; outcome: string; planVersion?: string
}
export interface ResumeResult { taskId?: string; resumeId: string; skills: Array<{skill_id:string;skill_name:string;evidence:string;confidence:number}>; education: string; experienceYears?: number; certificates: string[]; warnings: string[]; ocr?: {engine:string;language:string;pages:number} | null; confirmed?: boolean; fileName?: string; uploadedAt?: string; textPreview?: string }

export interface EnterpriseResume extends ResumeResult {
  candidateName: string
  contentConfidence: number
}
export interface EnterpriseAssessmentCandidate {
  id: string; candidateCode: string; fileName: string; resumeId: string; reportId: string
  status: string; score: number | null; result: MatchResult & { candidateName?: string; contentConfidence?: number; confidenceNotice?: string }; error: string
}
export interface EnterpriseAssessmentBatch {
  id: string; roleId: string; roleName: string; status: string; candidateCount: number
  completedCount: number; averageScore: number; createdAt: string; candidates?: EnterpriseAssessmentCandidate[]
}
export interface EnterpriseOverview {
  resumeCount: number; assessmentBatchCount: number; assessedCandidateCount: number
  averageMatchScore: number; pendingSubmissionCount: number; publishedSubmissionCount: number
  recentBatches: EnterpriseAssessmentBatch[]
}
export interface EnterpriseJobSubmission {
  id: string; roleId: string; roleName: string; companyName: string; jobCategory: string
  location: string; openingCount: number; status: string; statusLabel: string; createdAt: string
}

export interface WorkspaceProfileData {
  audience: 'seeker'; profile: Record<string, any>
  workStyleAssessment: Record<string, any>; updatedAt: string
}
export interface DatasetItem { id: string; name: string; category: string; records: number; version: string; boundary: string; path: string; sha256?: string; syncStatus?: string; syncResult?: Record<string,any>; updatedAt?: string }
export interface DatasetRevision { id:string; fileName:string; path:string; records:number; version:string; sha256:string; syncStatus:string; syncResult:Record<string,any>; createdAt:string }
export interface ReviewItem { id: string; roleId: string; roleName: string; candidateType: string; status: string; definition: Record<string, any>; evidence: Array<Record<string, any>>; evidenceClass?: 'data_backed' | 'aggregated' | 'curated'; evidenceLabel?: string }
