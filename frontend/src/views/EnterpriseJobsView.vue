<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { useBusinessUnsaved } from '@/composables/useBusinessUnsaved'
import { Building2, Check, FileText, LoaderCircle, MapPin, Plus, Send, UploadCloud, Users, X } from 'lucide-vue-next'
import { insightService } from '@/services/insightService'
import type { EnterpriseJobSubmission } from '@/types/domain'

const form = reactive({ companyName: '', contact: '', roleName: '', jobCategory: '', location: '', openingCount: 1, responsibilities: '', requiredSkills: '', bonusSkills: '', applicationScenarios: '', jdText: '' })
const savedForm = ref(JSON.stringify(form))
useBusinessUnsaved(computed(() => JSON.stringify(form) !== savedForm.value))
const submissions = ref<EnterpriseJobSubmission[]>([])
const loading = ref(false)
const error = ref('')
const status = ref('')
const attempted = ref(false)
const fieldErrors = computed(() => ({companyName: form.companyName.trim().length >= 2 ? '' : '企业名称至少填写 2 个字符', roleName: form.roleName.trim().length >= 2 ? '' : '岗位名称至少填写 2 个字符', jobCategory: form.jobCategory.trim().length >= 2 ? '' : '岗位类别至少填写 2 个字符', responsibilities: lines(form.responsibilities).length ? '' : '请填写至少一项核心职责', requiredSkills: lines(form.requiredSkills).length ? '' : '请填写至少一项必备技能', openingCount: Number.isInteger(form.openingCount) && form.openingCount >= 1 && form.openingCount <= 10000 ? '' : '招聘人数需为 1–10000 的整数'}))
const fileName = ref('')
const valid = computed(() => Number.isInteger(form.openingCount) && form.openingCount >= 1 && form.openingCount <= 10000 && form.companyName.trim().length >= 2 && form.roleName.trim().length >= 2 && form.jobCategory.trim().length >= 2 && lines(form.responsibilities).length > 0 && lines(form.requiredSkills).length > 0)
function lines(value: string) { return value.split(/\r?\n|[,，]/).map(item => item.trim()).filter(Boolean) }
function stateClass(value: string) { return value === 'approved' ? 'approved' : value === 'rejected' ? 'rejected' : 'pending' }
async function load() {
  try { submissions.value = (await insightService.getEnterpriseJobSubmissions()).items }
  catch (reason: any) { error.value = reason.message || '提交记录读取失败' }
}
async function readJd(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  fileName.value = file.name
  try { form.jdText = await file.text(); status.value = `已读取 ${file.name}，提交时将作为岗位说明证据。` }
  catch { error.value = '该文件无法在浏览器中读取，请粘贴 JD 正文。' }
}
async function submit() {
  attempted.value = true
  if (!valid.value || loading.value) { await nextTick(); document.querySelector<HTMLElement>('.job-form [aria-invalid="true"]')?.focus(); return }
  loading.value = true; error.value = ''; status.value = ''
  try {
    const item = await insightService.createEnterpriseJobSubmission({
      companyName: form.companyName.trim(), contact: form.contact.trim(), roleName: form.roleName.trim(), jobCategory: form.jobCategory.trim(),
      location: form.location.trim(), openingCount: form.openingCount, responsibilities: lines(form.responsibilities), requiredSkills: lines(form.requiredSkills),
      bonusSkills: lines(form.bonusSkills), applicationScenarios: lines(form.applicationScenarios), jdText: form.jdText,
    })
    submissions.value = [item, ...submissions.value]
    status.value = '岗位已提交至候选复核。可在右侧提交记录中跟踪状态，批准后进入发布流程。'
    Object.assign(form, { roleName: '', jobCategory: '', location: '', openingCount: 1, responsibilities: '', requiredSkills: '', bonusSkills: '', applicationScenarios: '', jdText: '' })
    fileName.value = ''; attempted.value = false; savedForm.value = JSON.stringify(form)
  } catch (reason: any) { error.value = reason.message || '岗位提交失败' }
  finally { loading.value = false }
}
onMounted(load)
</script>

<template>
  <div class="enterprise-jobs">
    <section class="submission-guide"><div><span><Building2/></span><div><h2>企业岗位进入治理发布流程</h2><p>HR 提交岗位定义和 JD 证据，治理管理员复核后生成版本，再由管理员正式发布。</p></div></div><ol><li class="active"><b>1</b><span>企业提交<small>结构化岗位与 JD</small></span></li><li><b>2</b><span>治理复核<small>核对定义与能力</small></span></li><li><b>3</b><span>批准发布<small>同步岗位库与图谱</small></span></li></ol></section>
    <p v-if="status" class="enterprise-success" role="status"><Check/>{{ status }}<button aria-label="关闭提示" @click="status = ''"><X/></button></p>
    <p v-if="error" class="enterprise-error" role="alert">{{ error }}</p>
    <div class="jobs-layout">
      <form class="job-form" @submit.prevent="submit" novalidate>
        <header><h2>提交招聘岗位</h2><p>带 * 的字段用于形成可复核岗位定义。</p></header>
        <div class="form-grid">
          <label><span>企业名称 *</span><div><Building2/><input v-model="form.companyName" :aria-invalid="attempted && Boolean(fieldErrors.companyName)" :aria-describedby="attempted && fieldErrors.companyName ? 'error-companyName' : undefined" maxlength="255" placeholder="例如：示例科技有限公司" name="companyName" autocomplete="organization" /></div><small v-if="attempted && fieldErrors.companyName" id="error-companyName" class="ui-field-error">{{ fieldErrors.companyName }}</small></label>
          <label><span>联系方式</span><input v-model="form.contact" maxlength="160" placeholder="企业邮箱或招聘联系人" name="contact" autocomplete="off" /></label>
          <label><span>岗位名称 *</span><input v-model="form.roleName" :aria-invalid="attempted && Boolean(fieldErrors.roleName)" :aria-describedby="attempted && fieldErrors.roleName ? 'error-roleName' : undefined" maxlength="255" placeholder="例如：大模型应用工程师" name="roleName" autocomplete="off" /><small v-if="attempted && fieldErrors.roleName" id="error-roleName" class="ui-field-error">{{ fieldErrors.roleName }}</small></label>
          <label><span>岗位类别 *</span><input v-model="form.jobCategory" :aria-invalid="attempted && Boolean(fieldErrors.jobCategory)" :aria-describedby="attempted && fieldErrors.jobCategory ? 'error-jobCategory' : undefined" maxlength="120" placeholder="例如：人工智能研发" name="jobCategory" autocomplete="off" /><small v-if="attempted && fieldErrors.jobCategory" id="error-jobCategory" class="ui-field-error">{{ fieldErrors.jobCategory }}</small></label>
          <label><span>招聘城市</span><div><MapPin/><input v-model="form.location" maxlength="120" placeholder="例如：杭州" name="location" autocomplete="off" /></div></label>
          <label><span>招聘人数</span><div><Users/><input v-model.number="form.openingCount" :aria-invalid="attempted && Boolean(fieldErrors.openingCount)" :aria-describedby="attempted && fieldErrors.openingCount ? 'error-openingCount' : undefined" type="number" min="1" max="10000" name="openingCount" autocomplete="off" /></div><small v-if="attempted && fieldErrors.openingCount" id="error-openingCount" class="ui-field-error">{{ fieldErrors.openingCount }}</small></label>
          <label class="wide"><span>核心职责 * <small>每行一项</small></span><textarea v-model="form.responsibilities" :aria-invalid="attempted && Boolean(fieldErrors.responsibilities)" :aria-describedby="attempted && fieldErrors.responsibilities ? 'error-responsibilities' : undefined" rows="3" placeholder="负责大模型应用场景的需求分析与方案落地&#10;建设知识检索和效果评估流程" name="responsibilities" autocomplete="off"></textarea><small v-if="attempted && fieldErrors.responsibilities" id="error-responsibilities" class="ui-field-error">{{ fieldErrors.responsibilities }}</small></label>
          <label><span>必备技能 * <small>每行一项</small></span><textarea v-model="form.requiredSkills" :aria-invalid="attempted && Boolean(fieldErrors.requiredSkills)" :aria-describedby="attempted && fieldErrors.requiredSkills ? 'error-requiredSkills' : undefined" rows="4" placeholder="Python&#10;大模型应用开发&#10;RAG" name="requiredSkills" autocomplete="off"></textarea><small v-if="attempted && fieldErrors.requiredSkills" id="error-requiredSkills" class="ui-field-error">{{ fieldErrors.requiredSkills }}</small></label>
          <label><span>加分技能 <small>可选，每行一项</small></span><textarea v-model="form.bonusSkills" rows="4" placeholder="知识图谱&#10;模型评测&#10;数据治理" name="bonusSkills" autocomplete="off"></textarea></label>
          </div><details class="optional-fields"><summary>补充应用场景与完整 JD 证据（可选）</summary><div class="form-grid"><label class="wide"><span>典型应用场景 <small>可选，每行一项</small></span><textarea v-model="form.applicationScenarios" rows="4" placeholder="企业知识助手&#10;智能客服与业务流程自动化" name="applicationScenarios" autocomplete="off"></textarea></label>
          <div class="wide jd-evidence"><label for="job-jd-text">完整 JD 证据</label><textarea id="job-jd-text" v-model="form.jdText" rows="8" placeholder="粘贴完整职位描述，或通过下方按钮读取本地 TXT / MD 文件。" name="jdText" autocomplete="off"></textarea><div class="jd-file"><label><UploadCloud/><input type="file" accept=".txt,.md" @change="readJd" />读取 JD 文件</label><span v-if="fileName"><FileText/>{{ fileName }}</span></div></div>
        </div></details>
        <footer><p>提交后保留原始 JD 证据，由治理管理员复核后发布。</p><button type="submit" :disabled="loading"><LoaderCircle v-if="loading" class="spin"/><Send v-else/>{{ loading ? '正在提交' : '提交治理复核' }}</button></footer>
      </form>
      <aside class="submission-history">
        <header><h2>提交记录</h2><span>{{ submissions.length }}</span></header>
        <div><article v-for="item in submissions" :key="item.id"><header><span :class="stateClass(item.status)">{{ item.statusLabel }}</span><time>{{ new Date(item.createdAt).toLocaleDateString('zh-CN') }}</time></header><h3>{{ item.roleName }}</h3><p>{{ item.jobCategory }}<span>·</span>{{ item.location || '地点待定' }}</p><dl><div><dt>招聘人数</dt><dd>{{ item.openingCount }}</dd></div><div><dt>企业</dt><dd>{{ item.companyName }}</dd></div></dl></article><div v-if="!submissions.length" class="history-empty"><Plus/><strong>暂无岗位提交</strong><p>首条记录提交后会在这里显示复核状态。</p></div></div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.enterprise-jobs{display:grid;gap:14px}.submission-guide{padding:18px 20px;display:flex;align-items:center;justify-content:space-between;gap:24px;background:#fff;border:1px solid #dfeae7;border-radius:8px}.submission-guide>div{display:flex;gap:12px}.submission-guide>div>span{width:40px;height:40px;display:grid;place-items:center;border-radius:6px;background:#e9f7f4;color:#0f8d82}.submission-guide svg{width:20px}.submission-guide h2{margin:0;font-size:16px}.submission-guide p{margin:4px 0 0;color:#71817d;font-size:11px}.submission-guide ol{margin:0;padding:0;display:flex;list-style:none}.submission-guide li{position:relative;min-width:135px;display:flex;align-items:center;gap:8px;color:#75837f}.submission-guide li:not(:last-child)::after{content:"";position:absolute;right:8px;width:28px;border-top:1px solid #cddbd7}.submission-guide li b{width:24px;height:24px;display:grid;place-items:center;border-radius:50%;background:#e9efed;font-size:10px}.submission-guide li.active b{background:#0f9d8f;color:#fff}.submission-guide li span{display:grid;font-size:11px;font-weight:700}.submission-guide li small{color:#919c99;font-size:8px;font-weight:400}.enterprise-success,.enterprise-error{margin:0;padding:10px 13px;display:flex;align-items:center;gap:8px;font-size:12px}.enterprise-success{background:#eaf8f2;border-color:#10b981;color:#28684f}.enterprise-error{background:#fff1ec;border-color:#e86a3f;color:#8a3f28}.enterprise-success svg{width:15px}.enterprise-success button{margin-left:auto;background:none;color:inherit}.enterprise-success button svg{width:14px}.jobs-layout{display:grid;grid-template-columns:minmax(0,1fr) 330px;gap:14px;align-items:start}.job-form,.submission-history{background:#fff;border:1px solid #dfeae7;border-radius:8px}.job-form>header,.submission-history>header{padding:18px 20px;border-bottom:1px solid #e3ebe9}.job-form h2,.submission-history h2{margin:0;font-size:17px}.job-form>header p{margin:4px 0 0;color:#798783;font-size:11px}.form-grid{padding:20px;display:grid;grid-template-columns:1fr 1fr;gap:16px}.form-grid label{min-width:0;display:grid;align-content:start;gap:6px;color:#425550;font-size:11px;font-weight:700}.form-grid label.wide{grid-column:1/-1}.form-grid label>span small{margin-left:6px;color:#8d9996;font-weight:400}.form-grid input,.form-grid textarea,.form-grid label>div{width:100%;border:1px solid #d8e3e0;border-radius:6px;background:#fff}.form-grid input{height:40px;padding:0 11px;outline:0}.form-grid textarea{padding:10px 11px;resize:vertical;outline:0;line-height:1.6}.form-grid label>div:not(.jd-file){display:flex;align-items:center;padding-left:10px}.form-grid label>div:not(.jd-file) svg{width:15px;color:#7b8c87}.form-grid label>div:not(.jd-file) input{min-width:0;border:0}.form-grid input:focus,.form-grid textarea:focus,.form-grid label>div:focus-within{border-color:#0f9d8f;box-shadow:0 0 0 2px rgba(15,157,143,.1)}.jd-file{display:flex;align-items:center;gap:12px;border:0!important}.jd-file label{width:max-content;height:34px;padding:0 11px;display:flex;align-items:center;gap:6px;border:1px solid #afd0ca;border-radius:5px;color:#0b8177;cursor:pointer}.jd-file input{display:none}.jd-file svg{width:14px}.jd-file>span{display:flex;align-items:center;gap:5px;color:#75837f;font-size:10px;font-weight:400}.job-form>footer{padding:15px 20px;display:flex;align-items:center;justify-content:space-between;gap:16px;border-top:1px solid #e3ebe9}.job-form>footer p{margin:0;color:#778681;font-size:10px}.job-form>footer button{min-height:42px;padding:0 17px;display:flex;align-items:center;gap:7px;border-radius:6px;background:#0f9d8f;color:#fff;font-weight:700}.job-form>footer button:disabled{opacity:.45;cursor:not-allowed}.job-form>footer svg{width:16px}.submission-history>header{display:flex;justify-content:space-between}.submission-history>header span{min-width:24px;height:24px;display:grid;place-items:center;background:#e7f5f2;color:#0b8177;border-radius:4px;font-size:10px}.submission-history>div{max-height:780px;overflow:auto}.submission-history article{padding:16px 18px;border-bottom:1px solid #e8eeec}.submission-history article>header{display:flex;justify-content:space-between}.submission-history article>header span{padding:3px 6px;border-radius:4px;font-size:9px}.submission-history .pending{background:#fff4e9;color:#a85b22}.submission-history .approved{background:#e9f7ef;color:#287354}.submission-history .rejected{background:#fff0ec;color:#a4442c}.submission-history time{color:#8c9895;font-size:9px}.submission-history h3{margin:10px 0 3px;font-size:14px}.submission-history article>p{margin:0;color:#788681;font-size:10px}.submission-history article>p span{margin:0 5px}.submission-history dl{margin:12px 0 0;padding-top:10px;display:grid;grid-template-columns:80px 1fr;gap:10px;border-top:1px solid #edf1f0}.submission-history dl div{min-width:0}.submission-history dt{color:#87938f;font-size:9px}.submission-history dd{margin:2px 0 0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:10px;font-weight:700}.history-empty{min-height:260px;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#81908c;text-align:center}.history-empty svg{width:36px;color:#a9bbb6}.history-empty strong{margin-top:10px}.history-empty p{margin:4px 0;font-size:10px}.spin{animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
@media(max-width:1050px){.submission-guide{align-items:flex-start;flex-direction:column}.jobs-layout{grid-template-columns:1fr}.submission-history>div{max-height:400px}}
@media(max-width:650px){.form-grid{grid-template-columns:1fr;padding:15px}.form-grid label.wide{grid-column:auto}.submission-guide ol{width:100%}.submission-guide li{min-width:0;flex:1}.submission-guide li:not(:last-child)::after{display:none}.submission-guide li small{display:none}.job-form>footer{align-items:flex-start;flex-direction:column}.job-form>footer button{width:100%;justify-content:center}}
</style>
