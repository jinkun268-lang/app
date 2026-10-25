<template>
  <div class="page center">
    <div class="card box">
      <h2>无权限</h2>
      <p class="muted">当前账号无权访问该页面。</p>
      <button class="btn btn-primary" @click="$router.push('/')">返回首页</button>
    </div>
  </div>
</template>

<style scoped>
.center { display: flex; align-items: center; justify-content: center; height: 100%; }
.box { padding: 32px; text-align: center; }
</style>
