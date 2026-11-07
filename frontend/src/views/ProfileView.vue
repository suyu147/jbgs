<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ChevronRight, FileText, LoaderCircle, Mail, MapPin, MoreHorizontal,
  Phone, Plus, Save, ShieldCheck, Target, Upload, UserRound,
} from 'lucide-vue-next'
import { useAuthStore } from '@/stores/auth'
import { useWorkspaceStore, type UserProfile } from '@/stores/workspace'
import { insightService } from '@/services/insightService'
import type { ResumeResult } from '@/types/domain'

const router = useRouter()
const auth = useAuthStore()
const workspace = useWorkspaceStore()
const { resume, resumeConfirmed, skills, education, experienceYears } = storeToRefs(workspace)
const draft = ref<UserProfile>({ ...workspace.profile })
const loading = ref(false)
const error = ref('')
const resumes = ref<ResumeResult[]>([])

const displayName = computed(() => draft.value.fullName || auth.user?.displayName || '用户')
const profileFields = computed(() => [draft.value.fullName, draft.value.phone, draft.value.email, draft.value.city, draft.value.education, draft.value.desiredRole])
const completeness = computed(() => Math.round(profileFields.value.filter(Boolean).length / profileFields.value.length * 100))

onMounted(async () => {
  if (!draft.value.fullName) draft.value.fullName = auth.user?.displayName || ''
  if (!draft.value.education && education.value) draft.value.education = education.value
  if (draft.value.experienceYears === undefined && experienceYears.value !== undefined) draft.value.experienceYears = experienceYears.value
  if (insightService.isProductPreview()) { resumes.value = resume.value ? [resume.value] : []; return }
  loading.value = true
  error.value = ''
  try {
    const [stored, resumeResponse] = await Promise.all([
      insightService.getWorkspaceProfile(),
      insightService.getMyResumes(4),
    ])
    workspace.selectAudience('seeker')
    workspace.updateProfile(stored.profile)
    workspace.workStyleAssessment = { ...workspace.workStyleAssessment, ...stored.workStyleAssessment }
    draft.value = { ...workspace.profile }
    const resumeItems = resumeResponse.items
    resumes.value = resumeItems
    const selected = resumeItems.find(item => item.resumeId === resume.value?.resumeId) || resumeItems[0]
    if (selected) activateResume(selected)
  } catch (reason: any) {
    error.value = reason.message || '账号资料读取失败'
  } finally {
    loading.value = false
  }
})

async function persistWorkspace(message: string) {
  if (!insightService.isProductPreview()) {
    await insightService.saveWorkspaceProfile({
      audience: workspace.audience,
      profile: workspace.profile,
      workStyleAssessment: workspace.workStyleAssessment,
    })
  }
  ElMessage.success(message)
}

async function saveProfile() {
  loading.value = true
  error.value = ''
  workspace.updateProfile(draft.value)
  if (draft.value.education) education.value = draft.value.education
  if (draft.value.experienceYears !== undefined) experienceYears.value = draft.value.experienceYears
  try {
    await persistWorkspace('个人资料已保存')
  } catch (reason: any) {
    error.value = reason.message || '资料保存失败'
  } finally {
    loading.value = false
  }
}

async function uploadResume(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  loading.value = true
  error.value = ''
  resumeConfirmed.value = false
  try {
    const parsed = await insightService.uploadResume(file)
    const uploaded = { ...parsed, fileName: file.name, uploadedAt: new Date().toISOString() }
    resumes.value = [uploaded, ...resumes.value.filter(item => item.resumeId !== uploaded.resumeId)].slice(0, 4)
    activateResume(uploaded)
    if (parsed.education) draft.value.education = parsed.education
    ElMessage.success('简历解析完成，请确认能力信息')
  } catch (reason: any) {
    error.value = reason.message || '简历上传失败，请确认后端服务已启动'
  } finally {
    loading.value = false
    input.value = ''
  }
}

function activateResume(item: ResumeResult) {
  resume.value = item
  resumeConfirmed.value = Boolean(item.confirmed)
  skills.value = item.skills.map(skill => skill.skill_name)
  education.value = item.education || draft.value.education
  experienceYears.value = item.experienceYears ?? draft.value.experienceYears
}

function formatDate(value?: string) {
  if (!value) return '本次会话'
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}
</script>

<template>
  <div class="profile-hub">
    <section class="profile-identity-band">
      <div class="profile-avatar"><UserRound /></div>
      <div class="profile-identity-copy">
        <span class="section-code">ACCOUNT & CAREER PROFILE</span>
        <h1>{{ displayName }}</h1>
        <p>个人职业成长工作区 · 当前地区 {{ workspace.location || '全国' }}</p>
      </div>
      <div class="profile-completeness">
        <span>资料完整度</span><strong>{{ completeness }}%</strong>
        <i><b :style="{ width: `${completeness}%` }"></b></i>
      </div>
    </section>

    <div class="profile-content-grid">
      <section class="panel profile-edit-panel">
        <header class="panel-head"><div><span class="section-code">BASIC INFORMATION</span><h2>个人基本信息</h2><p>用于完善职业画像与结果解释，不影响原始市场数据。</p></div></header>
        <form class="profile-form" @submit.prevent="saveProfile">
          <div class="profile-form-grid">
            <label><span>姓名 / 称呼</span><div><UserRound /><input v-model.trim="draft.fullName" maxlength="30" placeholder="请输入姓名" /></div></label>
            <label><span>所在城市</span><div><MapPin /><input v-model.trim="draft.city" maxlength="30" placeholder="例如：杭州" /></div></label>
            <label><span>手机号码</span><div><Phone /><input v-model.trim="draft.phone" maxlength="20" placeholder="用于账号联系" /></div></label>
            <label><span>电子邮箱</span><div><Mail /><input v-model.trim="draft.email" maxlength="80" placeholder="name@example.com" /></div></label>
          </div>

          <div class="profile-form-grid">
            <label><span>当前状态</span><select v-model="draft.careerStatus"><option value="">请选择</option><option>在校学生</option><option>应届求职</option><option>在职看机会</option><option>转岗准备中</option></select></label>
            <label><span>最高学历</span><select v-model="draft.education"><option value="">请选择</option><option>大专</option><option>本科</option><option>硕士</option><option>博士</option></select></label>
            <label><span>工作经验</span><input v-model.number="draft.experienceYears" type="number" min="0" max="50" step="0.5" placeholder="请输入经验年限" /></label>
            <label><span>学校</span><input v-model.trim="draft.school" maxlength="50" placeholder="请输入学校名称" /></label>
            <label><span>专业</span><input v-model.trim="draft.major" maxlength="50" placeholder="请输入专业名称" /></label>
            <label><span>毕业年份</span><input v-model.trim="draft.graduationYear" maxlength="4" inputmode="numeric" placeholder="例如：2027" /></label>
            <label><span>意向岗位</span><input v-model.trim="draft.desiredRole" maxlength="50" placeholder="例如：前端开发工程师" /></label>
          </div>

          <footer><span><ShieldCheck />资料按当前账号保存在本机数据库，可在下次登录时继续使用。</span><button class="primary-btn" type="submit" :disabled="loading"><Save :size="16" />保存资料</button></footer>
        </form>
      </section>

      <section class="panel resume-vault-panel resume-manager-panel">
        <header class="resume-manager-head"><div><span class="section-code">RESUME BAR</span><h2>个人简历</h2></div><nav><label class="resume-manager-add" title="快捷添加简历"><input type="file" accept=".pdf,.docx,.txt" @change="uploadResume" /><LoaderCircle v-if="loading" class="spin" /><Plus v-else /></label><button title="进入个人简历" aria-label="进入个人简历" @click="router.push('/me/resumes')"><MoreHorizontal /></button></nav></header>
        <div v-if="resumes.length" class="resume-manager-list">
          <button v-for="item in resumes" :key="item.resumeId" :class="{ active:resume?.resumeId===item.resumeId }" @click="activateResume(item)"><span><FileText /></span><div><strong>{{ item.fileName || '已解析简历' }}</strong><small>{{ formatDate(item.uploadedAt) }} · {{ item.skills.length }} 项技能</small><em>{{ item.confirmed ? '已确认' : '待确认' }}</em></div><ChevronRight /></button>
        </div>
        <button v-else class="resume-manager-empty" @click="router.push('/me/resumes')"><Upload /><span><strong>添加第一份简历</strong><small>支持多份简历独立管理</small></span><ChevronRight /></button>
        <button v-if="resume" class="resume-manager-diagnose" @click="router.push('/matching?resume=mine')"><Target />使用当前简历进行能力诊断<ChevronRight /></button>
        <p v-if="error" class="error-text profile-resume-error">{{ error }}</p>
      </section>

    </div>
  </div>
</template>

<style scoped>
.profile-hub{display:grid;gap:20px}.profile-identity-band{min-height:152px;padding:28px 32px;display:flex;align-items:center;gap:20px;background:#153f3b;color:#fff;box-shadow:0 10px 30px rgba(18,58,54,.12)}
.profile-avatar{width:68px;height:68px;display:grid;place-items:center;border:1px solid rgba(255,255,255,.24);background:#23605a}.profile-avatar svg{width:30px;height:30px;color:#70d8cf}.profile-identity-copy{min-width:0;flex:1}.profile-identity-copy .section-code{color:#70cfc7}.profile-identity-copy h1{margin:6px 0 5px;font-size:28px}.profile-identity-copy p{margin:0;color:#bed3cf;font-size:14px}.profile-completeness{width:210px;display:grid;grid-template-columns:1fr auto;align-items:end;gap:6px 12px}.profile-completeness span{color:#b5ceca;font-size:12px}.profile-completeness strong{font:700 24px Bahnschrift,Arial,sans-serif}.profile-completeness i{grid-column:1/-1;height:5px;background:rgba(255,255,255,.14);overflow:hidden}.profile-completeness b{display:block;height:100%;background:#52c9bf}
.profile-content-grid{display:grid;grid-template-columns:minmax(0,1.55fr) minmax(340px,.85fr);gap:20px;align-items:start}.profile-edit-panel,.resume-vault-panel{background:#fff}.profile-form{padding:24px}.profile-form-grid{display:grid;grid-template-columns:1fr 1fr;gap:17px 18px;margin-bottom:20px;padding-bottom:20px;border-bottom:1px solid #e5ecea}.profile-form-grid:last-of-type{margin-bottom:0;border-bottom:0}.profile-form label{display:grid;gap:7px;color:#405a56;font-size:12px;font-weight:700}.profile-form label>div{height:43px;display:flex;align-items:center;gap:8px;padding:0 11px;border:1px solid #cad8d5;background:#fff}.profile-form label>div:focus-within{border-color:#299e96;box-shadow:0 0 0 3px rgba(41,158,150,.08)}.profile-form label svg{width:16px;color:#78918d}.profile-form input,.profile-form select{width:100%;height:43px;padding:0 11px;border:1px solid #cad8d5;outline:0;background:#fff;color:#233d3a;font-size:14px}.profile-form label>div input{height:100%;padding:0;border:0}.profile-form input:focus,.profile-form select:focus{border-color:#299e96;box-shadow:0 0 0 3px rgba(41,158,150,.08)}.profile-form footer{padding-top:18px;display:flex;align-items:center;justify-content:space-between;gap:16px;border-top:1px solid #e5ecea}.profile-form footer span{display:flex;align-items:center;gap:6px;color:#718682;font-size:11px}.profile-form footer svg{color:#43837d}
.resume-vault-panel{min-height:490px}.resume-file-head{padding:24px 22px 18px;display:grid;grid-template-columns:44px 1fr auto;align-items:center;gap:12px}.resume-file-head>span{width:44px;height:48px;display:grid;place-items:center;background:#e7f4f1;color:#198b84}.resume-file-head strong,.resume-file-head small{display:block}.resume-file-head strong{max-width:190px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:14px}.resume-file-head small{margin-top:4px;color:#788a87;font-size:10px}.resume-file-head em{display:flex;align-items:center;gap:4px;padding:5px 7px;background:#fff3df;color:#98661e;font-size:10px;font-style:normal}.resume-file-head em.confirmed{background:#e7f5ed;color:#277a59}.resume-file-head em svg{width:13px;height:13px}.resume-facts{margin:0 22px;padding:14px 0;display:grid;grid-template-columns:repeat(3,1fr);border-top:1px solid #e4ecea;border-bottom:1px solid #e4ecea}.resume-facts div{padding:0 10px;border-right:1px solid #e4ecea}.resume-facts div:last-child{border-right:0}.resume-facts dt{color:#7a8e8a;font-size:10px}.resume-facts dd{margin:5px 0 0;color:#294d49;font-weight:700}.resume-skill-preview{padding:18px 22px 8px;display:flex;flex-wrap:wrap;gap:6px}.resume-skill-preview span,.resume-skill-preview small{padding:5px 7px;background:#edf5f3;color:#356c67;font-size:11px}.resume-warning{margin:10px 22px 0;padding:9px 10px;background:#fff6e8;color:#8b6426;font-size:11px;line-height:1.6}.resume-actions{padding:20px 22px;display:flex;align-items:center;flex-wrap:wrap;gap:8px}.resume-actions .primary-btn,.resume-actions .secondary-btn{height:38px}.resume-actions svg{width:15px;height:15px}.resume-actions .secondary-btn svg:last-child{width:13px}.resume-replace{position:relative;cursor:pointer}.resume-replace input,.profile-resume-upload input{position:absolute;inset:0;opacity:0;cursor:pointer}.resume-remove{margin-left:auto;color:#9d4d55}.profile-resume-upload{position:relative;min-height:350px;margin:22px;display:flex;flex-direction:column;align-items:center;justify-content:center;border:1px dashed #94b5b0;background:#f6faf9;text-align:center;cursor:pointer}.profile-resume-upload:hover{border-color:#279f97;background:#eef8f6}.profile-resume-upload>span{width:52px;height:52px;display:grid;place-items:center;background:#dff1ee;color:#148b84}.profile-resume-upload svg{width:24px;height:24px}.profile-resume-upload strong{margin-top:16px;font-size:16px}.profile-resume-upload p{margin:7px 0 14px;color:#718581;font-size:12px}.profile-resume-upload b{padding:8px 14px;background:#176b65;color:#fff;font-size:12px}.profile-resume-error{margin:0 22px 22px}
.profile-identity-band{border-radius:12px;background:linear-gradient(120deg,#0F4C45,#173F3A);box-shadow:0 2px 12px rgba(0,0,0,.08)}
.profile-avatar{border:2px solid #fff;border-radius:50%;background:rgba(255,255,255,.10)}.profile-avatar svg{color:#fff}
.profile-identity-copy h1{color:#fff;font-weight:700}.profile-identity-copy p{color:rgba(255,255,255,.72)}
.profile-completeness span{color:rgba(255,255,255,.72)}.profile-completeness strong{color:#fff}.profile-completeness i{height:7px;border-radius:4px;background:rgba(255,255,255,.18)}.profile-completeness b{border-radius:4px;background:#D4A853}
.profile-edit-panel,.resume-vault-panel{border:0;border-radius:12px;box-shadow:0 2px 12px rgba(0,0,0,.06);overflow:hidden}
.profile-form label{color:#444;font-size:14px}.profile-form label>div,.profile-form input,.profile-form select{height:44px;border:1px solid #E0E0E0;border-radius:8px}
.profile-form label>div:focus-within,.profile-form input:focus,.profile-form select:focus{border-color:#D4A853;box-shadow:0 0 0 3px rgba(212,168,83,.12)}
.profile-form label>div{min-width:0;overflow:hidden;box-sizing:border-box}
.profile-form label>div input{width:auto;min-width:0;flex:1;box-sizing:border-box;border:0!important;border-radius:0;background:transparent}
.profile-form footer span{color:#888;font-size:12px}.profile-form footer .primary-btn{background:#0F4C45}
.profile-resume-upload{border-radius:12px;background:#F8FAF9}.profile-resume-upload:hover{border-color:#D4A853;background:#F8FAF9}
.profile-resume-upload>span{border-radius:8px;background:#EAF3F0;color:#0F4C45}.profile-resume-upload b{padding:9px 16px;border-radius:8px;background:#0F4C45;color:#fff}
.resume-file-head em,.resume-skill-preview span,.resume-skill-preview small{border-radius:6px}.resume-skill-preview span{background:#EAF3F0;color:#0F4C45}
.profile-content-grid{grid-template-columns:minmax(0,1fr) minmax(270px,310px)}.resume-manager-panel{min-height:0}.resume-manager-head{min-height:74px;padding:16px 18px;display:flex;align-items:center;justify-content:space-between;gap:12px;border-bottom:1px solid #edf1ef}.resume-manager-head h2{margin:4px 0 0;font-size:18px}.resume-manager-head nav{display:flex;gap:7px}.resume-manager-head nav>button,.resume-manager-add{position:relative;width:36px;height:36px;display:grid;place-items:center;border-radius:8px;background:#EAF3F0;color:#0F4C45;cursor:pointer}.resume-manager-head nav>button:hover,.resume-manager-add:hover{background:#0F4C45;color:#fff}.resume-manager-add input{position:absolute;inset:0;opacity:0;cursor:pointer}.resume-manager-head svg{width:17px}.resume-manager-list{padding:10px;display:grid;gap:7px;max-height:326px;overflow:auto}.resume-manager-list>button{min-width:0;min-height:70px;padding:10px;display:grid;grid-template-columns:34px minmax(0,1fr) 14px;align-items:center;gap:9px;border-radius:8px;background:#f7faf9;text-align:left;transition:all .2s ease}.resume-manager-list>button:hover{background:#eef5f3}.resume-manager-list>button.active{box-shadow:inset 3px 0 #D4A853;background:#eef5f3}.resume-manager-list>button>span{width:34px;height:38px;display:grid;place-items:center;border-radius:7px;background:#fff;color:#0F4C45}.resume-manager-list svg{width:15px}.resume-manager-list strong,.resume-manager-list small,.resume-manager-list em{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.resume-manager-list strong{font-size:12px}.resume-manager-list small{margin-top:3px;color:#899692;font-size:9px}.resume-manager-list em{width:max-content;margin-top:4px;padding:2px 5px;border-radius:4px;background:#fff4df;color:#966216;font-size:8px;font-style:normal}.resume-manager-list>button.active em{background:#e6f4ec;color:#267052}.resume-manager-empty{width:calc(100% - 20px);min-height:94px;margin:10px;padding:14px;display:grid;grid-template-columns:34px 1fr 14px;align-items:center;gap:10px;border:1px dashed #a8bdb9;border-radius:8px;background:#f8faf9;text-align:left}.resume-manager-empty>svg{color:#0F4C45}.resume-manager-empty strong,.resume-manager-empty small{display:block}.resume-manager-empty small{margin-top:3px;color:#888;font-size:10px}.resume-manager-diagnose{width:calc(100% - 20px);height:40px;margin:0 10px 12px;padding:0 11px;display:flex;align-items:center;gap:7px;border-radius:8px;background:#0F4C45;color:#fff;font-size:11px;font-weight:600}.resume-manager-diagnose svg:last-child{margin-left:auto}.profile-resume-error{margin:0 12px 12px}
@media(max-width:1100px){.profile-content-grid{grid-template-columns:1fr}.resume-vault-panel{min-height:0}}@media(max-width:760px){.profile-identity-band{align-items:flex-start;flex-wrap:wrap;padding:22px}.profile-completeness{width:100%}.profile-form-grid{grid-template-columns:1fr}.profile-form footer{align-items:flex-start;flex-direction:column}.profile-form footer .primary-btn{width:100%}}
</style>
