<script setup lang="ts">
import { jobVisualTone } from '@/utils/jobVisualTone'
import { onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, CheckCircle2, CircleAlert, ExternalLink, FileSearch, LoaderCircle, Telescope, X } from 'lucide-vue-next'
import { insightService } from '@/services/insightService'
import type { EmergingRoleDetail, EmergingRoleSignal } from '@/types/domain'
import { useWorkspaceStore } from '@/stores/workspace'

const emit = defineEmits<{ count: [value: number] }>()
const router = useRouter()
const workspace = useWorkspaceStore()
const roles = ref<EmergingRoleSignal[]>([])
const selectedRole = ref<EmergingRoleSignal | null>(null)
const detail = ref<EmergingRoleDetail | null>(null)
const loading = ref(false)
const error = ref('')
const drawerOpen = ref(false)
const detailLoading = ref(false)
const detailError = ref('')
let loadVersion = 0
let detailVersion = 0

function itemName(item: string | Record<string, any>, key = 'skill_name') {
  return typeof item === 'string' ? item : String(item[key] || item.name || item.scenario || '')
}
async function loadRoles() {
  const version = ++loadVersion
  loading.value = true
  error.value = ''
  try {
    const result = await insightService.getForecastOverview(3, 'baseline', 'year', '', workspace.location)
    if (version !== loadVersion) return
    roles.value = result.emergingRoles
    emit('count', roles.value.length)
  } catch (reason: any) {
    if (version !== loadVersion) return
    roles.value = []
    emit('count', 0)
    error.value = reason?.message || '新岗位信号读取失败'
  } finally {
    if (version === loadVersion) loading.value = false
  }
}
async function openRole(role: EmergingRoleSignal) {
  selectedRole.value = role
  detail.value = null
  detailError.value = ''
  drawerOpen.value = true
  const version = ++detailVersion
  detailLoading.value = true
  try {
    const value = await insightService.getEmergingRole(role.id, 3)
    if (version === detailVersion) detail.value = value
  } catch (reason: any) {
    if (version === detailVersion) detailError.value = reason?.message || '岗位信号详情读取失败'
  } finally {
    if (version === detailVersion) detailLoading.value = false
  }
}
function closeDetail() {
  drawerOpen.value = false
  selectedRole.value = null
  detail.value = null
  detailError.value = ''
}
function openPublishedRole(role: EmergingRoleSignal) {
  if (role.roleId && role.canOpenJob) router.push(`/jobs/${encodeURIComponent(role.roleId)}`)
}

onMounted(loadRoles)
watch(() => workspace.location, loadRoles)
</script>

<template>
  <section class="emerging-lab job-emerging-lab" aria-label="新岗位目录">
    <header class="emerging-intro">
      <div><h2>未来可能形成的新岗位</h2><p>每项信号至少有 5 条有效招聘证据、覆盖 2 个来源；形成时间为预测，需结合证据判断。</p></div>
      <div><span><i class="stage-accelerating"></i>加速形成</span><span><i class="stage-forming"></i>正在形成</span><span><i class="stage-early"></i>早期信号</span></div>
    </header>
    <div v-if="loading" class="forecast-loading"><LoaderCircle aria-hidden="true" class="spin" />正在读取新岗位信号…</div>
    <div v-else-if="error" class="forecast-error"><CircleAlert aria-hidden="true" /><div><strong>新岗位目录读取失败</strong><p>{{ error }}</p></div><button class="secondary-btn" @click="loadRoles">重试</button></div>
    <template v-else>
      <div class="emerging-grid">
        <article v-for="role in roles" :key="role.id" :data-job-tone="jobVisualTone(role.industry, role.name)" :class="`status-${role.reviewStatus || 'pending'}`">
          <header><span :class="`stage-${role.stage}`"></span><div><small>{{ role.publicationTitle || '新岗位发现' }} · {{ role.industry }}</small><button class="emerging-title-button" @click="openRole(role)">{{ role.name }}</button></div></header>
          <p>{{ role.rationale }}</p>
          <dl><div><dt>可能形成窗口</dt><dd>{{ role.expectedWindow }}</dd></div><div><dt>数据来源</dt><dd>{{ role.sourceCount || 0 }} 个</dd></div><div><dt>证据数量</dt><dd>{{ role.evidenceCount }} 条</dd></div></dl>
          <section><span>核心能力组合</span><div><em v-for="skill in role.coreSkills" :key="skill">{{ skill }}</em></div></section>
          <footer><button @click="openRole(role)"><FileSearch aria-hidden="true" />查看详情</button><button v-if="role.canOpenJob" @click="openPublishedRole(role)">岗位档案<ArrowRight aria-hidden="true" /></button><span :class="`signal-status ${role.reviewStatus || 'pending'}`"><CheckCircle2 aria-hidden="true" />{{ role.statusLabel || '等待专家复核' }}</span></footer>
        </article>
      </div>
      <div v-if="!roles.length" class="empty-state"><Telescope aria-hidden="true" /><h2>暂无达到证据门槛的新岗位信号</h2><p>新的多来源候选通过数据治理后会显示在这里。</p></div>
    </template>
  </section>

  <el-drawer class="career-drawer" :title="detail?.name || selectedRole?.name || '岗位信号详情'" :model-value="drawerOpen" size="min(720px, 94vw)" :with-header="false" @close="closeDetail">
    <div class="emerging-detail-drawer">
      <header><div><h2>{{ detail?.name || selectedRole?.name }}</h2><p>{{ detail?.publicationTitle || selectedRole?.publicationTitle || '新岗位发现' }}</p></div><button class="icon-btn" title="关闭" aria-label="关闭岗位信号详情" @click="closeDetail"><X aria-hidden="true" /></button></header>
      <div v-if="detailLoading" class="forecast-loading"><LoaderCircle aria-hidden="true" class="spin" />正在读取岗位信号证据…</div>
      <div v-else-if="detailError" class="forecast-error"><CircleAlert aria-hidden="true" /><div><strong>详情读取失败</strong><p>{{ detailError }}</p></div><button v-if="selectedRole" class="secondary-btn" @click="openRole(selectedRole)">重试</button></div>
      <template v-else-if="detail">
        <section class="signal-detail-summary"><span :class="`signal-status ${detail.reviewStatus}`">{{ detail.statusLabel }}</span><dl><div><dt>招聘记录</dt><dd>{{ detail.postingCount }} 条</dd></div><div><dt>数据来源</dt><dd>{{ detail.sourceCount }} 个</dd></div><div><dt>观测周期</dt><dd>{{ detail.firstSeen || '未知' }} 至 {{ detail.latestSeen || '未知' }}</dd></div></dl><p>{{ detail.rationale }}</p></section>
        <section class="signal-detail-section"><h3>核心职责</h3><ul><li v-for="item in detail.responsibilities" :key="itemName(item, 'responsibility')">{{ itemName(item, 'responsibility') }}</li></ul></section>
        <section class="signal-detail-section"><h3>能力要求</h3><div class="signal-skill-groups"><div><span>必备技能</span><em v-for="item in detail.requiredSkills" :key="itemName(item)">{{ itemName(item) }}</em></div><div><span>加分技能</span><em v-for="item in detail.bonusSkills" :key="itemName(item)">{{ itemName(item) }}</em></div></div></section>
        <section class="signal-detail-section"><h3>来源证据</h3><article v-for="record in detail.evidence" :key="record.recordId || `${record.source}-${record.period}`" class="signal-evidence-row"><div><strong>{{ record.source || record.type || '来源记录' }}</strong><small>{{ record.period || '时间未知' }} · {{ record.recordId || '聚合证据' }}</small></div><p>{{ record.excerpt || '该记录用于岗位信号统计与人工复核。' }}</p><a v-if="record.url" :href="record.url" target="_blank" rel="noopener noreferrer">打开来源<ExternalLink aria-hidden="true" /></a></article></section>
        <footer><button v-if="detail.canOpenJob" class="primary-btn" @click="openPublishedRole(detail)">查看正式岗位档案<ArrowRight aria-hidden="true" /></button><button class="secondary-btn" @click="workspace.jobSearchKeyword = detail.coreSkills[0] || detail.name; router.push('/jobs')">探索相近岗位</button></footer>
      </template>
    </div>
  </el-drawer>
</template>
