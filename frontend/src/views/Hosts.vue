<template>
  <div>
    <!-- 子标签条：在线终端 / 全部终端 / DHCP 租约 / 命名管理 -->
    <div class="page-h">
      <div class="seg tabs" role="tablist">
        <button v-for="k in TABS" :key="k" role="tab" :aria-selected="tab === k" :class="{ on: tab === k }" @click="setTab(k)">
          {{ t('hosts.tab.' + k) }}<span class="num faint cnt" v-if="counts[k] != null">{{ counts[k] }}</span></button>
      </div>
      <span class="sp" />
      <input v-if="tab === 'online' || tab === 'all' || tab === 'dhcp'" class="input search" v-model="q" :placeholder="t('hosts.search')" :aria-label="t('hosts.search')" />
    </div>
    <div v-if="error" class="err">{{ error }}</div>

    <!-- 终端列表 -->
    <div class="panel" v-if="tab === 'online' || tab === 'all'">
      <div class="panel-b head">
        <div class="info-bar"><span class="ic">i</span><div><b>{{ t('hosts.tab.' + tab) }}</b><span>{{ t('hosts.info.' + tab) }}</span></div></div>
        <div class="sec">{{ t('hosts.list') }}<span class="sp" />
          <button class="btn sm" @click="exportHosts"><Icon name="download" :size="15" />{{ t('common.export') }}</button>
          <button class="btn sm" @click="refresh"><Icon name="refresh" :size="15" />{{ t('common.refresh') }}</button></div>
      </div>
      <div class="tbl-wrap">
        <table class="tbl">
          <thead>
            <tr>
              <th class="sort" @click="sortBy('name')">{{ t('common.name') }} {{ arrow('name') }}</th>
              <th class="sort m-hide" @click="sortBy('ip')">{{ t('hosts.ip') }} {{ arrow('ip') }}</th>
              <th class="m-hide">{{ t('hosts.mac') }}</th>
              <th class="r sort m-hide" @click="sortBy('uptime')" v-if="tab === 'online'">{{ t('hosts.uptime') }} {{ arrow('uptime') }}</th>
              <th class="r sort m-hide" @click="sortBy('conns')" :title="t('hosts.connsHint')">{{ t('hosts.conns') }} {{ arrow('conns') }}</th>
              <th class="r sort" @click="sortBy('rate')">{{ t('common.rate') }} {{ arrow('rate') }}</th>
              <th class="r sort" @click="sortBy('today')">{{ t('range.today') }} {{ arrow('today') }}</th>
              <th class="r sort m-hide" @click="sortBy('week')">{{ t('range.week') }} {{ arrow('week') }}</th>
              <th class="r sort m-hide" @click="sortBy('month')">{{ t('range.month') }} {{ arrow('month') }}</th>
              <th class="m-hide">{{ t('hosts.topApp') }}</th>
              <th class="sort m-hide" @click="sortBy('last')" v-if="tab === 'all'">{{ t('hosts.lastSeen') }} {{ arrow('last') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="h in shown" :key="h.key" class="link" @click="$router.push(`/hosts/${enc(h.key)}`)">
              <td><span class="nm"><span class="dot" :class="{ on: h.online }" />
                <span class="dev" :title="t('dev.' + (h.dtype || 'unknown')) + (h.vendor ? ' · ' + h.vendor : '')"><Icon :name="'dev-' + (h.dtype || 'unknown')" :size="16" /></span>{{ h.name }}
                <router-link v-if="h.person" :to="`/people/${h.person.id}`" class="pill per" @click.stop>{{ h.person.name }}</router-link>
                <span v-if="h.alias_by" class="pill grey by" :title="t('hosts.byHint.' + h.alias_by)">{{ h.alias_by.toUpperCase() }}</span>
                <span class="faint hn m-hide" v-if="h.alias && h.hostname && h.hostname !== h.alias">{{ h.hostname }}</span>
                <button class="btn sm ghost ren" :title="t('hosts.rename')" :aria-label="t('hosts.rename')" @click.stop="rename(h)"><Icon name="edit" :size="14" /></button></span>
                <div class="m-only faint addr small">{{ h.ip }}<span v-if="h.top_app"> · {{ appName(h.top_app) }}</span></div></td>
              <td class="addr m-hide">{{ h.ip }}</td>
              <td class="addr faint m-hide">{{ h.mac || '-' }}</td>
              <td class="r num m-hide" v-if="tab === 'online'">{{ h.online_since ? duration(now - h.online_since, locale === 'zh') : '-' }}</td>
              <td class="r num m-hide">{{ h.conns || 0 }}</td>
              <td class="r num small"><span class="up">↑{{ rate(h.rate_up) }}</span><br /><span class="down">↓{{ rate(h.rate_down) }}</span></td>
              <td class="r num">{{ bytes(h.today.total) }}<span class="mini"><i :style="{ width: (h.today.total / maxToday * 100) + '%' }" /></span></td>
              <td class="r num m-hide">{{ bytes(h.week.total) }}</td>
              <td class="r num m-hide">{{ bytes(h.month.total) }}</td>
              <td class="m-hide"><span v-if="h.top_app" class="tag"><span class="chip" :style="{ background: catColor(h.top_app.category) }" />{{ appName(h.top_app) }}</span></td>
              <td class="muted small m-hide" v-if="tab === 'all'">{{ ago(h.last_seen) }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="!shown.length" class="empty">{{ loading ? t('common.loading') : t('common.empty') }}</div>
      </div>
    </div>

    <!-- DHCP 租约（来自 RouterOS） -->
    <div class="panel" v-if="tab === 'dhcp'">
      <div class="panel-b head">
        <div class="info-bar"><span class="ic">i</span><div><b>{{ t('hosts.tab.dhcp') }}</b><span>{{ t('hosts.info.dhcp') }}</span></div></div>
        <div class="pools" v-if="dhcp && dhcp.pools.length">
          <div v-for="p in dhcp.pools" :key="p.server" class="pool">
            <div class="p-h"><b>{{ p.server }}</b><span class="faint small">{{ p.interface }} · {{ p.pool }}</span></div>
            <div class="meter" :class="p.size && p.used / p.size >= .9 ? 'bad' : p.size && p.used / p.size >= .75 ? 'warn' : ''"><i :style="{ width: (p.size ? p.used / p.size * 100 : 0) + '%' }" /></div>
            <div class="small muted">{{ t('hosts.poolUse', { used: p.used, size: p.size, free: Math.max(p.size - p.used, 0) }) }}</div>
          </div>
        </div>
        <div class="sec">{{ t('hosts.leaseList') }}<span class="sp" />
          <button class="btn sm" @click="exportLeases" :disabled="!leasesShown.length"><Icon name="download" :size="15" />{{ t('common.export') }}</button>
          <button class="btn sm" @click="loadDhcp"><Icon name="refresh" :size="15" />{{ t('common.refresh') }}</button></div>
      </div>
      <div class="tbl-wrap" v-if="dhcp && dhcp.enabled">
        <table class="tbl">
          <thead><tr><th>{{ t('common.name') }}</th><th>{{ t('hosts.ip') }}</th><th class="m-hide">{{ t('hosts.mac') }}</th><th class="m-hide">{{ t('hosts.leaseType') }}</th>
            <th>{{ t('hosts.leaseStatus') }}</th><th class="m-hide">{{ t('hosts.expires') }}</th><th class="m-hide">{{ t('hosts.server') }}</th></tr></thead>
          <tbody>
            <tr v-for="l in leasesShown" :key="l.mac + l.address" :class="{ link: l.host_key }" @click="l.host_key && $router.push(`/hosts/${enc(l.host_key)}`)">
              <td>{{ l.alias || l.comment || l.host_name || '-' }}
                <span class="faint hn" v-if="(l.alias || l.comment) && l.host_name && l.host_name !== (l.alias || l.comment)">{{ l.host_name }}</span>
                <div class="m-only faint addr small">{{ l.mac }}</div></td>
              <td class="addr">{{ l.address }}</td>
              <td class="addr faint m-hide">{{ l.mac }}</td>
              <td class="m-hide"><span class="pill" :class="l.dynamic ? 'grey' : ''">{{ l.dynamic ? t('hosts.dynamic') : t('hosts.static') }}</span></td>
              <td><span class="pill" :class="l.status === 'bound' ? 'ok' : 'grey'">{{ l.status || '-' }}</span></td>
              <td class="num muted m-hide">{{ l.expires_after || '-' }}</td>
              <td class="muted m-hide">{{ l.server }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="!leasesShown.length" class="empty">{{ t('common.empty') }}</div>
      </div>
      <div v-else-if="dhcp" class="empty">{{ t('hosts.dhcpNeedsRos') }} <router-link to="/settings#guide" class="link">{{ t('overview.openGuide') }}</router-link></div>
    </div>

    <!-- 命名管理：按 MAC 或按 IP 给终端起名，可以提前给还没上线的设备命名 -->
    <div class="panel" v-if="tab === 'names'">
      <div class="panel-b head">
        <div class="info-bar"><span class="ic">i</span><div><b>{{ t('hosts.names') }}</b><span>{{ t('hosts.namesHint') }}</span></div></div>
        <div class="sec" v-if="isAdmin">{{ t('common.add') }}</div>
        <form class="nf" v-if="isAdmin" @submit.prevent="addName">
          <div class="seg" role="radiogroup" :aria-label="t('hosts.nameBy')">
            <button v-for="k in ['mac', 'ip']" :key="k" type="button" role="radio" :aria-checked="nf.kind === k" :class="{ on: nf.kind === k }" @click="nf.kind = k">{{ t('hosts.by.' + k) }}</button>
          </div>
          <input id="nf-value" class="input addr v" v-model="nf.value" :placeholder="nf.kind === 'mac' ? 'AA:BB:CC:DD:EE:FF' : '192.168.88.20'" :aria-label="t('hosts.' + nf.kind)" />
          <input id="nf-name" ref="nameInput" class="input n" v-model="nf.name" :placeholder="t('hosts.aliasPlaceholder')" :aria-label="t('hosts.alias')" />
          <button class="btn primary" :disabled="!nf.value.trim() || !nf.name.trim()">{{ nfSaved ? t('common.saved') : t('common.save') }}</button>
          <span class="faint small hint">{{ t('hosts.byHint.' + nf.kind) }}</span>
          <div class="err" v-if="nfErr">{{ nfErr }}</div>
        </form>
        <div class="sec">{{ t('hosts.nameList') }}<span class="faint small">{{ names.length }}</span></div>
      </div>
      <div class="tbl-wrap" v-if="names.length">
        <table class="tbl">
          <thead><tr><th>{{ t('hosts.nameBy') }}</th><th>{{ t('hosts.address') }}</th><th>{{ t('hosts.alias') }}</th><th>{{ t('hosts.matched') }}</th><th /></tr></thead>
          <tbody>
            <tr v-for="n in names" :key="n.kind + n.value">
              <td><span class="pill grey">{{ n.kind.toUpperCase() }}</span></td>
              <td class="addr">{{ n.value }}</td>
              <td><b>{{ n.name }}</b></td>
              <td class="muted small">
                <router-link v-if="n.host" :to="`/hosts/${enc(n.host.key)}`" class="link">{{ n.kind === 'mac' ? n.host.ip : (n.host.mac || n.host.ip) }}<span v-if="n.host.hostname"> · {{ n.host.hostname }}</span></router-link>
                <span v-else>{{ t('hosts.notSeen') }}</span>
              </td>
              <td class="r" v-if="isAdmin">
                <button class="btn sm ghost" @click="editName(n)">{{ t('common.edit') }}</button>
                <button class="btn sm danger" @click="delName(n)">{{ t('common.delete') }}</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="empty">{{ t('common.empty') }}</div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import http, { enc, isAdmin } from '../api.js'
import Icon from '../components/Icon.vue'
import { duration, exportCsv } from '../csv.js'
import { ago, appName, bytes, catColor, rate } from '../format.js'
import { usePoll } from '../poll.js'

const TABS = ['online', 'all', 'dhcp', 'names']
const { t, locale } = useI18n()
const route = useRoute()
const router = useRouter()
const tab = computed(() => (TABS.includes(route.query.tab) ? route.query.tab : 'online'))
const setTab = k => router.replace({ query: k === 'online' ? {} : { tab: k } })

const rows = ref([])
const q = ref('')
const sort = ref({ key: 'today', desc: true })
const now = ref(Date.now() / 1000)
const { loading, error, reload: refresh } = usePoll(async () => {
  rows.value = await http.get('/hosts')
  now.value = Date.now() / 1000
}, 30000)

const counts = computed(() => ({
  online: rows.value.filter(h => h.online).length, all: rows.value.length,
  dhcp: dhcp.value && dhcp.value.enabled ? dhcp.value.leases.length : null, names: names.value.length,
}))
const maxToday = computed(() => Math.max(1, ...rows.value.map(h => h.today.total)))
const ipNum = ip => (ip || '').split('.').reduce((s, x) => s * 256 + (+x || 0), 0)
const keyFn = {
  name: h => (h.name || '').toLowerCase(), ip: h => ipNum(h.ip), rate: h => h.rate_up + h.rate_down,
  today: h => h.today.total, week: h => h.week.total, month: h => h.month.total, last: h => h.last_seen || 0,
  uptime: h => (h.online_since ? now.value - h.online_since : -1), conns: h => h.conns || 0,
}
const match = (s, ...vals) => !s || vals.some(v => v && String(v).toLowerCase().includes(s))

const shown = computed(() => {
  const s = q.value.trim().toLowerCase()
  const list = rows.value.filter(h => (tab.value === 'all' || h.online) && match(s, h.name, h.ip, h.mac, h.hostname, h.alias))
  const f = keyFn[sort.value.key]
  const dir = sort.value.desc ? -1 : 1
  return [...list].sort((a, b) => (f(a) > f(b) ? dir : f(a) < f(b) ? -dir : 0))
})

function sortBy(k) {
  sort.value = { key: k, desc: sort.value.key === k ? !sort.value.desc : k !== 'name' && k !== 'ip' }
}
const arrow = k => (sort.value.key === k ? (sort.value.desc ? '↓' : '↑') : '')

function exportHosts() {
  exportCsv(tab.value === 'online' ? 'rosdpi-online-hosts' : 'rosdpi-hosts', [
    { label: t('common.name'), value: h => h.name }, { label: t('hosts.ip'), value: h => h.ip },
    { label: t('hosts.mac'), value: h => h.mac }, { label: t('hosts.hostname'), value: h => h.hostname },
    { label: t('common.online'), value: h => (h.online ? 1 : 0) },
    { label: t('hosts.uptime') + ' (s)', value: h => (h.online_since ? Math.round(now.value - h.online_since) : '') },
    { label: t('hosts.conns'), value: h => h.conns || 0 },
    { label: t('common.up') + ' bps', value: h => Math.round(h.rate_up * 8) }, { label: t('common.down') + ' bps', value: h => Math.round(h.rate_down * 8) },
    { label: t('range.today') + ' (B)', value: h => h.today.total }, { label: t('range.week') + ' (B)', value: h => h.week.total },
    { label: t('range.month') + ' (B)', value: h => h.month.total }, { label: t('hosts.topApp'), value: h => (h.top_app ? appName(h.top_app) : '') },
    { label: t('hosts.lastSeen'), value: h => (h.last_seen ? new Date(h.last_seen * 1000).toLocaleString() : '') },
  ], shown.value)
}

// ---------- DHCP 租约 ----------
const dhcp = ref(null)
async function loadDhcp() { try { dhcp.value = await http.get('/dhcp/leases') } catch (e) { error.value = e.message } }
watch(tab, k => { if (k === 'dhcp' && !dhcp.value) loadDhcp() }, { immediate: true })
const leasesShown = computed(() => {
  const s = q.value.trim().toLowerCase()
  return (dhcp.value?.leases || []).filter(l => match(s, l.alias, l.comment, l.host_name, l.address, l.mac))
    .sort((a, b) => ipNum(a.address) - ipNum(b.address))
})
function exportLeases() {
  exportCsv('rosdpi-dhcp-leases', [
    { label: t('common.name'), value: l => l.alias || l.comment || l.host_name }, { label: t('hosts.hostname'), value: l => l.host_name },
    { label: t('hosts.ip'), value: l => l.address }, { label: t('hosts.mac'), value: l => l.mac },
    { label: t('hosts.leaseType'), value: l => (l.dynamic ? t('hosts.dynamic') : t('hosts.static')) },
    { label: t('hosts.leaseStatus'), value: l => l.status }, { label: t('hosts.expires'), value: l => l.expires_after },
    { label: t('hosts.server'), value: l => l.server },
  ], leasesShown.value)
}

// ---------- 命名管理 ----------
const names = ref([])
const nf = reactive({ kind: 'mac', value: '', name: '' })
const nfErr = ref('')
const nfSaved = ref(false)
const nameInput = ref(null)

async function loadNames() {
  try { names.value = await http.get('/names') } catch (e) { nfErr.value = e.message }
}
onMounted(loadNames)

async function rename(h) {
  // 默认沿用当前的命名方式；没有命名过时有 MAC 按 MAC
  const kind = h.alias_by || (h.mac ? 'mac' : 'ip')
  Object.assign(nf, { kind, value: kind === 'mac' ? h.mac : h.ip, name: h.alias || '' })
  nfErr.value = ''
  setTab('names')
  await nextTick()
  window.scrollTo({ top: 0, behavior: 'smooth' })
  nameInput.value && nameInput.value.focus()
}
function editName(n) { rename({ alias_by: n.kind, mac: n.kind === 'mac' ? n.value : null, ip: n.kind === 'ip' ? n.value : null, alias: n.name }) }

async function addName() {
  nfErr.value = ''
  try {
    names.value = await http.put('/names', { kind: nf.kind, value: nf.value.trim(), name: nf.name.trim() })
    nf.value = nf.name = ''
    nfSaved.value = true
    setTimeout(() => (nfSaved.value = false), 1500)
    refresh()
  } catch (e) { nfErr.value = e.message }
}
async function delName(n) {
  if (!confirm(t('common.confirmDelete'))) return
  nfErr.value = ''
  try {
    names.value = await http.delete(`/names/${n.kind}/${enc(n.value)}`)
    refresh()
  } catch (e) { nfErr.value = e.message }
}
</script>

<style scoped>
.dev { color: var(--muted); display: inline-flex; margin-right: 6px; vertical-align: -3px; }
.per { margin-left: 6px; height: 20px; font-size: 11px; }
.tabs button { font-size: 15px; padding: 8px 14px 11px; }
.cnt { margin-left: 6px; font-size: 13px; }
.search { width: 260px; }
.head { display: grid; gap: 14px; padding-bottom: 6px; }
.nm { display: inline-flex; align-items: center; gap: 8px; }
.by { height: 18px; font: 600 10.5px/1 var(--cond); letter-spacing: .06em; padding: 0 5px; }
.hn { font-size: 12px; }
.small { font-size: 12px; line-height: 1.35; }
.ren { height: 24px; padding: 0 5px; opacity: 0; }
tr:hover .ren, .ren:focus-visible { opacity: 1; }
@media (hover: none) { .ren { opacity: .7; } }
.mini { display: block; height: 3px; margin: 4px 0 0 auto; width: 72px; border-radius: 2px; background: var(--sunk); }
.mini i { display: block; height: 100%; margin-left: auto; border-radius: 2px; background: var(--down); }

.pools { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; }
.pool { background: var(--sunk); border-radius: 12px; padding: 12px 14px; display: grid; gap: 8px; }
.p-h { display: flex; gap: 10px; align-items: baseline; }

.nf { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.nf .v { width: 200px; }
.nf .n { width: 220px; }
.nf .hint { flex-basis: 100%; }
@media (max-width: 640px) { .search, .nf .v, .nf .n { width: 100%; } .mini { display: none; } }
</style>
