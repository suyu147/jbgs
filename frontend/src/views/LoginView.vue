<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowRight, BriefcaseBusiness, CheckCircle2, Database, Eye, EyeOff,
  GraduationCap, KeyRound, LoaderCircle, LockKeyhole, LogIn, Sparkles, UserRound,
} from 'lucide-vue-next'
import { useAuthStore, type PortalRole } from '@/stores/auth'
import { useWorkspaceStore } from '@/stores/workspace'
import '@/styles/login.css'
import BrandLogo from '@/components/BrandLogo.vue'

type EntryType = 'seeker' | 'enterprise' | 'admin'
type AuthMode = 'login' | 'register'
type RegisterField = 'displayName' | 'username' | 'password' | 'confirmPassword'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const workspace = useWorkspaceStore()
const entry = ref<EntryType>(route.query.portal === 'admin' ? 'admin' : route.query.portal === 'enterprise' ? 'enterprise' : 'seeker')
const mode = ref<AuthMode>('login')
const username = ref('')
const displayName = ref('')
const password = ref('')
const confirmPassword = ref('')
const showPassword = ref(false)
const loading = ref(false)
const error = ref('')
const fieldErrors = ref<Record<RegisterField, string>>({
  displayName: '',
  username: '',
  password: '',
  confirmPassword: '',
})

const portal = computed<PortalRole>(() => entry.value === 'admin' ? 'admin' : entry.value === 'enterprise' ? 'enterprise' : 'personal')
const audienceName = computed(() => entry.value === 'enterprise' ? '企业 HR' : entry.value === 'admin' ? '治理管理员' : '个人用户')
const submitText = computed(() => {
  if (loading.value) return mode.value === 'register' ? '正在创建账号' : '正在验证账号'
  if (mode.value === 'register') return '注册并进入工作台'
  return entry.value === 'admin' ? '进入治理控制台' : entry.value === 'enterprise' ? '进入企业人才工作台' : '进入职业成长'
})

function selectEntry(value: EntryType) {
  entry.value = value
  if (value !== 'seeker') mode.value = 'login'
  error.value = ''
}
function clearFieldErrors() {
  fieldErrors.value = { displayName: '', username: '', password: '', confirmPassword: '' }
}
function clearFieldError(field: RegisterField) {
  fieldErrors.value[field] = ''
  error.value = ''
}
function setMode(value: AuthMode) {
  if (entry.value !== 'seeker' && value === 'register') entry.value = 'seeker'
  mode.value = value
  error.value = ''
  clearFieldErrors()
}
function prepareWorkspace(userId: string) {
  workspace.hydrate(userId)
  workspace.selectAudience('seeker')
}

async function submit() {
  error.value = ''
  clearFieldErrors()
  if (mode.value === 'register') {
    const account = username.value.trim()
    if (displayName.value.trim().length < 2) fieldErrors.value.displayName = '称呼至少需要 2 个字符'
    if (!account) fieldErrors.value.username = '请输入注册账号'
    else if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{3,31}$/.test(account)) fieldErrors.value.username = '账号需为 4-32 位字母、数字、点、横线或下划线'
    if (!/^[A-Za-z0-9]{4,12}$/.test(password.value)) fieldErrors.value.password = '密码需为 4-12 位，只能使用字母或数字'
    if (!confirmPassword.value) fieldErrors.value.confirmPassword = '请再次输入密码'
    else if (password.value !== confirmPassword.value) fieldErrors.value.confirmPassword = '两次输入的密码不一致'
    if (Object.values(fieldErrors.value).some(Boolean)) return
  } else if (!username.value.trim() || !password.value) {
    return void (error.value = '请输入账号和密码')
  }

  loading.value = true
  try {
    const session = mode.value === 'register'
      ? await auth.register(username.value.trim().toLowerCase(), password.value, displayName.value.trim())
      : await auth.login(username.value.trim(), password.value, portal.value)
    if (session.user.role === 'admin') await router.replace('/admin/dashboard')
    else if (session.user.role === 'enterprise') await router.replace('/enterprise/dashboard')
    else {
      prepareWorkspace(session.user.id)
      await router.replace('/')
    }
  } catch (reason: any) {
    error.value = reason.message || (mode.value === 'register' ? '注册服务暂时不可用' : '登录失败')
  } finally {
    loading.value = false
  }
}

async function enterPreview() {
  const session = auth.enterPreview('职业成长体验')
  prepareWorkspace(session.user.id)
  await router.replace('/')
}
</script>

<template>
  <main class="simple-auth-page login-atmosphere">
    <div class="login-brand"><BrandLogo /></div>
    <section
      class="login-identity"
      aria-label="职业成长与岗位能力洞察"
    >
      <div class="login-hero-copy">
        <span class="login-kicker"><i aria-hidden="true"></i>岗位能力图谱 · 人岗匹配 · 成长路径</span>
        <h1><span>以岗位为坐标</span><span class="login-title-signal">让成长有方向</span></h1>
        <p>从岗位能力图谱出发，发现与你匹配的机会，<br class="login-copy-break" />规划每一步成长。</p>
      </div>
    </section>

    <section class="auth-access">
      <div class="auth-card">
        <header>
          <span class="section-code">SECURE WORKSPACE</span>
          <h2>{{ mode === 'login' ? '欢迎使用职能洞察' : '创建个人账号' }}</h2>
          <p>{{ mode === 'login' ? '登录后进入你的职业洞察工作台。' : '注册后自动进入个人职业成长工作台；管理员账号不能自助注册。' }}</p>
        </header>

        <div class="auth-mode-tabs" role="tablist" aria-label="账号操作">
          <button :class="{ active: mode === 'login' }" @click="setMode('login')">账号登录</button>
          <button :class="{ active: mode === 'register' }" @click="setMode('register')">注册账号</button>
        </div>

         <section class="audience-choice">
           <span>{{ mode === 'register' ? '选择账号类型' : '选择进入入口' }}</span>
           <div>
             <button :class="{ active: entry === 'seeker' }" :aria-pressed="entry === 'seeker'" @click="selectEntry('seeker')"><GraduationCap /><span><strong>个人用户</strong><small>职业探索与成长</small></span><CheckCircle2 /></button>
             <button class="enterprise-audience-option" :class="{ active: entry === 'enterprise' }" :aria-pressed="entry === 'enterprise'" :disabled="mode === 'register'" @click="selectEntry('enterprise')"><BriefcaseBusiness /><span><strong>企业 HR</strong><small>{{ mode === 'register' ? '仅限企业已有账号' : '市场洞察与人才匹配' }}</small></span><CheckCircle2 /></button>
             <button class="admin-audience-option" :class="{ active: entry === 'admin' }" :aria-pressed="entry === 'admin'" :disabled="mode === 'register'" @click="selectEntry('admin')"><Database /><span><strong>治理管理员</strong><small>{{ mode === 'register' ? '仅限已有管理员账号' : '数据治理与审核' }}</small></span><CheckCircle2 /></button>
           </div>
         </section>

        <form @submit.prevent="submit">
          <label v-if="mode === 'register'" class="simple-auth-field" :class="{ invalid: fieldErrors.displayName }"><span>你的称呼</span><div><UserRound /><input v-model="displayName" maxlength="120" autocomplete="name" placeholder="例如：小陈" @input="clearFieldError('displayName')" /></div><small v-if="fieldErrors.displayName" class="simple-field-error">{{ fieldErrors.displayName }}</small></label>
          <label class="simple-auth-field" :class="{ invalid: fieldErrors.username }"><span>账号</span><div><BriefcaseBusiness /><input v-model="username" maxlength="80" autocomplete="username" :placeholder="mode === 'register' ? '4-32 位字母、数字、点、横线或下划线' : '请输入账号'" @input="clearFieldError('username')" /></div><small v-if="fieldErrors.username" class="simple-field-error">{{ fieldErrors.username }}</small></label>
          <label class="simple-auth-field" :class="{ invalid: fieldErrors.password }"><span>密码</span><div><KeyRound /><input v-model="password" :maxlength="mode === 'register' ? 12 : 200" :type="showPassword ? 'text' : 'password'" :autocomplete="mode === 'register' ? 'new-password' : 'current-password'" :placeholder="mode === 'register' ? '4-12 位，仅使用字母或数字' : '请输入密码'" @input="clearFieldError('password')" /><button type="button" :title="showPassword ? '隐藏密码' : '显示密码'" @click="showPassword = !showPassword"><EyeOff v-if="showPassword" /><Eye v-else /></button></div><small v-if="fieldErrors.password" class="simple-field-error">{{ fieldErrors.password }}</small></label>
          <label v-if="mode === 'register'" class="simple-auth-field" :class="{ invalid: fieldErrors.confirmPassword }"><span>确认密码</span><div><LockKeyhole /><input v-model="confirmPassword" maxlength="12" :type="showPassword ? 'text' : 'password'" autocomplete="new-password" placeholder="再次输入 4-12 位密码" @input="clearFieldError('confirmPassword')" /></div><small v-if="fieldErrors.confirmPassword" class="simple-field-error">{{ fieldErrors.confirmPassword }}</small></label>
          <p v-if="error" class="simple-auth-error">{{ error }}</p>
          <button class="simple-auth-submit" :disabled="loading"><LoaderCircle v-if="loading" class="spin" /><LogIn v-else />{{ submitText }}<ArrowRight v-if="!loading" /></button>
        </form>

         <button v-if="entry === 'seeker'" class="simple-preview-entry" @click="enterPreview"><Sparkles />无需账号，直接体验{{ audienceName }}工作台</button>
         <button v-if="mode === 'login' && entry !== 'seeker'" class="admin-entry-switch" @click="selectEntry('seeker')">返回个人用户登录</button>
      </div>
    </section>
  </main>
</template>
