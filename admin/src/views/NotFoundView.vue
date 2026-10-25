<template>
  <div class="page center">
    <div class="card box">
      <h2>404</h2>
      <p class="muted">页面不存在。</p>
      <button class="btn btn-primary" @click="$router.push('/')">返回首页</button>
    </div>
  </div>
</template>

<style scoped>
.center { display: flex; align-items: center; justify-content: center; height: 100%; }
.box { padding: 32px; text-align: center; }
</style>
