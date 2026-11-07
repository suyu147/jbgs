<script setup lang="ts">
import { watch } from 'vue'
import { useRoute } from 'vue-router'
import AppShell from '@/components/layout/AppShell.vue'
import AdminShell from '@/components/layout/AdminShell.vue'
import EnterpriseShell from '@/components/layout/EnterpriseShell.vue'
import { useAuthStore } from '@/stores/auth'
import { useWorkspaceStore } from '@/stores/workspace'

const route = useRoute(); const auth = useAuthStore(); const workspace = useWorkspaceStore()
watch(()=>auth.user?.id,id=>{if(id)workspace.hydrate(id)},{immediate:true})
</script>

<template><router-view v-if="route.path==='/login' || route.meta.layout==='auth'"/><AdminShell v-else-if="route.meta.portal==='admin'"/><EnterpriseShell v-else-if="route.meta.portal==='enterprise'"/><AppShell v-else/></template>
