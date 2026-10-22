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
        <div class="panel-h"><h2>{{ t('apps.byGroup') }}</h2><span class="faint small">{{ t('apps.byGroupHint') }}</span><span class="sp" />
          <button v-if="group" class="more" @click="pick({})">{{ t('apps.showAll') }}</button></div>
        <div class="panel-b"><Composition :groups="d.groups" clickable drill :active="group" height="340px" @pick="pick" /></div>
      </div>

      <!-- DPI 协议：大类 → 小类 → 应用 三级下钻，版式同维盟「DPI 协议详情」（debug9） -->
      <div class="panel mt">
        <div class="panel-b sums">
          <div><span>{{ t('apps.dpi.upRate') }}</span><b class="num up">{{ rate(lvlSum.rate_up) }}</b></div>
          <div><span>{{ t('apps.dpi.downRate') }}</span><b class="num down">{{ rate(lvlSum.rate_down) }}</b></div>
          <div><span>{{ t('apps.dpi.upBytes') }}</span><b class="num up">{{ bytes(lvlSum.up) }}</b></div>
          <div><span>{{ t('apps.dpi.downBytes') }}</span><b class="num down">{{ bytes(lvlSum.down) }}</b></div>
        </div>
        <div class="panel-h bar">
          <nav class="crumbs" :aria-label="t('apps.dpi.title')">
            <button class="lk" :class="{ cur: !group && !s }" @click="pick({})">{{ t('apps.dpi.title') }}</button>
            <template v-if="gObj && !s"><span class="faint">›</span>
              <button class="lk" :class="{ cur: !cat }" @click="pick({ group })">{{ groupName(gObj) }}</button></template>
            <template v-if="cObj && !s"><span class="faint">›</span><span class="lk cur">{{ catName(cObj) }}</span></template>
            <template v-if="s"><span class="faint">›</span><span class="lk cur">{{ t('apps.dpi.searchRes', { q: q.trim() }) }}</span></template>
          </nav>
          <span class="sp" />
          <input class="input search" v-model="q" :placeholder="t('apps.dpi.search')" :aria-label="t('apps.dpi.search')" />
          <select class="input every" v-model.number="every" :aria-label="t('apps.dpi.every')" :disabled="paused">
            <option v-for="n in [10, 30, 60]" :key="n" :value="n">{{ t('apps.dpi.sec', { n }) }}</option>
          </select>
          <button class="btn sm" @click="paused = !paused"><Icon name="refresh" :size="15" />{{ paused ? t('apps.dpi.resume') : t('apps.dpi.stop') }}</button>
          <template v-if="(group || cat) && !s">
            <button class="btn sm" @click="pick({})">{{ t('apps.dpi.top') }}</button>
            <button class="btn sm" @click="up1">{{ t('apps.dpi.up') }}</button>
          </template>
          <button class="btn sm" @click="exportRows"><Icon name="download" :size="15" />{{ t('common.export') }}</button>
        </div>
        <div class="tbl-wrap">
          <table class="tbl dpi">
            <thead><tr>
              <th class="rk m-hide">#</th>
              <th v-for="c in COLS" :key="c.k" :class="[c.cls, { sortable: true }]" :aria-sort="sortK === c.k ? (sortDesc ? 'descending' : 'ascending') : 'none'">
                <button class="th-b" @click="sortBy(c.k)">{{ t(c.label) }}<span class="arr" :class="{ on: sortK === c.k }">{{ sortK === c.k && !sortDesc ? '▲' : '▼' }}</span></button></th>
              <th class="r">{{ t('common.details') }}</th>
            </tr></thead>
            <tbody>
              <tr v-for="(r, i) in rows" :key="r.id" class="link" @click="open(r)">
                <td class="rk num faint m-hide">{{ i + 1 }}</td>
                <td class="nm"><span class="tag"><span class="chip" :style="{ background: r.color }" />{{ r.label }}</span>
                  <div class="faint small" v-if="r.sub">{{ r.sub }}</div></td>
                <td class="r num m-hide"><span :class="r.rate_up ? 'up' : 'faint'">{{ rate(r.rate_up) }}</span><span class="sh">{{ share(r.rate_up, lvlSum.rate_up) }}</span></td>
                <td class="r num"><span :class="r.rate_down ? 'down' : 'faint'">{{ rate(r.rate_down) }}</span><span class="sh">{{ share(r.rate_down, lvlSum.rate_down) }}</span></td>
                <td class="r num m-hide">{{ bytes(r.up) }}<span class="sh">{{ share(r.up, lvlSum.up) }}</span></td>
                <td class="r num"><b>{{ bytes(r.down) }}</b><span class="sh">{{ share(r.down, lvlSum.down) }}</span></td>
                <td class="r"><button class="lk more-l" :disabled="r.kind !== 'app' && !r.n" @click.stop="open(r)">{{ r.kind === 'app' ? t('apps.dpi.appPage') : t('apps.dpi.drill') }}</button></td>
              </tr>
            </tbody>
          </table>
          <div v-if="!rows.length" class="empty">{{ t('common.empty') }}</div>
        </div>
        <div class="panel-b foot faint small">{{ t('apps.dpi.note') }}</div>
      </div>
    </template>
    <div v-else-if="loading" class="empty">{{ t('common.loading') }}</div>
  </div>
</template>

<script setup>
import { computed, ref, watchEffect } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import http, { enc } from '../api.js'
import Composition from '../components/Composition.vue'
import Icon from '../components/Icon.vue'
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
// 筛选写在地址栏里：?group=media 或 ?cat=short_video（小类隐含所属大类）
const cat = computed(() => route.query.cat || '')
const group = computed(() => route.query.group || CAT_GROUP[cat.value] || '')
const s = computed(() => q.value.trim().toLowerCase())
const every = ref(10)      // 刷新间隔（秒）；按应用拆分的速率来自 RouterOS 每分钟的 IPFIX，刷得再快也不会变
const paused = ref(false)
const { loading, error, reload } = usePoll(async () => { d.value = await http.get('/apps', { params: { range: ui.range } }) },
  0, () => ui.range)
let timer = null
watchEffect(onCleanup => {
  if (paused.value) return
  timer = setInterval(() => { if (!document.hidden) reload() }, every.value * 1000)
  onCleanup(() => clearInterval(timer))
})

function pick(p) {
  q.value = ''
  router.replace({ query: p.cat ? { cat: p.cat } : p.group ? { group: p.group } : {} })
}
const up1 = () => pick(cat.value ? { group: group.value } : {})

const COLS = [
  { k: 'label', label: 'apps.dpi.proto', cls: '' },
  { k: 'rate_up', label: 'apps.dpi.upRateCol', cls: 'r m-hide' },
  { k: 'rate_down', label: 'apps.dpi.downRateCol', cls: 'r' },
  { k: 'up', label: 'apps.dpi.upBytesCol', cls: 'r m-hide' },
  { k: 'down', label: 'apps.dpi.downBytesCol', cls: 'r' },
]
const sortK = ref('down')
const sortDesc = ref(true)
function sortBy(k) {
  if (sortK.value === k) sortDesc.value = !sortDesc.value
  else { sortK.value = k; sortDesc.value = k !== 'label' }
}

const gObj = computed(() => d.value.groups.find(x => x.id === group.value))
const cObj = computed(() => cat.value && gObj.value && gObj.value.children.find(x => x.id === cat.value))
const sumRates = list => list.reduce((o, a) => { o.rate_up += a.rate_up; o.rate_down += a.rate_down; return o }, { rate_up: 0, rate_down: 0 })
const appRow = a => ({ kind: 'app', id: a.id, label: appName(a), sub: s.value ? `${groupName(a)} · ${catName(a)}` : '', color: catColor(a.category),
  up: a.up, down: a.down, rate_up: a.rate_up, rate_down: a.rate_down, hosts: a.hosts })
// 当前这一级的行：搜索时直接列出匹配的应用；否则按 顶层大类 / 大类下的小类 / 小类下的应用
const rows = computed(() => {
  const apps = d.value.apps
  let list
  if (s.value) {
    list = apps.filter(a => [a.id, a.name, a.name_en].some(v => v && v.toLowerCase().includes(s.value))).map(appRow)
  } else if (cat.value) {
    list = apps.filter(a => a.category === cat.value).map(appRow)
  } else if (group.value) {
    list = (gObj.value ? gObj.value.children : []).map(c => {
      const in_ = apps.filter(a => a.category === c.id)
      return { kind: 'cat', id: c.id, label: catName(c), color: catColor(c.id), up: c.up, down: c.down, n: in_.length, ...sumRates(in_) }
    })
  } else {
    list = d.value.groups.map(g => {
      const in_ = apps.filter(a => a.group === g.id)
      return { kind: 'group', id: g.id, label: groupName(g), color: catColor((g.children[0] || {}).id), up: g.up, down: g.down,
        n: g.children.length, ...sumRates(in_) }
    })
  }
  const k = sortK.value, dir = sortDesc.value ? -1 : 1
  return [...list].sort((a, b) => (k === 'label' ? a.label.localeCompare(b.label, 'zh') : a[k] - b[k]) * dir)
})
const lvlSum = computed(() => rows.value.reduce((o, r) => {
  for (const k of ['up', 'down', 'rate_up', 'rate_down']) o[k] += r[k]
  return o
}, { up: 0, down: 0, rate_up: 0, rate_down: 0 }))
const share = (v, total) => ` | ${pct(total ? v / total : 0, 2)}`

function open(r) {
  if (r.kind === 'app') router.push(`/apps/${enc(r.id)}`)
  else if (r.n) pick(r.kind === 'group' ? { group: r.id } : { cat: r.id })
}

function exportRows() {
  exportCsv('rosdpi-dpi', [
    { label: t('apps.dpi.proto'), value: r => r.label },
    { label: t('apps.dpi.upRateCol') + ' (bps)', value: r => Math.round(r.rate_up * 8) },
    { label: t('apps.dpi.downRateCol') + ' (bps)', value: r => Math.round(r.rate_down * 8) },
    { label: t('apps.dpi.upBytesCol') + ' (B)', value: r => r.up }, { label: t('apps.dpi.downBytesCol') + ' (B)', value: r => r.down },
    { label: t('common.share'), value: r => pct((r.up + r.down) / ((lvlSum.value.up + lvlSum.value.down) || 1), 2) },
  ], rows.value)
}
</script>

<style scoped>
.sums { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; padding-bottom: 4px; }
.sums div { display: grid; gap: 2px; }
.sums span { color: var(--muted); font-size: 13px; }
.sums b { font-size: 22px; font-weight: 600; }
.bar { flex-wrap: wrap; gap: 8px; }
.crumbs { display: flex; align-items: center; gap: 6px; font-size: 15px; font-weight: 600; min-width: 0; }
.lk { background: none; border: 0; padding: 0; font: inherit; color: var(--brand-ink); cursor: pointer; }
.lk.cur { color: var(--ink); cursor: default; }
.lk:disabled { color: var(--faint); cursor: default; }
.search { width: 200px; height: 32px; }
.every { width: 92px; height: 32px; }
.nm { font-weight: 500; }
.rk { width: 36px; padding-right: 0; }
.dpi td.num { white-space: nowrap; }
.sh { color: var(--faint); font-size: 12px; }
.th-b { background: none; border: 0; padding: 0; font: inherit; color: inherit; cursor: pointer; display: inline-flex; gap: 4px; align-items: center; }
.arr { font-size: 9px; color: var(--line-strong); }
.arr.on { color: var(--brand-ink); }
.more-l { font-size: 13px; }
.foot { padding-top: 10px; }
@media (max-width: 900px) { .sums { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 640px) { .search { width: 100%; } .sh { display: block; } .sums b { font-size: 18px; } }
</style>
