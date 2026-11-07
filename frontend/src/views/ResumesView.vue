<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Check, ChevronRight, Eye, FileText, LoaderCircle, Plus, Target, Trash2, Upload } from 'lucide-vue-next'
import { insightService } from '@/services/insightService'
import { useWorkspaceStore } from '@/stores/workspace'
import type { ResumeResult } from '@/types/domain'

const router = useRouter()
const workspace = useWorkspaceStore()
const resumes = ref<ResumeResult[]>([])
const selected = ref<ResumeResult | null>(null)
const loading = ref(false)
const busyId = ref('')
const error = ref('')
const activeId = computed(() => workspace.resume?.resumeId || '')

onMounted(load)

async function load() {
  loading.value = true
  error.value = ''
  try {
    resumes.value = insightService.isProductPreview() ? (workspace.resume ? [workspace.resume] : []) : (await insightService.getMyResumes(100)).items
  } catch (reason: any) { error.value = reason?.message || '简历列表读取失败' }
  finally { loading.value = false }
}

function activate(item: ResumeResult) {
  workspace.resume = item
  workspace.resumeConfirmed = Boolean(item.confirmed)
  workspace.skills = item.skills.map(skill => skill.skill_name)
  workspace.education = item.education || workspace.profile.education
  workspace.experienceYears = item.experienceYears ?? workspace.profile.experienceYears
}

async function upload(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  loading.value = true
  error.value = ''
  try {
    const parsed = await insightService.uploadResume(file)
    const item = { ...parsed, fileName:file.name, uploadedAt:new Date().toISOString() }
    resumes.value = [item, ...resumes.value]
    activate(item)
    ElMessage.success('简历上传并解析完成')
  } catch (reason: any) { error.value = reason?.message || '简历上传失败' }
  finally { loading.value = false; input.value = '' }
}

async function confirm(item: ResumeResult) {
  busyId.value = item.resumeId
  try {
    await insightService.confirmResume(item.resumeId, { skills:item.skills.map(skill => skill.skill_name), education:item.education, experienceYears:item.experienceYears, certificates:item.certificates || [] })
    item.confirmed = true
    if (activeId.value === item.resumeId) workspace.resumeConfirmed = true
    ElMessage.success('解析结果已确认')
  } catch (reason: any) { ElMessage.error(reason?.message || '确认失败') }
  finally { busyId.value = '' }
}

async function remove(item: ResumeResult) {
  try { await ElMessageBox.confirm(`确定删除“${item.fileName || '该简历'}”吗？删除后不可恢复。`, '删除简历', { type:'warning', confirmButtonText:'删除', cancelButtonText:'取消' }) }
  catch { return }
  busyId.value = item.resumeId
  try {
    if (!insightService.isProductPreview()) await insightService.deleteMyResume(item.resumeId)
    resumes.value = resumes.value.filter(resume => resume.resumeId !== item.resumeId)
    if (activeId.value === item.resumeId) {
      workspace.clearResume()
      const next = resumes.value[0]
      if (next) activate(next)
    }
    if (selected.value?.resumeId === item.resumeId) selected.value = null
    ElMessage.success('简历已删除')
  } catch (reason: any) { ElMessage.error(reason?.message || '简历删除失败') }
  finally { busyId.value = '' }
}

async function openOriginal(item: ResumeResult) {
  busyId.value = item.resumeId
  try {
    const blob = await insightService.getMyResumeFile(item.resumeId)
    const url = URL.createObjectURL(blob)
    window.open(url, '_blank', 'noopener,noreferrer')
    window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
  } catch (reason: any) { ElMessage.error(reason?.message || '原文件暂时无法打开') }
  finally { busyId.value = '' }
}

function diagnose(item: ResumeResult) { activate(item); router.push('/matching?resume=mine') }
function formatDate(value?: string) { return value ? new Intl.DateTimeFormat('zh-CN', {year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(new Date(value)) : '时间未知' }
function updatePreviewVisibility(value: boolean) { if (!value) selected.value = null }
</script>

<template>
  <section class="resume-library">
    <header class="resume-library-head"><div><h2>管理你的个人简历</h2><p>每份简历独立保存，可预览、删除，并任选一份用于能力诊断。</p></div><label class="primary-btn"><input type="file" accept=".pdf,.docx,.txt" @change="upload" /><LoaderCircle v-if="loading" class="spin" /><Plus v-else />添加简历</label></header>
    <p v-if="error" class="error-text">{{ error }}<button class="secondary-btn" @click="load">重试</button></p>
    <div v-if="loading && !resumes.length" class="resume-library-loading"><i v-for="item in 4" :key="item"></i></div>
    <div v-else-if="resumes.length" class="resume-library-grid">
      <article v-for="item in resumes" :key="item.resumeId" :class="{ active:activeId===item.resumeId }">
        <header><span><FileText /></span><div><small>{{ item.confirmed ? '解析已确认' : '等待确认' }}</small><h3>{{ item.fileName || '已解析简历' }}</h3><p>{{ formatDate(item.uploadedAt) }}</p></div><em v-if="activeId===item.resumeId"><Check />当前使用</em></header>
        <dl><div><dt>技能</dt><dd>{{ item.skills.length }} 项</dd></div><div><dt>学历</dt><dd>{{ item.education || '未识别' }}</dd></div><div><dt>经验</dt><dd>{{ item.experienceYears === undefined ? '未识别' : `${item.experienceYears} 年` }}</dd></div></dl>
        <div class="resume-library-skills"><span v-for="skill in item.skills.slice(0,6)" :key="skill.skill_name">{{ skill.skill_name }}</span><small v-if="item.skills.length>6">+{{ item.skills.length-6 }}</small></div>
        <footer><button class="secondary-btn" @click="selected=item"><Eye />预览</button><button v-if="!item.confirmed" class="secondary-btn" :disabled="busyId===item.resumeId" @click="confirm(item)"><Check />确认</button><button class="primary-btn" @click="diagnose(item)"><Target />用于诊断</button><button class="icon-btn" :disabled="busyId===item.resumeId" title="删除简历" :aria-label="`删除${item.fileName}`" @click="remove(item)"><Trash2 /></button></footer>
      </article>
    </div>
    <div v-else class="resume-library-empty"><Upload /><h2>还没有个人简历</h2><p>点击上方“添加简历”，系统会解析学历、经验、技能和证书。</p></div>

    <el-dialog :model-value="Boolean(selected)" width="min(760px, calc(100vw - 28px))" title="简历预览" append-to-body @update:model-value="updatePreviewVisibility">
      <div v-if="selected" class="resume-preview-dialog"><header><FileText /><div><strong>{{ selected.fileName }}</strong><small>{{ formatDate(selected.uploadedAt) }} · {{ selected.confirmed ? '已确认' : '待确认' }}</small></div><button class="secondary-btn" :disabled="busyId===selected.resumeId" @click="openOriginal(selected)"><Eye />打开原文件</button></header><dl><div><dt>学历</dt><dd>{{ selected.education || '未识别' }}</dd></div><div><dt>经验</dt><dd>{{ selected.experienceYears === undefined ? '未识别' : `${selected.experienceYears} 年` }}</dd></div><div><dt>证书</dt><dd>{{ selected.certificates?.join('、') || '未识别' }}</dd></div></dl><section><h3>识别技能</h3><div><span v-for="skill in selected.skills" :key="skill.skill_name">{{ skill.skill_name }}</span></div></section><section v-if="selected.textPreview"><h3>文本预览</h3><pre>{{ selected.textPreview }}</pre></section></div>
      <template #footer><button class="secondary-btn" @click="selected=null">关闭</button><button v-if="selected" class="primary-btn" @click="diagnose(selected)">使用此简历诊断<ChevronRight /></button></template>
    </el-dialog>
  </section>
</template>

<style scoped>
.resume-library{display:grid;gap:20px}.resume-library-head{min-height:132px;padding:25px 28px;display:flex;align-items:center;justify-content:space-between;gap:20px;border-radius:12px;background:#0F4C45;color:#fff;box-shadow:0 2px 12px rgba(0,0,0,.07)}.resume-library-head span{color:#a9d2ca;font:700 11px Bahnschrift,Consolas,monospace;letter-spacing:1.4px}.resume-library-head h2{margin:6px 0;font-size:25px}.resume-library-head p{margin:0;color:rgba(255,255,255,.68);font-size:13px}.resume-library-head label{position:relative;flex:none}.resume-library-head input{position:absolute;inset:0;opacity:0;cursor:pointer}.resume-library-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.resume-library-grid article{min-width:0;overflow:hidden;border-radius:12px;background:#fff;box-shadow:0 2px 12px rgba(0,0,0,.06);transition:all .25s ease}.resume-library-grid article:hover{box-shadow:0 4px 20px rgba(0,0,0,.08);transform:translateY(-2px)}.resume-library-grid article.active{box-shadow:inset 3px 0 #D4A853,0 2px 12px rgba(0,0,0,.06)}.resume-library-grid article>header{min-height:92px;padding:18px 20px;display:grid;grid-template-columns:42px minmax(0,1fr) auto;align-items:center;gap:12px;border-bottom:1px solid #edf1ef}.resume-library-grid header>span{width:42px;height:46px;display:grid;place-items:center;border-radius:8px;background:#EAF3F0;color:#0F4C45}.resume-library-grid header svg{width:18px}.resume-library-grid header small,.resume-library-grid header p{color:#899692;font-size:10px}.resume-library-grid h3{margin:4px 0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:15px}.resume-library-grid header p{margin:0}.resume-library-grid header em{padding:4px 7px;display:flex;align-items:center;gap:4px;border-radius:6px;background:#fff2d4;color:#8e631e;font-size:9px;font-style:normal}.resume-library-grid header em svg{width:12px}.resume-library-grid dl{margin:0;padding:14px 20px;display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.resume-library-grid dt{color:#899692;font-size:9px}.resume-library-grid dd{margin:4px 0 0;font-size:12px;font-weight:700}.resume-library-skills{min-height:66px;padding:0 20px 14px;display:flex;align-content:flex-start;flex-wrap:wrap;gap:6px}.resume-library-skills span,.resume-library-skills small{padding:4px 8px;border-radius:6px;background:#EAF3F0;color:#0F4C45;font-size:10px}.resume-library-grid footer{padding:14px 20px;display:flex;align-items:center;gap:7px;border-top:1px solid #edf1ef}.resume-library-grid footer button{height:36px;padding:0 10px}.resume-library-grid footer .icon-btn{margin-left:auto;padding:0;color:#79565a}.resume-library-grid footer svg{width:14px}.resume-library-empty{min-height:360px;display:flex;align-items:center;justify-content:center;flex-direction:column;border-radius:12px;background:#fff;box-shadow:0 2px 12px rgba(0,0,0,.06);text-align:center}.resume-library-empty>svg{width:42px;color:#9eb0ac}.resume-library-empty h2{margin:15px 0 6px}.resume-library-empty p{margin:0;color:#888}.resume-library-loading{display:grid;grid-template-columns:1fr 1fr;gap:16px}.resume-library-loading i{height:280px;border-radius:12px;background:#edf2f1}.resume-preview-dialog{display:grid;gap:18px}.resume-preview-dialog>header{padding:14px;display:grid;grid-template-columns:34px minmax(0,1fr) auto;align-items:center;gap:10px;border-radius:8px;background:#f5f8f7}.resume-preview-dialog header strong,.resume-preview-dialog header small{display:block}.resume-preview-dialog header small{margin-top:3px;color:#888}.resume-preview-dialog dl{margin:0;display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.resume-preview-dialog dl>div{padding:12px;border-radius:8px;background:#f7faf9}.resume-preview-dialog dt{color:#888;font-size:10px}.resume-preview-dialog dd{margin:5px 0 0}.resume-preview-dialog h3{margin:0 0 9px;font-size:14px}.resume-preview-dialog section>div{display:flex;flex-wrap:wrap;gap:6px}.resume-preview-dialog section span{padding:4px 8px;border-radius:6px;background:#EAF3F0;color:#0F4C45;font-size:11px}.resume-preview-dialog pre{max-height:260px;margin:0;padding:14px;overflow:auto;border-radius:8px;background:#f5f7f6;color:#40504d;font:12px/1.75 "Microsoft YaHei UI",sans-serif;white-space:pre-wrap}.error-text{display:flex;align-items:center;justify-content:space-between}
@media(max-width:900px){.resume-library-grid{grid-template-columns:1fr}}@media(max-width:620px){.resume-library-head{align-items:flex-start;flex-direction:column;padding:21px}.resume-library-head label{width:100%}.resume-library-grid footer{flex-wrap:wrap}.resume-preview-dialog dl{grid-template-columns:1fr}}
</style>
