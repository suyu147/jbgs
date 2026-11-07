<script setup lang="ts">
import logo from '@/assets/brand/career-intelligence-logo.png'
import symbol from '@/assets/brand/career-intelligence-symbol.png'

withDefaults(defineProps<{ compact?: boolean }>(), { compact: false })
</script>

<template>
  <span class="career-brand-logo" :class="{ 'is-compact': compact }">
    <img class="career-brand-full" :src="logo" width="2083" height="673" alt="职能洞察 · CAREER INTELLIGENCE" decoding="async" draggable="false">
    <img class="career-brand-symbol" :src="symbol" alt="职能洞察" decoding="async" draggable="false">
  </span>
</template>

<style scoped>
.career-brand-logo { display: block; width: var(--brand-logo-width, 196px); max-width: 100%; flex-shrink: 0; line-height: 0; }
.career-brand-logo img { display: block; width: 100%; height: auto; object-fit: contain; }
.career-brand-logo .career-brand-symbol { display: none; }
.career-brand-logo.is-compact { width: 40px; }
.career-brand-logo.is-compact .career-brand-full { display: none; }
.career-brand-logo.is-compact .career-brand-symbol { display: block; height: 40px; }
@media (max-width: 1100px) {
  .career-brand-logo.is-compact { width: var(--brand-logo-width, 196px); }
  .career-brand-logo.is-compact .career-brand-full { display: block; }
  .career-brand-logo.is-compact .career-brand-symbol { display: none; }
}
</style>
