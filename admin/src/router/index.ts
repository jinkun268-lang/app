import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { COLLECTION_ROLES, REVIEW_ROLES, TRAINING_ROLES, homeForRole } from '../auth/capabilities'
import type { Role } from '../types'

const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('../views/LoginView.vue'),
    meta: { public: true },
  },
  {
    path: '/',
    component: () => import('../layout/AppLayout.vue'),
    children: [
      { path: '', redirect: '/samples' },
      { path: 'samples', name: 'samples', component: () => import('../views/SamplesView.vue'), meta: { title: '采集记录', workspace: 'collection', roles: COLLECTION_ROLES } },
      { path: 'samples/:id', name: 'sample-detail', component: () => import('../views/SamplesView.vue'), meta: { title: '采集详情', workspace: 'collection', roles: COLLECTION_ROLES } },
      { path: 'reviews', name: 'reviews', component: () => import('../views/SamplesView.vue'), meta: { title: '样本核验', workspace: 'review', roles: REVIEW_ROLES } },
      { path: 'reviews/:id', name: 'review-detail', component: () => import('../views/SamplesView.vue'), meta: { title: '样本核验', workspace: 'review', roles: REVIEW_ROLES } },
      { path: 'training/quality', name: 'quality', component: () => import('../views/SamplesView.vue'), meta: { title: '质量检查', workspace: 'quality', roles: TRAINING_ROLES } },
      { path: 'training/quality/:id', name: 'quality-detail', component: () => import('../views/SamplesView.vue'), meta: { title: '质量检查', workspace: 'quality', roles: TRAINING_ROLES } },
      { path: 'exports', name: 'exports', component: () => import('../views/ExportsView.vue'), meta: { title: '数据导出', roles: TRAINING_ROLES } },
      { path: 'batches', name: 'batches', component: () => import('../views/BatchesView.vue'), meta: { title: '采集批次', roles: COLLECTION_ROLES } },
      { path: 'questions', name: 'questions', component: () => import('../views/QuestionsView.vue'), meta: { title: '专家咨询', roles: REVIEW_ROLES } },
      { path: 'tickets', name: 'tickets', component: () => import('../views/KnowledgeReviewView.vue'), meta: { title: '专家工单', roles: ['expert', 'super_admin'] as Role[] } },
      { path: 'settings/dictionaries', name: 'dictionaries', component: () => import('../views/DictionariesView.vue'), meta: { title: '基础字典', roles: ['super_admin'] as Role[] } },
      { path: 'settings/users', name: 'users', component: () => import('../views/UsersView.vue'), meta: { title: '账号管理', roles: ['super_admin'] as Role[] } },
      { path: 'settings/audit', name: 'audit', component: () => import('../views/AuditView.vue'), meta: { title: '审计', roles: ['super_admin'] as Role[] } },
      { path: 'no-permission', name: 'no-permission', component: () => import('../views/NoPermissionView.vue'), meta: { title: '无权限' } },
    ],
  },
  { path: '/:pathMatch(.*)*', name: 'not-found', component: () => import('../views/NotFoundView.vue') },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.initialized) await auth.init()

  if (to.meta.public) {
    if (auth.isAuthed && to.name === 'login') return homeForRole(auth.role)
    return true
  }
  if (!auth.isAuthed) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  const roles = to.meta.roles as Role[] | undefined
  if (roles && auth.role && !roles.includes(auth.role)) {
    return { path: '/no-permission' }
  }
  return true
})

export default router
