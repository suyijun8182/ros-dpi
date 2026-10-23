<template>
  <div>
    <div class="page-h">
      <h1>{{ t('apps.title') }}</h1>
      <span class="lead" v-if="d">{{ bytes(d.range_total.total) }} · {{ t('apps.count', { n: d.apps.length }) }}</span>
      <span class="sp" />
      <RangeTabs />
    </div>
    <div v-if="error" class="err">{{ error }}</div>
    <template v-if="d">
      <div class="panel">
        <div class="panel-h"><h2>{{ t('apps.byGroup') }}</h2><span class="faint small">{{ t('apps.byGroupHint') }}</span></div>
        <div class="panel-b"><Treemap :groups="d.groups" :group="group" height="320px" @pick="pick" /></div>
      </div>

      <!-- DPI 协议：页面上是 17 个大类（维盟）；点「查看详情」弹出「DPI 协议详情」，在弹窗里逐级下钻（debug12） -->
      <div class="panel mt">
        <div class="panel-b sums">
          <div><span>{{ t('apps.dpi.upRate') }}</span><b class="num up">{{ rate(pageSum.rate_up) }}</b></div>
          <div><span>{{ t('apps.dpi.downRate') }}</span><b class="num down">{{ rate(pageSum.rate_down) }}</b></div>
          <div><span>{{ t('apps.dpi.upBytes') }}</span><b class="num up">{{ bytes(pageSum.up) }}</b></div>
          <div><span>{{ t('apps.dpi.downBytes') }}</span><b class="num down">{{ bytes(pageSum.down) }}</b></div>
        </div>
        <div class="panel-h bar">
          <h2 class="crumbs">{{ s ? t('apps.dpi.searchRes', { q: q.trim() }) : t('apps.dpi.title') }}</h2>
          <span class="sp" />
          <input class="input search" v-model="q" :placeholder="t('apps.dpi.search')" :aria-label="t('apps.dpi.search')" />
          <select class="input every" v-model.number="every" :aria-label="t('apps.dpi.every')" :disabled="paused">
            <option v-for="n in [10, 30, 60]" :key="n" :value="n">{{ t('apps.dpi.sec', { n }) }}</option>
          </select>
          <button class="btn sm" @click="paused = !paused"><Icon name="refresh" :size="15" />{{ paused ? t('apps.dpi.resume') : t('apps.dpi.stop') }}</button>
          <button class="btn sm" @click="exportRows(pageRows)"><Icon name="download" :size="15" />{{ t('common.export') }}</button>
        </div>
        <DpiRows :rows="pageRows" @open="open" />
        <div class="panel-b foot faint small">{{ t('apps.dpi.note') }}</div>
      </div>
    </template>
    <div v-else-if="loading" class="empty">{{ t('common.loading') }}</div>

    <Modal :open="!!(d && group)" :title="t('apps.dpi.detailTitle')" width="1080px" @close="pick({})">
      <template v-if="d && group">
        <div class="sums m">
          <div><span>{{ t('apps.dpi.upRate') }}</span><b class="num up">{{ rate(modalSum.rate_up) }}</b></div>
          <div><span>{{ t('apps.dpi.downRate') }}</span><b class="num down">{{ rate(modalSum.rate_down) }}</b></div>
          <div><span>{{ t('apps.dpi.upBytes') }}</span><b class="num up">{{ bytes(modalSum.up) }}</b></div>
          <div><span>{{ t('apps.dpi.downBytes') }}</span><b class="num down">{{ bytes(modalSum.down) }}</b></div>
        </div>
        <div class="bar mbar">
          <nav class="crumbs" :aria-label="t('apps.dpi.title')">
            <button class="lk" @click="pick({})">{{ t('apps.dpi.title') }}</button>
            <span class="faint">›</span>
            <button class="lk" :class="{ cur: !cat }" @click="pick({ group })">{{ gObj ? groupName(gObj) : group }}</button>
            <template v-if="cObj"><span class="faint">›</span><span class="lk cur">{{ catName(cObj) }}</span></template>
          </nav>
          <span class="sp" />
          <select class="input every" v-model.number="every" :aria-label="t('apps.dpi.every')" :disabled="paused">
            <option v-for="n in [10, 30, 60]" :key="n" :value="n">{{ t('apps.dpi.sec', { n }) }}</option>
          </select>
          <button class="btn sm" @click="paused = !paused"><Icon name="refresh" :size="15" />{{ paused ? t('apps.dpi.resume') : t('apps.dpi.stop') }}</button>
          <button class="btn sm" @click="pick({})">{{ t('apps.dpi.top') }}</button>
          <button class="btn sm" @click="up1">{{ t('apps.dpi.up') }}</button>
          <button class="btn sm" @click="exportRows(modalRows)"><Icon name="download" :size="15" />{{ t('common.export') }}</button>
        </div>
        <DpiRows :rows="modalRows" @open="open" />
      </template>
    </Modal>
  </div>
</template>

<script setup>
import { computed, ref, watchEffect } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import http, { enc } from '../api.js'
import Treemap from '../components/Treemap.vue'
import Icon from '../components/Icon.vue'
import Modal from '../components/Modal.vue'
import DpiRows, { levelSum } from '../components/DpiRows.vue'
import { exportCsv } from '../csv.js'
import RangeTabs from '../components/RangeTabs.vue'
import { appName, bytes, CAT_GROUP, catColor, catName, groupName, pct, rate } from '../format.js'
import { usePoll } from '../poll.js'
import { ui } from '../state.js'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const d = ref(null)
const q = ref('')
// 弹窗里的层级写在地址栏里：?group=tv 或 ?cat=short_video（小类隐含所属大类）；都没有时弹窗关闭
const cat = computed(() => route.query.cat || '')
const group = computed(() => route.query.group || CAT_GROUP[cat.value] || '')
const s = computed(() => q.value.trim().toLowerCase())
const every = ref(10)      // 刷新间隔（秒）；按应用拆分的速率来自 RouterOS 每分钟的 IPFIX，刷得再快也不会变
const paused = ref(false)
const meta = ref({ groups: [], categories: [] })
const { loading, error, reload } = usePoll(async () => {
  if (!meta.value.groups.length) meta.value = await http.get('/meta')
  d.value = await http.get('/apps', { params: { range: ui.range } })
}, 0, () => ui.range)
let timer = null
watchEffect(onCleanup => {
  if (paused.value) return
  timer = setInterval(() => { if (!document.hidden) reload() }, every.value * 1000)
  onCleanup(() => clearInterval(timer))
})

function pick(p) {
  router.replace({ query: p.cat ? { cat: p.cat } : p.group ? { group: p.group } : {} })
}
const up1 = () => pick(cat.value ? { group: group.value } : {})

const gObj = computed(() => meta.value.groups.find(x => x.id === group.value))
const cObj = computed(() => cat.value && meta.value.categories.find(x => x.id === cat.value))
const ZERO = { up: 0, down: 0 }
const sumRates = list => list.reduce((o, a) => { o.rate_up += a.rate_up; o.rate_down += a.rate_down; return o }, { rate_up: 0, rate_down: 0 })
const appRow = (a, sub) => ({ kind: 'app', id: a.id, label: appName(a), sub: sub ? `${groupName(a)} · ${catName(a)}` : '', color: catColor(a.category),
  up: a.up, down: a.down, rate_up: a.rate_up, rate_down: a.rate_down, hosts: a.hosts })

// 顶层：17 个大类全部列出（没有数据也列），和维盟一样固定
const groupRows = computed(() => {
  const apps = d.value.apps
  const have = Object.fromEntries(d.value.groups.map(g => [g.id, g]))
  return meta.value.groups.map((g, i) => {
    const in_ = apps.filter(a => a.group === g.id)
    const x = have[g.id] || ZERO
    const first = meta.value.categories.find(c => c.group === g.id)
    return { kind: 'group', idx: i, id: g.id, label: groupName(g), color: catColor(first ? first.id : 'unknown'), up: x.up, down: x.down,
      n: meta.value.categories.filter(c => c.group === g.id).length, ...sumRates(in_) }
  })
})
// 页面：大类；搜索时直接列出匹配的应用
const pageRows = computed(() => (s.value
  ? d.value.apps.filter(a => [a.id, a.name, a.name_en].some(v => v && v.toLowerCase().includes(s.value))).map(a => appRow(a, true))
  : groupRows.value))
// 弹窗：大类下的小类（全部列出），或小类下的应用
const modalRows = computed(() => {
  if (!group.value) return []
  const apps = d.value.apps
  if (cat.value) return apps.filter(a => a.category === cat.value).map(a => appRow(a, false))
  const have = Object.fromEntries(((d.value.groups.find(x => x.id === group.value) || {}).children || []).map(c => [c.id, c]))
  return meta.value.categories.filter(c => c.group === group.value).map((c, i) => {
    const in_ = apps.filter(a => a.category === c.id)
    const x = have[c.id] || ZERO
    return { kind: 'cat', idx: i, id: c.id, label: catName(c), color: catColor(c.id), up: x.up, down: x.down, n: in_.length, ...sumRates(in_) }
  })
})
const pageSum = computed(() => levelSum(pageRows.value))
const modalSum = computed(() => levelSum(modalRows.value))

function open(r) {
  if (r.kind === 'app') router.push(`/apps/${enc(r.id)}`)
  else if (r.n) pick(r.kind === 'group' ? { group: r.id } : { cat: r.id })
}

function exportRows(rows) {
  const total = levelSum(rows)
  exportCsv('rosdpi-dpi', [
    { label: t('apps.dpi.proto'), value: r => r.label },
    { label: t('apps.dpi.upRateCol') + ' (bps)', value: r => Math.round(r.rate_up * 8) },
    { label: t('apps.dpi.downRateCol') + ' (bps)', value: r => Math.round(r.rate_down * 8) },
    { label: t('apps.dpi.upBytesCol') + ' (B)', value: r => r.up }, { label: t('apps.dpi.downBytesCol') + ' (B)', value: r => r.down },
    { label: t('common.share'), value: r => pct((r.up + r.down) / ((total.up + total.down) || 1), 2) },
  ], rows)
}
</script>

<style scoped>
.sums { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; padding-bottom: 4px; }
.sums div { display: grid; gap: 2px; }
.sums span { color: var(--muted); font-size: 13px; }
.sums b { font-size: 22px; font-weight: 600; }
.sums.m { padding: 4px 0 12px; border-bottom: 1px solid var(--line); }
.bar { flex-wrap: wrap; gap: 8px; }
.mbar { display: flex; align-items: center; padding: 12px 0 4px; }
.mbar .sp { flex: 1; }
.crumbs { display: flex; align-items: center; gap: 6px; font-size: 15px; font-weight: 600; min-width: 0; margin: 0; }
.lk { background: none; border: 0; padding: 0; font: inherit; color: var(--brand-ink); cursor: pointer; }
.lk.cur { color: var(--ink); cursor: default; }
.search { width: 200px; height: 32px; }
.every { width: 92px; height: 32px; }
.foot { padding-top: 10px; }
@media (max-width: 900px) { .sums { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 640px) { .search { width: 100%; } .sums b { font-size: 18px; } }
</style>
