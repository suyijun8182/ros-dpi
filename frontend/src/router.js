import { createRouter, createWebHistory } from 'vue-router'
import { auth, checkSetup, setupState } from './api.js'

const routes = [
  { path: '/setup', name: 'setup', component: () => import('./views/Setup.vue'), meta: { public: true } },
  { path: '/login', name: 'login', component: () => import('./views/Login.vue'), meta: { public: true } },
  { path: '/', name: 'overview', component: () => import('./views/Overview.vue') },
  { path: '/hosts', name: 'hosts', component: () => import('./views/Hosts.vue') },
  { path: '/hosts/:hostKey', name: 'host', component: () => import('./views/HostDetail.vue'), props: true },
  { path: '/apps', name: 'apps', component: () => import('./views/Apps.vue') },
  { path: '/apps/:id', name: 'app', component: () => import('./views/AppDetail.vue'), props: true },
  { path: '/flow', name: 'flow', component: () => import('./views/Flow.vue') },
  { path: '/people', name: 'people', component: () => import('./views/People.vue') },
  { path: '/people/:id', name: 'person', component: () => import('./views/PersonDetail.vue'), props: true },
  { path: '/audit', name: 'audit', component: () => import('./views/Audit.vue') },
  { path: '/rules', name: 'rules', component: () => import('./views/Rules.vue') },
  { path: '/settings', name: 'settings', component: () => import('./views/Settings.vue') },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach(async to => {
  if (!setupState.checked) {
    try { await checkSetup() } catch (e) { /* 后端不可达时照常进入页面，由页面显示错误 */ }
  }
  if (!setupState.configured && to.name !== 'setup') return { name: 'setup' }
  if (setupState.configured && to.name === 'setup') return { name: 'login' }
  if (!to.meta.public && !auth.token) return { name: 'login', query: { next: to.fullPath } }
})

export default router
