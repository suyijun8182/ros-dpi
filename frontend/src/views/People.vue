<template>
  <div>
    <div class="page-h">
      <div class="seg tabs" role="tablist">
        <button v-for="k in TABS" :key="k" role="tab" :aria-selected="tab === k" :class="{ on: tab === k }" @click="setTab(k)">{{ L('tab.' + k) }}</button>
      </div>
      <span class="sp" />
      <RangeTabs v-if="tab === 'list'" />
    </div>
    <div v-if="err" class="err">{{ err }}</div>

    <!-- 人员列表 -->
    <template v-if="tab === 'list'">
      <div class="panel">
        <div class="panel-b head">
          <div class="info-bar"><span class="ic">i</span><div><b>{{ L('title') }}</b><span>{{ L('info') }}</span></div></div>
          <div class="sec">
            <div class="chips">
              <button class="chip-b" :class="{ on: !dept }" @click="dept = 0">{{ t('people.all') }}<span class="num">{{ d ? d.people.length : '' }}</span></button>
              <button v-for="g in depts" :key="g.id" class="chip-b" :class="{ on: dept === g.id }" @click="dept = g.id">{{ g.name }}<span class="num">{{ g.n }}</span></button>
            </div>
            <span class="sp" />
            <input class="input search" v-model="q" :placeholder="t('common.search')" :aria-label="t('common.search')" />
            <template v-if="isAdmin">
              <button class="btn sm" @click="deptOpen = true">{{ L('manageDept') }}</button>
              <button class="btn sm primary" @click="edit(null)">{{ L('add') }}</button>
            </template>
          </div>
        </div>
        <div class="tbl-wrap" v-if="d">
          <table class="tbl">
            <thead><tr><th>{{ L('person') }}</th><th class="m-hide">{{ t('people.devices') }}</th><th class="r">{{ t('flow.bytes') }}</th>
              <th class="r m-hide">{{ t('people.online') }}</th><th class="m-hide">{{ L('leisureShare') }}</th><th>{{ t('people.tags') }}</th></tr></thead>
            <tbody>
              <tr v-for="p in shown" :key="p.id" class="link" @click="$router.push(`/people/${p.id}`)">
                <td><span class="nm"><span class="dot" :class="{ on: p.online }" /><b>{{ p.name }}</b></span>
                  <span v-if="p.dept" class="pill grey dp">{{ p.dept }}</span>
                  <div class="faint small m-only">{{ t('people.nDevices', { n: p.devices.length }) }} · {{ hours(p.online_seconds) }}</div></td>
                <td class="m-hide"><span v-for="h in p.devices" :key="h.key" class="dv" :class="{ on: h.online }" :title="`${h.name} ${h.ip || ''}`">
                  <Icon :name="'dev-' + (h.dtype || 'unknown')" :size="16" /></span>
                  <span v-if="!p.devices.length" class="faint small">{{ t('people.noDevice') }}</span></td>
                <td class="r num"><b>{{ bytes(p.total) }}</b><div class="small"><span class="up">↑{{ bytes(p.up) }}</span> <span class="down">↓{{ bytes(p.down) }}</span></div></td>
                <td class="r num m-hide">{{ hours(p.online_seconds) }}</td>
                <td class="m-hide eff">
                  <template v-if="p.work_online"><span class="bar"><i :style="{ width: pctN(p.leisure_work / p.work_online) + '%' }" :class="{ hi: p.leisure_work / p.work_online > .3 }" /></span>
                    <span class="num small">{{ pct(p.leisure_work / p.work_online, 0) }}</span></template>
                  <span v-else class="faint small">-</span></td>
                <td><Tags :tags="p.tags" :max="3" /></td>
              </tr>
            </tbody>
          </table>
          <div v-if="!shown.length" class="empty">{{ d.people.length ? t('common.empty') : L('empty') }}</div>
        </div>
        <div v-else class="empty">{{ t('common.loading') }}</div>
      </div>

      <!-- 还没有归属的设备 -->
      <div class="panel mt" v-if="d && isAdmin && d.unassigned.length">
        <div class="panel-h"><h2>{{ t('people.unassigned') }}</h2><span class="faint small">{{ t('people.unassignedHint', { n: d.unassigned.length }) }}</span></div>
        <div class="tbl-wrap">
          <table class="tbl">
            <thead><tr><th>{{ t('common.name') }}</th><th class="m-hide">IP / MAC</th><th class="m-hide">{{ t('people.dtype') }}</th><th class="r">{{ t('range.today') }}</th><th>{{ L('assignTo') }}</th></tr></thead>
            <tbody>
              <tr v-for="h in d.unassigned.slice(0, unLimit)" :key="h.key">
                <td><span class="nm"><span class="dot" :class="{ on: h.online }" /><Icon :name="'dev-' + (h.dtype || 'unknown')" :size="16" class="dvi" />
                  <router-link :to="`/hosts/${enc(h.key)}`" class="hl">{{ h.name }}</router-link></span></td>
                <td class="m-hide addr faint small">{{ h.ip }}<br />{{ h.mac || '' }}</td>
                <td class="m-hide small">{{ t('dev.' + (h.dtype || 'unknown')) }}<span class="faint" v-if="h.vendor"> · {{ h.vendor }}</span></td>
                <td class="r num">{{ bytes(h.today.total) }}</td>
                <td><select class="input sel" :aria-label="L('assignTo')" @change="bind(h.key, $event.target.value)">
                  <option value="">—</option>
                  <option v-for="p in d.people" :key="p.id" :value="p.id">{{ p.name }}</option>
                </select></td>
              </tr>
            </tbody>
          </table>
          <div class="more-row" v-if="d.unassigned.length > unLimit"><button class="btn sm" @click="unLimit += 50">{{ t('flow.showMore') }}</button></div>
        </div>
      </div>
    </template>

    <!-- 行为洞察（最近 7 天） -->
    <template v-if="tab === 'insight'">
      <div class="panel" v-if="ins">
        <div class="panel-b head">
          <div class="info-bar"><span class="ic">i</span><div><b>{{ L('tab.insight') }}</b><span>{{ L('insightInfo') }}</span></div></div>
        </div>
        <div class="panel-b">
          <div class="tagcards">
            <div v-for="g in tagGroups" :key="g.id" class="tc" :class="{ none: !g.items.length }">
              <div class="tc-h"><b>{{ t('tag.' + g.id) }}</b><span class="faint small">{{ t('tagDesc.' + g.id, descArgs) }}</span></div>
              <div v-if="!g.items.length" class="faint small">{{ t('people.nobody') }}</div>
              <router-link v-for="x in g.items" :key="x.s.id" :to="`/people/${x.s.id}`" class="tc-r">
                <span class="lv" :class="x.tag.level" /><span>{{ x.s.name }}</span><span class="sp" />
                <span class="num small">{{ tagValue(x.tag) }}</span></router-link>
            </div>
          </div>
        </div>
      </div>
      <div class="panel mt" v-if="ins">
        <div class="panel-h"><h2>{{ L('rankTitle') }}</h2><span class="faint small">{{ t('people.last7') }}</span></div>
        <div class="tbl-wrap">
          <table class="tbl">
            <thead><tr><th>{{ L('person') }}</th><th class="r">{{ t('people.online') }}</th><th class="r m-hide">{{ L('workOnline') }}</th>
              <th>{{ L('leisureShare') }}</th>
              <th class="r m-hide" v-if="scene.id === 'home'">{{ t('people.game') }}</th><th class="r m-hide" v-if="scene.id === 'home'">{{ t('people.shortVideo') }}</th>
              <th class="r m-hide">{{ t('people.night') }}</th></tr></thead>
            <tbody>
              <tr v-for="s in rank" :key="s.id" class="link" @click="$router.push(`/people/${s.id}`)">
                <td><b>{{ s.name }}</b><span v-if="s.dept" class="pill grey dp">{{ s.dept }}</span></td>
                <td class="r num">{{ hours(s.online) }}</td>
                <td class="r num m-hide">{{ hours(s.work_online) }}</td>
                <td class="eff"><template v-if="s.work_online"><span class="bar"><i :style="{ width: pctN(s.leisure_work / s.work_online) + '%' }" :class="{ hi: s.leisure_work / s.work_online > .3 }" /></span>
                  <span class="num small">{{ pct(s.leisure_work / s.work_online, 0) }}</span></template><span v-else class="faint small">-</span></td>
                <td class="r num m-hide" v-if="scene.id === 'home'">{{ hours(s.game) }}</td>
                <td class="r num m-hide" v-if="scene.id === 'home'">{{ hours(s.short_video) }}</td>
                <td class="r num m-hide">{{ hours(s.night) }}</td>
              </tr>
            </tbody>
          </table>
          <div v-if="!rank.length" class="empty">{{ L('empty') }}</div>
        </div>
      </div>
      <div v-if="!ins" class="empty">{{ t('common.loading') }}</div>
    </template>

    <!-- 分析设置 -->
    <template v-if="tab === 'settings' && cfg">
      <div class="panel">
        <div class="panel-h"><h2>{{ t('people.scenario') }}</h2><span class="faint small">{{ t('people.scenarioHint') }}</span></div>
        <div class="panel-b scn">
          <label v-for="k in ['home', 'enterprise']" :key="k" class="scn-c" :class="{ on: cfg.scenario === k }">
            <input type="radio" :value="k" :checked="cfg.scenario === k" @change="switchScene(k)" />
            <Icon :name="k === 'home' ? 'people' : 'users'" :size="22" />
            <div><b>{{ t('scn.' + k + '.name') }}</b><span class="faint small">{{ t('scn.' + k + '.desc') }}</span></div>
          </label>
        </div>
      </div>
      <div class="panel mt">
        <div class="panel-h"><h2>{{ L('workTime') }}</h2><span class="faint small">{{ L('workHint') }}</span></div>
        <div class="panel-b form">
          <div class="row days">
            <label v-for="x in 7" :key="x" class="chk"><input type="checkbox" :checked="cfg.work_days.includes(String(x))" @change="toggleDay(x)" /> {{ t('audit.dow.' + x) }}</label>
          </div>
          <div v-for="(w, i) in cfg.work" :key="i" class="row">
            <input class="input w" type="time" v-model="w[0]" :aria-label="t('audit.rule.from')" /><span>–</span>
            <input class="input w" type="time" v-model="w[1]" :aria-label="t('audit.rule.to')" />
            <button class="btn sm ghost" @click="cfg.work.splice(i, 1)" :aria-label="t('common.delete')"><Icon name="close" :size="14" /></button>
          </div>
          <div><button class="btn sm" @click="cfg.work.push(['09:00', '12:00'])">{{ t('people.addRange') }}</button></div>
          <label>{{ t('people.nightWin') }}</label>
          <div class="row"><input class="input w" type="time" v-model="cfg.night[0]" :aria-label="t('audit.rule.from')" /><span>–</span>
            <input class="input w" type="time" v-model="cfg.night[1]" :aria-label="t('audit.rule.to')" /></div>
          <label>{{ t('people.leisure') }}</label>
          <div class="chips">
            <button v-for="c in leisureChoices" :key="c.id" class="chip-b" :class="{ on: cfg.leisure.includes(c.id) }" @click="toggleLeisure(c.id)">{{ catName(c) }}</button>
          </div>
          <template v-if="cfg.scenario === 'home'">
            <label>{{ t('people.limits') }}</label>
            <div class="lims">
              <label v-for="k in ['screen', 'game', 'short_video']" :key="k" class="lim">{{ t('people.lim.' + k) }}
                <input class="input num" type="number" min="0" max="24" step="0.5" :value="cfg.limits[k] / 3600" @input="cfg.limits[k] = Math.round(+$event.target.value * 3600)" />
                <span class="faint">{{ t('people.hoursUnit') }}</span></label>
            </div>
            <div class="faint small">{{ t('people.limitsHint') }}</div>
          </template>
          <div class="err" v-if="cfgErr">{{ cfgErr }}</div>
          <div><button class="btn primary" @click="saveCfg">{{ cfgSaved ? t('common.saved') : t('common.save') }}</button></div>
        </div>
      </div>
    </template>

    <!-- 编辑人员 -->
    <Modal :open="!!form" :title="form && form.id ? L('edit') : L('add')" width="560px" @close="form = null">
      <form v-if="form" class="pf" @submit.prevent="save">
        <label for="pf-name">{{ t('common.name') }}</label>
        <input id="pf-name" class="input" v-model.trim="form.name" required maxlength="64" />
        <label for="pf-dept">{{ L('dept') }}</label>
        <select id="pf-dept" class="input" v-model="form.dept_id"><option :value="null">—</option>
          <option v-for="g in d.departments" :key="g.id" :value="g.id">{{ g.name }}</option></select>
        <label for="pf-q">{{ t('people.devices') }}</label>
        <input id="pf-q" class="input" v-model="hq" :placeholder="t('audit.rule.hostSearch')" />
        <div class="hostbox">
          <label v-for="h in hostChoices" :key="h.key" class="chk"><input type="checkbox" :checked="form.hosts.includes(h.key)" @change="toggleHost(h.key)" />
            <Icon :name="'dev-' + (h.dtype || 'unknown')" :size="15" /> {{ h.name }} <span class="faint addr small">{{ h.ip }}</span>
            <span v-if="h.owner && h.owner !== form.id" class="pill grey dp">{{ h.ownerName }}</span></label>
        </div>
        <label for="pf-note">{{ t('people.note') }}</label>
        <input id="pf-note" class="input" v-model="form.note" maxlength="255" />
        <div class="err" v-if="formErr">{{ formErr }}</div>
        <div class="row end">
          <button v-if="form.id" type="button" class="btn danger" @click="del">{{ t('common.delete') }}</button>
          <span class="sp" />
          <button type="button" class="btn" @click="form = null">{{ t('common.cancel') }}</button>
          <button class="btn primary">{{ t('common.save') }}</button></div>
      </form>
    </Modal>

    <!-- 部门 / 分组 -->
    <Modal :open="deptOpen" :title="L('manageDept')" width="460px" @close="deptOpen = false">
      <div class="pf">
        <div v-for="g in d ? d.departments : []" :key="g.id" class="row">
          <input class="input grow" v-model="g.name" :aria-label="t('common.name')" />
          <button class="btn sm" @click="renameDept(g)">{{ t('common.save') }}</button>
          <button class="btn sm danger" @click="delDept(g)">{{ t('common.delete') }}</button>
        </div>
        <form class="row" @submit.prevent="addDept">
          <input class="input grow" v-model.trim="newDept" :placeholder="L('deptName')" :aria-label="L('deptName')" />
          <button class="btn sm primary" :disabled="!newDept">{{ t('common.add') }}</button>
        </form>
        <div class="err" v-if="deptErr">{{ deptErr }}</div>
      </div>
    </Modal>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import http, { enc, isAdmin } from '../api.js'
import Icon from '../components/Icon.vue'
import Modal from '../components/Modal.vue'
import RangeTabs from '../components/RangeTabs.vue'
import Tags from '../components/Tags.vue'
import { bytes, catName, pct } from '../format.js'
import { hours, L, loadScene, scene } from '../scenario.js'
import { ui } from '../state.js'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const TABS = computed(() => (isAdmin.value ? ['list', 'insight', 'settings'] : ['list', 'insight']))
const tab = computed(() => (TABS.value.includes(route.query.tab) ? route.query.tab : 'list'))
const setTab = k => router.replace({ query: k === 'list' ? {} : { tab: k } })
const err = ref('')
const pctN = x => Math.min(100, Math.round((x || 0) * 100))

// ---------- 列表 ----------
const d = ref(null)
const dept = ref(0)
const q = ref('')
const unLimit = ref(50)
async function load() {
  try { d.value = await http.get('/people', { params: { range: ui.range } }); scene.id = d.value.scenario; err.value = '' } catch (e) { err.value = e.message }
}
const depts = computed(() => (d.value ? d.value.departments.map(g => ({ ...g, n: d.value.people.filter(p => p.dept_id === g.id).length })) : []))
const shown = computed(() => {
  const s = q.value.trim().toLowerCase()
  return (d.value ? d.value.people : []).filter(p => (!dept.value || p.dept_id === dept.value)
    && (!s || p.name.toLowerCase().includes(s) || p.devices.some(h => (h.name + ' ' + (h.ip || '')).toLowerCase().includes(s))))
})
async function bind(host, pid) {
  if (!pid) return
  await http.put('/devices/bind', { host, person_id: +pid })
  await load()
}

// ---------- 编辑人员 ----------
const form = ref(null)
const formErr = ref('')
const hq = ref('')
const allHosts = ref([])
async function edit(p) {
  formErr.value = ''
  hq.value = ''
  if (!allHosts.value.length) allHosts.value = await http.get('/hosts')
  form.value = p ? { id: p.id, name: p.name, dept_id: p.dept_id, note: p.note || '', hosts: p.devices.map(h => h.key) }
    : { id: null, name: '', dept_id: dept.value || null, note: '', hosts: [] }
}
const hostChoices = computed(() => {
  const s = hq.value.trim().toLowerCase()
  const owner = {}
  for (const p of d.value ? d.value.people : []) for (const h of p.devices) owner[h.key] = p
  return allHosts.value.filter(h => !s || [h.name, h.ip, h.mac].some(v => v && v.toLowerCase().includes(s)))
    .map(h => ({ ...h, owner: owner[h.key] && owner[h.key].id, ownerName: owner[h.key] && owner[h.key].name }))
    .sort((a, b) => (form.value.hosts.includes(b.key) - form.value.hosts.includes(a.key)) || (!!a.owner - !!b.owner))
    .slice(0, 150)
})
function toggleHost(k) {
  const i = form.value.hosts.indexOf(k)
  i >= 0 ? form.value.hosts.splice(i, 1) : form.value.hosts.push(k)
}
async function save() {
  formErr.value = ''
  const f = form.value
  try {
    const body = { name: f.name, dept_id: f.dept_id, note: f.note || null, hosts: f.hosts }
    if (f.id) await http.put(`/people/${f.id}`, body)
    else await http.post('/people', body)
    form.value = null
    await Promise.all([load(), loadScene(true)])
  } catch (e) { formErr.value = e.message }
}
async function del() {
  if (!confirm(t('common.confirmDelete'))) return
  await http.delete(`/people/${form.value.id}`)
  form.value = null
  await Promise.all([load(), loadScene(true)])
}

// ---------- 部门 ----------
const deptOpen = ref(false)
const newDept = ref('')
const deptErr = ref('')
async function addDept() {
  deptErr.value = ''
  try { await http.post('/departments', { name: newDept.value }); newDept.value = ''; await load() } catch (e) { deptErr.value = e.message }
}
async function renameDept(g) {
  deptErr.value = ''
  try { await http.put(`/departments/${g.id}`, { name: g.name }); await load() } catch (e) { deptErr.value = e.message }
}
async function delDept(g) {
  if (!confirm(t('common.confirmDelete'))) return
  await http.delete(`/departments/${g.id}`)
  if (dept.value === g.id) dept.value = 0
  await load()
}

// ---------- 洞察 ----------
const ins = ref(null)
async function loadIns() {
  try { ins.value = await http.get('/insights'); scene.id = ins.value.scenario } catch (e) { err.value = e.message }
}
const TAG_IDS = { enterprise: ['job', 'stock_work', 'game_work', 'video_work', 'shop_work', 'late_night'],
  home: ['adult', 'screen_over', 'game_over', 'short_video_over', 'late_night', 'study_leisure'] }
const tagGroups = computed(() => (TAG_IDS[scene.id] || []).map(id => ({
  id, items: (ins.value ? ins.value.subjects : []).flatMap(s => s.tags.filter(x => x.id === id).map(tag => ({ s, tag })))
    .sort((a, b) => (b.tag.level === 'high') - (a.tag.level === 'high') || b.tag.value - a.tag.value),
})))
const descArgs = computed(() => {
  const c = ins.value ? ins.value.config : {}
  const l = c.limits || {}
  return { screen: hours(l.screen), game: hours(l.game), sv: hours(l.short_video), night: (c.night || []).join('–') }
})
const tagValue = x => (x.unit === 'days' ? t('people.days', { n: x.value }) : hours(x.value))
const rank = computed(() => (ins.value ? [...ins.value.subjects].sort((a, b) =>
  (b.work_online ? b.leisure_work / b.work_online : -1) - (a.work_online ? a.leisure_work / a.work_online : -1)) : []))

// ---------- 设置 ----------
const cfg = ref(null)
const choices = ref([])
const cfgErr = ref('')
const cfgSaved = ref(false)
async function loadCfg() {
  const r = await http.get('/analysis/settings')
  cfg.value = JSON.parse(JSON.stringify(r.config))
  choices.value = r.choices
}
const leisureChoices = computed(() => choices.value.filter(c => c.kind === 'group' && !['base', 'unknown'].includes(c.id))
  .concat(choices.value.filter(c => ['short_video', 'shopping', 'live', 'mobile_game', 'social'].includes(c.id) && c.kind === 'category')))
function toggleDay(x) {
  const s = new Set(cfg.value.work_days.split(''))
  s.has(String(x)) ? s.delete(String(x)) : s.add(String(x))
  cfg.value.work_days = [...s].sort().join('')
}
function toggleLeisure(id) {
  const i = cfg.value.leisure.indexOf(id)
  i >= 0 ? cfg.value.leisure.splice(i, 1) : cfg.value.leisure.push(id)
}
async function switchScene(k) {
  cfgErr.value = ''
  try {
    cfg.value = (await http.put('/analysis/settings', { scenario: k })).config
    scene.id = k
  } catch (e) { cfgErr.value = e.message }
}
async function saveCfg() {
  cfgErr.value = ''
  try {
    cfg.value = (await http.put('/analysis/settings', cfg.value)).config
    scene.id = cfg.value.scenario
    cfgSaved.value = true
    setTimeout(() => (cfgSaved.value = false), 1500)
  } catch (e) { cfgErr.value = e.message }
}

onMounted(() => loadScene())
watch([tab, () => ui.range], () => {
  if (tab.value === 'list') load()
  else if (tab.value === 'insight') loadIns()
  else if (tab.value === 'settings') loadCfg()
}, { immediate: true })
</script>

<style scoped>
.tabs button { font-size: 15px; padding: 8px 14px 11px; }
.head { display: grid; gap: 14px; padding-bottom: 6px; }
.chips { display: flex; gap: 6px; flex-wrap: wrap; }
.chip-b { border: 1px solid var(--line); background: var(--panel); color: var(--ink); border-radius: 16px; padding: 4px 12px; font: inherit; font-size: 13px; cursor: pointer; display: inline-flex; gap: 6px; align-items: center; }
.chip-b .num { color: var(--faint); font-size: 12px; }
.chip-b.on { border-color: var(--brand-ink); background: var(--brand-weak); color: var(--brand-ink); }
.search { width: 200px; height: 32px; }
.nm { display: inline-flex; align-items: center; gap: 8px; }
.dp { margin-left: 8px; height: 20px; font-size: 11px; }
.dv { display: inline-flex; color: var(--faint); margin-right: 4px; }
.dv.on { color: var(--ok); }
.dvi { color: var(--muted); }
.hl:hover { color: var(--brand-ink); }
.eff { white-space: nowrap; }
.bar { display: inline-block; width: 80px; height: 6px; border-radius: 3px; background: var(--sunk); vertical-align: middle; margin-right: 8px; overflow: hidden; }
.bar i { display: block; height: 100%; background: var(--accent); border-radius: 3px; }
.bar i.hi { background: var(--warn); }
.sel { height: 30px; min-width: 120px; }
.more-row { display: flex; justify-content: center; padding: 12px; }
.tagcards { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
.tc { background: var(--sunk); border-radius: 12px; padding: 12px 14px; display: grid; gap: 6px; align-content: start; }
.tc.none { opacity: .7; }
.tc-h { display: grid; gap: 2px; margin-bottom: 4px; }
.tc-r { display: flex; align-items: center; gap: 8px; font-size: 14px; padding: 4px 0; border-top: 1px solid var(--line); }
.tc-r:hover b, .tc-r:hover span:nth-child(2) { color: var(--brand-ink); }
.tc-r .sp { flex: 1; }
.lv { width: 8px; height: 8px; border-radius: 50%; background: var(--warn); }
.lv.high { background: var(--bad); }
.scn { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; }
.scn-c { display: flex; gap: 12px; align-items: flex-start; border: 1px solid var(--line); border-radius: 12px; padding: 14px; cursor: pointer; }
.scn-c input { display: none; }
.scn-c :deep(svg) { color: var(--brand-ink); flex: none; margin-top: 2px; }
.scn-c div { display: grid; gap: 4px; }
.scn-c.on { border-color: var(--brand-ink); background: var(--brand-weak); }
.form { display: grid; gap: 10px; max-width: 640px; }
.form > label { font-size: 13px; color: var(--muted); margin-top: 6px; }
.row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.row.end { justify-content: flex-end; margin-top: 8px; }
.row .sp { flex: 1; }
.days { gap: 14px; }
.w { width: 130px; }
.grow { flex: 1; min-width: 160px; }
.chk { display: inline-flex; gap: 6px; align-items: center; font-size: 13px; color: var(--muted); cursor: pointer; }
.lims { display: flex; gap: 16px; flex-wrap: wrap; }
.lim { display: inline-flex; gap: 8px; align-items: center; font-size: 13px; }
.lim input { width: 80px; }
.pf { display: grid; gap: 8px; }
.pf > label { font-size: 13px; color: var(--muted); margin-top: 4px; }
.hostbox { max-height: 220px; overflow-y: auto; border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; display: grid; gap: 4px; }
.hostbox .chk { color: var(--ink); }
@media (max-width: 640px) { .search { width: 100%; } }
</style>
