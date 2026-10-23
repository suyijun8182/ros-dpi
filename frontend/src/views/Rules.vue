<template>
  <div>
    <div class="page-h"><h1>{{ t('rules.title') }}</h1><span class="lead">{{ t('rules.libCount', { n: meta.apps.length.toLocaleString() }) }}</span></div>

    <!-- 识别库：来源、版本、规模、自动更新与自检结果 -->
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
          <tbody>
            <tr v-for="x in lib.sources" :key="x.id">
              <td><a :href="x.url" target="_blank" rel="noopener" class="link"><b>{{ t('lib.name.' + x.id) }}</b></a></td>
              <td class="m-hide muted small wrap">{{ t('lib.desc.' + x.id) }}</td>
              <td class="num small">
                <template v-if="x.id === 'curated'">v{{ x.version }}</template>
                <template v-else-if="x.id === 'v2fly'">{{ x.sha ? x.sha.slice(0, 7) : '-' }} <span class="faint">{{ day(x.date) }}</span>
                  <div class="faint">{{ x.active === 'data' ? t('lib.fromUpdate') : t('lib.fromImage') }}</div></template>
                <template v-else>{{ x.updated ? datetime(x.updated) : '-' }}</template>
              </td>
              <td class="r num small">
                <template v-if="x.id === 'asn'">{{ x.rows ? t('lib.ranges', { n: x.rows.toLocaleString() }) : '-' }}<div class="faint">{{ t('lib.asnApps', { n: x.asns }) }}</div></template>
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
                  <span class="pill" :class="x.rows || x.ranges || x.domains ? 'ok' : x.error ? 'bad' : 'grey'">{{ x.rows || x.ranges || x.domains ? t('lib.result.loaded') : x.error ? t('lib.result.failed') : t('lib.notLoaded') }}</span>
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
        <div class="panel-h"><h2>{{ t('rules.custom') }}</h2><span class="faint">{{ rules.length }}</span></div>
        <div class="tbl-wrap">
          <table class="tbl">
            <thead><tr><th>{{ t('rules.kind') }}</th><th>{{ t('rules.pattern') }}</th><th>{{ t('rules.target') }}</th><th /></tr></thead>
            <tbody>
              <tr v-for="r in rules" :key="r.id">
                <td><span class="tag">{{ t('rules.kinds.' + r.kind) }}</span></td>
                <td class="addr">{{ r.pattern }}</td>
                <td>{{ appLabel(r.app_id) }}</td>
                <td class="r"><button class="btn sm danger" v-if="isAdmin" @click="del(r)">{{ t('common.delete') }}</button></td>
              </tr>
            </tbody>
          </table>
          <div v-if="!rules.length" class="empty">{{ t('common.empty') }}</div>
        </div>
      </div>
    </div>

    <div class="panel mt">
      <div class="panel-h">{{ t('rules.unknown') }}<span class="sp" /><RangeTabs :list="['today', 'week', 'month']" /></div>
      <p class="panel-b muted hint">{{ t('rules.unknownHint') }}</p>
      <div class="tbl-wrap">
        <table class="tbl">
          <thead><tr><th>{{ t('hosts.domain') }}</th><th class="r">{{ t('rules.bytes') }}</th><th class="r">{{ t('common.hosts') }}</th><th /></tr></thead>
          <tbody>
            <tr v-for="u in unknown" :key="u.domain">
              <td>{{ u.domain }}</td>
              <td class="r num">{{ bytes(u.bytes) }}</td>
              <td class="r num">{{ u.hosts }}</td>
              <td class="r"><button class="btn sm" @click="classify(u.domain)">{{ t('rules.classify') }}</button></td>
            </tr>
          </tbody>
        </table>
        <div v-if="!unknown.length" class="empty">{{ t('common.empty') }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import http, { isAdmin } from '../api.js'
import Icon from '../components/Icon.vue'
import RangeTabs from '../components/RangeTabs.vue'
import { ago, appName, bytes, catName, datetime, groupName } from '../format.js'
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
onMounted(() => { load(); loadUnknown(); loadLib() })
watch(() => ui.range, loadUnknown)

// 下拉框里分类带上所属大类，例如"影音娱乐 · 短视频"
const catLabel = c => `${groupName(meta.value.groups.find(g => g.id === c.group))} · ${catName(c)}`

function appLabel(id) {
  const a = meta.value.apps.find(x => x.id === id)
  return a ? appName(a) : id
}

// 取注册域名（简单处理：最后两段；.com.cn 这类取三段）
function baseDomain(d) {
  const p = d.split('.')
  const n = /^(com|net|org|gov|edu)\.[a-z]{2}$/.test(p.slice(-2).join('.')) ? 3 : 2
  return p.slice(-n).join('.')
}

function classify(domain) {
  f.kind = 'domain'
  f.pattern = baseDomain(domain)
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

async function add() {
  formErr.value = ''
  try {
    await http.post('/rules', { ...f, app_name: newApp.value ? f.app_name : null, category: newApp.value ? f.category : null })
    f.pattern = ''
    await load()
    await loadUnknown()
  } catch (e) { formErr.value = e.message }
}

async function del(r) {
  if (!confirm(t('common.confirmDelete'))) return
  formErr.value = ''
  try {
    await http.delete(`/rules/${r.id}`)
    await load()
  } catch (e) { formErr.value = e.message }
}

async function test() {
  if (!testDomain.value.trim()) return
  formErr.value = ''
  try { testRes.value = await http.get('/rules/test', { params: { domain: testDomain.value.trim() } }) }
  catch (e) { formErr.value = e.message }
}
</script>

<style scoped>
.intro { padding-bottom: 0; }
.lib { margin-bottom: 14px; }
.lib .chk { display: flex; gap: 6px; align-items: center; color: var(--muted); font-size: 13px; cursor: pointer; }
.lib .wrap { white-space: normal; max-width: 340px; line-height: 1.5; }
.lib .note { margin: 0; padding-top: 10px; }
.lib td { vertical-align: top; }
.mt { margin-top: 14px; }
.form { display: flex; flex-direction: column; gap: 10px; }
.test { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; border-top: 1px solid var(--line); }
.test .input { flex: 1; min-width: 160px; }
.hint { margin: 0; padding-bottom: 4px; font-size: 13px; }
</style>
