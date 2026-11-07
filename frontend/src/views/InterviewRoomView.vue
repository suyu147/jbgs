<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Award, Bot, CircleCheck, CircleAlert, FileText, LoaderCircle, Mic, MicOff, Send, Sparkles, TrendingUp, Volume2 } from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import { insightService } from '@/services/insightService'
import type { InterviewAnswerResult, InterviewSessionState } from '@/types/domain'

const route = useRoute()
const router = useRouter()

const session = ref<InterviewSessionState | null>(null)
const error = ref('')
const loading = ref(true)
const answerText = ref('')
const submitting = ref(false)
const generatingReport = ref(false)
const autoSpeak = ref(true)

const recording = ref(false)
const processingAudio = ref(false)
let mediaRecorder: MediaRecorder | null = null
let audioChunks: Blob[] = []

const finished = computed(() => Boolean(session.value && session.value.currentIndex >= session.value.totalCount))
const currentQuestion = computed(() => {
  const interview = session.value
  if (!interview || finished.value) return null
  return interview.questions[interview.currentIndex] || null
})
const answeredQuestions = computed(() => (session.value?.questions || []).filter(item => item.answered))
const transcriptEl = ref<HTMLElement | null>(null)

function speak(text: string) {
  if (!autoSpeak.value || typeof window === 'undefined' || !('speechSynthesis' in window)) return
  window.speechSynthesis.cancel()
  const utterance = new SpeechSynthesisUtterance(text)
  utterance.lang = 'zh-CN'
  utterance.rate = 1
  window.speechSynthesis.speak(utterance)
}

function replayQuestion() {
  if (typeof window === 'undefined' || !('speechSynthesis' in window)) { ElMessage.warning('当前浏览器不支持语音朗读'); return }
  window.speechSynthesis.cancel()
  const utterance = new SpeechSynthesisUtterance(currentQuestion.value?.question || '')
  utterance.lang = 'zh-CN'
  window.speechSynthesis.speak(utterance)
}

async function loadSession() {
  loading.value = true
  try {
    session.value = await insightService.getInterviewSession(String(route.params.id))
    await nextTick()
    if (currentQuestion.value) speak(currentQuestion.value.question)
  } catch (reason: any) { error.value = reason?.message || '面试会话加载失败' }
  finally { loading.value = false }
}

function applyAnswerResult(result: InterviewAnswerResult) {
  const interview = session.value
  if (!interview) return
  const item = interview.questions[interview.currentIndex]
  if (item) {
    item.answered = true
    item.answer = result.transcript || answerText.value
    item.feedback = result.feedback
    item.score = result.score
    item.referencePoints = result.referencePoints || item.referencePoints
  }
  interview.currentIndex += 1
  interview.status = result.status
  if (result.nextQuestion) speak(result.nextQuestion.question)
  answerText.value = ''
  void nextTick(() => transcriptEl.value?.scrollIntoView({ behavior: 'smooth', block: 'end' }))
}

async function submitText() {
  const text = answerText.value.trim()
  if (!text || submitting.value || !session.value || finished.value) return
  submitting.value = true
  try {
    const result = await insightService.sendInterviewAnswer(session.value.id, text)
    applyAnswerResult(result)
  } catch (reason: any) { ElMessage.error(reason?.message || '提交失败，请重试') }
  finally { submitting.value = false }
}

async function submitAudio(blob: Blob) {
  if (!session.value || processingAudio.value) return
  processingAudio.value = true
  try {
    const result = await insightService.uploadInterviewAudio(session.value.id, blob)
    applyAnswerResult(result)
  } catch (reason: any) { ElMessage.error(reason?.message || '语音识别失败，请重试或改用文字作答') }
  finally { processingAudio.value = false }
}

async function toggleRecording() {
  if (processingAudio.value || submitting.value) return
  if (recording.value) { mediaRecorder?.stop(); return }
  if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) { ElMessage.warning('当前浏览器不支持录音，请使用文字作答'); return }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    const mimeType = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4'].find(type => MediaRecorder.isTypeSupported(type)) || ''
    mediaRecorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
    audioChunks = []
    mediaRecorder.ondataavailable = event => { if (event.data.size) audioChunks.push(event.data) }
    mediaRecorder.onstop = () => {
      stream.getTracks().forEach(track => track.stop())
      recording.value = false
      const blob = new Blob(audioChunks, { type: mediaRecorder?.mimeType || 'audio/webm' })
      if (blob.size) void submitAudio(blob)
    }
    mediaRecorder.start()
    recording.value = true
  } catch { ElMessage.error('无法访问麦克风，请检查浏览器权限或改用文字作答') }
}

async function generateReport() {
  if (!session.value || generatingReport.value) return
  generatingReport.value = true
  try { session.value.report = await insightService.getInterviewReport(session.value.id) }
  catch (reason: any) { ElMessage.error(reason?.message || '报告生成失败，请重试') }
  finally { generatingReport.value = false }
}

function scoreClass(score: number | null) {
  if (score === null) return 'muted'
  return score >= 75 ? 'good' : score >= 60 ? 'mid' : 'bad'
}

onMounted(loadSession)
onUnmounted(() => { if (typeof window !== 'undefined' && 'speechSynthesis' in window) window.speechSynthesis.cancel() })
</script>

<template>
  <div class="stack-lg interview-room">
    <button class="back-btn" @click="router.back()"><ArrowLeft :size="16" />返回</button>
    <p v-if="error" class="error-text">{{ error }}</p>

    <div v-if="loading" class="panel interview-loading"><LoaderCircle :size="18" class="spin" />正在加载面试会话…</div>

    <template v-else-if="session">
      <section class="panel">
        <div class="panel-head">
          <div>
            <span class="section-code">INTERVIEW IN PROGRESS</span>
            <h2>{{ session.roleName }} · AI 模拟面试</h2>
            <p>第 {{ Math.min(session.currentIndex + (finished ? 0 : 1), session.totalCount) }} / {{ session.totalCount }} 题
              · {{ finished ? '问答已完成' : '回答后 AI 会点评并给出下一题' }}</p>
          </div>
          <label class="speak-toggle"><input v-model="autoSpeak" type="checkbox" />自动朗读问题</label>
        </div>
        <div class="interview-progress"><i :style="{ width: `${session.totalCount ? (session.currentIndex / session.totalCount) * 100 : 0}%` }"></i></div>
      </section>

      <section ref="transcriptEl" class="stack-md">
        <article v-for="item in answeredQuestions" :key="item.index" class="qa-item">
          <div class="qa-question"><Bot :size="18" /><div><small>第 {{ item.index + 1 }} 题 · {{ item.focus }}</small><p>{{ item.question }}</p></div></div>
          <div class="qa-answer"><p>{{ item.answer }}</p></div>
          <div class="qa-feedback">
            <header><span :class="['score-chip', scoreClass(item.score)]">{{ item.score === null ? '已记录' : `${item.score} 分` }}</span><strong>AI 点评</strong></header>
            <p>{{ item.feedback }}</p>
            <div v-if="item.referencePoints.length" class="qa-points">
              <small>参考要点：</small>
              <span v-for="point in item.referencePoints" :key="point">{{ point }}</span>
            </div>
          </div>
        </article>

        <article v-if="currentQuestion" class="panel current-question">
          <div class="qa-question"><Bot :size="20" /><div><small>第 {{ currentQuestion.index + 1 }} 题 · {{ currentQuestion.focus }}</small>
            <p>{{ currentQuestion.question }}</p></div></div>
          <button class="text-btn speak-btn" @click="replayQuestion"><Volume2 :size="15" />重新朗读</button>
          <div class="answer-area">
            <el-input v-model="answerText" type="textarea" :rows="4" maxlength="8000" :disabled="submitting || processingAudio"
              placeholder="在这里输入你的回答，或点击下方麦克风按钮用语音作答" @keydown.ctrl.enter="submitText" />
            <div class="answer-actions">
              <button class="secondary-btn record-btn" :class="{ recording }" :disabled="submitting || processingAudio" @click="toggleRecording">
                <MicOff v-if="recording" :size="16" />
                <LoaderCircle v-else-if="processingAudio" :size="16" class="spin" />
                <Mic v-else :size="16" />
                {{ recording ? '点击结束录音' : processingAudio ? '语音识别中…' : '语音作答' }}
              </button>
              <button class="primary-btn" :disabled="!answerText.trim() || submitting || processingAudio" @click="submitText">
                <LoaderCircle v-if="submitting" :size="16" class="spin" />
                <Send v-else :size="15" />
                {{ submitting ? 'AI 点评中…' : '提交回答' }}
              </button>
            </div>
            <small class="answer-tip">录音需后端配置语音识别（ASR）密钥；未配置时请使用文字作答。Ctrl+Enter 快速提交。</small>
          </div>
        </article>

        <article v-else-if="finished && !session.report" class="panel finish-panel">
          <CircleCheck :size="22" />
          <div><h3>问答全部完成</h3><p>点击下方按钮，AI 将综合全部回答生成面试评估报告。</p></div>
          <button class="primary-btn" :disabled="generatingReport" @click="generateReport">
            <LoaderCircle v-if="generatingReport" :size="16" class="spin" />
            <FileText v-else :size="15" />
            {{ generatingReport ? '报告生成中…' : '生成面试报告' }}
          </button>
        </article>
      </section>

      <section v-if="session.report" class="panel report-panel">
        <div class="panel-head">
          <div><span class="section-code">INTERVIEW REPORT</span><h2>面试评估报告</h2><p>综合 {{ session.totalCount }} 个问题的回答表现生成。</p></div>
          <span class="report-score"><small>综合得分</small><strong>{{ session.report.overallScore }}</strong><em>/100</em></span>
        </div>
        <div class="report-body">
          <p class="report-summary">{{ session.report.summary }}</p>
          <div class="report-dimensions">
            <div v-for="dimension in session.report.dimensions" :key="dimension.name" class="dimension">
              <header><strong>{{ dimension.name }}</strong><span>{{ dimension.score }}</span></header>
              <div class="dimension-bar"><i :style="{ width: `${dimension.score}%` }" :class="scoreClass(dimension.score)"></i></div>
              <small>{{ dimension.comment }}</small>
            </div>
          </div>
          <div class="report-lists">
            <div><header><CircleCheck :size="15" />亮点</header><ul><li v-for="item in session.report.strengths" :key="item">{{ item }}</li></ul></div>
            <div><header><CircleAlert :size="15" />待提升</header><ul><li v-for="item in session.report.improvements" :key="item">{{ item }}</li></ul></div>
            <div><header><TrendingUp :size="15" />提升建议</header><ul><li v-for="item in session.report.suggestions" :key="item">{{ item }}</li></ul></div>
          </div>
          <footer class="report-footer">
            <button class="secondary-btn" @click="router.push(`/jobs/${encodeURIComponent(session.roleId)}`)"><Award :size="15" />回到岗位档案</button>
            <button class="primary-btn" @click="router.push('/interview')"><Sparkles :size="15" />再来一场面试</button>
          </footer>
        </div>
      </section>
    </template>
  </div>
</template>

<style scoped>
.interview-room { max-width: 860px; }
.interview-loading { display: flex; align-items: center; gap: 10px; padding: 28px; color: #6b7f7c; }
.stack-md { display: grid; gap: 16px; }
.speak-toggle { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: #5c6f6c; white-space: nowrap; }
.interview-progress { height: 4px; background: #edf2f1; }
.interview-progress i { display: block; height: 100%; background: #0f8f87; transition: width .3s ease; }

.qa-item { display: grid; gap: 10px; padding: 18px; border: 1px solid #e4ebe9; border-radius: 12px; background: #fff; }
.qa-question { display: flex; gap: 10px; align-items: flex-start; color: #1d3a36; }
.qa-question small { color: #8a9a97; font-size: 12px; }
.qa-question p { margin: 4px 0 0; font-weight: 600; line-height: 1.6; }
.qa-answer { padding: 12px 14px; border-radius: 10px; background: #f2f7f6; }
.qa-answer p { margin: 0; white-space: pre-wrap; line-height: 1.7; color: #33453f; }
.qa-feedback { padding: 12px 14px; border-left: 3px solid #0f8f87; background: #fbfefd; border-radius: 0 10px 10px 0; }
.qa-feedback header { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
.qa-feedback p { margin: 0; line-height: 1.7; color: #40544f; font-size: 14px; }
.score-chip { padding: 2px 10px; border-radius: 999px; font-size: 12px; font-weight: 700; }
.score-chip.good { background: #e3f6ee; color: #177245; }
.score-chip.mid { background: #fdf3e0; color: #9a6b13; }
.score-chip.bad { background: #fdecee; color: #a13748; }
.score-chip.muted { background: #eef1f0; color: #6b7f7c; }
.qa-points { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; align-items: center; }
.qa-points small { color: #8a9a97; }
.qa-points span { padding: 2px 9px; border-radius: 6px; background: #f0f5f4; color: #4c625d; font-size: 12px; }

.current-question { display: grid; gap: 14px; padding: 20px; }
.speak-btn { align-self: flex-start; color: #0f8f87; }
.answer-area { display: grid; gap: 12px; }
.answer-actions { display: flex; gap: 10px; flex-wrap: wrap; }
.record-btn.recording { border-color: #a13748; color: #a13748; background: #fdecee; animation: record-pulse 1.4s ease infinite; }
@keyframes record-pulse { 50% { box-shadow: 0 0 0 6px rgba(161,55,72,.08); } }
.answer-tip { color: #93a5a1; font-size: 12px; }

.finish-panel { display: flex; align-items: center; gap: 16px; padding: 22px; flex-wrap: wrap; color: #177245; }
.finish-panel h3 { margin: 0 0 4px; font-size: 16px; color: #1d3a36; }
.finish-panel p { margin: 0; color: #6b7f7c; font-size: 13px; }
.finish-panel .primary-btn { margin-left: auto; }

.report-score { display: grid; justify-items: center; line-height: 1.1; }
.report-score small { color: #8a9a97; font-size: 12px; }
.report-score strong { font-size: 34px; color: #0f8f87; }
.report-score em { color: #9aa9a6; font-style: normal; font-size: 12px; }
.report-body { display: grid; gap: 22px; padding: 24px; }
.report-summary { margin: 0; line-height: 1.8; color: #33453f; }
.report-dimensions { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; }
.dimension header { display: flex; justify-content: space-between; font-size: 14px; margin-bottom: 6px; }
.dimension-bar { height: 8px; border-radius: 999px; background: #eef2f1; overflow: hidden; }
.dimension-bar i { display: block; height: 100%; border-radius: 999px; }
.dimension-bar i.good { background: #17a05d; }
.dimension-bar i.mid { background: #e2a03c; }
.dimension-bar i.bad { background: #d0566b; }
.dimension-bar i.muted { background: #9aa9a6; }
.dimension small { color: #7d8f8b; font-size: 12px; }
.report-lists { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px; }
.report-lists > div { padding: 16px; border-radius: 10px; background: #f7faf9; }
.report-lists header { display: flex; align-items: center; gap: 7px; font-weight: 600; font-size: 14px; margin-bottom: 8px; color: #22423e; }
.report-lists ul { margin: 0; padding-left: 18px; display: grid; gap: 6px; color: #475a55; font-size: 13px; line-height: 1.6; }
.report-footer { display: flex; gap: 10px; flex-wrap: wrap; }
.spin { animation: interview-spin 1s linear infinite; }
@keyframes interview-spin { to { transform: rotate(360deg); } }
</style>
