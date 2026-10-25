import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import { useAuthStore } from './stores/auth'
import './styles.css'

async function bootstrap() {
  const app = createApp(App)
  const pinia = createPinia()
  app.use(pinia)

  // 先恢复会话再决策路由：刷新令牌存在时刷新并拉 /me，失败清会话。
  const auth = useAuthStore()
  await auth.init()

  app.use(router)
  await router.isReady()
  app.mount('#app')
}

void bootstrap()
