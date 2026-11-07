<script setup lang="ts">
withDefaults(defineProps<{
  busy?: boolean
  online?: boolean
  message?: string
  mode?: 'career_planning' | 'ability_analysis'
  compact?: boolean
}>(), {
  busy: false,
  online: true,
  compact: false,
  mode: 'career_planning',
  message: '一起找到职业成长的下一步。',
})
</script>

<template>
  <div class="assistant-robot-scene"
    :class="{ 'is-compact': compact, 'is-busy': busy, 'is-offline': !online }"
    role="img"
    :aria-label="busy ? '职业助手查查正在整理信息' : online ? '职业助手查查' : '职业助手查查暂时离线'">
    <div v-if="!compact && message" class="robot-bubble">{{ message }}</div>
    <div class="robot-stage" aria-hidden="true">
      <svg class="robot-svg" viewBox="0 0 96 96" fill="none" focusable="false">
        <g class="robot-art" stroke-linecap="round" stroke-linejoin="round">
          <g class="robot-sprout">
            <path d="M48 28V18" stroke="#2b816f" stroke-width="3" />
            <path d="M48 20C36 21 30 15 31 7c10-1 18 3 17 13Z" fill="#a4dbb8" stroke="#2b816f" stroke-width="2" />
            <path d="M48 20C48 9 54 4 64 5c1 9-5 15-16 15Z" fill="#d1edb7" stroke="#2b816f" stroke-width="2" />
            <path d="m39 14 9 6 8-8" stroke="#2b816f" stroke-width="1.8" />
          </g>
          <rect x="7" y="43" width="11" height="22" rx="5.5" fill="#bde3d8" stroke="#2b816f" stroke-width="2" />
          <rect x="78" y="43" width="11" height="22" rx="5.5" fill="#bde3d8" stroke="#2b816f" stroke-width="2" />
          <path d="M34 25h28c14 0 21 8 21 22v14c0 12-6 19-16 21l-9 8-3-7H34c-14 0-21-8-21-22V47c0-14 7-22 21-22Z" fill="#e8f8f0" stroke="#2b816f" stroke-width="2.5" />
          <rect x="22" y="36" width="52" height="34" rx="14" fill="#155f55" />
          <g class="robot-eyes" fill="#d9f8e6">
            <rect class="robot-eye" x="33" y="45" width="6" height="10" rx="3" />
            <rect class="robot-eye" x="57" y="45" width="6" height="10" rx="3" />
          </g>
          <path class="robot-smile" d="M43 58c3 3 7 3 10 0" stroke="#b9e5d2" stroke-width="2.5" />
          <circle cx="27" cy="59" r="2" fill="#84c7ad" />
          <circle cx="69" cy="59" r="2" fill="#84c7ad" />
          <path d="M39 76h12" stroke="#93cdb8" stroke-width="2.5" />
        </g>
      </svg>
    </div>
  </div>
</template>

<style scoped>
.assistant-robot-scene { display: grid; justify-items: center; gap: 12px; width: 160px; color: #203b33; }
.robot-bubble { padding: 10px 14px; border: 1px solid #c8ded2; border-radius: 12px; background: #f5fcf7; font-size: 13px; line-height: 1.6; }
.robot-stage { width: 136px; height: 136px; }
.robot-svg { display: block; width: 100%; height: 100%; overflow: visible; }
.robot-art { transform-origin: 48px 56px; transition: transform 200ms ease; }
.is-compact { width: var(--assistant-size, 40px); height: var(--assistant-size, 40px); min-height: 0; gap: 0; flex-shrink: 0; }
.is-compact .robot-stage { width: 100%; height: 100%; }
.assistant-robot-scene:hover .robot-art { transform: rotate(-4deg) translateY(-1px); }
.is-busy .robot-eye { animation: assistant-thinking 900ms ease-in-out infinite alternate; }
.is-busy .robot-eye:last-child { animation-delay: 180ms; }
.is-offline { filter: saturate(.25); }
@keyframes assistant-thinking { to { opacity: .4; transform: translateY(2px); } }
@media (prefers-reduced-motion: reduce) {
  .robot-art, .robot-eye { transition: none; animation: none !important; }
  .assistant-robot-scene:hover .robot-art { transform: none; }
}
</style>
