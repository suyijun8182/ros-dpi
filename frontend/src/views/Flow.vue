<template>
  <div>
    <!-- 子标签：实时连接 / 访问目标排行 / 代理分流 -->
    <div class="page-h">
      <div class="seg tabs" role="tablist">
        <button v-for="k in TABS" :key="k" role="tab" :aria-selected="tab === k" :class="{ on: tab === k }" @click="setTab(k)">{{ t('flow.tab.' + k) }}</button>
      </div>
      <span class="sp" />
      <RangeTabs v-if="tab === 'dest'" />
    </div>
    <div v-if="err" class="err">{{ err }}</div>

    <!-- 实时连接 -->
    <div class="panel" v-if="tab === 'live'">
      <div class="panel-b head">
        <div class="info-bar"><span class="ic">i</span><div><b>{{ t('flow.tab.live') }}</b><span>{{ t('flow.info.live') }}</span></div></div>
        <div class="sum" v-if="live">
          <div><span class="muted small">{{ t('flow.active') }}</span><b class="num accent">{{ live.count.toLocaleString() }}</b></div>
          <div><span class="muted small">{{ t('common.up') }}</span><b class="num up">{{ rate(live.rate_up) }}</b></div>
          <div><span class="muted small">{{ t('common.down') }}</span><b class="num down">{{ rate(live.rate_down) }}</b></div>
        </div>
        <div class="sec">{{ t('flow.liveList') }}<span class="faint small" v-if="live && live.count > live.sessions.length">{{ t('flow.topN', { n: live.sessions.length }) }}</span>
          <span class="sp" />
          <input id="live-q" class="input search" v-model="liveQ" :placeholder="t('flow.liveSearch')" :aria-label="t('flow.liveSearch')" />
          <button class="btn sm" :class="{ primary: paused }" @click="paused = !paused">{{ paused ? t('flow.resume') : t('flow.pause') }}</button>
          <button class="btn sm" @click="exportLive" :disabled="!live || !live.sessions.length"><Icon name="download" :size="15" />{{ t('common.export') }}</button>
        </div>
      </div>
      <div class="tbl-wrap" v-if="live">
        <table class="tbl">
          <thead><tr>
            <th>{{ t('flow.host') }}</th><th>{{ t('flow.remote') }}</th><th class="m-hide">{{ t('flow.port') }}</th><th class="m-hide">{{ t('apps.app') }}</th>
            <th class="r">{{ t('common.rate') }}</th><th class="r m-hide">{{ t('flow.bytes') }}</th><th class="r m-hide">{{ t('flow.duration') }}</th><th class="m-hide">{{ t('flow.source') }}</th>
          </tr></thead>
          <tbody>
            <tr v-for="s in live.sessions" :key="s.host + s.remote + s.port + s.proto + s.host_port">
              <td><router-link :to="`/hosts/${enc(s.host)}`" class="hl"><span class="dot" :class="{ on: s.online }" />{{ s.host_name }}</router-link>
                <div class="faint addr small">{{ s.host_ip }}<span v-if="s.host_port">:{{ s.host_port }}</span></div></td>
              <td class="rm"><div class="dn" :title="s.domain || s.remote">{{ s.domain || s.remote }}</div>
                <div class="faint addr small" v-if="s.domain && s.remote !== s.domain">{{ s.remote }}</div>
                <div class="faint small dn" v-else-if="s.asn">{{ countryName(s.asn.country) || s.asn.country }} · {{ s.asn.name }}</div>
                <div class="small dn route" v-if="s.route" :title="s.route.rule">{{ s.route.group }} · {{ s.route.node }}</div>
                <div class="m-only faint small">{{ appName(s.app) }} · {{ proto(s.proto) }} {{ s.port || '' }}</div></td>
              <td class="num m-hide"><span class="pill grey">{{ proto(s.proto) }}</span> {{ s.port || '' }}</td>
              <td class="m-hide"><router-link :to="`/apps/${enc(s.app.id)}`" class="tag"><span class="chip" :style="{ background: catColor(s.app.category) }" />{{ appName(s.app) }}</router-link></td>
              <td class="r num small"><span class="up">↑{{ rate(s.rate_up) }}</span><br /><span class="down">↓{{ rate(s.rate_down) }}</span></td>
              <td class="r num small m-hide"><span class="up">↑{{ bytes(s.up) }}</span><br /><span class="down">↓{{ bytes(s.down) }}</span></td>
              <td class="r num muted m-hide">{{ duration(s.last - s.start, locale === 'zh') }}</td>
              <td class="m-hide"><span class="pill" :class="SRC_CLASS[s.source]" :title="s.route ? s.route.rule : t('settings.matchKind.' + s.source)">{{ t('flow.src.' + s.source) }}</span></td>
            </tr>
          </tbody>
        </table>
        <div v-if="!live.sessions.length" class="empty">{{ t('flow.noLive') }}</div>
        <div v-else-if="live.count > live.sessions.length" class="more-row"><button class="btn sm" @click="limit += 200; loadLive()">{{ t('flow.showMore') }}</button></div>
      </div>
      <div v-else class="empty">{{ t('common.loading') }}</div>
    </div>

    <!-- 访问目标排行 -->
    <div class="panel" v-if="tab === 'dest'">
      <div class="panel-b head">
        <div class="info-bar"><span class="ic">i</span><div><b>{{ t('flow.tab.dest') }}</b><span>{{ t('flow.info.dest') }}</span></div></div>
        <div class="sec">{{ t('flow.destList') }}<span class="faint small" v-if="dest">{{ t('range.' + ui.range) }} · {{ bytes(dest.range_total.total) }}</span>
          <span class="sp" />
          <div class="seg" role="radiogroup" :aria-label="t('flow.kindLabel')">
            <button v-for="k in ['all', 'domain', 'ip']" :key="k" role="radio" :aria-checked="kind === k" :class="{ on: kind === k }" @click="kind = k">{{ t('flow.kind.' + k) }}</button>
          </div>
          <label class="chk"><input type="checkbox" v-model="merge" /> {{ t('flow.merge') }}</label>
          <input id="dest-q" class="input search" v-model="destQ" :placeholder="t('flow.destSearch')" :aria-label="t('flow.destSearch')" @keyup.enter="loadDest" />
          <button class="btn sm" @click="exportDest" :disabled="!dest || !dest.rows.length"><Icon name="download" :size="15" />{{ t('common.export') }}</button>
        </div>
      </div>
      <div class="panel-b ctry" v-if="dest && countries.length">
        <div class="sec">{{ t('flow.countries') }}<span class="faint small">{{ t('flow.countriesHint') }}</span>
          <span class="sp" /><button v-if="country" class="btn sm" @click="country = ''">{{ t('apps.showAll') }}</button></div>
        <div class="mapgrid">
          <WorldMap :countries="dest.countries" :home="dest.home" :active="country" height="340px" @pick="cc => (country = country === cc ? '' : cc)" />
          <div class="clist">
            <button v-for="(c, i) in countries" :key="c.cc" class="cr" :class="{ on: country === c.cc, unk: c.cc === '-' }"
                    @click="country = country === c.cc ? '' : c.cc">
              <span class="rk num">{{ c.cc === '-' ? '' : i + 1 }}</span>
              <span class="cn">{{ c.name }}<span v-if="c.cc === dest.home" class="pill grey home">{{ t('flow.home') }}</span></span>
              <span class="num v">{{ bytes(c.bytes) }}</span>
              <span class="bar"><i :style="{ width: (c.bytes / maxCountry * 100) + '%' }" /></span>
              <span class="num faint p">{{ pct(c.bytes / countryTotal) }}</span>
            </button>
            <div class="faint small unk-note" v-if="countries.some(c => c.cc === '-')">{{ t('flow.unknownNote') }}</div>
          </div>
        </div>
      </div>
      <div class="tbl-wrap" v-if="dest">
        <table class="tbl">
          <thead><tr>
            <th class="rk m-hide">#</th><th>{{ t('flow.dest') }}</th><th class="m-hide">{{ t('flow.country') }}</th><th class="m-hide">{{ t('flow.mainApp') }}</th><th class="r">{{ t('flow.bytes') }}</th>
            <th class="r m-hide">{{ t('common.share') }}</th><th class="r">{{ t('common.hosts') }}</th><th class="m-hide" />
          </tr></thead>
          <tbody>
            <template v-for="(r, i) in destRows" :key="r.dest">
              <tr class="link" @click="toggle(r)">
                <td class="rk num faint m-hide">{{ i + 1 }}</td>
                <td class="rm"><div class="dn"><span :class="{ addr: r.ip }">{{ r.dest }}</span>
                  <span v-if="merge && r.names > 1" class="faint small"> · {{ t('flow.subdomains', { n: r.names }) }}</span>
                  <span v-if="r.ip" class="pill grey ipt">IP</span></div>
                  <div class="faint small dn" v-if="r.asn">AS{{ r.asn.asn }} {{ r.asn.name }}</div>
                  <div class="m-only faint small">{{ appName(r.app) }}<template v-if="r.country"> · {{ countryName(r.country) }}</template></div></td>
                <td class="m-hide nowrap">{{ countryName(r.country) || '-' }}</td>
                <td class="m-hide"><span class="tag"><span class="chip" :style="{ background: catColor(r.app.category) }" />{{ appName(r.app) }}</span></td>
                <td class="r num"><b>{{ bytes(r.bytes) }}</b></td>
                <td class="r share m-hide"><span class="num muted">{{ pct(r.bytes / (dest.range_total.total || 1)) }}</span>
                  <span class="bar"><i :style="{ width: (r.bytes / (dest.rows[0].bytes || 1) * 100) + '%' }" /></span></td>
                <td class="r num">{{ r.hosts }}</td>
                <td class="r m-hide"><Icon name="chevron" :size="16" class="chev" :class="{ open: open === r.dest }" /></td>
              </tr>
              <!-- 展开：访问这个目标的终端 -->
              <tr v-if="open === r.dest" class="sub">
                <td />
                <td colspan="7">
                  <div v-if="!who" class="muted small">{{ t('common.loading') }}</div>
                  <ul v-else class="who">
                    <li v-for="h in who" :key="h.key">
                      <router-link :to="`/hosts/${enc(h.key)}`" class="hl"><span class="dot" :class="{ on: h.online }" />{{ h.name }}</router-link>
                      <span class="faint addr small">{{ h.ip }}</span>
                      <span class="faint small names" v-if="merge">{{ h.names.join('、') }}</span>
                      <span class="sp" /><b class="num">{{ bytes(h.bytes) }}</b>
                    </li>
                  </ul>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
        <div v-if="!destRows.length" class="empty">{{ t('common.empty') }}</div>
      </div>
      <div v-else class="empty">{{ t('common.loading') }}</div>
    </div>

    <!-- 代理分流：sing-box 按 策略组 → 出口节点 的流量（debug9） -->
    <div class="panel" v-if="tab === 'proxy'">
      <div class="panel-b head">
        <div class="info-bar"><span class="ic">i</span><div><b>{{ t('flow.tab.proxy') }}</b><span>{{ t('flow.info.proxy') }}</span></div></div>
        <div v-if="px && !px.enabled" class="empty">{{ t('flow.pxOff') }} <router-link to="/settings?tab=sources" class="link">{{ t('flow.pxGo') }}</router-link></div>
        <div v-else-if="px && !px.ok && px.error" class="err">{{ px.error }}</div>
        <div class="sum" v-if="px && px.enabled">
          <div><span class="muted small">{{ t('flow.pxGroups') }}</span><b class="num accent">{{ pxGroups.length }}</b></div>
          <div><span class="muted small">{{ t('common.up') }}</span><b class="num up">{{ bytes(px.up) }}</b></div>
          <div><span class="muted small">{{ t('common.down') }}</span><b class="num down">{{ bytes(px.down) }}</b></div>
        </div>
      </div>
      <div class="tbl-wrap" v-if="px && px.enabled">
        <table class="tbl">
          <thead><tr><th>{{ t('flow.pxGroup') }} / {{ t('flow.pxNode') }}</th><th class="m-hide">{{ t('flow.pxApps') }}</th>
            <th class="r">{{ t('flow.bytes') }}</th><th class="r m-hide">{{ t('common.share') }}</th><th class="r m-hide">{{ t('flow.pxConns') }}</th></tr></thead>
          <tbody>
            <template v-for="g in pxGroups" :key="g.group">
              <tr class="grp">
                <td><b>{{ g.group }}</b><span class="faint small"> · {{ t('flow.pxNodes', { n: g.nodes.length }) }}</span></td>
                <td class="m-hide" /><td class="r num"><b>{{ bytes(g.total) }}</b></td>
                <td class="r share m-hide"><span class="num muted">{{ pct(g.total / pxTotal) }}</span>
                  <span class="bar"><i :style="{ width: (g.total / pxGroups[0].total * 100) + '%' }" /></span></td>
                <td class="r num m-hide">{{ g.conns }}</td>
              </tr>
              <tr v-for="n in g.nodes" :key="g.group + n.node">
                <td class="node"><span class="addr">{{ n.node }}</span>
                  <div class="m-only faint small">{{ n.apps.slice(0, 3).map(a => appName(a)).join('、') }}</div></td>
                <td class="m-hide"><span v-for="a in n.apps.slice(0, 4)" :key="a.id" class="tag ap"><span class="chip" :style="{ background: catColor(a.category) }" />{{ appName(a) }}
                  <span class="faint small num">{{ bytes(a.bytes) }}</span></span>
                  <span v-if="n.apps_count > 4" class="faint small">+{{ n.apps_count - 4 }}</span></td>
                <td class="r num small"><span class="up">↑{{ bytes(n.up) }}</span><br /><span class="down">↓{{ bytes(n.down) }}</span></td>
                <td class="r num muted m-hide">{{ pct(n.total / pxTotal) }}</td>
                <td class="r num muted m-hide">{{ n.conns }}</td>
              </tr>
            </template>
          </tbody>
        </table>
        <div v-if="!px.rows.length" class="empty">{{ t('flow.pxEmpty') }}</div>
      </div>
      <div v-else-if="!px" class="empty">{{ t('common.loading') }}</div>
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import http, { enc } from '../api.js'
import Icon from '../components/Icon.vue'
import RangeTabs from '../components/RangeTabs.vue'
import WorldMap from '../components/WorldMap.vue'
import { duration, exportCsv } from '../csv.js'
import { appName, bytes, catColor, countryName, pct, rate } from '../format.js'
import { ui } from '../state.js'

const TABS = ['live', 'dest', 'proxy']
const SRC_CLASS = { conn: 'ok', proxy: 'ok', pair: '', ip: 'grey', none: 'warn' }
const { t, locale } = useI18n()
const route = useRoute()
const router = useRouter()
const tab = computed(() => (TABS.includes(route.query.tab) ? route.query.tab : 'live'))
const setTab = k => router.replace({ query: k === 'live' ? {} : { tab: k } })
const err = ref('')
const proto = p => ({ 6: 'TCP', 17: 'UDP', 1: 'ICMP', 58: 'ICMPv6', 47: 'GRE', 50: 'ESP' }[p] || `IP/${p}`)

// ---------- 实时连接：10 秒刷新，可暂停 ----------
const live = ref(null)
const liveQ = ref('')
const paused = ref(false)
const limit = ref(100)
let timer = null
let qTimer = null
async function loadLive() {
  try {
    live.value = await http.get('/sessions', { params: { q: liveQ.value.trim() || undefined, limit: limit.value } })
    err.value = ''
  } catch (e) { err.value = e.message }
}
function tick() {
  if (document.hidden) return
  if (tab.value === 'live' && !paused.value) loadLive()
  else if (tab.value === 'proxy') loadPx()
}
onMounted(() => { timer = setInterval(tick, 10000) })
onBeforeUnmount(() => clearInterval(timer))
watch(liveQ, () => { clearTimeout(qTimer); qTimer = setTimeout(loadLive, 300) })
function exportLive() {
  exportCsv('rosdpi-sessions', [
    { label: t('flow.host'), value: s => s.host_name }, { label: t('hosts.ip'), value: s => s.host_ip },
    { label: t('flow.remote'), value: s => s.domain || '' }, { label: 'IP', value: s => s.remote },
    { label: t('flow.port'), value: s => `${proto(s.proto)} ${s.port || ''}` }, { label: t('apps.app'), value: s => appName(s.app) },
    { label: t('common.up') + ' bps', value: s => Math.round(s.rate_up * 8) }, { label: t('common.down') + ' bps', value: s => Math.round(s.rate_down * 8) },
    { label: t('common.up') + ' (B)', value: s => s.up }, { label: t('common.down') + ' (B)', value: s => s.down },
    { label: t('flow.duration') + ' (s)', value: s => s.last - s.start }, { label: t('flow.source'), value: s => t('flow.src.' + s.source) },
  ], live.value.sessions)
}

// ---------- 访问目标排行 ----------
const dest = ref(null)
const destQ = ref('')
const merge = ref(true)
const kind = ref('all')
const open = ref('')
const who = ref(null)
async function loadDest() {
  open.value = ''
  try {
    dest.value = await http.get('/destinations', { params: { range: ui.range, q: destQ.value.trim() || undefined, merge: merge.value, kind: kind.value } })
    err.value = ''
  } catch (e) { err.value = e.message }
}
// 国家 / 地区分布：按排行里的目标汇总，点一个只看该国家的目标
const country = ref('')
// “未知”（查不到 IP 的域名）放最后
const countries = computed(() => (dest.value ? dest.value.countries : [])
  .map(c => ({ ...c, name: countryName(c.cc) || t('flow.unknownCountry') }))
  .sort((a, b) => (a.cc === '-') - (b.cc === '-') || b.bytes - a.bytes).slice(0, 20))
const maxCountry = computed(() => Math.max(1, ...countries.value.map(c => c.bytes)))
const countryTotal = computed(() => (dest.value ? dest.value.countries.reduce((n, c) => n + c.bytes, 0) : 0) || 1)
const destRows = computed(() => (dest.value ? dest.value.rows.filter(r => !country.value || (r.country || '-') === country.value) : []))

// ---------- 代理分流 ----------
const px = ref(null)
async function loadPx() {
  try { px.value = await http.get('/proxy/routes'); err.value = '' } catch (e) { err.value = e.message }
}
const pxTotal = computed(() => (px.value ? px.value.up + px.value.down : 0) || 1)
const pxGroups = computed(() => {
  const m = new Map()
  for (const r of px.value ? px.value.rows : []) {
    const g = m.get(r.group) || { group: r.group, total: 0, conns: 0, nodes: [] }
    g.total += r.total
    g.conns += r.conns
    g.nodes.push(r)
    m.set(r.group, g)
  }
  return [...m.values()].sort((a, b) => b.total - a.total)
})

async function toggle(r) {
  if (open.value === r.dest) { open.value = ''; return }
  open.value = r.dest
  who.value = null
  err.value = ''
  try {
    who.value = await http.get('/destinations/hosts', { params: { dest: r.dest, range: ui.range, merge: merge.value && !r.ip } })
  } catch (e) { err.value = e.message; open.value = '' }  // 失败就收起，不留一个空转的 loading
}
function exportDest() {
  exportCsv('rosdpi-destinations', [
    { label: t('flow.dest'), value: r => r.dest }, { label: t('flow.country'), value: r => countryName(r.country) },
    { label: t('flow.mainApp'), value: r => appName(r.app) },
    { label: t('flow.bytes') + ' (B)', value: r => r.bytes }, { label: t('common.share'), value: r => pct(r.bytes / (dest.value.range_total.total || 1)) },
    { label: t('common.hosts'), value: r => r.hosts },
  ], destRows.value)
}

watch([tab, () => ui.range, merge, kind], () => {
  country.value = ''
  if (tab.value === 'dest') loadDest()
  else if (tab.value === 'proxy') loadPx()
  else loadLive()
}, { immediate: true })
</script>

<style scoped>
.tabs button { font-size: 15px; padding: 8px 14px 11px; }
.more-row { display: flex; justify-content: center; padding: 12px; }
.head { display: grid; gap: 14px; padding-bottom: 6px; }
.sum { display: flex; gap: 12px; flex-wrap: wrap; }
.sum div { background: var(--sunk); border-radius: 12px; padding: 10px 16px; display: grid; min-width: 150px; }
.sum b { font-size: 24px; font-weight: 600; line-height: 1.2; }
.search { width: 240px; height: 32px; }
.chk { display: flex; gap: 6px; align-items: center; color: var(--muted); font-size: 13px; cursor: pointer; }
.hl { display: inline-flex; align-items: center; gap: 8px; font-weight: 500; }
.hl:hover { color: var(--brand-ink); }
.small { font-size: 12px; }
.rm { max-width: 380px; }
.dn { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ipt { height: 18px; font-size: 11px; margin-left: 6px; }
.rk { width: 36px; padding-right: 0; }
.share { min-width: 120px; }
.bar { display: block; height: 4px; margin: 5px 0 0 auto; width: 90px; border-radius: 2px; background: var(--sunk); }
.bar i { display: block; height: 100%; border-radius: 2px; background: var(--accent); }
.chev { color: var(--faint); transition: transform .15s; }
.chev.open { transform: rotate(90deg); }
tr.sub td { background: var(--sunk); white-space: normal; }
.who { list-style: none; margin: 0; padding: 0; display: grid; gap: 6px; }
.who li { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.who .sp { flex: 1; }
.names { max-width: 420px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.route { color: var(--brand-ink); }
.nowrap { white-space: nowrap; }
.ctry { padding-top: 0; }
.mapgrid { display: grid; grid-template-columns: minmax(0, 2.2fr) minmax(240px, 1fr); gap: 18px; margin-top: 10px; align-items: start; }
.clist { display: grid; gap: 2px; max-height: 340px; overflow-y: auto; align-content: start; }
.cr { display: grid; grid-template-columns: 22px minmax(0, 1fr) auto 46px; grid-template-rows: auto 4px; column-gap: 8px; row-gap: 4px;
  align-items: center; background: none; border: 0; border-radius: 8px; padding: 7px 8px; font: inherit; font-size: 13px; color: var(--ink);
  cursor: pointer; text-align: left; }
.cr:hover, .cr.on { background: var(--sunk); }
.cr.on .cn { color: var(--brand-ink); }
.cr .rk { grid-column: 1; grid-row: 1 / 3; color: var(--faint); font-size: 12px; }
.cr .cn { grid-column: 2; grid-row: 1; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; display: flex; align-items: center; gap: 6px; }
.cr .v { grid-column: 3; grid-row: 1; font-weight: 600; }
.cr .p { grid-column: 4; grid-row: 1; text-align: right; font-size: 12px; }
.cr .bar { grid-column: 2 / 5; grid-row: 2; height: 4px; margin: 0; width: auto; border-radius: 2px; background: var(--sunk); }
.cr .bar i { background: var(--accent); }
.cr.unk { color: var(--muted); margin-top: 6px; border-top: 1px dashed var(--line); border-radius: 0; }
.cr.unk .bar i { background: var(--line-strong); }
.home { height: 18px; font-size: 10px; }
.unk-note { padding: 2px 8px 0 38px; line-height: 1.5; }
@media (max-width: 900px) { .mapgrid { grid-template-columns: 1fr; } .clist { max-height: none; } }
.cc { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 2px 8px; align-items: center; text-align: left; background: var(--sunk);
  border: 1px solid transparent; border-radius: 10px; padding: 8px 12px; cursor: pointer; color: var(--ink); font: inherit; font-size: 13px; }
.cc:hover, .cc.on { border-color: var(--brand-ink); }
.cc .cn { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 500; }
.cc .bar { margin: 0; width: 100%; background: var(--panel); }
.grp td { background: var(--sunk); }
.node { padding-left: 28px !important; }
.ap { margin-right: 10px; }
@media (max-width: 640px) { .search { width: 100%; } .node { padding-left: 14px !important; } }
</style>
