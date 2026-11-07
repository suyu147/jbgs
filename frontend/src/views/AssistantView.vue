<script setup lang="ts">
import { ElMessageBox } from 'element-plus'
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { storeToRefs } from 'pinia'
import { BriefcaseBusiness, Check, CircleHelp, DatabaseZap, History, LoaderCircle, Pencil, Send, SquarePen, Target, Trash2, User, X } from 'lucide-vue-next'
import { insightService } from '@/services/insightService'
import { apiUrl } from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useWorkspaceStore } from '@/stores/workspace'
import type { AgentSessionSummary } from '@/types/domain'
import AssistantRobot from '@/components/assistant/AssistantRobot.vue'

type AssistantMode = 'career_planning' | 'ability_analysis'

const auth = useAuthStore()
const route = useRoute()
const workspace = useWorkspaceStore()
const { assistantDraft: input, assistantMessages: messages } = storeToRefs(workspace)
const sessions = ref<AgentSessionSummary[]>([])
const sessionId = ref('')
const activeSessionId = ref('')
const loading = ref(false)
const historyOpen = ref(false)
const historyLoading = ref(false)
const deletingId = ref('')
const editingId = ref('')
const renamingId = ref('')
const renameDraft = ref('')
const renameError = ref('')
const modelAvailable = ref<boolean | null>(null)
const providerConfigured = ref(false)
const providerReason = ref('')
const error = ref('')
const messagesPanel = ref<HTMLElement | null>(null)
const mode = ref<AssistantMode>(String(route.query.mode || '') === 'ability_analysis' ? 'ability_analysis' : 'career_planning')
const modeMeta = computed(() => mode.value === 'ability_analysis'
  ? { label: '能力分析助手', code: 'ABILITY ANALYSIS', title: '解释诊断结果与能力变化', description: '围绕已确认简历、目标岗位和本地匹配报告，梳理差距、优先级与行动建议。', botLabel: '能力分析助手', questions: ['为什么这些技能会成为当前岗位的主要差距？', '请解释当前岗位的能力要求变化。', '把待提升技能整理成行动顺序。'] }
  : { label: '岗位规划助手', code: 'CAREER PLANNING', title: '从岗位信息走到下一步', description: '围绕岗位职责、技能、趋势和学习资源，帮助你理解机会并规划成长方向。', botLabel: '岗位规划助手', questions: ['这个岗位未来几年的发展方向是什么？', '我应该优先学习哪些技能？', '这个岗位适合怎样的学习路径？'] })
const agentStatus = computed(() => {
  if (modelAvailable.value !== false) return { title: modelAvailable.value === null ? '正在确认服务状态' : '智能体已配置', detail: '回答可展开查看引用证据' }
  if (!providerConfigured.value) return { title: '本地规则解释', detail: `${modeMeta.value.botLabel}尚未配置` }
  if (providerReason.value === 'insufficient_credits') return { title: '智能体已接入 · 降级运行', detail: '当前 Coze 额度不足，已启用本地规则' }
  if (providerReason.value === 'authentication_failed') return { title: '智能体已接入 · 鉴权异常', detail: '当前凭证不可用，已启用本地规则' }
  if (providerReason.value === 'rate_limited') return { title: '智能体已接入 · 请求受限', detail: '请求频率受限，已启用本地规则' }
  return { title: '智能体已接入 · 降级运行', detail: '外部服务暂不可用，已启用本地规则' }
})

function switchMode(nextMode: AssistantMode) {
  mode.value = nextMode
  error.value = ''
}

async function loadSessions(selectLatest = false) {
  historyLoading.value = true
  try {
    const result = await insightService.getAgentSessions()
    sessions.value = result.items
    if (selectLatest && result.items[0]) await selectSession(result.items[0].id, true)
  } catch (reason: any) {
    error.value = reason.message || '历史对话暂时无法读取'
  } finally {
    historyLoading.value = false
  }
}

async function selectSession(id: string, preserveDraft = false) {
  if (!id || id === activeSessionId.value || loading.value) return
  historyLoading.value = true
  error.value = ''
  try {
    const session = await insightService.getAgentSession(id)
    activeSessionId.value = id
    sessionId.value = id
    messages.value = session.messages.map(message => ({ role: message.role, content: message.content, evidence: message.evidence || [] }))
    if (!preserveDraft) input.value = ''
  } catch (reason: any) {
    error.value = reason.message || '对话内容读取失败'
  } finally {
    historyLoading.value = false
  }
}

function newChat() {
  cancelRename()
  sessionId.value = ''
  activeSessionId.value = ''
  messages.value = []
  input.value = ''
  error.value = ''
}

function beginRename(session: AgentSessionSummary) {
  editingId.value = session.id
  renameDraft.value = session.title
  renameError.value = ''
  nextTick(() => {
    const input = document.getElementById(`session-title-${session.id}`) as HTMLInputElement | null
    input?.focus()
    input?.select()
  })
}

function cancelRename() {
  if (renamingId.value) return
  editingId.value = ''
  renameDraft.value = ''
  renameError.value = ''
}

async function saveSessionTitle(session: AgentSessionSummary) {
  const title = renameDraft.value.trim()
  if (!title) {
    renameError.value = '对话名称不能为空'
    return
  }
  if (title.length > 60) {
    renameError.value = '对话名称不能超过 60 个字符'
    return
  }
  if (title === session.title) {
    cancelRename()
    return
  }
  renamingId.value = session.id
  renameError.value = ''
  try {
    const updated = await insightService.renameAgentSession(session.id, title)
    sessions.value = sessions.value.map(item => item.id === session.id ? { ...item, ...updated } : item)
    editingId.value = ''
    renameDraft.value = ''
  } catch (reason: any) {
    renameError.value = reason.message || '对话重命名失败'
  } finally {
    renamingId.value = ''
  }
}

async function removeSession(session: AgentSessionSummary) {
  if (deletingId.value) return
  try { await ElMessageBox.confirm('删除后将移除此对话记录。', `删除“${session.title}”？`, { confirmButtonText: '删除对话', cancelButtonText: '保留', type: 'warning' }) } catch { return }
  deletingId.value = session.id
  try {
    await insightService.deleteAgentSession(session.id)
    sessions.value = sessions.value.filter(item => item.id !== session.id)
    if (activeSessionId.value === session.id) {
      newChat()
      if (sessions.value[0]) await selectSession(sessions.value[0].id)
    }
  } catch (reason: any) {
    error.value = reason.message || '删除历史对话失败'
  } finally {
    deletingId.value = ''
  }
}

async function send() {
  const text = input.value.trim()
  if (!text || loading.value || !workspace.targetRoleId) return
  messages.value.push({ role: 'user', content: text })
  input.value = ''
  loading.value = true
  error.value = ''
  try {
    const response = await fetch(apiUrl('/agent/chat'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(auth.session?.accessToken ? { Authorization: `Bearer ${auth.session.accessToken}` } : {}) },
      body: JSON.stringify({ agentMode: mode.value, message: text, sessionId: sessionId.value, reportId: workspace.matchResult?.reportId || '', roleId: workspace.targetRoleId, roleName: workspace.targetRoleName }),
    })
    if (!response.ok) throw new Error('智能体暂时无法回答，请稍后重试；你的问题已保留。')
    const assistantIndex = messages.value.push({ role: 'assistant', content: '', evidence: [] }) - 1
    const reader = response.body?.getReader()
    if (!reader) throw new Error('浏览器不支持流式响应')
    const decoder = new TextDecoder()
    let buffer = ''
    let evidence: any[] = []
    let done: any = null
    let pendingToken = ''
    let flushFrame: number | null = null

    const scrollToLatest = () => {
      nextTick(() => {
        const panel = messagesPanel.value
        if (!panel) return
        const distanceFromBottom = panel.scrollHeight - panel.scrollTop - panel.clientHeight
        if (distanceFromBottom < 180) panel.scrollTop = panel.scrollHeight
      })
    }

    const flushToken = () => {
      flushFrame = null
      if (!pendingToken) return
      const current = messages.value[assistantIndex]
      messages.value[assistantIndex] = { ...current, content: `${current?.content || ''}${pendingToken}` }
      pendingToken = ''
      scrollToLatest()
    }

    const queueToken = (content: string) => {
      pendingToken += content
      if (flushFrame === null) flushFrame = requestAnimationFrame(flushToken)
    }

    const handleBlock = (block: string) => {
      const dataLine = block.split(/\r?\n/).find(line => line.startsWith('data:'))
      if (!dataLine) return
      try {
        const event = JSON.parse(dataLine.slice(5).trim())
        if (event.type === 'token' && typeof event.content === 'string') {
          queueToken(event.content)
        } else if (event.type === 'evidence') {
          evidence = Array.isArray(event.items) ? event.items : []
          const current = messages.value[assistantIndex]
          messages.value[assistantIndex] = { ...current, evidence }
        } else if (event.type === 'done') {
          done = event
        }
      } catch {
        // Ignore incomplete or non-JSON SSE frames; the next chunk completes them.
      }
    }

    while (true) {
      const { value, done: streamDone } = await reader.read()
      buffer += decoder.decode(value || new Uint8Array(), { stream: !streamDone })
      const blocks = buffer.split(/\r?\n\r?\n/)
      buffer = blocks.pop() || ''
      blocks.forEach(handleBlock)
      if (streamDone) break
    }
    if (buffer.trim()) handleBlock(buffer)
    if (flushFrame !== null) cancelAnimationFrame(flushFrame)
    flushToken()
    const finalMessage = messages.value[assistantIndex]
    if (!finalMessage?.content) messages.value[assistantIndex] = { ...finalMessage, content: '未生成回答', evidence }
    sessionId.value = done?.sessionId || sessionId.value
    activeSessionId.value = sessionId.value
    if (typeof done?.modelAvailable === 'boolean') modelAvailable.value = done.modelAvailable
    providerReason.value = typeof done?.providerReason === 'string' ? done.providerReason : ''
    await loadSessions()
  } catch (reason: any) {
    error.value = reason.message || '对话请求失败，请稍后重试。'
    if (!input.value.trim()) input.value = text
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  if (route.query.mode === 'ability_analysis') mode.value = 'ability_analysis'
  try {
    providerConfigured.value = Boolean((await insightService.health()).agentConfigured)
    modelAvailable.value = providerConfigured.value
  } catch {
    providerConfigured.value = false
    modelAvailable.value = false
  }
  await loadSessions(true)
  if (typeof route.query.prompt === 'string' && route.query.prompt.trim()) input.value = route.query.prompt.trim()
})
</script>

<template>
  <div class="assistant-layout assistant-workbench">
    <aside class="assistant-sidebar"><button class="mobile-history-toggle secondary-btn" :aria-expanded="historyOpen" @click="historyOpen = !historyOpen"><History aria-hidden="true" :size="16" />{{ historyOpen ? '收起历史对话' : '查看历史对话' }}</button>
      <section class="assistant-identity" aria-label="职业助手状态">
          <span class="assistant-service-icon"><AssistantRobot compact :busy="loading" :online="modelAvailable !== false" :mode="mode" /></span>
          <div class="agent-status assistant-identity-status">
            <span :class="modelAvailable === false ? 'degraded' : 'online'"></span>
            <div><strong>{{ agentStatus.title }}</strong><small>{{ agentStatus.detail }}</small></div>
          </div>
      </section>

      <section class="assistant-context">
        <div class="assistant-mode-switch-row">
          <div class="assistant-mode-switch" role="group" aria-label="选择助手模式">
            <button type="button" :class="{ active: mode === 'career_planning' }" :aria-pressed="mode === 'career_planning'" @click="switchMode('career_planning')"><BriefcaseBusiness aria-hidden="true" :size="15" /><span class="assistant-mode-dot" :class="mode === 'career_planning' ? 'active' : 'standby'"></span>岗位规划助手</button>
            <button type="button" :class="{ active: mode === 'ability_analysis' }" :aria-pressed="mode === 'ability_analysis'" @click="switchMode('ability_analysis')"><Target aria-hidden="true" :size="15" /><span class="assistant-mode-dot" :class="mode === 'ability_analysis' ? 'active' : 'standby'"></span>能力分析助手</button>
          </div>
          <button class="assistant-agent-info" type="button" aria-label="查看智能体职责说明" title="岗位规划助手：职业路径、发展方向、学习规划&#10;能力分析助手：技能差距、能力雷达、提升建议">
            <CircleHelp aria-hidden="true" :size="17" />
            <span class="assistant-agent-tooltip" role="tooltip"><strong>岗位规划助手</strong><small>擅长：职业路径、发展方向、学习规划</small><strong>能力分析助手</strong><small>擅长：技能差距、能力雷达、提升建议</small></span>
          </button>
        </div>
        <div v-if="workspace.targetRoleId" class="assistant-role">
          <BriefcaseBusiness aria-hidden="true" />
          <div><small>当前分析岗位</small><strong>{{ workspace.targetRoleName }}</strong></div>
          <span>{{ workspace.matchResult ? '已关联诊断' : '证据模式' }}</span>
        </div>
      </section>

      <section class="assistant-history" :class="{ 'mobile-open': historyOpen }" aria-label="历史对话">
        <button class="history-new" type="button" @click="newChat">
          <SquarePen aria-hidden="true" :size="18" />
          <span>新对话</span>
          
        </button>
        <div class="history-heading">
          <History aria-hidden="true" :size="15" />
          <span>历史对话</span>
          <LoaderCircle aria-hidden="true" v-if="historyLoading" class="spin" :size="14" />
        </div>
        <div v-if="!sessions.length && !historyLoading" class="history-empty">发送第一条消息后，对话会保存在这里。</div>
        <div class="history-list">
          <article v-for="session in sessions" :key="session.id" :class="['history-row', { active: activeSessionId === session.id }]">
            <form v-if="editingId === session.id" class="history-rename" @submit.prevent="saveSessionTitle(session)" @click.stop>
              <input :id="`session-title-${session.id}`" v-model="renameDraft" class="history-rename-input" maxlength="60" aria-label="对话名称" @keydown.esc.prevent="cancelRename"  name="renameDraft" autocomplete="off">
              <button type="submit" title="保存名称" aria-label="保存名称" :disabled="renamingId === session.id"><LoaderCircle aria-hidden="true" v-if="renamingId === session.id" class="spin" :size="14" /><Check aria-hidden="true" v-else :size="14" /></button>
              <button type="button" title="取消重命名" aria-label="取消重命名" :disabled="renamingId === session.id" @click="cancelRename"><X aria-hidden="true" :size="14" /></button>
            </form>
            <template v-else>
              <button class="history-select" type="button" :title="session.title" @click="selectSession(session.id)">
                <span class="history-dot"><AssistantRobot compact aria-hidden="true" /></span>
                <span class="history-copy"><strong>{{ session.title }}</strong><small>{{ session.messageCount }} 条消息 · {{ session.lastMessage || '尚未发送内容' }}</small></span>
              </button>
              <div class="history-actions">
                <button type="button" :aria-label="`重命名 ${session.title}`" title="重命名" @click.stop="beginRename(session)"><Pencil aria-hidden="true" :size="14" /></button>
                <button class="delete" type="button" :aria-label="`删除 ${session.title}`" title="删除" :disabled="deletingId === session.id" @click.stop="removeSession(session)"><LoaderCircle aria-hidden="true" v-if="deletingId === session.id" class="spin" :size="14" /><Trash2 aria-hidden="true" v-else :size="14" /></button>
              </div>
            </template>
          </article>
        </div>
        <p v-if="renameError" class="history-error" role="alert">{{ renameError }}</p>
      </section>
    </aside>

    <section class="chat-panel">
      <div class="chat-head">
        <span class="chat-head-icon"><AssistantRobot compact :busy="loading" :mode="mode" aria-hidden="true" /></span>
        <div><strong>{{ sessions.find(item => item.id === activeSessionId)?.title || workspace.targetRoleName || '新对话' }}</strong><small>{{ modeMeta.label }} · {{ workspace.targetRoleName || '尚未选择岗位' }} · 证据受控</small></div>
        <button class="chat-new" type="button" title="新对话" aria-label="新对话" @click="newChat"><SquarePen aria-hidden="true" :size="17" /></button>
      </div>
      <div ref="messagesPanel" class="messages" role="log" aria-label="职业咨询对话" :aria-busy="loading">
        <div v-if="!messages.length" class="empty-chat"><span><DatabaseZap aria-hidden="true" /></span><h2>从一个具体问题开始</h2><p>当前岗位和最近一次能力诊断会自动带入对话。</p><small>可询问岗位趋势、技能差距、学习顺序和证据来源</small></div>
        <article v-for="(message, index) in messages" :key="index" :class="['message', message.role]">
          <span><User aria-hidden="true" v-if="message.role === 'user'" /><AssistantRobot v-else compact aria-hidden="true" /></span>
          <div><p>{{ message.content }}</p><details v-if="message.evidence?.length"><summary>{{ message.evidence.length }} 条引用证据</summary><div v-for="(e, i) in message.evidence" :key="i"><b>{{ e.sourceRecord || '证据记录' }}</b><small v-if="e.period">周期 {{ e.period }}</small><small>{{ e.snippet || '已通过本地图谱核验' }}</small><a v-if="e.url" :href="e.url" target="_blank" rel="noreferrer">查看来源</a></div></details></div>
        </article>
        <div v-if="loading" class="typing"><LoaderCircle aria-hidden="true" class="spin" :size="15" />正在查询本地图谱…</div>
      </div>
      <p v-if="error" class="assistant-error" role="alert">{{ error }}</p>
      <section class="chat-recommendations" aria-label="推荐问题">
        <span>为你推荐</span>
        <div class="question-list">
          <button v-for="question in modeMeta.questions" :key="question" type="button" :disabled="loading || !workspace.targetRoleId" @click="input = question; send()">{{ question }}</button>
        </div>
      </section>
      <form class="chat-input" @submit.prevent="send"><textarea v-model="input" aria-label="向职业助手提问" aria-describedby="composer-hint" rows="2" placeholder="询问岗位、趋势、差距或学习路径" name="input" autocomplete="off"></textarea><button class="primary-btn" :disabled="loading || !workspace.targetRoleId || !input.trim()"><Send aria-hidden="true" :size="17" />发送</button></form>
      <p id="composer-hint" class="composer-hint"><template v-if="!workspace.targetRoleId">先<router-link to="/jobs">选择一个目标岗位</router-link>，再开始咨询。</template><template v-else>围绕 {{ workspace.targetRoleName }} 提问 · 回答仅供职业探索参考，请结合引用证据判断。</template></p>
    </section>
  </div>
</template>

<style scoped>
.assistant-sidebar{display:flex;flex-direction:column;min-height:0}
.assistant-history{flex:1;min-height:0;display:flex;flex-direction:column}
.history-list{overflow:auto;min-height:0}
.chat-panel{display:flex;flex-direction:column;min-height:0}
.chat-head{display:flex;align-items:center;gap:12px;flex-shrink:0}
.chat-head>div{min-width:0;flex:1}.chat-head strong,.chat-head small{display:block}
.chat-new{min-width:44px;min-height:44px;background:transparent;color:var(--ui-brand)}
.messages{flex:1;overflow:auto}.message{display:flex;align-items:flex-start}
.message.user{flex-direction:row-reverse}.message p{margin:0;white-space:pre-wrap}
.message>span{flex-shrink:0;width:28px;height:28px;display:grid;place-items:center;color:var(--ui-brand)}
.message details>div{padding:12px 0;border-top:1px solid var(--ui-line)}
.message details small{display:block}.message details a{text-decoration:underline;text-underline-offset:3px}
.chat-input{display:flex;gap:10px}.chat-input textarea{flex:1;min-width:0;border:0}
.question-list{display:flex;flex-wrap:wrap}.typing{color:var(--ui-muted);display:flex;gap:8px}
.history-row{display:flex;align-items:center}.history-select{display:flex;flex:1;min-width:0;gap:8px;padding:10px;background:transparent;text-align:left}
.history-copy{min-width:0}.history-copy strong,.history-copy small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.history-actions{display:flex}.history-actions button{background:transparent;color:var(--ui-muted)}
.history-empty{color:var(--ui-muted);font-size:12px;padding:12px 0}
.history-new{display:flex;align-items:center;gap:8px;min-height:44px;background:transparent;color:var(--ui-brand)}
.assistant-error,.history-error{color:var(--ui-danger);padding:12px;font-size:13px}
</style>
