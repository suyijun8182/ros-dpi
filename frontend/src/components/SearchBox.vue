<template>
  <!-- 顶栏功能搜索：页面名、终端（名称 / IP / MAC）、应用。按 / 聚焦，↑↓ 选择，回车打开 -->
  <div class="sb" :class="{ open: open && q }" @keydown="onKey">
    <Icon name="search" :size="16" class="ic" />
    <input ref="inp" v-model="q" class="q" :placeholder="t('search.placeholder')" :aria-label="t('search.placeholder')"
           @focus="open = true" @blur="close" autocomplete="off" />
    <kbd v-if="!q">/</kbd>
    <div v-if="open && q" class="dd" role="listbox">
      <template v-for="g in groups" :key="g.key">
        <div v-if="g.items.length" class="gh">{{ t('search.' + g.key) }}</div>
        <router-link v-for="it in g.items" :key="it.to" :to="it.to" class="it" :class="{ on: flat[active] === it }"
                     role="option" @mousedown.prevent @click="pick">
          <span class="nm">{{ it.label }}</span><span class="sub faint">{{ it.sub }}</span>
        </router-link>
      </template>
      <div v-if="!flat.length" class="none">{{ loading ? t('common.loading') : t('search.none') }}</div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import http, { enc } from '../api.js'
import { appName, catName, groupName } from '../format.js'
import Icon from './Icon.vue'

const props = defineProps({ pages: { type: Array, default: () => [] } })
const { t } = useI18n()
const router = useRouter()
const q = ref('')
const open = ref(false)
const loading = ref(false)
const res = ref({ hosts: [], apps: [] })
const active = ref(0)
const inp = ref(null)
let timer = null
let seq = 0

watch(q, v => {
  clearTimeout(timer)
  active.value = 0
  if (!v.trim()) { res.value = { hosts: [], apps: [] }; return }
  loading.value = true
  timer = setTimeout(async () => {
    const my = ++seq
    try {
      const r = await http.get('/search', { params: { q: v.trim() } })
      if (my === seq) res.value = r
    } catch (e) { /* 搜索失败不打扰，显示无结果 */ } finally { if (my === seq) loading.value = false }
  }, 180)
})

const groups = computed(() => {
  const s = q.value.trim().toLowerCase()
  return [
    { key: 'pages', items: props.pages.filter(p => p.label.toLowerCase().includes(s)).map(p => ({ to: p.to, label: p.label, sub: '' })) },
    { key: 'hosts', items: res.value.hosts.map(h => ({ to: `/hosts/${enc(h.key)}`, label: h.name, sub: [h.ip, h.mac].filter(Boolean).join(' · ') })) },
    { key: 'apps', items: res.value.apps.map(a => ({ to: `/apps/${enc(a.id)}`, label: appName(a), sub: `${groupName(a)} · ${catName(a)}` })) },
  ]
})
const flat = computed(() => groups.value.flatMap(g => g.items))

function onKey(e) {
  if (e.key === 'ArrowDown') { active.value = Math.min(active.value + 1, flat.value.length - 1); e.preventDefault() }
  else if (e.key === 'ArrowUp') { active.value = Math.max(active.value - 1, 0); e.preventDefault() }
  else if (e.key === 'Enter' && flat.value[active.value]) { router.push(flat.value[active.value].to); pick() }
  else if (e.key === 'Escape') { inp.value.blur() }
}
function pick() { q.value = ''; open.value = false; inp.value && inp.value.blur() }
function close() { setTimeout(() => (open.value = false), 120) }

// 按 / 聚焦搜索框（输入框里打字时不拦截）
function slash(e) {
  if (e.key === '/' && !/input|textarea|select/i.test(document.activeElement?.tagName || '')) { e.preventDefault(); inp.value.focus() }
}
onMounted(() => document.addEventListener('keydown', slash))
onBeforeUnmount(() => document.removeEventListener('keydown', slash))
</script>

<style scoped>
.sb { position: relative; display: flex; align-items: center; width: 280px; height: 36px; background: var(--sunk); border-radius: 18px; padding: 0 12px; gap: 8px; }
.sb:focus-within { box-shadow: 0 0 0 2px color-mix(in srgb, var(--focus) 35%, transparent); background: var(--panel); }
.ic { color: var(--faint); flex: none; }
.q { flex: 1; min-width: 0; border: 0; outline: none; background: none; height: 100%; font-size: 13.5px; }
kbd { font: 500 11px/1 var(--cond); color: var(--faint); border: 1px solid var(--line-strong); border-radius: 4px; padding: 2px 5px; }
.dd { position: absolute; top: 42px; left: 0; right: 0; background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 6px; box-shadow: 0 12px 32px rgba(20, 30, 50, .14); z-index: 50; max-height: 420px; overflow-y: auto; min-width: 300px; }
.gh { font-size: 12px; color: var(--faint); padding: 8px 10px 4px; }
.it { display: flex; align-items: baseline; gap: 10px; padding: 8px 10px; border-radius: 8px; }
.it:hover, .it.on { background: var(--brand-weak); }
.nm { font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.sub { font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.none { padding: 14px 10px; color: var(--muted); font-size: 13px; }
@media (max-width: 860px) { .sb { width: 100%; } }
</style>
