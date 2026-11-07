import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import type { FavoriteJob, JobSummary } from '@/types/domain'
import { insightService } from '@/services/insightService'
import { readAuthSession } from '@/stores/auth'

const PREVIEW_KEY = 'ci_preview_favorite_jobs'

export const useFavoritesStore = defineStore('favorites', () => {
  const items = ref<FavoriteJob[]>([])
  const loading = ref(false)
  const loaded = ref(false)
  const ownerId = ref('')
  const ids = computed(() => new Set(items.value.map(item => item.roleId)))

  function previewItems() {
    try { return JSON.parse(localStorage.getItem(PREVIEW_KEY) || '[]') as FavoriteJob[] }
    catch { return [] }
  }

  async function load(force = false) {
    const session = readAuthSession()
    const currentOwner = session?.user.id || ''
    if (ownerId.value !== currentOwner) {
      items.value = []
      loaded.value = false
      ownerId.value = currentOwner
    }
    if ((loaded.value && !force) || loading.value) return
    loading.value = true
    try {
      items.value = insightService.isProductPreview() ? previewItems() : (await insightService.getFavoriteJobs(500)).items
      loaded.value = true
    } finally { loading.value = false }
  }

  function isFavorite(roleId: string) { return ids.value.has(roleId) }

  async function toggle(job: Pick<JobSummary, 'id' | 'name' | 'field'>) {
    const previous = [...items.value]
    if (isFavorite(job.id)) {
      items.value = items.value.filter(item => item.roleId !== job.id)
      try {
        if (insightService.isProductPreview()) localStorage.setItem(PREVIEW_KEY, JSON.stringify(items.value))
        else await insightService.deleteFavoriteJob(job.id)
      } catch (error) {
        items.value = previous
        throw error
      }
      return false
    }
    try {
      const saved = insightService.isProductPreview()
        ? { id: `preview-${job.id}`, roleId: job.id, roleName: job.name, field: job.field, createdAt: new Date().toISOString() }
        : await insightService.saveFavoriteJob(job.id)
      items.value = [saved, ...items.value.filter(item => item.roleId !== job.id)]
      if (insightService.isProductPreview()) localStorage.setItem(PREVIEW_KEY, JSON.stringify(items.value))
      return true
    } catch (error) {
      items.value = previous
      throw error
    }
  }

  return { items, loading, loaded, ids, load, isFavorite, toggle }
})
