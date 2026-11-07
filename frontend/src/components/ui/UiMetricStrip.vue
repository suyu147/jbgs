<script setup lang="ts">
defineProps<{ items: Array<{ label: string; value: number | string | null | undefined; unit?: string; note?: string; attention?: boolean }>; loading?: boolean }>()
</script>
<template><section class="ui-metrics" aria-label="关键指标" :aria-busy="loading || undefined"><article v-for="item in items" :key="item.label" :class="{ 'needs-attention': item.attention }"><span>{{ item.label }}</span><strong v-if="!loading">{{ item.value == null ? '—' : typeof item.value === 'number' ? item.value.toLocaleString('zh-CN') : item.value }}<small v-if="item.value != null">{{ item.unit }}</small></strong><i v-else class="ui-value-skeleton"></i><p>{{ item.note }}</p></article></section></template>
