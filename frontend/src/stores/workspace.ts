import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'
import type { LearningStage, MatchResult, ResumeResult } from '@/types/domain'

const RETENTION_MS = 7 * 24 * 60 * 60 * 1000

interface PersistedWorkspace {
  expiresAt: number
  state: Record<string, unknown>
}

export interface AssistantMessage { role: string; content: string; evidence?: any[] }
/** The product has one end-user workspace. Legacy HR values are normalized on hydrate. */
export type WorkspaceAudience = 'seeker'
export interface UserProfile {
  fullName: string
  phone: string
  email: string
  city: string
  careerStatus: string
  education: string
  experienceYears?: number
  school: string
  major: string
  graduationYear: string
  desiredRole: string
}

export interface WorkStyleAssessment {
  collaboration: number
  adaptability: number
  resilience: number
  initiative: number
}

const emptyProfile = (): UserProfile => ({
  fullName: '', phone: '', email: '', city: '', careerStatus: '', education: '', experienceYears: undefined, school: '', major: '',
  graduationYear: '', desiredRole: '',
})
const defaultWorkStyleAssessment = (): WorkStyleAssessment => ({
  collaboration: 65, adaptability: 65, resilience: 60, initiative: 65,
})

export const useWorkspaceStore = defineStore('workspace', () => {
  const ownerId = ref('')
  const audience = ref<WorkspaceAudience>('seeker')
  const targetRoleId = ref('')
  const targetRoleName = ref('')
  const skills = ref<string[]>([])
  const education = ref('')
  const experienceYears = ref<number>()
  const resume = ref<ResumeResult | null>(null)
  const resumeConfirmed = ref(false)
  const profile = ref<UserProfile>(emptyProfile())
  const workStyleAssessment = ref<WorkStyleAssessment>(defaultWorkStyleAssessment())
  const matchResult = ref<MatchResult | null>(null)
  const learningPath = ref<LearningStage[]>([])
  const jobSearchKeyword = ref('')
  const location = ref('')
  const graphKeyword = ref('')
  const graphViewMode = ref<'role' | 'stack' | 'entity'>('role')
  const graphTechStack = ref('')
  const graphSkillTier = ref('')
  const graphSeniority = ref('')
  const assistantDraft = ref('请解释我与目标岗位的主要技能差距')
  const assistantMessages = ref<AssistantMessage[]>([])
  const updatedAt = ref(0)
  const expiresAt = ref(0)
  let hydrating = false

  const storageKey = computed(() => ownerId.value ? `ci_workspace_v2_${ownerId.value}` : '')
  const hasProfile = computed(() => skills.value.length > 0 || Boolean(education.value) || experienceYears.value !== undefined)

  function snapshot() {
    return {
      audience: audience.value,
      targetRoleId: targetRoleId.value,
      targetRoleName: targetRoleName.value,
      skills: skills.value,
      education: education.value,
      experienceYears: experienceYears.value,
      resume: resume.value,
      resumeConfirmed: resumeConfirmed.value,
      profile: profile.value,
      workStyleAssessment: workStyleAssessment.value,
      matchResult: matchResult.value,
      learningPath: learningPath.value,
      jobSearchKeyword: jobSearchKeyword.value,
      location: location.value,
      graphKeyword: graphKeyword.value,
      graphViewMode: graphViewMode.value,
      graphTechStack: graphTechStack.value,
      graphSkillTier: graphSkillTier.value,
      graphSeniority: graphSeniority.value,
      assistantDraft: assistantDraft.value,
      assistantMessages: assistantMessages.value.slice(-30),
      updatedAt: Date.now(),
    }
  }

  function persist() {
    if (hydrating || !storageKey.value) return
    updatedAt.value = Date.now()
    expiresAt.value = updatedAt.value + RETENTION_MS
    const payload: PersistedWorkspace = { expiresAt: expiresAt.value, state: snapshot() }
    localStorage.setItem(storageKey.value, JSON.stringify(payload))
  }

  function clearState() {
    audience.value = 'seeker'
    targetRoleId.value = ''
    targetRoleName.value = ''
    skills.value = []
    education.value = ''
    experienceYears.value = undefined
    resume.value = null
    resumeConfirmed.value = false
    profile.value = emptyProfile()
    workStyleAssessment.value = defaultWorkStyleAssessment()
    matchResult.value = null
    learningPath.value = []
    jobSearchKeyword.value = ''
    location.value = ''
    graphKeyword.value = ''
    graphViewMode.value = 'role'
    graphTechStack.value = ''
    graphSkillTier.value = ''
    graphSeniority.value = ''
    assistantDraft.value = '请解释我与目标岗位的主要技能差距'
    assistantMessages.value = []
    updatedAt.value = 0
    expiresAt.value = 0
  }

  function hydrate(userId: string) {
    if (!userId || ownerId.value === userId) return
    hydrating = true
    ownerId.value = userId
    clearState()
    try {
      const raw = localStorage.getItem(`ci_workspace_v2_${userId}`)
      const payload = raw ? JSON.parse(raw) as PersistedWorkspace : null
      if (payload && payload.expiresAt > Date.now()) {
        const state = payload.state as any
        audience.value = 'seeker'
        targetRoleId.value = state.targetRoleId || ''
        targetRoleName.value = state.targetRoleName || ''
        skills.value = Array.isArray(state.skills) ? state.skills : []
        education.value = state.education || ''
        experienceYears.value = state.experienceYears
        resume.value = state.resume || null
        resumeConfirmed.value = Boolean(state.resumeConfirmed)
        profile.value = { ...emptyProfile(), ...(state.profile || {}) }
        workStyleAssessment.value = { ...defaultWorkStyleAssessment(), ...(state.workStyleAssessment || {}) }
        matchResult.value = state.matchResult || null
        learningPath.value = Array.isArray(state.learningPath) ? state.learningPath : []
        jobSearchKeyword.value = state.jobSearchKeyword || ''
        location.value = state.location || ''
        graphKeyword.value = state.graphKeyword || ''
        graphViewMode.value = ['stack', 'entity'].includes(state.graphViewMode) ? state.graphViewMode : 'role'
        graphTechStack.value = state.graphTechStack || ''
        graphSkillTier.value = state.graphSkillTier || ''
        graphSeniority.value = state.graphSeniority || ''
        assistantDraft.value = state.assistantDraft || '请解释我与目标岗位的主要技能差距'
        assistantMessages.value = Array.isArray(state.assistantMessages) ? state.assistantMessages : []
        updatedAt.value = Number(state.updatedAt || 0)
        expiresAt.value = payload.expiresAt
      } else if (raw) {
        localStorage.removeItem(`ci_workspace_v2_${userId}`)
      }
    } finally {
      hydrating = false
    }
  }

  function selectTarget(roleId: string, roleName: string) {
    if (targetRoleId.value && targetRoleId.value !== roleId) {
      matchResult.value = null
      learningPath.value = []
    }
    targetRoleId.value = roleId
    targetRoleName.value = roleName
  }

  function selectAudience(_value: WorkspaceAudience = 'seeker') {
    audience.value = 'seeker'
  }

  function selectLocation(value: string) {
    location.value = value
  }

  function setMatch(result: MatchResult) {
    targetRoleId.value = result.roleId
    targetRoleName.value = result.roleName
    matchResult.value = result
    learningPath.value = []
  }

  function updateProfile(value: Partial<UserProfile>) {
    profile.value = { ...profile.value, ...value }
  }

  function clearResume() {
    resume.value = null
    resumeConfirmed.value = false
  }

  function clearWorkspace() {
    const key = storageKey.value
    clearState()
    if (key) localStorage.removeItem(key)
  }

  watch(
    [audience, targetRoleId, targetRoleName, skills, education, experienceYears, resume, resumeConfirmed, profile, workStyleAssessment, matchResult, learningPath, jobSearchKeyword, location, graphKeyword, graphViewMode, graphTechStack, graphSkillTier, graphSeniority, assistantDraft, assistantMessages],
    persist,
    { deep: true },
  )

  return {
    audience, targetRoleId, targetRoleName, skills, education, experienceYears, resume, resumeConfirmed, profile, workStyleAssessment,
    matchResult, learningPath, jobSearchKeyword, location, graphKeyword, graphViewMode, graphTechStack, graphSkillTier, graphSeniority, assistantDraft, assistantMessages,
    updatedAt, expiresAt, hasProfile, hydrate, selectAudience, selectLocation, selectTarget, setMatch, updateProfile, clearResume, clearWorkspace,
  }
})
