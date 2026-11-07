import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import App from './App.vue'
import router from './router'
import './styles/index.css'
import './styles/design-system.css'
import './styles/workspace-atmosphere.css'
import './styles/business-ui.css'
import './styles/brand.css'
import './styles/content-accents.css'
import './styles/governance-dashboard.css'
import './styles/home-skill-radar.css'

// Vite emits this event when a browser keeps an old dynamically imported
// module after a frontend update. Retry once with a clean document instead of
// leaving the user on a blank route; the guard prevents an infinite reload.
window.addEventListener('vite:preloadError', event => {
  event.preventDefault()
  const reloadKey = 'ci-vite-module-reload'
  if (!sessionStorage.getItem(reloadKey)) {
    sessionStorage.setItem(reloadKey, '1')
    window.location.reload()
  } else {
    sessionStorage.removeItem(reloadKey)
  }
})

createApp(App).use(createPinia()).use(router).use(ElementPlus).mount('#app')
