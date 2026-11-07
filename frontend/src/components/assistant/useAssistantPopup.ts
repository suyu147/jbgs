import { computed, type Ref } from 'vue'
import { useWindowSize } from '@vueuse/core'

/** Keep a draggable assistant's panel inside the viewport at every anchor position. */
export function useAssistantPopup(
  launcher: Ref<HTMLElement | null>,
  position: Ref<{ left: number; top: number } | null>,
  preferredWidth = 360,
) {
  const { width, height } = useWindowSize()
  return computed(() => {
    const anchor = position.value || launcher.value?.getBoundingClientRect() || { left: width.value - 80, top: height.value - 84 }
    const anchorWidth = launcher.value?.offsetWidth || 60
    const anchorHeight = launcher.value?.offsetHeight || 60
    const panelWidth = Math.min(preferredWidth, width.value - 32)
    const left = Math.max(16, Math.min(width.value - panelWidth - 16, anchor.left + anchorWidth - panelWidth))
    const below = anchor.top < height.value / 2
    const available = below ? height.value - anchor.top - anchorHeight - 24 : anchor.top - 24
    return {
      left: `${left - anchor.left}px`, right: 'auto',
      top: below ? 'calc(100% + 12px)' : 'auto',
      bottom: below ? 'auto' : 'calc(100% + 12px)',
      maxHeight: `${Math.max(80, available)}px`,
    }
  })
}
