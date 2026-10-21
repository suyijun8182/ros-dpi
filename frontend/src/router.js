import { createRouter, createWebHistory } from 'vue-router'
import { auth } from './api.js'

const routes = [
  { path: '/login', name: 'login', component: () => import('./views/Login.vue'), meta: { public: true } },
  { path: '/', name: 'overview', component: () => import('./views/Overview.vue') },
  { path: '/hosts', name: 'hosts', component: () => import('./views/Hosts.vue') },
  { path: '/hosts/:hostKey', name: 'host', component: () => import('./views/HostDetail.vue'), props: true },
  { path: '/apps', name: 'apps', component: () => import('./views/Apps.vue') },
  { path: '/apps/:id', name: 'app', component: () => import('./views/AppDetail.vue'), props: true },
  { path: '/flow', name: 'flow', component: () => import('./views/Flow.vue') },
  { path: '/rules', name: 'rules', component: () => import('./views/Rules.vue') },
  { path: '/settings', name: 'settings', component: () => import('./views/Settings.vue') },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach(to => {
  if (!to.meta.public && !auth.token) return { name: 'login', query: { next: to.fullPath } }
})

export default router
