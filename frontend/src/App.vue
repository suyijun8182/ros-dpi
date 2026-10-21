<template>
  <router-view v-if="$route.meta.public" />
  <div v-else class="shell">
    <header class="top">
      <div class="top-in">
        <router-link to="/" class="brand"><Mark :size="22" /><span>ROS-DPI</span></router-link>
        <nav class="nav" aria-label="main">
          <router-link v-for="n in nav" :key="n.to" :to="n.to" :class="{ on: isOn(n) }">{{ t(n.label) }}</router-link>
        </nav>
        <div class="tools">
          <button class="btn ghost sm" @click="toggleTheme" :aria-label="t('common.theme')" :title="t('common.theme')">
            <svg v-if="ui.theme === 'dark'" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
            <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>
          </button>
          <button class="btn ghost sm" @click="setLang(locale === 'zh' ? 'en' : 'zh')">{{ t('common.lang') }}</button>
          <button class="btn ghost sm" @click="logout">{{ t('nav.logout') }}</button>
        </div>
      </div>
    </header>
    <main class="main">
      <div class="page"><router-view /></div>
    </main>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import { setAuth } from './api.js'
import Mark from './components/Mark.vue'
import { setLang } from './i18n/index.js'
import { toggleTheme, ui } from './state.js'

const { t, locale } = useI18n()
const route = useRoute()
const router = useRouter()

const nav = [
  { to: '/', label: 'nav.overview' },
  { to: '/hosts', label: 'nav.hosts' },
  { to: '/apps', label: 'nav.apps' },
  { to: '/flow', label: 'nav.flow' },
  { to: '/rules', label: 'nav.rules' },
  { to: '/settings', label: 'nav.settings' },
]

const isOn = n => (n.to === '/' ? route.path === '/' : route.path.startsWith(n.to))

function logout() {
  setAuth('')
  router.push('/login')
}
</script>

<style scoped>
.top { background: var(--panel); border-bottom: 1px solid var(--line); position: sticky; top: 0; z-index: 30; }
.top-in { max-width: 1488px; margin: 0 auto; padding: 0 24px; height: 56px; display: flex; align-items: center; gap: 28px; }
.brand { display: flex; align-items: center; gap: 9px; font: 700 19px/1 var(--cond); letter-spacing: .02em; flex: none; }
.nav { display: flex; gap: 4px; height: 100%; flex: 1; min-width: 0; overflow-x: auto; scrollbar-width: none; }
.nav::-webkit-scrollbar { display: none; }
.nav a {
  display: flex; align-items: center; padding: 0 12px; color: var(--muted); font-weight: 500;
  position: relative; white-space: nowrap;
}
.nav a:hover { color: var(--ink); }
.nav a.on { color: var(--ink); }
/* 当前页：底部一段蓝对色线 */
.nav a.on::after { content: ""; position: absolute; left: 12px; right: 12px; bottom: 0; height: 3px; border-radius: 3px 3px 0 0; background: var(--pair-blue); }
.tools { display: flex; gap: 2px; flex: none; }
.main { padding: 24px 24px 56px; }

@media (max-width: 860px) {
  .top-in { flex-wrap: wrap; height: auto; padding: 10px 16px 0; gap: 8px 12px; }
  .brand { order: 1; }
  .tools { order: 2; margin-left: auto; }
  .nav { order: 3; flex-basis: 100%; height: 42px; margin: 0 -8px; }
  .main { padding: 18px 16px 40px; }
}
</style>
