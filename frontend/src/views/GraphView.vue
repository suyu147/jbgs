<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Check, Copy, ExternalLink, Focus, RotateCcw, Search, Target, X } from 'lucide-vue-next'
import GraphChart from '@/components/charts/GraphChart.vue'
import { insightService } from '@/services/insightService'
import type { GraphData, GraphFilterOptions, JobSummary } from '@/types/domain'
import { useWorkspaceStore } from '@/stores/workspace'

const route = useRoute()
const router = useRouter()
const workspace = useWorkspaceStore()
const jobs = ref<JobSummary[]>([])
const filters = ref<GraphFilterOptions>({ viewModes: [], techStacks: [], skillTiers: [], seniorityLevels: [], entityTypes: [], method: { techStack: '', skillTier: '', seniority: '' } })
const graph = ref<GraphData>({ nodes: [], edges: [], totalNodes: 0, totalEdges: 0, truncated: false })
const selectedId = ref('')
const loading = ref(false)
const error = ref('')
const entityType = ref('')
const nodeDetail = ref<Record<string, any>>({})
const copiedUrl = ref('')
let ready = false
let initializing = true

const roleId = computed({
  get: () => workspace.targetRoleId,
  set: (id: string) => {
    const job = jobs.value.find(item => item.id === id)
    workspace.selectTarget(id, job?.name || id)
  },
})
const keyword = computed({ get: () => workspace.graphKeyword, set: value => { workspace.graphKeyword = value } })
const viewMode = computed<'role' | 'stack' | 'entity'>({ get: () => workspace.graphViewMode, set: value => { workspace.graphViewMode = value } })
const techStack = computed({ get: () => workspace.graphTechStack, set: value => { workspace.graphTechStack = value } })
const skillTier = computed({ get: () => workspace.graphSkillTier, set: value => { workspace.graphSkillTier = value } })
const seniority = computed({ get: () => workspace.graphSeniority, set: value => { workspace.graphSeniority = value } })
const selected = computed(() => graph.value.nodes.find(node => node.id === selectedId.value))
const roleOptions = computed(() => {
  const center = graph.value.nodes.find(node => node.id === roleId.value && node.type === 'job')
  return center && !jobs.value.some(job => job.id === center.id)
    ? [{ id: center.id, name: center.name }, ...jobs.value]
    : jobs.value
})
const edgeCount = computed(() => graph.value.edges.filter(edge => edge.source === selectedId.value || edge.target === selectedId.value).length)
const statistics = computed(() => graph.value.statistics || { roleCount: graph.value.nodes.filter(node => node.type === 'job').length, skillCount: graph.value.nodes.filter(node => node.type === 'skill').length, relationCount: graph.value.edges.length })
const stackLabel = computed(() => filters.value.techStacks.find(item => item.value === techStack.value)?.label || '')
const tierLabel = computed(() => filters.value.skillTiers.find(item => item.value === skillTier.value)?.label || '全部能力')
const seniorityLabel = computed(() => filters.value.seniorityLevels.find(item => item.value === seniority.value)?.label || '全部级别')
const entityTypeLabel = computed(() => filters.value.entityTypes.find(item => item.value === entityType.value)?.label || '全部实体')
const typeLabels: Record<string,string> = { job:'岗位角色',posting:'招聘记录',skill:'技能实体',certificate:'能力证书',course:'学习课程',major:'相关专业',standard:'职业标准',requirement:'职业要求',report:'趋势报告',signal:'趋势信号',topic:'趋势主题',snapshot:'需求快照',period:'时间周期' }
const selectedTypeLabel = computed(() => selected.value ? typeLabels[selected.value.type] || '图谱实体' : '')
const propertyLabels: Record<string,string> = { entity_name:'规范名称',role_name:'岗位名称',skill_type:'技能类型',definition:'定义',definition_canonical:'职业定义',issuer_canonical:'颁发机构',provider_canonical:'课程提供方',objectives_clean:'课程目标',learning_outcomes_clean:'学习成果',discipline_name:'学科',occupation_name:'职业名称',requirement_type:'要求类型',evidence_text_clean:'证据',source_url:'来源地址',published_date_clean:'发布时间',time_id:'周期标识',period:'统计周期',start_date:'开始日期',end_date:'结束日期',source_record_count:'来源记录数',posting_count:'样本量' }
const detailFacts = computed(() => Object.entries(nodeDetail.value).filter(([key,value]) => propertyLabels[key] && !/url/i.test(key) && value !== '' && value !== null && value !== undefined).slice(0, 8).map(([key,value]) => ({ label: propertyLabels[key], value: Array.isArray(value) ? value.join('、') : String(value) })))

const sourceUrls = computed(() => {
  const urls: string[] = []
  const add = (value: unknown) => {
    if (typeof value !== 'string') return
    value.split(/[\s,;|]+/).map(item => item.trim()).filter(item => /^https?:\/\//i.test(item)).forEach(item => {
      if (!urls.includes(item)) urls.push(item)
    })
  }
  const collect = (value: unknown) => {
    if (Array.isArray(value)) value.forEach(collect)
    else if (value && typeof value === 'object') Object.values(value as Record<string, unknown>).forEach(collect)
    else add(value)
  }
  Object.entries(nodeDetail.value).forEach(([key, value]) => {
    if (/source|url/i.test(key) || key === 'postings' || key === 'skills') collect(value)
  })
  return urls.slice(0, 20)
})
const entityTypeCounts = computed(() => Object.entries(graph.value.statistics?.typeCounts || {}).sort((a, b) => b[1] - a[1]))

function graphParams() {
  return {
    viewMode: viewMode.value,
    roleId: viewMode.value === 'role' ? roleId.value : '',
    techStack: viewMode.value === 'stack' ? techStack.value : '',
    skillTier: skillTier.value,
    seniority: viewMode.value === 'stack' ? seniority.value : '',
    entityType: viewMode.value === 'entity' ? entityType.value : '',
    keyword: keyword.value.trim(),
    limit: viewMode.value === 'entity' ? 220 : 100,
  }
}

async function syncRoute() {
  await router.replace({
    query: {
      mode: viewMode.value,
      roleId: viewMode.value === 'role' ? roleId.value || undefined : undefined,
      stack: viewMode.value === 'stack' ? techStack.value || undefined : undefined,
      entityType: viewMode.value === 'entity' ? entityType.value || undefined : undefined,
      tier: skillTier.value || undefined,
      seniority: viewMode.value === 'stack' ? seniority.value || undefined : undefined,
      q: keyword.value.trim() || undefined,
    },
  })
}

async function load() {
  if (!ready || (viewMode.value === 'role' && !roleId.value) || (viewMode.value === 'stack' && !techStack.value)) return
  loading.value = true
  error.value = ''
  try {
    graph.value = await insightService.getGraph(graphParams())
    const center = graph.value.nodes.find(node => node.id === roleId.value && node.type === 'job')
    if (center) workspace.targetRoleName = center.name
    if (!graph.value.nodes.some(node => node.id === selectedId.value)) {
      selectedId.value = ''
    }
    await syncRoute()
  } catch (reason: any) {
    error.value = reason.message
    graph.value = { nodes: [], edges: [], totalNodes: 0, totalEdges: 0, truncated: false }
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  skillTier.value = ''
  seniority.value = ''
  keyword.value = ''
  entityType.value = ''
}

function setTarget() {
  if (!selected.value || selected.value.type !== 'job') return
  workspace.selectTarget(selected.value.id, selected.value.name)
}

onMounted(async () => {
  loading.value = true
  try {
    const [jobData, filterData] = await Promise.all([
      insightService.getJobs({ pageSize: 100 }),
      insightService.getGraphFilters(),
    ])
    jobs.value = jobData.items
    filters.value = filterData
    const requestedMode = String(route.query.mode || '')
    viewMode.value = requestedMode === 'stack' ? 'stack' : requestedMode === 'entity' ? 'entity' : requestedMode === 'role' ? 'role' : workspace.graphViewMode
    keyword.value = String(route.query.q || workspace.graphKeyword || '')
    skillTier.value = String(route.query.tier || workspace.graphSkillTier || '')
    seniority.value = String(route.query.seniority || workspace.graphSeniority || '')
    techStack.value = String(route.query.stack || workspace.graphTechStack || filterData.techStacks.find(item => Number(item.count) > 0)?.value || '')
    entityType.value = String(route.query.entityType || '')
    const requestedRole = String(route.query.roleId || '')
    if (requestedRole) roleId.value = requestedRole
    else if (!roleId.value) roleId.value = jobData.items[0]?.id || ''
    ready = true
    await load()
    initializing = false
  } catch (reason: any) {
    error.value = reason.message
    initializing = false
  } finally {
    loading.value = false
  }
})

watch([viewMode, techStack, skillTier, seniority], () => { if (ready && !initializing) load() })
watch(entityType, () => { if (ready && !initializing && viewMode.value === 'entity') load() })
watch(roleId, () => { if (ready && !initializing && viewMode.value === 'role') load() })
watch(selectedId, async id => {
  nodeDetail.value = {}
  copiedUrl.value = ''
  if (!id) return
  try { nodeDetail.value = (await insightService.getGraphNode(id)).properties || {} } catch { nodeDetail.value = {} }
})
async function copySourceUrl(url: string) {
  try {
    await navigator.clipboard.writeText(url)
    copiedUrl.value = url
    window.setTimeout(() => { if (copiedUrl.value === url) copiedUrl.value = '' }, 1800)
  } catch {
    copiedUrl.value = ''
  }
}
</script>

<template>
  <div class="graph-workspace">
    <section class="graph-control-bar" aria-label="图谱视图筛选">
      <div class="segmented graph-mode-switch" role="group" aria-label="图谱视图模式">
        <button type="button" :class="{ active: viewMode === 'role' }" :aria-pressed="viewMode === 'role'" @click="viewMode = 'role'">岗位视图</button>
        <button type="button" :class="{ active: viewMode === 'stack' }" :aria-pressed="viewMode === 'stack'" @click="viewMode = 'stack'">技术栈视图</button>
        <button type="button" :class="{ active: viewMode === 'entity' }" :aria-pressed="viewMode === 'entity'" @click="viewMode = 'entity'">全实体视图</button>
      </div>

      <label class="graph-filter">
        <span>{{ viewMode === 'role' ? '中心岗位' : viewMode === 'stack' ? '技术栈' : '实体类型' }}</span>
        <el-select v-if="viewMode === 'role'" v-model="roleId" filterable placeholder="选择中心岗位">
          <el-option v-for="job in roleOptions" :key="job.id" :label="job.name" :value="job.id" />
        </el-select>
        <el-select v-else-if="viewMode === 'stack'" v-model="techStack" placeholder="选择技术栈">
          <el-option v-for="item in filters.techStacks" :key="item.value" :label="`${item.label} · ${item.count || 0}`" :value="item.value" :disabled="!item.count" />
        </el-select>
        <el-select v-else v-model="entityType" clearable placeholder="全部实体">
          <el-option v-for="item in filters.entityTypes" :key="item.value" :label="`${item.label} · ${item.count || 0}`" :value="item.value" :disabled="!item.count" />
        </el-select>
      </label>

      <fieldset v-if="viewMode !== 'entity'" class="graph-tier-filter">
        <legend>能力级别</legend>
        <div class="segmented">
          <button type="button" :class="{ active: !skillTier }" :aria-pressed="!skillTier" @click="skillTier = ''">全部</button>
          <button v-for="item in filters.skillTiers" :key="item.value" type="button" :class="{ active: skillTier === item.value }" :aria-pressed="skillTier === item.value" @click="skillTier = item.value">{{ item.label.replace('能力', '') }}</button>
        </div>
      </fieldset>

      <label v-if="viewMode === 'stack'" class="graph-filter graph-seniority-filter">
        <span>岗位级别</span>
        <el-select v-model="seniority" placeholder="全部级别" clearable>
          <el-option v-for="item in filters.seniorityLevels" :key="item.value" :label="`${item.label} · ${item.count || 0}`" :value="item.value" :disabled="!item.count" />
        </el-select>
      </label>

      <div class="graph-query">
        <span>图谱内检索</span>
        <div class="inline-search">
          <Search aria-hidden="true" :size="16" />
          <input v-model="keyword" aria-label="搜索图谱内的节点" :placeholder="viewMode === 'role' ? '筛选技能' : viewMode === 'stack' ? '筛选岗位或技能' : '搜索岗位、技能、证书、课程等'" @keyup.enter="load"  name="keyword" autocomplete="off">
        </div>
      </div>

      <div class="graph-toolbar-actions">
        <button class="icon-btn" type="button" title="重置筛选" aria-label="重置筛选" @click="resetFilters"><RotateCcw aria-hidden="true" :size="17" /></button>
        <button class="icon-btn primary" type="button" title="重新计算图谱" aria-label="重新计算图谱" @click="load"><Focus aria-hidden="true" :size="17" /></button>
      </div>
    </section>

    <div class="graph-filter-summary" aria-live="polite">
      <div>
        <span>{{ viewMode === 'role' ? '岗位局部图谱' : viewMode === 'stack' ? stackLabel : '全域知识图谱' }}</span>
        <i v-if="viewMode !== 'entity'">{{ tierLabel }}</i>
        <i v-if="viewMode === 'stack'">{{ seniorityLabel }}</i>
        <i v-if="viewMode === 'entity'">{{ entityTypeLabel }}</i>
      </div>
      <p v-if="viewMode !== 'entity'">匹配 {{ statistics.roleCount }} 个岗位 · {{ statistics.skillCount }} 个技能 · {{ statistics.relationCount }} 条证据关系</p>
      <p v-else>展示 {{ graph.totalNodes }} 个多源实体 · {{ statistics.relationCount }} 条可查询关系</p>
      <small v-if="graph.appliedFilters?.fallback === 'true'" class="graph-fallback-note">{{ graph.appliedFilters.fallbackLabel }}</small>
      <small v-if="graph.appliedFilters?.tierFallback === 'true'" class="graph-fallback-note">{{ graph.appliedFilters.tierFallbackLabel }}</small>
      <small v-if="graph.truncated">当前画布显示 {{ graph.totalNodes }} 个节点、{{ graph.totalEdges }} 条关系，请继续缩小条件。</small>
    </div>

    <section v-if="viewMode === 'entity'" class="entity-view-guide" aria-label="全实体视图说明">
      <div><strong>全实体视图</strong><span>在同一张图里查看岗位、招聘记录、技能、证书、课程、专业、职业标准与趋势资产的上下游证据关系。</span></div>
      <div class="entity-type-counts"><span v-for="item in entityTypeCounts" :key="item[0]">{{ typeLabels[item[0]] || item[0] }} <b>{{ item[1] }}</b></span></div>
    </section>
    <p v-if="error" class="error-text" role="alert">{{ error }}</p>
    <div class="graph-interaction-guide"><p>点击节点查看证据；拖动可调整位置，使用缩放按钮查看全貌。</p><label>直接选择节点<select v-model="selectedId" aria-label="选择节点查看详情"><option value="">请选择节点</option><option v-for="node in graph.nodes" :key="node.id" :value="node.id">{{ node.name }}</option></select></label></div>
    <div class="graph-stage" :class="{ 'has-detail': selected && !loading }" :aria-busy="loading">
      <div v-if="loading" class="loading-overlay" role="status">正在按筛选条件计算图谱…</div>
      <div v-else-if="!graph.edges.length" class="graph-empty" role="status">
        <Search aria-hidden="true" :size="28" />
        <h2>当前条件没有可展示的证据关系</h2>
        <p>调整技术栈、能力级别或岗位级别后重新查看。</p>
        <button class="secondary-btn" type="button" @click="resetFilters">重置筛选</button>
      </div>
      <GraphChart v-else :data="graph" @select="selectedId = $event" />

      <aside v-if="selected && !loading" class="entity-drawer">
        <div class="drawer-head">
          <span>{{ selectedTypeLabel }}</span>
          <button class="icon-btn" type="button" title="关闭" aria-label="关闭节点详情" @click="selectedId = ''"><X aria-hidden="true" :size="16" /></button>
        </div>
        <h2>{{ selected.name }}</h2>
        <p>{{ selected.type === 'job' ? '标准岗位角色，能力关系由多源 JD 证据与人工发布版本共同形成。' : `已治理的${selectedTypeLabel}，可沿画布关系继续查看上下游证据。` }}</p>
        <dl>
          <div><dt>实体类别</dt><dd>{{ selectedTypeLabel }}</dd></div>
          <div><dt>当前关联</dt><dd>{{ edgeCount }}</dd></div>
          <div><dt>数据状态</dt><dd>已治理</dd></div>
          <div v-for="fact in detailFacts" :key="fact.label"><dt>{{ fact.label }}</dt><dd :title="fact.value">{{ fact.value }}</dd></div>
        </dl>
        <div v-if="sourceUrls.length" class="source-url-fact">
          <dt>来源地址</dt>
          <dd>
            <div v-for="url in sourceUrls" :key="url" class="source-url-row">
              <a :href="url" target="_blank" rel="noreferrer" :title="url">{{ url }} <ExternalLink aria-hidden="true" :size="13" /></a>
              <button type="button" class="copy-url-btn" :aria-label="`复制来源地址 ${url}`" @click="copySourceUrl(url)">
                <Check aria-hidden="true" v-if="copiedUrl === url" :size="14" /><Copy aria-hidden="true" v-else :size="14" />{{ copiedUrl === url ? '已复制' : '复制' }}
              </button>
            </div>
          </dd>
        </div>
        <button v-if="selected.type === 'job'" class="secondary-btn graph-target-action" type="button" :disabled="workspace.targetRoleId === selected.id" @click="setTarget">
          <Target aria-hidden="true" :size="15" />{{ workspace.targetRoleId === selected.id ? '当前目标岗位' : '设为目标岗位' }}
        </button>
      </aside>
    </div>
  </div>
</template>
