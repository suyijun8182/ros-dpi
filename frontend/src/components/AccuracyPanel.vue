<template>
  <!-- 识别校验（0.6.29）：拿"已知答案"的流量核对认得对不对 -->
  <div class="panel mt">
    <div class="panel-h"><h2>{{ t('diag.acc.title') }}</h2>
      <span class="faint small" v-if="sum.probes">{{ t('diag.acc.overall', { n: sum.probes, p: pct(sum.hit / sum.total), c: pct((sum.hit + sum.same_cat) / sum.total) }) }}</span>
    </div>
    <div class="panel-b">
      <p class="muted hint">{{ t('diag.acc.intro') }}</p>
      <form v-if="isAdmin" class="acc-form" @submit.prevent="add(null)">
        <select class="input" v-model="f.host" required>
          <option value="" disabled>{{ t('diag.acc.pickHost') }}</option>
          <option v-for="h in hosts" :key="h.key" :value="h.key">{{ h.online ? '● ' : '' }}{{ h.name }} · {{ h.ip }}</option>
        </select>
        <select class="input" v-model="f.expected" required>
          <option value="" disabled>{{ t('diag.acc.pickApp') }}</option>
          <optgroup v-for="c in meta.categories" :key="c.id" :label="catLabel(c)">
            <option v-for="a in meta.apps.filter(x => x.category === c.id)" :key="a.id" :value="a.id">{{ appName(a) }}</option>
          </optgroup>
        </select>
        <button class="btn primary" :disabled="!f.host || !f.expected">{{ t('diag.acc.start') }}</button>
        <span class="faint small">{{ t('diag.acc.or') }}</span>
        <button type="button" class="btn" :disabled="!f.host || !f.expected" @click="add(back)">{{ t('diag.acc.back', { n: back }) }}</button>
        <select class="input sm-in" v-model.number="back"><option v-for="n in [5, 10, 15, 30, 60]" :key="n" :value="n">{{ n }}</option></select>
      </form>
      <div class="err" v-if="err">{{ err }}</div>
    </div>
    <div class="tbl-wrap" v-if="items.length">
      <table class="tbl">
        <thead><tr><th>{{ t('diag.acc.host') }}</th><th>{{ t('diag.acc.expected') }}</th><th class="m-hide">{{ t('diag.acc.window') }}</th>
          <th class="r">{{ t('diag.acc.total') }}</th><th>{{ t('diag.acc.result') }}</th><th class="m-hide">{{ t('diag.acc.top') }}</th><th /></tr></thead>
        <tbody>
          <tr v-for="p in items" :key="p.id">
            <td><b>{{ p.host.name }}</b><div class="faint small">{{ p.host.ip }}</div></td>
            <td>{{ appName(p.expected) }}</td>
            <td class="m-hide num small muted">{{ datetime(p.start) }}<div>{{ p.end ? mins(p.end - p.start) : t('diag.acc.running') }}</div></td>
            <td class="r num">{{ bytes(p.total) }}</td>
            <td class="res">
              <template v-if="p.total">
                <div class="stack">
                  <span v-for="k in KINDS" :key="k" :class="'k-' + k" :style="{ width: (p[k] / p.total * 100) + '%' }" :title="t('diag.acc.kind.' + k) + ' ' + pct(p[k] / p.total)" />
                </div>
                <div class="small"><b>{{ pct(p.hit / p.total) }}</b> <span class="muted">{{ t('diag.acc.kind.hit') }}</span>
                  <span class="faint"> · {{ t('diag.acc.kind.vague') }} {{ pct(p.vague / p.total) }} · {{ t('diag.acc.kind.wrong') }} {{ pct(p.wrong / p.total) }}</span></div>
              </template>
              <span v-else class="faint small">{{ p.state === 'running' ? t('diag.acc.waiting') : t('diag.acc.noData') }}</span>
              <span v-if="p.state === 'settling'" class="faint small"> · {{ t('diag.acc.settling') }}</span>
            </td>
            <td class="m-hide small">
              <span v-for="a in p.apps.slice(0, 4)" :key="a.app.id" class="ac-tag" :class="'c-' + a.kind">{{ appName(a.app) }} {{ pct(a.bytes / p.total, 0) }}</span>
            </td>
            <td class="r nowrap">
              <button v-if="isAdmin && p.state === 'running'" class="btn sm primary" @click="stop(p)">{{ t('diag.acc.stop') }}</button>
              <button v-if="isAdmin" class="btn sm" @click="del(p)">{{ t('common.delete') }}</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p class="panel-b faint small" v-if="items.length">{{ t('diag.acc.legend') }}</p>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import http, { isAdmin } from '../api.js'
import { appName, bytes, catName, datetime, groupName, pct } from '../format.js'

const props = defineProps({ meta: { type: Object, required: true } })
const { t } = useI18n()
const KINDS = ['hit', 'same_cat', 'vague', 'wrong']
const items = ref([])
const sum = ref({ probes: 0 })
const hosts = ref([])
const f = reactive({ host: '', expected: '' })
const back = ref(10)
const err = ref('')
let timer

const catLabel = c => `${groupName(props.meta.groups.find(g => g.id === c.group))} · ${catName(c)}`
const mins = s => t('diag.acc.mins', { n: Math.max(1, Math.round(s / 60)) })

async function load() {
  try {
    const r = await http.get('/accuracy/probes')
    items.value = r.items
    sum.value = r.summary
    err.value = ''
  } catch (e) { err.value = e.message }
  clearTimeout(timer)
  // 有进行中或等结果的：30 秒刷新一次
  if (items.value.some(p => p.state !== 'done')) timer = setTimeout(load, 30000)
}
async function loadHosts() {
  try {
    const list = await http.get('/hosts')
    hosts.value = list.sort((a, b) => (b.online - a.online) || a.name.localeCompare(b.name))
  } catch (e) { /* 列表空着 */ }
}
async function add(minutes) {
  try {
    await http.post('/accuracy/probes', { host: f.host, expected: f.expected, back: minutes })
    await load()
  } catch (e) { err.value = e.message }
}
async function stop(p) {
  try { await http.post(`/accuracy/probes/${p.id}/stop`); await load() } catch (e) { err.value = e.message }
}
async function del(p) {
  try { await http.delete(`/accuracy/probes/${p.id}`); await load() } catch (e) { err.value = e.message }
}

onMounted(() => { load(); if (isAdmin.value) loadHosts() })
onUnmounted(() => clearTimeout(timer))
</script>

<style scoped>
.hint { margin: 0 0 10px; }
.acc-form { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.acc-form .input { width: auto; min-width: 180px; }
.acc-form .sm-in { min-width: 64px; }
.res { min-width: 180px; }
.stack { display: flex; height: 8px; border-radius: 4px; overflow: hidden; background: var(--line); margin-bottom: 4px; }
.k-hit { background: var(--ok); }
.k-same_cat { background: color-mix(in srgb, var(--ok) 45%, transparent); }
.k-vague { background: var(--line-strong); }
.k-wrong { background: var(--bad); }
.ac-tag { display: inline-block; margin: 0 6px 2px 0; padding: 0 6px; border-radius: 9px; background: var(--line); white-space: nowrap; }
.ac-tag.c-hit { color: var(--ok); }
.ac-tag.c-wrong { color: var(--bad); }
.nowrap { white-space: nowrap; }
</style>
