<template>
  <div class="login-wrap">
    <form class="card login-card" @submit.prevent="submit">
      <div class="brand-line">
        <span class="brand-icon"><Sprout :size="20" /></span>
        <div class="brand-text">
          <h1 class="title">柑橘病虫害管理端</h1>
        </div>
      </div>

      <div class="field">
        <label class="form-label" for="login-username">账号</label>
        <input id="login-username" v-model="username" class="input" placeholder="请输入账号" autocomplete="username" />
      </div>
      <div class="field">
        <label class="form-label" for="login-password">密码</label>
        <input
          id="login-password"
          v-model="password"
          class="input"
          type="password"
          placeholder="请输入密码"
          autocomplete="current-password"
        />
      </div>

      <p v-if="error" class="err" role="alert">{{ error }}</p>

      <button class="btn btn-primary full" type="submit" :disabled="submitting" :aria-busy="submitting">
        {{ submitting ? '登录中…' : '登录' }}
      </button>

    </form>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Sprout } from 'lucide-vue-next'
import { useAuthStore } from '../stores/auth'
import { homeForRole, isSafeRedirect } from '../auth/capabilities'
import { errorMessage } from '../util/error'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const username = ref('')
const password = ref('')
const error = ref('')
const submitting = ref(false)

async function submit() {
  error.value = ''
  submitting.value = true
  try {
    await auth.login(username.value.trim(), password.value)
    const redirect = route.query.redirect
    const target = isSafeRedirect(redirect) ? redirect : homeForRole(auth.role)
    await router.push(target)
  } catch (e) {
    error.value = errorMessage(e)
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.login-wrap {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  background:
    radial-gradient(560px 380px at 85% 12%, rgba(217, 119, 6, 0.22), transparent 60%),
    linear-gradient(160deg, #0c241a 0%, #14532d 62%, #1b6b41 100%);
}
.login-card { width: 360px; max-width: 100%; padding: 30px 28px; }
.brand-line { display: flex; align-items: center; gap: 12px; margin-bottom: 24px; }
.brand-icon {
  width: 40px;
  height: 40px;
  flex-shrink: 0;
  border-radius: 11px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--primary-weak);
  color: var(--primary);
}
.brand-text { min-width: 0; }
.title { margin: 0; font-size: 19px; }
.full { width: 100%; min-height: 38px; margin-top: 4px; }
.err {
  color: var(--danger);
  font-size: 13px;
  margin: 0 0 12px;
  padding: 8px 10px;
  background: #fef2f2;
  border: 1px solid #f3c8c8;
  border-radius: 8px;
}
</style>
