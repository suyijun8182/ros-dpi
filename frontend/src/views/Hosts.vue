<template>
  <div>
    <div class="page-h">
      <h1>{{ t('hosts.title') }}</h1>
      <span class="muted" v-if="rows.length">{{ t('hosts.count', { n: rows.length, m: onlineN }) }}</span>
      <span class="sp" />
      <label class="chk"><input type="checkbox" v-model="onlineOnly" /> {{ t('hosts.onlineOnly') }}</label>
      <input class="input search" v-model="q" :placeholder="t('hosts.search')" />
      <button class="btn" :class="{ primary: showNames }" @click="toggleNames">{{ t('hosts.names') }}<span class="faint num" v-if="names.length && !showNames"> {{ names.length }}</span></button>
    </div>
    <div v-if="error" class="err">{{ error }}</div>

    <!-- 命名管理：按 MAC 或按 IP 给终端起名，可以提前给还没上线的设备命名 -->
    <div class="panel names" v-if="showNames">
      <div class="panel-h"><h2>{{ t('hosts.names') }}</h2><span class="faint small">{{ t('hosts.namesHint') }}</span></div>
      <form class="panel-b nf" @submit.prevent="addName">
        <div class="seg" role="radiogroup" :aria-label="t('hosts.nameBy')">
          <button v-for="k in ['mac', 'ip']" :key="k" type="button" role="radio" :aria-checked="nf.kind === k" :class="{ on: nf.kind === k }" @click="nf.kind = k">{{ t('hosts.by.' + k) }}</button>
        </div>
        <input class="input addr v" v-model="nf.value" :placeholder="nf.kind === 'mac' ? 'AA:BB:CC:DD:EE:FF' : '192.168.88.20'" :aria-label="t('hosts.' + nf.kind)" />
        <input ref="nameInput" class="input n" v-model="nf.name" :placeholder="t('hosts.aliasPlaceholder')" :aria-label="t('hosts.alias')" />
        <button class="btn primary" :disabled="!nf.value.trim() || !nf.name.trim()">{{ nfSaved ? t('common.saved') : t('common.save') }}</button>
        <span class="faint small hint">{{ t('hosts.byHint.' + nf.kind) }}</span>
        <div class="err" v-if="nfErr">{{ nfErr }}</div>
      </form>
      <div class="tbl-wrap" v-if="names.length">
        <table class="tbl">
          <thead><tr><th>{{ t('hosts.nameBy') }}</th><th>{{ t('hosts.address') }}</th><th>{{ t('hosts.alias') }}</th><th>{{ t('hosts.matched') }}</th><th /></tr></thead>
          <tbody>
            <tr v-for="n in names" :key="n.kind + n.value">
              <td><span class="kind">{{ n.kind.toUpperCase() }}</span></td>
              <td class="addr">{{ n.value }}</td>
              <td><b>{{ n.name }}</b></td>
              <td class="muted small">
                <router-link v-if="n.host" :to="`/hosts/${enc(n.host.key)}`" class="lk">{{ n.kind === 'mac' ? n.host.ip : (n.host.mac || n.host.ip) }}<span v-if="n.host.hostname"> · {{ n.host.hostname }}</span></router-link>
                <span v-else>{{ t('hosts.notSeen') }}</span>
              </td>
              <td class="r">
                <button class="btn sm ghost" @click="editName(n)">{{ t('common.edit') }}</button>
                <button class="btn sm danger" @click="delName(n)">{{ t('common.delete') }}</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div class="panel">
      <div class="tbl-wrap">
        <table class="tbl">
          <thead>
            <tr>
              <th class="sort" @click="sortBy('name')">{{ t('common.name') }} {{ arrow('name') }}</th>
              <th class="sort" @click="sortBy('ip')">{{ t('hosts.ip') }} {{ arrow('ip') }}</th>
              <th>{{ t('hosts.mac') }}</th>
              <th class="r sort" @click="sortBy('rate')">{{ t('common.rate') }} {{ arrow('rate') }}</th>
              <th class="r sort" @click="sortBy('today')">{{ t('range.today') }} {{ arrow('today') }}</th>
              <th class="r sort" @click="sortBy('week')">{{ t('range.week') }} {{ arrow('week') }}</th>
              <th class="r sort" @click="sortBy('month')">{{ t('range.month') }} {{ arrow('month') }}</th>
              <th>{{ t('hosts.topApp') }}</th>
              <th class="sort" @click="sortBy('last')">{{ t('hosts.lastSeen') }} {{ arrow('last') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="h in shown" :key="h.key" class="link" @click="$router.push(`/hosts/${enc(h.key)}`)">
              <td><span class="nm"><span class="dot" :class="{ on: h.online }" />{{ h.name }}
                <span v-if="h.alias_by" class="kind" :title="t('hosts.byHint.' + h.alias_by)">{{ h.alias_by.toUpperCase() }}</span>
                <span class="faint hn" v-if="h.alias && h.hostname">{{ h.hostname }}</span>
                <button class="btn sm ghost ren" :title="t('hosts.rename')" :aria-label="t('hosts.rename')" @click.stop="rename(h)">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>
                </button></span></td>
              <td class="addr">{{ h.ip }}</td>
              <td class="addr faint">{{ h.mac || '-' }}</td>
              <td class="r num small"><span class="down">↓{{ rate(h.rate_down) }}</span><br /><span class="up">↑{{ rate(h.rate_up) }}</span></td>
              <td class="r num">{{ bytes(h.today.total) }}<span class="mini"><i :style="{ width: (h.today.total / maxToday * 100) + '%' }" /></span></td>
              <td class="r num">{{ bytes(h.week.total) }}</td>
              <td class="r num">{{ bytes(h.month.total) }}</td>
              <td><span v-if="h.top_app" class="tag"><span class="chip" :style="{ background: catColor(h.top_app.category) }" />{{ appName(h.top_app) }}</span></td>
              <td class="muted small">{{ ago(h.last_seen) }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="!shown.length" class="empty">{{ loading ? t('common.loading') : t('common.empty') }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import http, { enc } from '../api.js'
import { ago, appName, bytes, catColor, rate } from '../format.js'
import { usePoll } from '../poll.js'

const { t } = useI18n()
const rows = ref([])
const q = ref('')
const onlineOnly = ref(false)
const sort = ref({ key: 'today', desc: true })
const { loading, error, reload: refresh } = usePoll(async () => { rows.value = await http.get('/hosts') }, 30000)

const onlineN = computed(() => rows.value.filter(h => h.online).length)
const maxToday = computed(() => Math.max(1, ...rows.value.map(h => h.today.total)))
const ipNum = ip => (ip || '').split('.').reduce((s, x) => s * 256 + (+x || 0), 0)
const keyFn = {
  name: h => (h.name || '').toLowerCase(), ip: h => ipNum(h.ip), rate: h => h.rate_up + h.rate_down,
  today: h => h.today.total, week: h => h.week.total, month: h => h.month.total, last: h => h.last_seen || 0,
}

const shown = computed(() => {
  const s = q.value.trim().toLowerCase()
  let list = rows.value.filter(h => (!onlineOnly.value || h.online) &&
    (!s || [h.name, h.ip, h.mac, h.hostname, h.alias].some(v => v && v.toLowerCase().includes(s))))
  const f = keyFn[sort.value.key]
  const dir = sort.value.desc ? -1 : 1
  return [...list].sort((a, b) => (f(a) > f(b) ? dir : f(a) < f(b) ? -dir : 0))
})

function sortBy(k) {
  sort.value = { key: k, desc: sort.value.key === k ? !sort.value.desc : k !== 'name' && k !== 'ip' }
}
const arrow = k => (sort.value.key === k ? (sort.value.desc ? '↓' : '↑') : '')

// ---------- 命名管理 ----------
const showNames = ref(false)
const names = ref([])
const nf = reactive({ kind: 'mac', value: '', name: '' })
const nfErr = ref('')
const nfSaved = ref(false)
const nameInput = ref(null)

async function loadNames() { names.value = await http.get('/names') }
onMounted(loadNames)
function toggleNames() { showNames.value = !showNames.value }

async function rename(h) {
  // 默认沿用当前的命名方式；没有命名过时有 MAC 按 MAC
  const kind = h.alias_by || (h.mac ? 'mac' : 'ip')
  Object.assign(nf, { kind, value: kind === 'mac' ? h.mac : h.ip, name: h.alias || '' })
  nfErr.value = ''
  showNames.value = true
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
  names.value = await http.delete(`/names/${n.kind}/${enc(n.value)}`)
  refresh()
}
</script>

<style scoped>
.search { width: 240px; }
.chk { display: flex; gap: 6px; align-items: center; color: var(--muted); font-size: 13px; cursor: pointer; }
.nm { display: inline-flex; align-items: center; gap: 8px; }
.hn { font-size: 12px; }
.small { font-size: 12px; line-height: 1.35; }
.kind { font: 600 10.5px/1 var(--cond); letter-spacing: .06em; color: var(--muted); border: 1px solid var(--line-strong); border-radius: 3px; padding: 2px 4px; }
.ren { height: 24px; padding: 0 5px; opacity: 0; }
tr:hover .ren, .ren:focus-visible { opacity: 1; }
@media (hover: none) { .ren { opacity: .7; } }
.mini { display: block; height: 3px; margin: 4px 0 0 auto; width: 72px; border-radius: 2px; background: color-mix(in srgb, var(--line) 55%, transparent); }
.mini i { display: block; height: 100%; margin-left: auto; border-radius: 2px; background: var(--down); }

.names { margin-bottom: 16px; }
.nf { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.nf .seg { border-bottom: 0; }
.nf .v { width: 200px; }
.nf .n { width: 220px; }
.nf .hint { flex-basis: 100%; }
.lk:hover { color: var(--ink); text-decoration: underline; text-underline-offset: 3px; }
@media (max-width: 640px) { .search, .nf .v, .nf .n { width: 100%; } }
</style>
