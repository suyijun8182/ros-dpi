<template>
  <div>
    <!-- 子标签：实时连接 / 访问目标排行 -->
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
            <th>{{ t('flow.host') }}</th><th>{{ t('flow.remote') }}</th><th>{{ t('flow.port') }}</th><th>{{ t('apps.app') }}</th>
            <th class="r">{{ t('common.rate') }}</th><th class="r">{{ t('flow.bytes') }}</th><th class="r">{{ t('flow.duration') }}</th><th>{{ t('flow.source') }}</th>
          </tr></thead>
          <tbody>
            <tr v-for="s in live.sessions" :key="s.host + s.remote + s.port + s.proto + s.host_port">
              <td><router-link :to="`/hosts/${enc(s.host)}`" class="hl"><span class="dot" :class="{ on: s.online }" />{{ s.host_name }}</router-link>
                <div class="faint addr small">{{ s.host_ip }}<span v-if="s.host_port">:{{ s.host_port }}</span></div></td>
              <td class="rm"><div class="dn" :title="s.domain || s.remote">{{ s.domain || s.remote }}</div><div class="faint addr small" v-if="s.domain">{{ s.remote }}</div></td>
              <td class="num"><span class="pill grey">{{ proto(s.proto) }}</span> {{ s.port || '' }}</td>
              <td><router-link :to="`/apps/${enc(s.app.id)}`" class="tag"><span class="chip" :style="{ background: catColor(s.app.category) }" />{{ appName(s.app) }}</router-link></td>
              <td class="r num small"><span class="up">↑{{ rate(s.rate_up) }}</span><br /><span class="down">↓{{ rate(s.rate_down) }}</span></td>
              <td class="r num small"><span class="up">↑{{ bytes(s.up) }}</span><br /><span class="down">↓{{ bytes(s.down) }}</span></td>
              <td class="r num muted">{{ duration(s.last - s.start, locale === 'zh') }}</td>
              <td><span class="pill" :class="SRC_CLASS[s.source]" :title="t('settings.matchKind.' + s.source)">{{ t('flow.src.' + s.source) }}</span></td>
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
      <div class="tbl-wrap" v-if="dest">
        <table class="tbl">
          <thead><tr>
            <th class="rk">#</th><th>{{ t('flow.dest') }}</th><th>{{ t('flow.mainApp') }}</th><th class="r">{{ t('flow.bytes') }}</th>
            <th class="r">{{ t('common.share') }}</th><th class="r">{{ t('common.hosts') }}</th><th />
          </tr></thead>
          <tbody>
            <template v-for="(r, i) in dest.rows" :key="r.dest">
              <tr class="link" @click="toggle(r)">
                <td class="rk num faint">{{ i + 1 }}</td>
                <td class="rm"><div class="dn"><span :class="{ addr: r.ip }">{{ r.dest }}</span>
                  <span v-if="merge && r.names > 1" class="faint small"> · {{ t('flow.subdomains', { n: r.names }) }}</span>
                  <span v-if="r.ip" class="pill grey ipt">IP</span></div></td>
                <td><span class="tag"><span class="chip" :style="{ background: catColor(r.app.category) }" />{{ appName(r.app) }}</span></td>
                <td class="r num"><b>{{ bytes(r.bytes) }}</b></td>
                <td class="r share"><span class="num muted">{{ pct(r.bytes / (dest.range_total.total || 1)) }}</span>
                  <span class="bar"><i :style="{ width: (r.bytes / (dest.rows[0].bytes || 1) * 100) + '%' }" /></span></td>
                <td class="r num">{{ r.hosts }}</td>
                <td class="r"><Icon name="chevron" :size="16" class="chev" :class="{ open: open === r.dest }" /></td>
              </tr>
              <!-- 展开：访问这个目标的终端 -->
              <tr v-if="open === r.dest" class="sub">
                <td />
                <td colspan="6">
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
        <div v-if="!dest.rows.length" class="empty">{{ t('common.empty') }}</div>
      </div>
      <div v-else class="empty">{{ t('common.loading') }}</div>
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
import { duration, exportCsv } from '../csv.js'
import { appName, bytes, catColor, pct, rate } from '../format.js'
import { ui } from '../state.js'

const TABS = ['live', 'dest']
const SRC_CLASS = { conn: 'ok', pair: '', ip: 'grey', none: 'warn' }
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
function tick() { if (tab.value === 'live' && !paused.value && !document.hidden) loadLive() }
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
async function toggle(r) {
  if (open.value === r.dest) { open.value = ''; return }
  open.value = r.dest
  who.value = null
  who.value = await http.get('/destinations/hosts', { params: { dest: r.dest, range: ui.range, merge: merge.value && !r.ip } })
}
function exportDest() {
  exportCsv('rosdpi-destinations', [
    { label: t('flow.dest'), value: r => r.dest }, { label: t('flow.mainApp'), value: r => appName(r.app) },
    { label: t('flow.bytes') + ' (B)', value: r => r.bytes }, { label: t('common.share'), value: r => pct(r.bytes / (dest.value.range_total.total || 1)) },
    { label: t('common.hosts'), value: r => r.hosts },
  ], dest.value.rows)
}

watch([tab, () => ui.range, merge, kind], () => { if (tab.value === 'dest') loadDest(); else loadLive() }, { immediate: true })
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
@media (max-width: 640px) { .search { width: 100%; } }
</style>
