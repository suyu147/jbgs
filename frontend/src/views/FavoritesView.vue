<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowRight, BriefcaseBusiness, Star } from 'lucide-vue-next'
import { useFavoritesStore } from '@/stores/favorites'
import { jobVisualTone } from '@/utils/jobVisualTone'

const router = useRouter()
const favorites = useFavoritesStore()

onMounted(() => favorites.load(true))

async function remove(roleId: string, roleName: string, field: string) {
  try {
    await favorites.toggle({ id: roleId, name: roleName, field })
    ElMessage.success('已取消收藏')
  } catch (reason: any) { ElMessage.error(reason?.message || '取消收藏失败') }
}

function formatDate(value: string) {
  if (!value) return '收藏时间未知'
  return `${new Intl.DateTimeFormat('zh-CN', { year:'numeric', month:'2-digit', day:'2-digit' }).format(new Date(value))} 收藏`
}
</script>

<template>
  <section class="favorite-page">
    <header class="favorite-summary"><div><h2>已收藏 {{ favorites.items.length }} 个岗位</h2><p>收藏只属于当前账号，进入岗位档案可继续查看能力图谱、演化趋势和能力诊断。</p></div><Star :size="26" fill="currentColor" /></header>
    <div v-if="favorites.loading && !favorites.loaded" class="favorite-skeleton"><i v-for="item in 4" :key="item"></i></div>
    <div v-else-if="favorites.items.length" class="favorite-list">
      <article v-for="item in favorites.items" :key="item.roleId" :data-job-tone="jobVisualTone(item.field, item.roleName)">
        <button class="favorite-open" @click="router.push(`/jobs/${item.roleId}`)">
          <span><BriefcaseBusiness :size="19" /></span>
          <div><small>{{ item.field || '岗位类别待完善' }}</small><h3>{{ item.roleName }}</h3><p>{{ formatDate(item.createdAt) }}</p></div>
          <ArrowRight :size="18" />
        </button>
        <button class="favorite-remove active" :aria-label="`取消收藏${item.roleName}`" title="取消收藏" @click="remove(item.roleId,item.roleName,item.field)"><Star :size="18" fill="currentColor" /></button>
      </article>
    </div>
    <div v-else class="favorite-empty"><Star :size="42" /><h2>暂时没有收藏岗位</h2><p>在岗位库或岗位详情中点击五角星，即可在这里集中查看。</p><button class="primary-btn" @click="router.push('/jobs')">前往岗位库<ArrowRight :size="16" /></button></div>
  </section>
</template>
