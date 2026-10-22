<template>
  <router-view v-if="$route.meta.public" />
  <div v-else class="shell" :class="{ mini: ui.side === 'mini', drawer }">
    <!-- 顶栏：logo 区与侧边栏同宽，然后是折叠按钮、面包屑、搜索、工具按钮 -->
    <header class="top">
      <router-link to="/" class="brand" :aria-label="'ROS-DPI'"><Logo /></router-link>
      <button class="btn ghost icon" @click="toggleSide" :aria-label="t('shell.toggleMenu')" :title="t('shell.toggleMenu')"><Icon name="menu" /></button>
      <nav class="crumb" aria-label="breadcrumb">
        <span class="faint">ROS-DPI</span>
        <template v-for="c in crumbs" :key="c.label"><Icon name="chevron" :size="14" class="faint" />
          <router-link v-if="c.to" :to="c.to">{{ c.label }}</router-link><b v-else>{{ c.label }}</b></template>
      </nav>
      <span class="sp" />
      <SearchBox class="search" :pages="pages" />
      <div class="tools">
        <button class="btn ghost icon" @click="toggleTheme" :aria-label="t('common.theme')" :title="t('common.theme')"><Icon :name="ui.theme === 'dark' ? 'sun' : 'moon'" /></button>
        <button class="btn ghost icon" @click="setLang(locale === 'zh' ? 'en' : 'zh')" :title="t('common.lang')" :aria-label="t('common.lang')"><Icon name="lang" /></button>
        <span class="user">{{ auth.username || 'admin' }}<span v-if="auth.role === 'user'" class="pill grey role">{{ t('users.roles.user') }}</span></span>
        <button class="btn ghost icon" @click="logout" :aria-label="t('nav.logout')" :title="t('nav.logout')"><Icon name="logout" /></button>
      </div>
    </header>

    <div class="scrim" v-if="drawer" @click="drawer = false" />
    <aside class="side" :aria-label="t('shell.menu')">
      <nav class="nav">
        <router-link v-for="n in nav" :key="n.to" :to="n.to" :class="{ on: isOn(n) }" :title="ui.side === 'mini' ? t(n.label) : null" @click="drawer = false">
          <Icon :name="n.icon" :size="19" /><span>{{ t(n.label) }}</span>
        </router-link>
      </nav>
      <div class="side-foot"><span class="dot" :class="status" /><span>v{{ version }}</span></div>
    </aside>

    <main class="main">
      <div class="page"><router-view /></div>
      <footer class="foot">ROS-DPI v{{ version }} · {{ t('app.subtitle') }} ·
        <a href="https://github.com/suyijun8182/ros-dpi" target="_blank" rel="noopener">GitHub</a></footer>
    </main>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import http, { auth, setAuth } from './api.js'
import Icon from './components/Icon.vue'
import Logo from './components/Logo.vue'
import SearchBox from './components/SearchBox.vue'
import { setLang } from './i18n/index.js'
import { toggleTheme, ui } from './state.js'

const { t, locale } = useI18n()
const route = useRoute()
const router = useRouter()
const drawer = ref(false)
const version = ref('')
const status = ref('')

const nav = [
  { to: '/', label: 'nav.overview', icon: 'overview' },
  { to: '/hosts', label: 'nav.hosts', icon: 'hosts' },
  { to: '/apps', label: 'nav.apps', icon: 'apps' },
  { to: '/flow', label: 'nav.flow', icon: 'flow' },
  { to: '/audit', label: 'nav.audit', icon: 'audit' },
  { to: '/rules', label: 'nav.rules', icon: 'rules' },
  { to: '/settings', label: 'nav.settings', icon: 'settings' },
]
const pages = computed(() => nav.map(n => ({ to: n.to, label: t(n.label) })))
const isOn = n => (n.to === '/' ? route.path === '/' : route.path.startsWith(n.to))

// 面包屑：一级页面 + 详情页
const crumbs = computed(() => {
  const top = nav.find(isOn)
  if (!top) return []
  const out = [{ label: t(top.label), to: route.path === top.to ? null : top.to }]
  if (route.name === 'host') out.push({ label: t('shell.hostDetail') })
  if (route.name === 'app') out.push({ label: t('shell.appDetail') })
  return out
})

// 窄屏：折叠按钮打开抽屉；宽屏：在完整 / 只有图标之间切换
function toggleSide() {
  if (window.matchMedia('(max-width: 860px)').matches) drawer.value = !drawer.value
  else ui.side = ui.side === 'mini' ? 'full' : 'mini'
}
watch(() => route.fullPath, () => (drawer.value = false))

// 登录后、进入管理页面时再读版本和采集状态（App 在登录页也会挂载，那时还没有令牌）
async function loadInfo() {
  try {
    version.value = (await http.get('/health')).version
    auth.role = (await http.get('/auth/me')).role || ''  // 管理员可能改了你的角色
    try { localStorage.setItem('rosdpi.role', auth.role) } catch (e) { /* ignore */ }
    status.value = (await http.get('/system')).collector.flow_ok ? 'on' : 'warn'
  } catch (e) { /* 只影响侧边栏底部的小字 */ }
}
watch(() => !route.meta.public && !!auth.token && route.name, ok => { if (ok && !version.value) loadInfo() }, { immediate: true })

function logout() {
  setAuth('')
  router.push('/login')
}
</script>

<style scoped>
.user .role { margin-left: 6px; height: 20px; font-size: 11px; }
.shell { min-height: 100vh; }
.top {
  position: sticky; top: 0; z-index: 30; height: var(--top); display: flex; align-items: center; gap: 10px;
  background: var(--panel); border-bottom: 1px solid var(--line); padding: 0 16px 0 0;
}
.brand { width: var(--side); flex: none; display: flex; align-items: center; padding-left: 18px; }
.mini .brand { width: 64px; padding-left: 12px; overflow: hidden; }
.mini .brand :deep(.wm) { display: none; }
.icon { width: 36px; height: 36px; padding: 0; border-radius: 10px; }
.crumb { display: flex; align-items: center; gap: 6px; font-size: 14px; white-space: nowrap; min-width: 0; overflow: hidden; }
.crumb a:hover { color: var(--brand-ink); }
.crumb b { font-weight: 600; }
.sp { flex: 1; }
.tools { display: flex; align-items: center; gap: 2px; flex: none; }
.user { font-size: 13.5px; color: var(--muted); padding: 0 6px 0 8px; border-left: 1px solid var(--line); margin-left: 6px; }

.side {
  position: fixed; top: var(--top); bottom: 0; left: 0; width: var(--side); background: var(--panel);
  display: flex; flex-direction: column; padding: 14px 12px; z-index: 20; border-right: 1px solid var(--line);
}
.mini .side { width: 64px; padding: 14px 8px; }
.nav { display: flex; flex-direction: column; gap: 4px; }
.nav a {
  display: flex; align-items: center; gap: 12px; height: 44px; padding: 0 14px; border-radius: 10px;
  color: var(--ink); font-weight: 500; white-space: nowrap; position: relative;
}
.nav a :deep(svg) { color: var(--muted); flex: none; }
.nav a:hover { background: var(--sunk); }
/* 选中：淡紫底 + 钢蓝字，左侧一道竖线 */
.nav a.on { background: var(--brand-weak); color: var(--brand-ink); }
.nav a.on :deep(svg) { color: var(--brand-ink); }
.nav a.on::before { content: ""; position: absolute; left: -12px; top: 10px; bottom: 10px; width: 3px; border-radius: 0 3px 3px 0; background: var(--brand-ink); }
.mini .nav a { justify-content: center; padding: 0; }
.mini .nav a span { display: none; }
.mini .nav a.on::before { left: -8px; }
.side-foot { margin-top: auto; display: flex; align-items: center; gap: 8px; font: 500 12px/1 var(--cond); color: var(--faint); padding: 0 14px; }
.mini .side-foot { justify-content: center; padding: 0; }
.mini .side-foot span:last-child { display: none; }

.main { margin-left: var(--side); padding: 16px 18px 12px; min-width: 0; }
.mini .main { margin-left: 64px; }
.foot { text-align: center; color: var(--faint); font-size: 12.5px; padding: 22px 0 6px; }
.foot a:hover { color: var(--brand-ink); }
.scrim { display: none; }

@media (max-width: 860px) {
  .top { flex-wrap: wrap; height: auto; padding: 8px 12px; gap: 8px; }
  .brand, .mini .brand { width: auto; padding-left: 0; }
  .mini .brand :deep(.wm) { display: grid; }
  .crumb { display: none; }
  .search { order: 5; flex-basis: 100%; }
  .user { display: none; }
  .side, .mini .side { width: 240px; padding: 14px 12px; transform: translateX(-100%); transition: transform .2s ease; top: 0; z-index: 40; }
  .mini .nav a { justify-content: flex-start; padding: 0 14px; }
  .mini .nav a span { display: inline; }
  .drawer .side { transform: none; box-shadow: 8px 0 30px rgba(0, 0, 0, .18); }
  .scrim { display: block; position: fixed; inset: 0; background: rgba(10, 15, 25, .35); z-index: 35; }
  .main, .mini .main { margin-left: 0; padding: 12px 12px 10px; }
}
</style>
