<template>
  <div>
    <div class="page-h"><h1>{{ t('rules.title') }}</h1><span class="lead">{{ t('rules.libCount', { n: meta.apps.length.toLocaleString() }) }}</span></div>

    <!-- 识别库：按识别层级分组（同一组内按优先级排列），前面一层认出来就不再往下查 -->
    <div class="panel lib" v-if="lib">
      <div class="panel-h"><h2>{{ t('lib.title') }}</h2>
        <span class="faint small">{{ t('lib.total', { apps: lib.total_apps.toLocaleString(), domains: lib.total_domains.toLocaleString() }) }}</span>
        <span class="sp" />
        <label class="chk" v-if="isAdmin"><input id="lib-auto" type="checkbox" :checked="lib.auto" @change="setAuto($event.target.checked)" /> {{ t('lib.auto') }}</label>
        <button class="btn sm" v-if="isAdmin" @click="updateNow" :disabled="updating"><Icon name="refresh" :size="15" />{{ updating ? t('lib.checking') : t('lib.checkNow') }}</button>
      </div>
      <div class="tbl-wrap">
        <table class="tbl">
          <thead><tr><th>{{ t('lib.source') }}</th><th class="m-hide">{{ t('lib.what') }}</th><th>{{ t('lib.version') }}</th>
            <th class="r">{{ t('lib.size') }}</th><th class="m-hide">{{ t('lib.license') }}</th><th>{{ t('lib.state') }}</th></tr></thead>
          <tbody v-for="(tier, ti) in tiers" :key="tier.id">
            <tr class="tier"><td colspan="6"><span class="no">{{ ti + 1 }}</span><b>{{ t('lib.tier.' + tier.id) }}</b>
              <span class="faint small">{{ t('lib.tierHint.' + tier.id) }}</span></td></tr>
            <tr v-for="x in tier.rows" :key="x.id">
              <td><a :href="x.url" target="_blank" rel="noopener" class="link"><b>{{ t('lib.name.' + x.id) }}</b></a></td>
              <td class="m-hide muted small wrap">{{ t('lib.desc.' + x.id) }}
                <div v-if="x.parts" class="parts">{{ x.parts.map(p => `${t('lib.name.' + p.id)} ${(p.ranges || 0).toLocaleString()}`).join(' · ') }}</div></td>
              <td class="num small">
                <template v-if="x.id === 'curated'">v{{ x.version }}</template>
                <template v-else-if="x.id === 'v2fly'">{{ x.sha ? x.sha.slice(0, 7) : '-' }} <span class="faint">{{ day(x.date) }}</span>
                  <div class="faint">{{ x.active === 'data' ? t('lib.fromUpdate') : t('lib.fromImage') }}</div></template>
                <template v-else>{{ x.updated ? datetime(x.updated) : '-' }}</template>
              </td>
              <td class="r num small">
                <template v-if="x.id === 'bm7'">{{ t('lib.rules', { n: (x.rules || 0).toLocaleString() }) }}<div class="faint">{{ t('lib.apps', { n: x.apps || 0 }) }}</div></template>
                <template v-else-if="x.id === 'asn'">{{ x.rows ? t('lib.ranges', { n: x.rows.toLocaleString() }) : '-' }}<div class="faint">{{ t('lib.asnApps', { n: x.asns }) }}</div></template>
                <template v-else-if="x.id === 'local'">{{ t('lib.ips', { n: (x.ips || 0).toLocaleString() }) }}<div class="faint">{{ t('lib.domains', { n: (x.domains || 0).toLocaleString() }) }}</div></template>
                <template v-else-if="x.domains != null && x.apps == null">{{ t('lib.domains', { n: x.domains.toLocaleString() }) }}</template>
                <template v-else-if="x.ranges != null">{{ t('lib.ranges', { n: x.ranges.toLocaleString() }) }}</template>
                <template v-else>{{ t('lib.apps', { n: x.apps.toLocaleString() }) }}<div class="faint">{{ t('lib.domains', { n: x.domains.toLocaleString() }) }}</div></template>
              </td>
              <td class="m-hide small muted">{{ x.license }}</td>
              <td class="small">
                <template v-if="x.id === 'curated'"><span class="pill grey">{{ t('lib.withRelease') }}</span></template>
                <template v-else-if="x.id === 'v2fly'">
                  <span class="pill" :class="RES[x.result] || 'grey'">{{ x.result ? t('lib.result.' + x.result) : t('lib.never') }}</span>
                  <div class="faint" v-if="x.checked">{{ t('lib.checked', { t: ago(x.checked) }) }}</div>
                  <div class="err" v-if="x.error">{{ x.error }}</div>
                </template>
                <template v-else>
                  <span class="pill" :class="x.rows || x.ranges || x.domains || x.rules ? 'ok' : x.error ? 'bad' : 'grey'">{{ x.rows || x.ranges || x.domains || x.rules ? t('lib.result.loaded') : x.error ? t('lib.result.failed') : t('lib.notLoaded') }}</span>
                  <div class="err" v-if="x.error">{{ x.error }}</div>
                </template>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="panel-b faint small note">{{ t('lib.note') }}</p>
    </div>

    <div class="grid g2-wide">
      <div class="panel" v-if="isAdmin">
        <div class="panel-h"><h2>{{ t('rules.addTitle') }}</h2></div>
        <div class="panel-b intro"><div class="info-bar"><span class="ic">i</span><div><b>{{ t('rules.title') }}</b><span>{{ t('rules.intro') }}</span></div></div></div>
        <form class="panel-b form" @submit.prevent="add">
          <div class="seg">
            <button type="button" v-for="k in ['domain', 'cidr', 'port']" :key="k" :class="{ on: f.kind === k }" @click="f.kind = k">{{ t('rules.kinds.' + k) }}</button>
          </div>
          <input class="input" v-model="f.pattern" :placeholder="t('rules.patternHint.' + f.kind)" />
          <div class="seg">
            <button type="button" :class="{ on: !newApp }" @click="newApp = false">{{ t('rules.existingApp') }}</button>
            <button type="button" :class="{ on: newApp }" @click="newApp = true">{{ t('rules.newApp') }}</button>
          </div>
          <select v-if="!newApp" class="input" v-model="f.app_id">
            <optgroup v-for="c in meta.categories" :key="c.id" :label="catLabel(c)">
              <option v-for="a in meta.apps.filter(x => x.category === c.id)" :key="a.id" :value="a.id">{{ appName(a) }}</option>
            </optgroup>
          </select>
          <template v-else>
            <input class="input" v-model="f.app_id" :placeholder="t('rules.appId')" />
            <input class="input" v-model="f.app_name" :placeholder="t('rules.appName')" />
            <select class="input" v-model="f.category">
              <option v-for="c in meta.categories" :key="c.id" :value="c.id">{{ catLabel(c) }}</option>
            </select>
          </template>
          <div class="err" v-if="formErr">{{ formErr }}</div>
          <div><button class="btn primary" :disabled="!f.pattern || !f.app_id">{{ t('common.add') }}</button></div>
        </form>
        <div class="panel-b test">
          <input class="input" v-model="testDomain" :placeholder="t('rules.test')" @keyup.enter="test" />
          <button class="btn" @click="test">{{ t('rules.test') }}</button>
          <span v-if="testRes" class="muted">{{ testRes.app ? t('rules.testResult', { app: appName(testRes.app) }) : t('rules.testNone') }}</span>
        </div>
      </div>

      <div class="panel">
        <div class="panel-h"><h2>{{ t('rules.custom') }}</h2><span class="faint">{{ rules.length }}</span><span class="sp" />
          <button class="btn sm" v-if="isAdmin" @click="reclassify" :disabled="reclassing" :title="t('rules.reclassifyHint')">
            {{ reclassing ? t('rules.reclassifying') : t('rules.reclassify') }}</button>
          <span v-if="reclassRes" class="muted small">{{ reclassRes }}</span></div>
        <div class="tbl-wrap">
          <table class="tbl">
            <thead><tr><th>{{ t('rules.kind') }}</th><th>{{ t('rules.pattern') }}</th><th>{{ t('rules.target') }}</th><th /></tr></thead>
            <tbody>
              <tr v-for="r in rules" :key="r.id">
                <td><span class="tag">{{ t('rules.kinds.' + r.kind) }}</span></td>
                <td class="addr">{{ r.pattern }}</td>
                <td>{{ appLabel(r.app_id) }} <span v-if="r.share" class="pill grey" :title="t('rules.cm.share')">{{ t('rules.cm.shared1') }}</span></td>
                <td class="r acts"><template v-if="isAdmin">
                  <button class="btn sm" @click="openCm('edit', [], r)">{{ t('common.edit') }}</button>
                  <button class="btn sm danger" @click="del(r)">{{ t('common.delete') }}</button></template></td>
              </tr>
            </tbody>
          </table>
          <div v-if="!rules.length" class="empty">{{ t('common.empty') }}</div>
        </div>
      </div>
    </div>

    <!-- 未识别域名 Top（debug26）：归类 / 忽略都在弹窗里完成，可多选批量处理 -->
    <div class="panel mt" id="unknown">
      <div class="panel-h">{{ t('rules.unknown') }}<span class="sp" /><RangeTabs :list="['today', 'week', 'month']" /></div>
      <div class="panel-b steps">
        <p class="muted hint">{{ t('rules.unknownHint') }}</p>
        <ol v-if="isAdmin" class="small muted">
          <li v-for="i in 3" :key="i">{{ t('rules.unknownStep' + i) }}</li>
        </ol>
        <p v-if="flash" class="flash small"><span class="pill ok">{{ t('common.saved') }}</span> {{ flash }}</p>
        <div v-if="isAdmin && picked.length" class="bulk">
          <span class="small">{{ t('rules.cm.selected', { n: picked.length }) }}</span>
          <button class="btn sm primary" @click="openCm('classify', picked)">{{ t('rules.cm.bulkClassify') }}</button>
          <button class="btn sm" @click="openCm('ignore', picked)">{{ t('rules.cm.bulkIgnore') }}</button>
          <button class="btn sm ghost" @click="sel = {}">{{ t('common.cancel') }}</button>
        </div>
      </div>
      <div class="tbl-wrap">
        <table class="tbl">
          <thead><tr><th v-if="isAdmin" class="ck"><input type="checkbox" :checked="allPicked" @change="pickAll($event.target.checked)"
                                                           :aria-label="t('rules.cm.pickAll')" /></th>
            <th>{{ t('hosts.domain') }}</th><th class="r">{{ t('rules.bytes') }}</th><th class="r">{{ t('common.hosts') }}</th><th v-if="isAdmin" /></tr></thead>
          <tbody>
            <tr v-for="u in unknown" :key="u.domain">
              <td v-if="isAdmin" class="ck"><input type="checkbox" v-model="sel[u.domain]" :aria-label="u.domain" /></td>
              <td class="addr">{{ u.domain }}</td>
              <td class="r num">{{ bytes(u.bytes) }}</td>
              <td class="r num">{{ u.hosts }}</td>
              <td v-if="isAdmin" class="r acts">
                <button class="btn sm primary" @click="openCm('classify', [u])">{{ t('rules.classify') }}</button>
                <button class="btn sm ghost" @click="openCm('ignore', [u])">{{ t('rules.cm.ignore') }}</button></td>
            </tr>
          </tbody>
        </table>
        <div v-if="!unknown.length" class="empty">{{ t('common.empty') }}</div>
      </div>
      <details v-if="ignoredList.length" class="panel-b ign">
        <summary class="small">{{ t('rules.cm.ignoredTitle', { n: ignoredList.length }) }}</summary>
        <p class="faint small">{{ t('rules.cm.ignoredHint') }}</p>
        <div v-for="x in ignoredList" :key="x.pattern" class="ig">
          <span class="addr">{{ x.pattern }}</span><span class="faint small">{{ datetime(x.created) }}</span><span class="sp" />
          <button v-if="isAdmin" class="btn sm" @click="unignore(x.pattern)">{{ t('rules.cm.unignore') }}</button>
        </div>
      </details>
    </div>
    <ClassifyModal :open="!!cm" :mode="cm ? cm.mode : 'classify'" :rows="cm ? cm.rows : []" :rule="cm && cm.rule" :meta="meta"
                   @close="cm = null" @saved="onSaved" />

    <!-- 未匹配流量诊断（debug25）：没有任何域名的流量是哪类远端、哪个端口、哪台终端 -->
    <div class="panel mt" v-if="unm">
      <div class="panel-h">{{ t('rules.unm.title') }}<span class="sp" /><RangeTabs :list="['today', 'week', 'month']" /></div>
      <div class="panel-b">
        <p class="muted hint">{{ t('rules.unm.share', { b: bytes(unm.total), p: pct(Math.min(unm.total / Math.max(unm.range_total, 1), 1)) }) }}。{{ t('rules.unm.hint') }}</p>
        <p v-if="unm.nat" class="hint"><span class="pill warn">{{ t('check.natTitle') }}</span>
          <span class="muted"> {{ t('rules.nat', { name: unm.nat.name, ip: unm.nat.ip, p: pct(unm.nat.share) }) }}</span></p>
        <div class="unm">
          <div><div class="sec">{{ t('rules.unm.byKind') }}</div><BarList :items="unmKinds" :total="unm.total" />
            <p v-for="k in ['broadband', 'idc']" :key="k" class="faint small kh">{{ t('rules.unm.kind.' + k) }}：{{ t('rules.unm.kindHint.' + k) }}</p></div>
          <div><div class="sec">{{ t('rules.unm.byApp') }}</div><BarList :items="unmApps" :total="unm.total" /></div>
          <div><div class="sec">{{ t('rules.unm.byPort') }}</div><BarList :items="unmPorts" :total="unm.total" /></div>
          <div><div class="sec">{{ t('rules.unm.byHost') }}</div><BarList :items="unmHosts" :total="unm.total" /></div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import http, { isAdmin } from '../api.js'
import BarList from '../components/BarList.vue'
import ClassifyModal from '../components/ClassifyModal.vue'
import Icon from '../components/Icon.vue'
import RangeTabs from '../components/RangeTabs.vue'
import { CAT_GROUP, ago, appName, bytes, catColor, catName, datetime, groupName, pct } from '../format.js'
import { ui } from '../state.js'

const { t } = useI18n()
const meta = ref({ groups: [], categories: [], apps: [] })
const rules = ref([])
const unknown = ref([])
const newApp = ref(false)
const f = reactive({ kind: 'domain', pattern: '', app_id: '', app_name: '', category: 'web' })
const formErr = ref('')
const testDomain = ref('')
const testRes = ref(null)

const unknownRange = () => (['today', 'week', 'month'].includes(ui.range) ? ui.range : 'week')

// ---------- 识别库 ----------
const RES = { updated: 'ok', uptodate: 'ok', rejected: 'warn', failed: 'bad' }
// 识别库按识别层级分组；4 家官方 IP 段合并成一行（各家规模列在说明下面）
const TIERS = [
  { id: 'appDomain', ids: ['curated', 'v2fly', 'bm7'] },
  { id: 'appIp', ids: ['asn'] },
  { id: 'category', ids: ['hagezi', 'ut1'] },
  { id: 'fallback', ids: ['cnlist', 'official', 'cn'] },
  { id: 'learn', ids: ['local'] },
]
const OFFICIAL = ['google', 'cloudflare', 'aws', 'github']
const tiers = computed(() => {
  const by = Object.fromEntries((lib.value ? lib.value.sources : []).map(x => [x.id, x]))
  const parts = OFFICIAL.map(id => by[id]).filter(Boolean)
  if (parts.length) {
    by.official = { id: 'official', url: parts[0].url, license: parts[0].license, parts,
      ranges: parts.reduce((n, p) => n + (p.ranges || 0), 0), updated: Math.max(...parts.map(p => p.updated || 0)),
      error: parts.map(p => p.error).filter(Boolean).join('；') }
  }
  return TIERS.map(tr => ({ id: tr.id, rows: tr.ids.map(id => by[id]).filter(Boolean) })).filter(tr => tr.rows.length)
})
const lib = ref(null)
const updating = ref(false)
const day = s => (s ? s.slice(0, 10) : '')
async function loadLib() { try { lib.value = await http.get('/library') } catch (e) { /* 面板不显示 */ } }
async function updateNow() {
  updating.value = true
  try { lib.value = await http.post('/library/update', null, { timeout: 180000 }); await load() } catch (e) { formErr.value = e.message } finally { updating.value = false }
}
async function setAuto(v) {
  formErr.value = ''
  try {
    await http.put('/settings', { rules_auto_update: v })
    lib.value.auto = v
  } catch (e) { formErr.value = e.message }
}

async function load() {
  formErr.value = ''
  try {
    ;[meta.value, rules.value] = await Promise.all([http.get('/meta'), http.get('/rules')])
  } catch (e) { formErr.value = e.message; return }
  // 下拉框默认选中第一个应用，避免“添加”按钮莫名其妙地灰着
  if (!f.app_id) {
    const first = meta.value.categories.map(c => meta.value.apps.find(a => a.category === c.id)).find(Boolean)
    if (first) f.app_id = first.id
  }
}
async function loadUnknown() {
  try { unknown.value = await http.get('/rules/unknown-domains', { params: { range: unknownRange() } }) }
  catch (e) { /* 未识别域名列表加载失败不阻塞页面 */ }
}
// ---------- 未匹配流量诊断 ----------
const unm = ref(null)
async function loadUnm() {
  try { unm.value = await http.get('/rules/unmatched', { params: { range: unknownRange() } }) }
  catch (e) { /* 诊断加载失败不阻塞页面 */ }
}
const io = r => ({ value: r.total, up: r.up, down: r.down })
const PROTO = { 6: 'TCP', 17: 'UDP', 1: 'ICMP', 58: 'ICMPv6', 47: 'GRE', 50: 'ESP' }
const unmKinds = computed(() => (unm.value ? unm.value.kinds : []).map(r => ({ key: r.kind, label: t('rules.unm.kind.' + r.kind), ...io(r) })))
const unmApps = computed(() => (unm.value ? unm.value.apps : []).map(r => ({
  key: r.app.id, label: appName(r.app), sub: groupName({ name: r.app.group_name, name_en: r.app.group_name_en }),
  color: CAT_GROUP[r.app.category] ? catColor(r.app.category) : null, to: `/apps/${r.app.id}`, ...io(r) })))
const unmPorts = computed(() => (unm.value ? unm.value.ports : []).map(r => ({
  key: `${r.proto}/${r.port}`, label: `${PROTO[r.proto] || r.proto} ${r.port === 65536 ? t('rules.unm.highPort') : (r.port || '')}`.trim(), ...io(r) })))
const unmHosts = computed(() => (unm.value ? unm.value.hosts : []).map(r => ({
  key: r.host.key, label: r.host.name, sub: r.host.ip, online: r.host.online, to: `/hosts/${encodeURIComponent(r.host.key)}`, ...io(r) })))

onMounted(() => { load(); loadUnknown(); loadLib(); loadUnm(); loadIgnored() })
watch(() => ui.range, () => { sel.value = {}; loadUnknown(); loadUnm() })

// 下拉框里分类带上所属大类，例如"影音娱乐 · 短视频"
const catLabel = c => `${groupName(meta.value.groups.find(g => g.id === c.group))} · ${catName(c)}`

function appLabel(id) {
  const a = meta.value.apps.find(x => x.id === id)
  return a ? appName(a) : id
}

// ---------- 归类 / 忽略 / 修改弹窗（debug26） ----------
const cm = ref(null)                 // { mode, rows, rule }
const sel = ref({})                  // 勾选的未识别域名
const flash = ref('')
const ignoredList = ref([])
const picked = computed(() => unknown.value.filter(u => sel.value[u.domain]))
const allPicked = computed(() => unknown.value.length > 0 && picked.value.length === unknown.value.length)
function pickAll(on) { sel.value = on ? Object.fromEntries(unknown.value.map(u => [u.domain, true])) : {} }
function openCm(mode, rows, rule = null) { flash.value = ''; cm.value = { mode, rows, rule } }
async function loadIgnored() {
  try { ignoredList.value = await http.get('/rules/ignored') } catch (e) { /* 不阻塞页面 */ }
}
async function onSaved(msg) {
  cm.value = null
  sel.value = {}
  flash.value = msg
  await Promise.all([load(), loadUnknown(), loadIgnored()])
}
async function unignore(pattern) {
  try {
    await http.post('/rules/unignore', { patterns: [pattern] })
    await Promise.all([loadUnknown(), loadIgnored()])
  } catch (e) { formErr.value = e.message }
}

async function add() {
  formErr.value = ''
  try {
    const r = await http.post('/rules', { ...f, app_name: newApp.value ? f.app_name : null, category: newApp.value ? f.category : null },
      { timeout: 120000 })
    f.pattern = ''
    flash.value = t(r.bytes_moved ? 'rules.cm.done' : 'rules.cm.done0', { app: appLabel(r.app_id), b: bytes(r.bytes_moved) })
    await load()
    await loadUnknown()
  } catch (e) { formErr.value = e.message }
}

async function del(r) {
  if (!confirm(t('rules.cm.delConfirm', { p: r.pattern }))) return
  formErr.value = ''
  try {
    const res = await http.delete(`/rules/${r.id}`, { timeout: 120000 })
    flash.value = t(res.bytes_moved ? 'rules.cm.deleted' : 'rules.cm.deleted0', { p: r.pattern, b: bytes(res.bytes_moved) })
    await load()
    await loadUnknown()
  } catch (e) { formErr.value = e.message }
}

async function test() {
  if (!testDomain.value.trim()) return
  formErr.value = ''
  try { testRes.value = await http.get('/rules/test', { params: { domain: testDomain.value.trim() } }) }
  catch (e) { formErr.value = e.message }
}

const reclassing = ref(false)
const reclassRes = ref('')
async function reclassify() {
  if (!confirm(t('rules.reclassifyConfirm'))) return
  reclassing.value = true
  reclassRes.value = ''
  try {
    // 数据多时要一两分钟（审计报告 P1-3：实测 80 秒），默认 20 秒超时会误报失败而后端其实还在跑
    const r = await http.post('/rules/reclassify', null, { timeout: 600000 })
    reclassRes.value = t('rules.reclassifyDone', { b: bytes(r.bytes_moved), s: r.seconds })
  } catch (e) { reclassRes.value = e.message } finally { reclassing.value = false }
}
</script>

<style scoped>
.intro { padding-bottom: 0; }
.lib { margin-bottom: 14px; }
.lib .chk { display: flex; gap: 6px; align-items: center; color: var(--muted); font-size: 13px; cursor: pointer; }
.lib .wrap { white-space: normal; max-width: 340px; line-height: 1.5; }
.lib .note { margin: 0; padding-top: 10px; }
.lib .tier td { background: var(--sunk); padding-top: 9px; padding-bottom: 9px; }
.lib .tier b { margin-right: 10px; }
.lib .tier .no { display: inline-grid; place-items: center; width: 20px; height: 20px; margin-right: 8px; border-radius: 50%;
  background: var(--brand-ink); color: var(--panel); font: 600 12px/1 var(--cond); }
.lib .parts { margin-top: 3px; color: var(--faint); }
.lib td { vertical-align: top; }
.mt { margin-top: 14px; }
.unm { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px 28px; margin-top: 12px; }
.unm .kh { margin: 6px 0 0; line-height: 1.5; }
@media (max-width: 760px) { .unm { grid-template-columns: minmax(0, 1fr); } }
.form { display: flex; flex-direction: column; gap: 10px; }
.test { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; border-top: 1px solid var(--line); }
.test .input { flex: 1; min-width: 160px; }
.hint { margin: 0; padding-bottom: 4px; font-size: 13px; }
.steps ol { margin: 6px 0 0; padding-left: 20px; line-height: 1.7; }
.flash { margin: 10px 0 0; line-height: 1.6; }
.bulk { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-top: 10px; padding: 8px 12px; border-radius: 10px; background: var(--sunk); }
.ck { width: 34px; }
.acts { white-space: nowrap; }
.acts .btn + .btn { margin-left: 6px; }
.ign { border-top: 1px solid var(--line); }
.ign summary { cursor: pointer; color: var(--muted); }
.ign p { margin: 6px 0; }
.ig { display: flex; gap: 10px; align-items: center; padding: 6px 0; border-bottom: 1px solid var(--line); }
.ig:last-child { border-bottom: 0; }
.ig .sp { flex: 1; }
</style>
