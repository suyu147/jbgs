<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { CheckCircle2, Download, FileText, X, XCircle } from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import UiState from '@/components/ui/UiState.vue'
import { insightService } from '@/services/insightService'

const quality = ref<any>(null)
const health = ref<any>(null)
const error = ref('')
const loading = ref(true)
const reportOpen = ref(false)
const exporting = ref('')
const benchmark = computed(() => {
  const metrics = quality.value?.evaluation?.metrics
  if (!metrics) return []
  return [
    { name: 'JD 字段精确准确率', value: metrics.jdFields?.fieldExactAccuracy, threshold: metrics.thresholds?.jdFieldExact, passed: metrics.passed?.jdFieldExact },
    { name: '简历技能 F1', value: metrics.resumeExtraction?.f1, threshold: metrics.thresholds?.resumeSkillF1, passed: metrics.passed?.resumeSkillF1 },
    { name: '全库检索 Top-1', value: metrics.matching?.top1Accuracy, threshold: metrics.thresholds?.matchingTop1, passed: metrics.passed?.matchingTop1 },
    { name: '全库检索 Top-3', value: metrics.matching?.top3Accuracy, threshold: null, passed: true },
    { name: '扫描简历技能 F1', value: quality.value?.ocrEvaluation?.resumeSkillExtraction?.f1, threshold: quality.value?.ocrEvaluation?.thresholds?.resumeSkillF1, passed: quality.value?.ocrEvaluation?.passed },
    { name: '后端测试覆盖率', value: quality.value?.coverage?.coverage, threshold: quality.value?.coverage?.threshold, passed: quality.value?.coverage?.passed },
  ]
})

async function exportReport(format: 'pdf' | 'csv' | 'json') {
  exporting.value = format
  try {
    const blob = await insightService.downloadQualityReport(format)
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `职能洞察-质量验收报告.${format}`
    anchor.click()
    URL.revokeObjectURL(url)
    ElMessage.success(`质量报告 ${format.toUpperCase()} 已导出`)
  } catch (reason: any) {
    ElMessage.error(reason.message || '报告导出失败')
  } finally { exporting.value = '' }
}

function formatTime(value: string) {
  return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '--'
}

async function load() {
  loading.value = true; error.value = ''
  try {
    ;[quality.value, health.value] = await Promise.all([insightService.getQuality(), insightService.health()])
  } catch (reason: any) {
    error.value = reason.message
  } finally { loading.value = false }
}
onMounted(load)
</script>

<template>
  <div class="stack-lg">
    <UiState v-if="error" kind="error" title="质量数据读取失败" :description="error" action="重新加载" @action="load"/><UiState v-if="loading && !quality" kind="loading"/>
    <section v-if="quality" class="quality-overview-strip"><div class="quality-score-value"><strong>{{ quality.score }}</strong><div><h2>数据与图谱质量得分</h2><p>{{ quality.checks.filter((item: any) => item.passed).length }} / {{ quality.checks.length }} 项规则通过 · 更新于 {{ formatTime(quality.generatedAt) }}</p></div></div><div class="quality-services"><div><span>MySQL / Neo4j</span><span :class="['status-chip',health?.mysql && health?.neo4j ? 'approved' : 'failed']">{{ health?.mysql && health?.neo4j ? '数据服务在线' : '连接需检查' }}</span></div><div><span>外部智能体</span><span class="status-chip">{{ health?.agentConfigured ? '已接入' : '未接入 · 规则降级' }}</span></div></div></section>
    <section v-if="quality" class="ui-callout"><p>待复核 {{ quality.pendingReviews }} 项。批准生成版本后，仍需核验质量并单独发布。</p><RouterLink to="/admin/reviews" class="secondary-btn">前往复核与发布</RouterLink></section>
    <section v-if="benchmark.length" class="panel metric-panel">
      <div class="panel-head"><div><h2>算法与测试指标</h2></div><div class="report-toolbar"><button class="secondary-btn" @click="reportOpen = true"><FileText :size="16" />查看报告</button><el-dropdown trigger="click" @command="exportReport"><button class="primary-btn" :disabled="Boolean(exporting)"><Download :size="16" />{{ exporting ? '正在导出' : '导出报告' }}</button><template #dropdown><el-dropdown-menu><el-dropdown-item command="pdf">PDF 完整报告</el-dropdown-item><el-dropdown-item command="csv">CSV 指标明细</el-dropdown-item><el-dropdown-item command="json">JSON 原始结果</el-dropdown-item></el-dropdown-menu></template></el-dropdown><em :class="['status-chip', quality.evaluation.passed && quality.coverage?.passed && quality.ocrEvaluation?.passed ? 'approved' : 'pending']">{{ quality.evaluation.passed && quality.coverage?.passed && quality.ocrEvaluation?.passed ? '全部通过' : '存在未达标项' }}</em></div></div>
      <div class="metric-list">
        <article v-for="item in benchmark" :key="item.name" :class="{ failed: !item.passed }">
          <CheckCircle2 v-if="item.passed" /><XCircle v-else />
          <div><strong>{{ item.name }}</strong><small v-if="item.threshold">验收线 {{ item.threshold }}%</small><small v-else>报告项</small></div>
          <b>{{ item.value == null ? '—' : `${item.value.toFixed(2)}%` }}</b>
        </article>
      </div>
      <p v-if="!quality.evaluation.passed" class="warning-inline">JD 标签差异未达到验收线，需双人复核后再发布。</p>
    </section>
    <section v-if="quality" class="panel rule-panel">
      <div class="panel-head"><div><h2>当前质量规则</h2></div><em :class="['status-chip', quality.status === 'failed' ? 'failed' : quality.status === 'pass_with_reviews' ? 'pending' : 'approved']">{{ quality.status === 'failed' ? '未通过' : quality.status === 'passed' ? '通过' : quality.status === 'pass_with_reviews' ? '规则通过 · 待人工复核' : '待核验' }}</em></div>
      <div class="rule-list"><div v-for="rule in quality.rules" :key="rule"><CheckCircle2 /><strong>{{ rule }}</strong><span>已启用</span></div></div>
    </section>
    <el-drawer v-model="reportOpen" size="min(760px, 94vw)" title="数据质量与验收报告" :with-header="false">
      <div v-if="quality" class="quality-report">
        <header><div><h2>数据质量与验收报告</h2><p>生成于 {{ formatTime(quality.generatedAt) }} · 评测版本 {{ quality.evaluation?.id || '未登记' }}</p></div><button class="icon-btn" aria-label="关闭质量报告" title="关闭报告" @click="reportOpen = false"><X :size="18" /></button></header>
        <section class="report-score"><div><strong>{{ quality.score }}</strong><span>综合质量得分</span></div><em :class="['status-chip', quality.status === 'failed' ? 'pending' : 'approved']">{{ quality.status === 'failed' ? '未通过' : quality.status === 'passed' ? '通过' : quality.status === 'pass_with_reviews' ? '规则通过 · 待人工复核' : '待核验' }}</em></section>
        <section><div class="report-section-head"><div><h3>算法与测试指标</h3></div><small>{{ quality.evaluation?.suite }}</small></div><div class="report-benchmarks"><div v-for="item in benchmark" :key="item.name"><span :class="item.passed ? 'pass-mark' : 'fail-mark'">{{ item.passed ? '通过' : '未通过' }}</span><strong>{{ item.name }}</strong><b>{{ item.value == null ? '—' : `${item.value.toFixed(2)}%` }}</b><small>{{ item.threshold ? `验收线 ${item.threshold}%` : '报告项' }}</small></div></div></section>
        <section><div class="report-section-head"><div><h3>质量规则</h3></div><small>{{ quality.checks.filter((item: any) => item.passed).length }} / {{ quality.checks.length }} 通过</small></div><div class="report-checks"><div v-for="check in quality.checks" :key="check.name"><CheckCircle2 v-if="check.passed"/><XCircle v-else/><span>{{ check.name }}</span><b>{{ check.passed ? '通过' : '未通过' }}</b></div></div></section>
        <section><div class="report-section-head"><div><h3>图谱与数据状态</h3></div></div><dl class="report-facts"><div><dt>图谱节点</dt><dd>{{ quality.graph.nodeCount.toLocaleString() }}</dd></div><div><dt>图谱关系</dt><dd>{{ quality.graph.relationCount.toLocaleString() }}</dd></div><div><dt>待人工复核</dt><dd>{{ quality.pendingReviews }}</dd></div><div><dt>复核数据集</dt><dd>{{ quality.reviewDatasets }}</dd></div><div><dt>迁移校验</dt><dd>{{ quality.migration?.status || '未生成' }}</dd></div><div><dt>测试覆盖率</dt><dd>{{ quality.coverage?.coverage?.toFixed(2) || '--' }}%</dd></div></dl></section>
        <p class="report-boundary">报告基于当前本地 MySQL、Neo4j 图谱、迁移校验、金标评测与覆盖率文件生成。待复核候选不会自动进入正式图谱；部分年度样本不足时不作趋势强结论。</p>
        <footer><button class="secondary-btn" @click="exportReport('json')"><Download :size="16" />JSON</button><button class="secondary-btn" @click="exportReport('csv')"><Download :size="16" />CSV</button><button class="primary-btn" @click="exportReport('pdf')"><Download :size="16" />导出 PDF 报告</button></footer>
      </div>
    </el-drawer>
  </div>
</template>
