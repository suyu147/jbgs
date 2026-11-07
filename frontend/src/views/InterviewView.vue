<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, BriefcaseBusiness, FileText, LoaderCircle, Mic, Sparkles, Upload } from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import { insightService } from '@/services/insightService'
import type { JobDetail, ResumeResult } from '@/types/domain'

const route = useRoute()
const router = useRouter()

const roleId = computed(() => String(route.query.roleId || '').trim())
const roleName = computed(() => String(route.query.roleName || '').trim())

const job = ref<JobDetail | null>(null)
const error = ref('')
const loadingJob = ref(true)
const resumes = ref<ResumeResult[]>([])
const selectedResumeId = ref('')
const selfIntro = ref('')
const questionCount = ref(6)
const starting = ref(false)
const uploadingResume = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

const topSkills = computed(() => (job.value?.skills || []).slice(0, 8).map(item => item.name))
const canStart = computed(() => Boolean(roleId.value) && !starting.value)

async function loadJob() {
  if (!roleId.value) { error.value = '缺少岗位参数，请从岗位详情页进入模拟面试'; loadingJob.value = false; return }
  try { job.value = await insightService.getJob(roleId.value) }
  catch (reason: any) { error.value = reason?.message || '岗位信息加载失败' }
  finally { loadingJob.value = false }
}

async function loadResumes() {
  try {
    const result = await insightService.getMyResumes()
    resumes.value = result.items || []
    if (resumes.value.length) selectedResumeId.value = resumes.value[0].resumeId
  } catch { /* 未登录或无简历时忽略，用户仍可直接开始 */ }
}

async function onPickResumeFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  uploadingResume.value = true
  try {
    const result = await insightService.uploadResume(file)
    await loadResumes()
    selectedResumeId.value = result.resumeId
    ElMessage.success('简历上传并解析成功')
  } catch (reason: any) { ElMessage.error(reason?.message || '简历上传失败') }
  finally { uploadingResume.value = false }
}

async function start() {
  if (!canStart.value) return
  starting.value = true
  try {
    const session = await insightService.startInterview({
      roleId: roleId.value,
      resumeId: selectedResumeId.value || undefined,
      selfIntro: selfIntro.value.trim(),
      questionCount: questionCount.value,
    })
    router.push(`/interview/${session.id}`)
  } catch (reason: any) { ElMessage.error(reason?.message || '面试启动失败，请稍后重试') }
  finally { starting.value = false }
}

onMounted(() => Promise.all([loadJob(), loadResumes()]))
</script>

<template>
  <div class="stack-lg">
    <button class="back-btn" @click="router.back()"><ArrowLeft :size="16" />返回</button>
    <p v-if="error" class="error-text">{{ error }}</p>

    <section class="panel">
      <div class="panel-head">
        <div>
          <span class="section-code">AI MOCK INTERVIEW</span>
          <h2>{{ roleName || job?.name || '模拟面试' }}</h2>
          <p>确认岗位与个人材料后开始。AI 将基于岗位技能要求与你的背景逐题提问，结束后生成评估报告。</p>
        </div>
        <Mic :size="22" />
      </div>

      <div class="interview-form">
        <div v-if="loadingJob" class="interview-hint"><LoaderCircle :size="16" class="spin" />正在加载岗位信息…</div>
        <div v-else-if="job" class="interview-job-brief">
          <span><BriefcaseBusiness :size="15" />{{ job.field || '岗位族待完善' }} · {{ job.postingCount }} 条 JD</span>
          <span v-if="topSkills.length"><Sparkles :size="15" />核心技能：{{ topSkills.join('、') }}</span>
        </div>

        <label class="interview-field">
          <span class="interview-label">选择简历（可选）</span>
          <div class="resume-row">
            <el-select v-model="selectedResumeId" placeholder="不使用简历" clearable style="flex:1">
              <el-option v-for="item in resumes" :key="item.resumeId" :value="item.resumeId" :label="item.fileName || '未命名简历'" />
            </el-select>
            <input ref="fileInput" type="file" accept=".pdf,.docx,.txt,.md" class="hidden-file" @change="onPickResumeFile" />
            <button class="secondary-btn" :disabled="uploadingResume" @click="fileInput?.click()">
              <Upload :size="15" />{{ uploadingResume ? '解析中…' : '上传新简历' }}
            </button>
          </div>
          <small>上传简历后，AI 会针对简历里的项目经历追问细节。</small>
        </label>

        <label class="interview-field">
          <span class="interview-label">自我介绍（可选）</span>
          <el-input v-model="selfIntro" type="textarea" :rows="4" maxlength="2000" show-word-limit
            placeholder="用 100-300 字介绍你的教育背景、工作经历和求职方向，AI 会据此定制面试问题" />
        </label>

        <label class="interview-field">
          <span class="interview-label">面试题量</span>
          <el-radio-group v-model="questionCount">
            <el-radio-button :value="3">3 题（快速）</el-radio-button>
            <el-radio-button :value="6">6 题（标准）</el-radio-button>
            <el-radio-button :value="8">8 题（深入）</el-radio-button>
          </el-radio-group>
        </label>

        <div class="interview-actions">
          <button class="primary-btn large" :disabled="!canStart" @click="start">
            <LoaderCircle v-if="starting" :size="16" class="spin" />
            <Mic v-else :size="16" />
            {{ starting ? '正在生成面试问题…' : '开始模拟面试' }}
          </button>
          <span class="interview-hint"><FileText :size="14" />支持文字或语音作答；语音朗读由浏览器自动完成</span>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.interview-form { display: grid; gap: 20px; padding: 24px; }
.interview-job-brief { display: flex; flex-wrap: wrap; gap: 10px 22px; padding: 14px 16px; border-radius: 10px; background: #f6f9f8; color: #46615d; font-size: 13px; }
.interview-job-brief span { display: inline-flex; align-items: center; gap: 7px; }
.interview-field { display: grid; gap: 8px; }
.interview-label { font-weight: 600; font-size: 14px; color: #22423e; }
.interview-field small { color: #8a9a97; font-size: 12px; }
.resume-row { display: flex; gap: 10px; align-items: center; }
.hidden-file { display: none; }
.interview-actions { display: flex; align-items: center; gap: 14px; flex-wrap: wrap; margin-top: 4px; }
.interview-hint { display: inline-flex; align-items: center; gap: 6px; color: #8a9a97; font-size: 12px; }
.spin { animation: interview-spin 1s linear infinite; }
@keyframes interview-spin { to { transform: rotate(360deg); } }
</style>
