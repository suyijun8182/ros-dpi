import { createRouter, createWebHistory } from 'vue-router'
import http, { auth, checkSetup, setupState } from './api.js'
import { loadSites, pickSite, siteState } from './site.js'

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
  { path: '/sites', name: 'sites', component: () => import('./views/Sites.vue') },
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
  if (to.meta.public) return
  // 多站点（0.7.0）：地址里保持 ?site=，换页时带上；“全部”是单独的总览页 /sites
  if (!siteState.loaded) {
    try { await loadSites(http) } catch (e) { /* 拿不到站点列表时按单站点显示 */ }
  }
  if (!siteState.multi) {
    if (to.name === 'sites') return { path: '/' }
    if (to.query.site) { const q = { ...to.query }; delete q.site; return { path: to.path, query: q, hash: to.hash, replace: true } }
    return
  }
  if (to.query.site === 'all') return { name: 'sites' }
  if (to.name === 'sites') return
  const slug = pickSite(to.query.site)
  if (slug && to.query.site !== slug) return { path: to.path, query: { ...to.query, site: slug }, hash: to.hash, replace: true }
})

export default router
