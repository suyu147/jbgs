<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { Database, History, Pencil, RefreshCw, ShieldCheck, Upload, X } from 'lucide-vue-next'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { useBusinessUnsaved } from '@/composables/useBusinessUnsaved'
import UiState from '@/components/ui/UiState.vue'
import { insightService } from '@/services/insightService'
import type { DatasetItem, DatasetRevision } from '@/types/domain'

const items = ref<DatasetItem[]>([])
const route = useRoute(), router = useRouter()
const keyword = ref(String(route.query.q || ''))
const boundary = ref(String(route.query.boundary || 'all'))
const filteredItems = computed(() => items.value.filter(item => (boundary.value === 'all' || item.boundary === boundary.value) && `${item.name}${item.category}${item.version}`.toLowerCase().includes(keyword.value.trim().toLowerCase())))
const total = ref(0)
const page = ref(Math.max(1,Number(route.query.page)||1))
watch([keyword,boundary,page], () => {void router.replace({query:{...route.query,q:keyword.value || undefined,boundary:boundary.value==='all'?undefined:boundary.value,page:String(page.value)}})})
watch(() => [route.query.q,route.query.boundary,route.query.page], ([q,b,p])=>{keyword.value=String(q||'');boundary.value=String(b||'all');const n=Math.max(1,Number(p)||1);if(page.value!==n){page.value=n;void load()}})
const loading = ref(true)
const saving = ref(false)
const attempted = ref(false)
const fileError = ref('')
const error = ref('')
const editing = ref<DatasetItem | null | 'new'>(null)
const revisions = ref<DatasetRevision[]>([])
const selectedFile = ref<File | null>(null)
const fileInput = ref<HTMLInputElement>()
const form = reactive({ name: '', category: '上传资产', version: '', boundary: 'review', syncGraph: true })
const editorBaseline = ref('')
const editorDirty = computed(() => Boolean(editing.value) && (JSON.stringify(form)!==editorBaseline.value || Boolean(selectedFile.value)))
useBusinessUnsaved(editorDirty)
function confirmEditorClose(done?: () => void) {
 if(saving.value) return
 if(editorDirty.value && !window.confirm('有尚未保存的资产修改，确认关闭并放弃？')) return
 editing.value=null; done?.()
}
const formalCount = computed(() => items.value.filter(item => item.boundary === 'formal').length)
const reviewCount = computed(() => items.value.filter(item => item.boundary !== 'formal').length)
const pendingSyncCount = computed(() => items.value.filter(item => !['synced', 'not_requested'].includes(item.syncStatus || '')).length)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await insightService.getDatasets(page.value, 20)
    items.value = data.items
    total.value = data.total
  } catch (reason: any) { error.value = reason.message } finally { loading.value = false }
}

function resetForm() {
  attempted.value=false;fileError.value=''
  Object.assign(form, { name: '', category: '上传资产', version: '', boundary: 'review', syncGraph: true })
  selectedFile.value = null
  revisions.value = []
  if (fileInput.value) fileInput.value.value = ''
}

function openCreate() {
  resetForm()
  editing.value = 'new'
  editorBaseline.value = JSON.stringify(form)
}

async function openEdit(item: DatasetItem) {
  resetForm()
  editing.value = item
  Object.assign(form, { name: item.name, category: item.category, version: item.version, boundary: item.boundary, syncGraph: true })
  editorBaseline.value = JSON.stringify(form)
  try { revisions.value = await insightService.getDatasetRevisions(item.id) } catch { ElMessage.error('版本历史读取失败，请关闭后重试。') }
}

function chooseFile(event: Event) {
  selectedFile.value = (event.target as HTMLInputElement).files?.[0] || null
  fileError.value=selectedFile.value && selectedFile.value.size > 250*1024*1024 ? '文件超过 250 MB，请压缩或拆分后重试。' : ''
  if (editing.value === 'new' && selectedFile.value && !form.name) form.name = selectedFile.value.name.replace(/\.[^.]+$/, '')
}

function formData() {
  const body = new FormData()
  if (selectedFile.value) body.append('file', selectedFile.value)
  body.append('name', form.name.trim())
  body.append('category', form.category.trim())
  body.append('version', form.version.trim())
  body.append('boundary', form.boundary)
  body.append('syncGraph', String(form.syncGraph))
  return body
}

async function submit() {
  if(saving.value) return
  attempted.value=true
  if (!form.name.trim()) {document.querySelector<HTMLInputElement>('.dataset-editor input[name=name]')?.focus();return}
  if (fileError.value || (editing.value === 'new' && !selectedFile.value)) {fileError.value ||= '请选择需要上传的数据文件';fileInput.value?.focus();return}
  if (form.boundary === 'formal' && selectedFile.value && form.syncGraph) {
    try {
      await ElMessageBox.confirm('正式数据会按业务主键合并到 Neo4j。原始文件不会被覆盖，是否继续？', '同步正式图谱', { confirmButtonText: '确认上传并同步', cancelButtonText: '取消', type: 'warning' })
    } catch { return }
  }
  saving.value = true
  try {
    const result = editing.value === 'new'
      ? await insightService.createDataset(formData())
      : await insightService.updateDataset(editing.value!.id, formData())
    ElMessage.success(result.syncStatus === 'failed' ? '资产已保存，但图谱同步失败，请查看同步结果' : '资产与版本信息已保存')
    editing.value = null
    await load()
  } catch (reason: any) { ElMessage.error(reason.message || '保存失败，请稍后重试') } finally { saving.value = false }
}

async function sync(item: DatasetItem) {
  try {
    await ElMessageBox.confirm(`确认将“${item.name}”按当前版本同步到 Neo4j？`, '重新同步图谱', { confirmButtonText: '开始同步', cancelButtonText: '取消', type: 'warning' })
  } catch { return }
  saving.value = true
  try {
    const result = await insightService.syncDataset(item.id)
    if (result.syncStatus === 'failed') ElMessage.error(String(result.syncResult?.message || '图谱同步失败'))
    else ElMessage.success(String(result.syncResult?.message || '图谱同步完成'))
    await load()
  } catch (reason: any) { ElMessage.error(reason.message || '同步失败，请稍后重试') } finally { saving.value = false }
}

function syncLabel(item: DatasetItem) {
  return { synced: '已同步图谱', failed: '同步失败', not_requested: '未请求同步', registered: '已登记' }[item.syncStatus || 'registered'] || '待同步'
}

onMounted(load)
</script>

<template>
  <div class="stack-lg">
    <section class="data-boundary">
      <Database />
      <div><h2>数据资产登记</h2><p>统一管理来源、版本和图谱同步边界。</p></div>
      <button class="data-upload-btn" type="button" @click="openCreate"><Upload :size="17" />上传资产</button>
      <ShieldCheck />
    </section>
    <section class="admin-kpi-strip" aria-label="数据资产概览">
      <article><span>已登记资产</span><strong>{{ total }}</strong><small>全部已登记资产</small></article>
      <article><span>正式使用</span><strong>{{ formalCount }}</strong><small>当前页 · 可进入正式图谱</small></article>
      <article><span>仅供复核</span><strong>{{ reviewCount }}</strong><small>当前页 · 与正式层隔离</small></article>
      <article :class="{ attention: pendingSyncCount > 0 }"><span>同步待处理</span><strong>{{ pendingSyncCount }}</strong><small>{{ pendingSyncCount ? '当前页需要关注' : '当前页已清零' }}</small></article>
    </section>
    <UiState v-if="error" kind="error" title="资产列表读取失败" :description="error" action="重新加载" @action="load"/>
    <section class="panel">
      <header class="ui-panel-head"><div><h2>资产清单</h2><p class="ui-note">共 {{ total }} 项 · 搜索与边界筛选作用于当前页</p></div><div class="ui-toolbar"><label class="ui-search"><span class="sr-only">搜索当前页资产</span><input v-model="keyword" type="search" placeholder="搜索资产名称、版本"/></label><select v-model="boundary" class="ui-select" aria-label="筛选资产使用边界"><option value="all">全部边界</option><option value="formal">正式使用</option><option value="review">仅供复核</option></select></div></header>
      <UiState v-if="loading" kind="loading"/>
      <div v-else-if="filteredItems.length" class="ui-table-scroll" tabindex="0" aria-label="可横向滚动的资产清单"><table class="ui-table asset-table"><thead><tr><th scope="col">数据资产 / 层级</th><th scope="col" class="num">记录数</th><th scope="col">使用边界</th><th scope="col">版本与同步</th><th scope="col">操作</th></tr></thead><tbody><tr v-for="item in filteredItems" :key="item.id"><td class="asset-name"><strong>{{ item.name }}</strong><small>{{ item.category }}</small></td><td class="num">{{ item.records.toLocaleString() }}</td><td><span :class="['status-chip', item.boundary]">{{ item.boundary === 'formal' ? '正式使用' : '仅供复核' }}</span></td><td><span>{{ item.version }}</span><small><em :class="['sync-state',item.syncStatus]">{{ syncLabel(item) }}</em></small></td><td><div class="ui-toolbar"><button class="icon-btn" :aria-label="`修改 ${item.name} 并查看版本`" title="修改并查看版本" @click="openEdit(item)"><Pencil :size="16"/></button><button class="icon-btn" :aria-label="`同步 ${item.name} 到图谱`" title="同步到图谱" :disabled="saving" @click="sync(item)"><RefreshCw :size="16"/></button></div></td></tr></tbody></table></div>
      <UiState v-else title="没有符合条件的数据资产" description="调整筛选或上传一份新的数据资产。" :action="keyword || boundary !== 'all' ? '清除筛选' : '上传资产'" @action="keyword || boundary !== 'all' ? (keyword='',boundary='all') : openCreate()"/>
      <div class="data-list-status"><span>{{ total ? `${(page-1)*20+1}–${Math.min(page*20,total)} / ${total} 项` : '0 项资产' }}</span><el-pagination v-if="total > 20" v-model:current-page="page" :page-size="20" :total="total" layout="prev, pager, next" @current-change="load"/></div>
    </section>

    <el-drawer :before-close="confirmEditorClose" :model-value="Boolean(editing)" size="min(640px, 94vw)" title="数据资产编辑" :with-header="false" @close="editing = null">
      <div v-if="editing" class="dataset-editor">
        <header><div><h2>{{ editing === 'new' ? '上传数据资产' : '修改数据资产' }}</h2><p>新文件不会覆盖原文件，每次保存都会生成可追溯版本。</p></div><button class="icon-btn" aria-label="关闭资产编辑" title="关闭" @click="confirmEditorClose()"><X :size="18" /></button></header>
        <label><span>资产名称</span><input :aria-invalid="attempted && !form.name.trim()" :aria-describedby="attempted && !form.name.trim() ? 'asset-name-error' : undefined" v-model="form.name" placeholder="例如：证书技能关系_增量" name="name" autocomplete="off" /><small v-if="attempted && !form.name.trim()" id="asset-name-error" class="ui-field-error" role="alert">请填写资产名称</small></label>
        <div class="editor-columns"><label><span>数据层级</span><input v-model="form.category" placeholder="例如：02_关系" name="category" autocomplete="off" /></label><label><span>版本</span><input v-model="form.version" placeholder="留空自动生成" name="version" autocomplete="off" /></label></div>
        <label><span>使用边界</span><el-radio-group v-model="form.boundary" aria-label="资产使用边界"><el-radio-button value="review">仅供复核</el-radio-button><el-radio-button value="formal">正式使用</el-radio-button></el-radio-group></label>
        <label class="dataset-file-drop"><input aria-describedby="asset-file-help" ref="fileInput" type="file" accept=".csv,.json,.xlsx,.xls,.txt" @change="chooseFile" /><Upload :size="22" /><strong>{{ selectedFile?.name || (editing === 'new' ? '选择数据文件' : '选择新文件以创建修订版本') }}</strong><small id="asset-file-help">支持 CSV、JSON、Excel、TXT，最大 250 MB</small><small v-if="fileError" class="ui-field-error" role="alert">{{ fileError }}</small></label>
        <label class="sync-switch"><span><b>同步知识图谱</b><small>{{ form.boundary === 'formal' ? '识别受支持的节点/关系 CSV 并按业务主键合并' : '复核数据只登记资产元数据' }}</small></span><el-switch v-model="form.syncGraph" aria-label="同步知识图谱" /></label>
        <p v-if="editing !== 'new' && !revisions.length" class="ui-note">暂无修订记录。保存新文件或元数据后会生成可追溯版本。</p><section v-if="revisions.length" class="revision-history"><div><History :size="16" /><b>版本记录</b></div><article v-for="revision in revisions.slice(0, 5)" :key="revision.id"><span><strong>{{ revision.version }}</strong><small>{{ revision.fileName }} · {{ new Date(revision.createdAt).toLocaleString() }}</small></span><em :class="['sync-state', revision.syncStatus]">{{ revision.syncStatus === 'synced' ? '已同步' : revision.syncStatus === 'failed' ? '失败' : '已保存' }}</em></article></section>
        <footer><button class="secondary-btn" @click="confirmEditorClose()">取消</button><button class="primary-btn" :disabled="saving" @click="submit"><Upload :size="16" />{{ saving ? '正在保存…' : editing === 'new' ? '上传并登记' : '保存修订' }}</button></footer>
      </div>
    </el-drawer>
  </div>
</template>
