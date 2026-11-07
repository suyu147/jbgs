import { onBeforeUnmount, onMounted, type Ref } from 'vue'
import { onBeforeRouteLeave, useRoute } from 'vue-router'

/** Keep form work intact without persisting candidate/contact data to storage. */
export function useBusinessUnsaved(dirty: Readonly<Ref<boolean>>) {
  const route = useRoute(), sourcePath = route.path
  function beforeUnload(event: BeforeUnloadEvent) {
    if (route.path === sourcePath && dirty.value) { event.preventDefault(); event.returnValue = '' }
  }
  onBeforeRouteLeave(() => !dirty.value || window.confirm('有尚未提交的修改，确认离开并放弃这些内容？'))
  onMounted(() => window.addEventListener('beforeunload', beforeUnload))
  onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload))
}
