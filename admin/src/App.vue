<template>
  <router-view />
  <Toasts />
</template>

<script setup lang="ts">
import { watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Toasts from './components/Toasts.vue'
import { useAuthStore } from './stores/auth'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

// Terminal session rejection must leave the protected screen immediately;
// a navigation guard alone only runs on the next navigation.
watch(() => auth.account, (account, previous) => {
  if (previous && !account && !route.meta.public) {
    void router.replace({ path: '/login', query: { redirect: route.fullPath } })
  }
})
</script>
