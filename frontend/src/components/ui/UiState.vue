<script setup lang="ts">
import { CircleAlert, Inbox } from 'lucide-vue-next'
withDefaults(defineProps<{ kind?: 'loading' | 'error' | 'empty'; title?: string; description?: string; action?: string }>(), { kind: 'empty' })
defineEmits<{ action: [] }>()
</script>
<template><div class="ui-state" :class="`is-${kind}`" :role="kind === 'error' ? 'alert' : 'status'" :aria-busy="kind === 'loading' || undefined"><template v-if="kind === 'loading'"><span class="sr-only">正在加载数据</span><div class="ui-skeleton" aria-hidden="true"><i v-for="n in 4" :key="n"></i></div></template><template v-else><CircleAlert v-if="kind === 'error'" :size="24"/><Inbox v-else :size="24"/><strong>{{ title }}</strong><p v-if="description">{{ description }}</p><button v-if="action" class="secondary-btn" @click="$emit('action')">{{ action }}</button></template></div></template>
