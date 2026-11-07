<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight } from 'lucide-vue-next'
import AssistantRobot from './AssistantRobot.vue'
import { useAssistantPopup } from './useAssistantPopup'
import { useAuthStore } from '@/stores/auth'
import { useWorkspaceStore } from '@/stores/workspace'
import { apiUrl } from '@/api/client'

type QuickMessage = { role: 'user' | 'assistant'; content: string }

const router = useRouter()
const auth = useAuthStore()
const workspace = useWorkspaceStore()
const launcher = ref<HTMLElement | null>(null)
const open = ref(false)
const draft = ref('')
const sending = ref(false)
const tipIndex = ref(0)
const messages = ref<QuickMessage[]>([
  { role: 'assistant', content: '我是你的职业洞察助手“查查”，有什么问题可以向我提问～' },
])
const position = ref<{ left: number; top: number } | null>(null)
const popupStyle = useAssistantPopup(launcher, position, 348)
const drag = ref({ active: false, moved: false, startX: 0, startY: 0, left: 0, top: 0 })
const tips = [
  '我是你的职业洞察助手“查查”，有什么问题可以向我提问～',
  '想了解岗位趋势、技能差距，问问我就好。',
  '告诉我目标岗位，我帮你找到下一步行动。',
]
const quickPrompts = ['这个岗位未来几年的发展方向？', '我应该优先学习哪些技能？']
let tipTimer: number | undefined

const currentTip = computed(() => tips[tipIndex.value] || tips[0])
const style = computed(() => position.value
  ? { left: `${position.value.left}px`, top: `${position.value.top}px`, right: 'auto', bottom: 'auto' }
  : {})
const popupBelow = computed(() => Boolean(position.value && position.value.top < 280))
const popupLeft = computed(() => Boolean(position.value && position.value.left < 360))

function clamp(left: number, top: number) {
  const width = launcher.value?.offsetWidth || 76
  const height = launcher.value?.offsetHeight || 76
  return {
    left: Math.max(8, Math.min(window.innerWidth - width - 8, left)),
    top: Math.max(8, Math.min(window.innerHeight - height - 8, top)),
  }
}

function pointerDown(event: PointerEvent) {
  if (event.pointerType === 'mouse' && event.button !== 0) return
  const target = event.currentTarget as HTMLElement
  const bounds = target.getBoundingClientRect()
  const current = position.value || { left: bounds.left, top: bounds.top }
  position.value = current
  drag.value = { active: true, moved: false, startX: event.clientX, startY: event.clientY, left: current.left, top: current.top }
  target.setPointerCapture?.(event.pointerId)
}

function pointerMove(event: PointerEvent) {
  if (!drag.value.active) return
  const state = drag.value
  drag.value = { ...state, moved: state.moved || Math.hypot(event.clientX - state.startX, event.clientY - state.startY) > 5 }
  position.value = clamp(state.left + event.clientX - state.startX, state.top + event.clientY - state.startY)
}

function pointerUp(event: PointerEvent) {
  if (!drag.value.active) return
  const moved = drag.value.moved
  drag.value = { ...drag.value, active: false }
  const target = event.currentTarget as HTMLElement
  target.releasePointerCapture?.(event.pointerId)
  if (!moved) open.value = !open.value
}

async function send(prefill?: string) {
  const text = (prefill ?? draft.value).trim()
  if (!text || sending.value) return
  messages.value.push({ role: 'user', content: text })
  draft.value = ''
  const assistantIndex = messages.value.push({ role: 'assistant', content: '' }) - 1
  sending.value = true
  const controller = new AbortController()
  const timeoutId = window.setTimeout(() => controller.abort(), 12000)
  try {
    const response = await fetch(apiUrl('/agent/chat'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...(auth.session?.accessToken ? { Authorization: `Bearer ${auth.session.accessToken}` } : {}) },
      signal: controller.signal,
      body: JSON.stringify({ agentMode: 'career_planning', message: text, sessionId: '', reportId: workspace.matchResult?.reportId || '', roleId: workspace.targetRoleId, roleName: workspace.targetRoleName }),
    })
    if (!response.ok) throw new Error('智能体服务暂不可用')
    const reader = response.body?.getReader()
    if (!reader) throw new Error('浏览器不支持流式响应')
    const decoder = new TextDecoder()
    let buffer = ''
    let streamFinished = false
    const handle = (block: string) => {
      const line = block.split(/\r?\n/).find(item => item.startsWith('data:'))
      if (!line) return
      try {
        const event = JSON.parse(line.slice(5).trim())
        if (event.type === 'token' && typeof event.content === 'string') messages.value[assistantIndex].content += event.content
        if (event.type === 'done') streamFinished = true
      } catch { /* Ignore incomplete SSE frames. */ }
    }
    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
      const blocks = buffer.split(/\r?\n\r?\n/)
      buffer = blocks.pop() || ''
      blocks.forEach(handle)
      if (done || streamFinished) {
        if (streamFinished && !done) await reader.cancel()
        break
      }
    }
    if (buffer.trim()) handle(buffer)
    if (!messages.value[assistantIndex].content) messages.value[assistantIndex].content = '我可以继续帮你梳理岗位趋势、技能差距和学习路径。'
  } catch {
    messages.value[assistantIndex].content = '暂时无法连接智能体，你可以进入完整职业助手继续咨询。'
  } finally {
    window.clearTimeout(timeoutId)
    sending.value = false
  }
}

onMounted(() => {
  tipTimer = window.setInterval(() => {
    if (!open.value && !drag.value.active) tipIndex.value = (tipIndex.value + 1) % tips.length
  }, 6500)
})
onBeforeUnmount(() => { if (tipTimer !== undefined) window.clearInterval(tipTimer) })
</script>

<template>
  <aside
    ref="launcher"
    class="floating-assistant"
    :class="{ 'is-dragging': drag.active, 'popup-below': popupBelow, 'popup-left': popupLeft }"
    :style="style"
    aria-label="AI职业洞察助手"
    @keydown.esc.stop.prevent="open = false"
  >
    <div v-if="!open" class="floating-assistant-tip" aria-live="polite">{{ currentTip }}</div>
    <section v-if="open" class="floating-assistant-chat" :style="popupStyle" role="dialog" aria-label="快速咨询职业助手">
      <header>
        <div><strong>AI职业助手</strong><small>轻量咨询 · 岗位规划助手</small></div>
        <button type="button" aria-label="关闭聊天框" @click="open = false">×</button>
      </header>
      <div class="floating-assistant-messages" aria-live="polite">
        <div v-for="(message, index) in messages" :key="`${message.role}-${index}`" :class="['floating-assistant-message', message.role]">
          <span v-if="message.role === 'assistant'" class="floating-assistant-avatar"><AssistantRobot compact aria-hidden="true" /></span>
          <p>{{ message.content || '正在整理岗位证据…' }}</p>
        </div>
      </div>
      <div class="floating-assistant-prompts">
        <button v-for="prompt in quickPrompts" :key="prompt" type="button" :disabled="sending" @click="send(prompt)">{{ prompt }}</button>
      </div>
      <form class="floating-assistant-input" @submit.prevent="send()">
        <input v-model="draft" :disabled="sending" placeholder="问问岗位、技能或学习路径" aria-label="输入咨询内容" />
        <button type="submit" :disabled="sending || !draft.trim()">发送</button>
      </form>
      <button class="floating-assistant-full" type="button" @click="router.push({ path: '/assistant', query: { mode: 'career_planning' } })">进入完整职业助手 <ArrowRight :size="14" /></button>
    </section>

    <button
      type="button"
      class="floating-assistant-button"
      :aria-expanded="open"
      aria-label="打开AI职业助手"
      title="拖动机器人，单击打开聊天"
      @pointerdown="pointerDown"
      @pointermove="pointerMove"
      @pointerup="pointerUp"
      @pointercancel="pointerUp"
      @keydown.enter.prevent="open = !open"
      @keydown.space.prevent="open = !open"
    >
      <AssistantRobot compact :busy="sending" :online="true" mode="career_planning" />
    </button>
  </aside>
</template>

<style scoped>
.floating-assistant{position:fixed;z-index:60;right:20px;bottom:24px;width:76px;min-height:76px;pointer-events:none;user-select:none}.floating-assistant.is-dragging{cursor:grabbing}.floating-assistant-button{position:relative;width:76px;height:76px;padding:9px;display:grid;place-items:center;border:1px solid #cbe6e0;border-radius:22px;background:rgba(255,255,255,.98);box-shadow:0 11px 26px rgba(15,76,69,.17),0 3px 8px rgba(15,76,69,.08);cursor:grab;pointer-events:auto;touch-action:none;transition:border-color .2s ease,box-shadow .2s ease,transform .2s ease}.floating-assistant-button:hover,.floating-assistant-button:focus-visible{border-color:#67bfb3;box-shadow:0 14px 30px rgba(15,76,69,.22),0 4px 10px rgba(15,76,69,.1);transform:translateY(-2px);outline:0}.floating-assistant.is-dragging .floating-assistant-button{cursor:grabbing;transform:scale(1.03)}

.floating-assistant-tip{position:absolute;right:4px;bottom:calc(100% + 12px);width:280px;padding:10px 13px;border:1px solid #cfe4df;border-radius:12px;background:#fff;color:#315d58;font-size:12px;line-height:1.5;box-shadow:0 10px 24px rgba(15,76,69,.14);pointer-events:none;animation:floating-assistant-tip-in .25s ease-out}.floating-assistant-tip::after{content:"";position:absolute;right:22px;bottom:-6px;width:10px;height:10px;border-right:1px solid #cfe4df;border-bottom:1px solid #cfe4df;background:#fff;transform:rotate(45deg)}
.floating-assistant.popup-below .floating-assistant-tip{top:calc(100% + 12px);bottom:auto}.floating-assistant.popup-below .floating-assistant-tip::after{top:-6px;bottom:auto;transform:rotate(225deg)}.floating-assistant.popup-left .floating-assistant-tip{right:auto;left:4px}.floating-assistant.popup-left .floating-assistant-tip::after{right:auto;left:22px}
.floating-assistant-chat{position:absolute;right:0;bottom:calc(100% + 12px);width:min(348px,calc(100vw - 32px));padding:0;overflow:hidden;border:1px solid #cfe4df;border-radius:14px;background:#fff;box-shadow:0 18px 42px rgba(15,76,69,.18),0 3px 10px rgba(15,76,69,.08);pointer-events:auto;animation:floating-assistant-chat-in .18s ease-out}.floating-assistant.popup-below .floating-assistant-chat{top:calc(100% + 12px);bottom:auto}.floating-assistant.popup-left .floating-assistant-chat{right:auto;left:0}.floating-assistant-chat>header{min-height:58px;padding:12px 14px;display:flex;align-items:center;justify-content:space-between;gap:12px;border-bottom:1px solid #e4efec;background:#f4fbf9}.floating-assistant-chat>header strong,.floating-assistant-chat>header small{display:block}.floating-assistant-chat>header strong{color:#123f3a;font-size:14px;font-weight:700}.floating-assistant-chat>header small{margin-top:3px;color:#6b817c;font-size:11px}.floating-assistant-chat>header>button{width:28px;height:28px;display:grid;place-items:center;border:0;border-radius:7px;background:transparent;color:#6e8781;font-size:22px;line-height:1;cursor:pointer}.floating-assistant-chat>header>button:hover,.floating-assistant-chat>header>button:focus-visible{background:#e4f3ef;color:#0f4c45;outline:0}
.floating-assistant-messages{max-height:222px;padding:12px 14px;overflow-y:auto;display:grid;gap:9px}.floating-assistant-message{display:flex;align-items:flex-start;gap:7px}.floating-assistant-message p{max-width:86%;margin:0;padding:8px 10px;border-radius:9px;color:#315d58;font-size:12px;line-height:1.55;white-space:pre-wrap;overflow-wrap:anywhere}.floating-assistant-message.assistant p{background:#f0f7f5}.floating-assistant-message.user{justify-content:flex-end}.floating-assistant-message.user p{background:#dff3ef;color:#174f48}.floating-assistant-avatar{width:24px;height:24px;flex:0 0 24px;display:grid;place-items:center;border-radius:7px;background:#e3f4f0;color:#0f9d8f}.floating-assistant-prompts{padding:0 14px 10px;display:flex;flex-wrap:wrap;gap:6px}.floating-assistant-prompts button{padding:5px 8px;border:1px solid #cbe3de;border-radius:6px;background:#fff;color:#31766e;font-size:11px;cursor:pointer}.floating-assistant-prompts button:hover:not(:disabled),.floating-assistant-prompts button:focus-visible{border-color:#0f9d8f;background:#edf9f6;outline:0}.floating-assistant-prompts button:disabled{cursor:wait;opacity:.55}
.floating-assistant-input{padding:10px 14px;display:flex;gap:7px;border-top:1px solid #e8f0ee}.floating-assistant-input input{min-width:0;flex:1;height:34px;padding:0 9px;border:1px solid #d5e5e1;border-radius:7px;background:#fff;color:#20312e;font-size:12px;outline:0}.floating-assistant-input input:focus{border-color:#0f9d8f;box-shadow:0 0 0 3px rgba(15,157,143,.1)}.floating-assistant-input button{height:34px;padding:0 12px;border:0;border-radius:7px;background:#0f9d8f;color:#fff;font-size:12px;cursor:pointer}.floating-assistant-input button:hover:not(:disabled){background:#0b7a70}.floating-assistant-input button:disabled{cursor:wait;opacity:.45}.floating-assistant-full{width:calc(100% - 28px);margin:0 14px 13px;padding:8px 0;display:flex;align-items:center;justify-content:center;gap:5px;border:0;border-radius:7px;background:#0f4c45;color:#fff;font-size:12px;cursor:pointer}.floating-assistant-full:hover,.floating-assistant-full:focus-visible{background:#0b3c37;outline:0}
@keyframes floating-assistant-tip-in{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:translateY(0)}}@keyframes floating-assistant-chat-in{from{opacity:0;transform:translateY(5px) scale(.98)}to{opacity:1;transform:translateY(0) scale(1)}}
@media(max-width:760px){.floating-assistant{right:14px;bottom:18px;width:68px;min-height:68px}.floating-assistant-button{width:68px;height:68px;border-radius:19px}.floating-assistant-tip{right:0;width:min(280px,calc(100vw - 30px))}.floating-assistant-chat{width:min(348px,calc(100vw - 24px))}}
@media(prefers-reduced-motion:reduce){.floating-assistant-tip,.floating-assistant-chat,.floating-assistant-button{animation:none;transition:none}}
</style>
