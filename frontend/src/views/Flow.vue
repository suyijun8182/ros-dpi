<template>
  <div>
    <div class="page-h">
      <h1>{{ t('flow.title') }}</h1>
      <span class="sp" />
      <RangeTabs />
    </div>
    <p class="lead muted">{{ t('flow.lead') }}</p>

    <div class="ctl">
      <label>{{ t('flow.hosts') }}
        <select class="input sm" v-model.number="nHosts"><option v-for="n in [8, 12, 20, 30]" :key="n" :value="n">{{ n }}</option></select>
      </label>
      <label>{{ t('flow.apps') }}
        <select class="input sm" v-model.number="nApps"><option v-for="n in [10, 16, 25, 40]" :key="n" :value="n">{{ n }}</option></select>
      </label>
      <span class="sp" />
      <span class="faint small">{{ t('flow.hint') }}</span>
    </div>

    <div v-if="error" class="err">{{ error }}</div>
    <div class="panel">
      <div class="panel-b">
        <Chart v-if="g && g.links.length" :option="opt" :height="height + 'px'" @click="open" />
        <div v-else class="empty">{{ loading ? t('common.loading') : t('common.empty') }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import http, { enc } from '../api.js'
import { sankeyOption } from '../charts.js'
import Chart from '../components/Chart.vue'
import RangeTabs from '../components/RangeTabs.vue'
import { usePoll } from '../poll.js'
import { ui } from '../state.js'

const { t, locale } = useI18n()
const router = useRouter()
const g = ref(null)
const nHosts = ref(12)
const nApps = ref(16)

const { loading, error } = usePoll(async () => {
  g.value = await http.get('/flow', { params: { range: ui.range, hosts: nHosts.value, apps: nApps.value } })
}, 60000, () => [ui.range, nHosts.value, nApps.value])

const opt = computed(() => (ui.theme, locale.value, sankeyOption(g.value)))
// 高度随两侧最多的节点数增长，保证每个节点和标签都有空间
const height = computed(() => {
  if (!g.value) return 480
  const hosts = g.value.nodes.filter(n => n.kind === 'host').length
  const apps = g.value.nodes.filter(n => n.kind === 'app').length
  return Math.max(420, Math.max(hosts, apps) * 30 + 40)
})

function open(p) {
  const n = p.data && p.data.raw
  if (!n) return
  if (n.kind === 'host' && n.key) router.push(`/hosts/${enc(n.key)}`)
  else if (n.kind === 'app' && n.app) router.push(`/apps/${enc(n.app)}`)
  else if (n.kind === 'category') router.push({ path: '/apps', query: { cat: n.category } })
}
</script>

<style scoped>
.lead { margin: -12px 0 18px; max-width: 70ch; }
.ctl { display: flex; align-items: center; gap: 20px; margin-bottom: 12px; flex-wrap: wrap; font-size: 14px; color: var(--muted); }
.ctl label { display: flex; align-items: center; gap: 8px; }
.input.sm { height: 30px; width: auto; padding: 0 8px; }
</style>
