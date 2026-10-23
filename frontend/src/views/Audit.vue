<template>
  <div>
    <!-- 子标签：访问日志 / 审计事件 / 审计规则 / 报表 / 操作日志 -->
    <div class="page-h">
      <div class="seg tabs" role="tablist">
        <button v-for="k in TABS" :key="k" role="tab" :aria-selected="tab === k" :class="{ on: tab === k }" @click="setTab(k)">
          {{ t('audit.tab.' + k) }}<span v-if="k === 'events' && sum && sum.events_today" class="num cnt">{{ sum.events_today }}</span></button>
      </div>
      <span class="sp" />
      <RangeTabs v-if="tab === 'logs' || tab === 'events'" />
    </div>
    <div v-if="err" class="err">{{ err }}</div>

    <!-- 访问日志 -->
    <div class="panel" v-if="tab === 'logs'">
      <div class="panel-b head">
        <div class="info-bar"><span class="ic">i</span><div><b>{{ t('audit.tab.logs') }}</b>
          <span>{{ t('audit.log.info', { days: sum ? sum.retention_log_days : 30 }) }}</span></div></div>
      </div>
      <AccessLog />
    </div>

    <!-- 审计事件 -->
    <div class="panel" v-if="tab === 'events'">
      <div class="panel-b head">
        <div class="info-bar"><span class="ic">i</span><div><b>{{ t('audit.tab.events') }}</b><span>{{ t('audit.ev.info') }}</span></div></div>
        <div class="sec">{{ t('audit.ev.list') }}<span class="faint small" v-if="ev">{{ ev.total }}</span><span class="sp" />
          <button class="btn sm" v-if="isAdmin" @click="setTab('rules')">{{ t('audit.ev.manage') }}</button></div>
      </div>
      <div class="tbl-wrap" v-if="ev">
        <table class="tbl">
          <thead><tr><th>{{ t('audit.log.time') }}</th><th>{{ t('audit.ev.rule') }}</th><th>{{ t('flow.host') }}</th>
            <th class="m-hide">{{ t('audit.ev.hit') }}</th><th class="r">{{ t('flow.bytes') }}</th><th class="m-hide">{{ t('audit.ev.notified') }}</th></tr></thead>
          <tbody>
            <tr v-for="e in ev.rows" :key="e.id">
              <td class="num small">{{ datetime(e.ts) }}</td>
              <td><span class="pill bad">{{ e.rule }}</span></td>
              <td><router-link :to="`/hosts/${enc(e.host)}?tab=timeline`" class="hl">{{ e.host_name }}</router-link><div class="faint addr small">{{ e.host_ip }}</div></td>
              <td class="m-hide small">
                <span v-for="x in e.items" :key="x.key" class="hit">
                  <template v-if="x.app"><span class="chip" :style="{ background: catColor(x.app.category) }" />{{ appName(x.app) }}</template>
                  <template v-else>{{ x.key }}</template></span></td>
              <td class="r num">{{ e.bytes ? bytes(e.bytes) : '-' }}</td>
              <td class="m-hide"><span class="pill" :class="['grey', 'ok', 'warn'][e.notified] || 'grey'">{{ t('audit.ev.st' + (e.notified || 0)) }}</span></td>
            </tr>
          </tbody>
        </table>
        <div v-if="!ev.rows.length" class="empty">{{ t('audit.ev.empty') }}</div>
      </div>
    </div>

    <!-- 审计规则 + 通知通道 -->
    <template v-if="tab === 'rules'">
      <div class="panel">
        <div class="panel-b head">
          <div class="info-bar"><span class="ic">i</span><div><b>{{ t('audit.tab.rules') }}</b><span>{{ t('audit.rule.info') }}</span></div></div>
          <div class="sec">{{ t('audit.rule.templates') }}</div>
          <div class="tpls">
            <button v-for="tp in TEMPLATES" :key="tp.key" class="tpl" @click="edit({ ...tp.rule, name: t('audit.tpl.' + tp.key) })">
              <b>{{ t('audit.tpl.' + tp.key) }}</b><span class="faint small">{{ t('audit.tplDesc.' + tp.key) }}</span></button>
          </div>
          <div class="sec">{{ t('audit.rule.list') }}<span class="faint small">{{ rules.length }}</span><span class="sp" />
            <button class="btn sm primary" @click="edit(null)">{{ t('audit.rule.add') }}</button></div>
        </div>
        <div class="tbl-wrap">
          <table class="tbl">
            <thead><tr><th>{{ t('common.name') }}</th><th>{{ t('audit.rule.cond') }}</th><th class="m-hide">{{ t('audit.rule.when') }}</th>
              <th class="m-hide">{{ t('audit.rule.scope') }}</th><th>{{ t('audit.rule.state') }}</th><th /></tr></thead>
            <tbody>
              <tr v-for="r in rules" :key="r.id">
                <td><b>{{ r.name }}</b></td>
                <td class="small">{{ condText(r) }}</td>
                <td class="m-hide small muted">{{ whenText(r) }}</td>
                <td class="m-hide small muted">{{ r.hosts.length ? scopeText(r.hosts) : t('audit.rule.allHosts') }}</td>
                <td><span class="pill" :class="r.enabled ? 'ok' : 'grey'">{{ r.enabled ? t('audit.rule.on') : t('audit.rule.off') }}</span>
                  <span v-if="r.notify && r.enabled" class="pill">{{ t('audit.rule.push') }}</span></td>
                <td class="r nowrap"><button class="btn sm ghost" @click="edit(r)">{{ t('common.edit') }}</button>
                  <button class="btn sm danger" @click="del(r)">{{ t('common.delete') }}</button></td>
              </tr>
            </tbody>
          </table>
          <div v-if="!rules.length" class="empty">{{ t('audit.rule.empty') }}</div>
        </div>
      </div>

    </template>

    <!-- 通知渠道（参照 EasySub） -->
    <NotifyChannels v-if="tab === 'notify'" @saved="enabledCh = $event" />

    <!-- 私接路由 / 共享上网 -->
    <div class="panel" v-if="tab === 'sharing'">
      <div class="panel-b head">
        <div class="info-bar"><span class="ic">i</span><div><b>{{ t('audit.tab.sharing') }}</b><span>{{ t('audit.sh.info') }}</span></div></div>
        <div class="sec" v-if="sh">{{ t('audit.sh.list') }}<span class="faint small">{{ t('audit.sh.base', { n: sh.base_hops, hosts: sh.hosts }) }}</span></div>
      </div>
      <div class="tbl-wrap" v-if="sh">
        <table class="tbl">
          <thead><tr><th>{{ t('flow.host') }}</th><th>{{ t('audit.sh.reason') }}</th><th class="m-hide">TTL</th><th class="r m-hide">{{ t('audit.sh.packets') }}</th></tr></thead>
          <tbody>
            <tr v-for="r in sh.rows" :key="r.host">
              <td><router-link :to="`/hosts/${enc(r.host)}`" class="hl">{{ r.meta.name }}</router-link><div class="faint addr small">{{ r.meta.ip }} {{ r.meta.mac || '' }}</div></td>
              <td><span v-for="x in r.reasons" :key="x" class="pill warn rs">{{ t('audit.sh.r.' + x) }}</span></td>
              <td class="m-hide num small">{{ Object.entries(r.ttls).map(([k, v]) => `${k}×${v}`).join('  ') }}</td>
              <td class="r num m-hide">{{ r.packets }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="!sh.rows.length" class="empty">{{ t('audit.sh.none') }}</div>
      </div>
    </div>

    <!-- 报表 -->
    <template v-if="tab === 'report'">
      <div class="panel">
        <div class="panel-h"><div class="seg">
            <button v-for="r in ['today', 'yesterday', 'week', 'month']" :key="r" :class="{ on: repRange === r }" @click="repRange = r">{{ t('range.' + r) }}</button></div>
          <span class="sp" />
          <template v-if="isAdmin">
          <label class="chk"><input type="checkbox" :checked="rep && rep.settings.daily" @change="setRep('daily', $event.target.checked)" /> {{ t('audit.rep.daily') }}</label>
          <label class="chk"><input type="checkbox" :checked="rep && rep.settings.weekly" @change="setRep('weekly', $event.target.checked)" /> {{ t('audit.rep.weekly') }}</label>
          <button class="btn sm" @click="pushRep" :disabled="!rep">{{ t('audit.rep.push') }}</button>
          </template>
        </div>
        <div class="panel-b" v-if="rep">
          <div class="grid g4 stats4">
            <Stat :label="t('common.total')" :value="bytes(rep.total.total)" :up="rep.total.up" :down="rep.total.down" />
            <Stat :label="t('overview.identified')" :value="pct(rep.identified_ratio, 0)" />
            <Stat :label="t('audit.rep.newHosts')" :value="rep.new_hosts.length" />
            <Stat :label="t('audit.tab.events')" :value="rep.events_total" />
          </div>
          <div class="grid g2-wide mt">
            <div><div class="sec">{{ t('overview.topHosts') }}</div><BarList :items="repHosts" :total="rep.total.total" /></div>
            <div><div class="sec">{{ t('overview.topApps') }}</div><BarList :items="repApps" :total="rep.total.total" /></div>
          </div>
          <div class="grid g2-wide mt">
            <div><div class="sec">{{ t('audit.rep.newHosts') }}</div>
              <ul class="plain nh"><li v-for="h in rep.new_hosts" :key="h.key"><router-link :to="`/hosts/${enc(h.key)}`" class="link">{{ h.name }}</router-link>
                <span class="faint addr small">{{ [h.name !== h.ip ? h.ip : '', h.mac].filter(Boolean).join(' · ') }}</span></li></ul>
              <div v-if="!rep.new_hosts.length" class="faint small">{{ t('common.empty') }}</div></div>
            <div><div class="sec">{{ t('audit.tab.events') }}</div>
              <ul class="plain"><li v-for="e in rep.events" :key="e.rule">{{ e.rule }} <b class="num">{{ e.count }}</b></li></ul>
              <div v-if="!rep.events.length" class="faint small">{{ t('common.empty') }}</div></div>
          </div>
          <div class="sec mt">{{ t('audit.rep.preview') }}</div>
          <pre class="code">{{ rep.title }}
{{ rep.text }}</pre>
          <div class="err small" v-if="repErr">{{ repErr }}</div>
        </div>
      </div>
    </template>

    <!-- 操作日志 -->
    <div class="panel" v-if="tab === 'oplog'">
      <div class="panel-b head">
        <div class="info-bar"><span class="ic">i</span><div><b>{{ t('audit.tab.oplog') }}</b><span>{{ t('audit.op.info') }}</span></div></div>
      </div>
      <div class="tbl-wrap" v-if="ops">
        <table class="tbl">
          <thead><tr><th>{{ t('audit.log.time') }}</th><th>{{ t('login.username') }}</th><th class="m-hide">IP</th><th>{{ t('audit.op.action') }}</th><th class="m-hide">{{ t('audit.op.detail') }}</th><th>{{ t('audit.rule.state') }}</th></tr></thead>
          <tbody>
            <tr v-for="o in ops.rows" :key="o.id">
              <td class="num small">{{ datetime(o.ts) }}</td><td>{{ o.user }}</td><td class="addr m-hide">{{ o.ip }}</td>
              <td>{{ te('audit.op.actions.' + o.action) ? t('audit.op.actions.' + o.action) : o.action }}</td>
              <td class="m-hide small muted det" :title="o.detail">{{ o.detail }}</td>
              <td><span class="pill" :class="o.ok ? 'ok' : 'bad'">{{ o.ok ? t('audit.op.ok') : t('audit.op.fail') }}</span></td>
            </tr>
          </tbody>
        </table>
        <div v-if="!ops.rows.length" class="empty">{{ t('common.empty') }}</div>
      </div>
    </div>

    <!-- 规则编辑 -->
    <Modal :open="!!form" :title="form && form.id ? t('audit.rule.edit') : t('audit.rule.add')" width="640px" @close="form = null">
      <form v-if="form" class="rf" @submit.prevent="saveRule">
        <label for="rf-name">{{ t('common.name') }}</label>
        <input id="rf-name" class="input" v-model="form.name" required maxlength="64" />
        <label for="rf-kind">{{ t('audit.rule.kind') }}</label>
        <select id="rf-kind" class="input" v-model="form.kind" @change="form.value = ''">
          <option v-for="k in KINDS" :key="k" :value="k">{{ t('audit.kind.' + k) }}</option>
        </select>
        <template v-if="form.kind === 'group'">
          <label for="rf-val">{{ t('apps.group') }}</label>
          <select id="rf-val" class="input" v-model="form.value"><option v-for="g in meta.groups" :key="g.id" :value="g.id">{{ groupName(g) }}</option></select>
        </template>
        <template v-else-if="form.kind === 'category'">
          <label for="rf-val">{{ t('common.category') }}</label>
          <select id="rf-val" class="input" v-model="form.value"><option v-for="c in meta.categories" :key="c.id" :value="c.id">{{ catName(c) }}</option></select>
        </template>
        <template v-else-if="form.kind === 'app'">
          <label for="rf-val">{{ t('apps.app') }}</label>
          <input id="rf-appq" class="input" v-model="appQ" :placeholder="t('common.search')" />
          <select id="rf-val" class="input" v-model="form.value" size="6">
            <option v-for="a in appChoices" :key="a.id" :value="a.id">{{ appName(a) }}</option></select>
        </template>
        <template v-else-if="form.kind === 'domain'">
          <label for="rf-val">{{ t('hosts.domain') }}</label>
          <input id="rf-val" class="input addr" v-model="form.value" placeholder="example.com" />
        </template>
        <template v-else-if="form.kind === 'upload'">
          <label for="rf-val">{{ t('audit.rule.uploadTo') }}</label>
          <select id="rf-val" class="input" v-model="form.value"><option value="">{{ t('audit.rule.anyDest') }}</option>
            <option v-for="g in meta.groups" :key="g.id" :value="g.id">{{ groupName(g) }}</option>
            <option v-for="c in meta.categories" :key="c.id" :value="c.id">· {{ catName(c) }}</option></select>
        </template>
        <div v-if="form.kind === 'sharing'" class="faint small">{{ t('audit.rule.sharingHint') }}</div>
        <template v-if="form.kind !== 'sharing' && form.kind !== 'new_host'">
        <label for="rf-min">{{ form.kind === 'upload' ? t('audit.rule.uploadMin') : t('audit.rule.minBytes') }}</label>
        <div class="row"><input id="rf-min" class="input num w" type="number" min="0" step="1" v-model.number="form.min_mb" /><span class="muted">MB</span>
          <span class="faint small">{{ ['traffic', 'upload'].includes(form.kind) ? t('audit.rule.minNeed') : t('audit.rule.minHint') }}</span></div>
        </template>
        <label>{{ t('audit.rule.when') }}</label>
        <div class="row days">
          <label v-for="d in 7" :key="d" class="chk"><input type="checkbox" :checked="form.days.includes(String(d))" @change="toggleDay(d)" /> {{ t('audit.dow.' + d) }}</label>
        </div>
        <div class="row"><input id="rf-from" class="input w" type="time" v-model="form.time_from" :aria-label="t('audit.rule.from')" /><span>–</span>
          <input id="rf-to" class="input w" type="time" v-model="form.time_to_ui" :aria-label="t('audit.rule.to')" />
          <span class="faint small">{{ t('audit.rule.timeHint') }}</span></div>
        <label>{{ t('audit.rule.scope') }}</label>
        <div class="chips" v-if="scene.people.length || scene.departments.length">
          <button v-for="g in scene.departments" :key="'d' + g.id" type="button" class="chip-b" :class="{ on: form.hosts.includes('dept:' + g.id) }" @click="toggleHost('dept:' + g.id)">{{ L('dept') }} · {{ g.name }}</button>
          <button v-for="x in scene.people" :key="'p' + x.id" type="button" class="chip-b" :class="{ on: form.hosts.includes('person:' + x.id) }" @click="toggleHost('person:' + x.id)">{{ x.name }}</button>
        </div>
        <input id="rf-hosts" class="input" v-model="hostQ" :placeholder="t('audit.rule.hostSearch')" :aria-label="t('audit.rule.hostSearch')" />
        <div class="hostbox">
          <label v-for="h in hostChoices" :key="h.key" class="chk"><input type="checkbox" :checked="form.hosts.includes(h.key)" @change="toggleHost(h.key)" />
            {{ h.name }} <span class="faint addr small">{{ h.ip }}</span></label>
        </div>
        <div class="faint small">{{ form.hosts.length ? scopeText(form.hosts) : t('audit.rule.allHostsHint') }}</div>
        <template v-if="form.notify">
          <label>{{ t('audit.rule.channels') }}</label>
          <div class="chips">
            <button v-for="k in enabledCh" :key="k" type="button" class="chip-b" :class="{ on: form.channels.includes(k) }" @click="toggleCh(k)">{{ t('nc.types.' + k) }}</button>
            <span v-if="!enabledCh.length" class="faint small">{{ t('audit.rule.noChannel') }}</span>
          </div>
          <div class="faint small" v-if="enabledCh.length">{{ form.channels.length ? '' : t('audit.rule.allChannels') }}</div>
        </template>
        <div class="row">
          <label class="chk"><input type="checkbox" v-model="form.notify" /> {{ t('audit.rule.notify') }}</label>
          <label class="chk"><input type="checkbox" v-model="form.enabled" /> {{ t('audit.rule.enable') }}</label>
        </div>
        <div class="err" v-if="formErr">{{ formErr }}</div>
        <div class="row end"><button type="button" class="btn" @click="form = null">{{ t('common.cancel') }}</button>
          <button class="btn primary">{{ t('common.save') }}</button></div>
      </form>
    </Modal>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import http, { enc, isAdmin } from '../api.js'
import AccessLog from '../components/AccessLog.vue'
import NotifyChannels from '../components/NotifyChannels.vue'
import { L, loadScene, scene } from '../scenario.js'
import BarList from '../components/BarList.vue'
import Icon from '../components/Icon.vue'
import Modal from '../components/Modal.vue'
import RangeTabs from '../components/RangeTabs.vue'
import Stat from '../components/Stat.vue'
import { appName, bytes, catColor, catName, datetime, groupName, pct } from '../format.js'
import { ui } from '../state.js'

const ALL_TABS = ['logs', 'events', 'rules', 'notify', 'report', 'sharing', 'oplog']
// 普通用户：看日志、事件、报表；审计规则、通知通道和操作日志只给管理员
const TABS = computed(() => ALL_TABS.filter(k => isAdmin.value || !['rules', 'notify', 'oplog'].includes(k)))
const KINDS = ['group', 'category', 'app', 'domain', 'traffic', 'upload', 'new_host', 'sharing']
const GB = 1024
const enabledCh = ref([])
const sh = ref(null)
async function loadSh() { sh.value = await http.get('/sharing') }
function toggleCh(k) {
  const i = form.value.channels.indexOf(k)
  i >= 0 ? form.value.channels.splice(i, 1) : form.value.channels.push(k)
}
function scopeText(list) {
  return list.map(x => x.startsWith('person:') ? (scene.people.find(p => 'person:' + p.id === x) || {}).name
    : x.startsWith('dept:') ? L('dept') + '·' + ((scene.departments.find(g => 'dept:' + g.id === x) || {}).name)
      : (hosts.value.find(h => h.key === x) || { name: x }).name).filter(Boolean).join('、')
}
// 常用模板：一键填好规则表单，用户再改
// 常用模板：一键填好规则表单，用户再改。家用侧重孩子的上网健康，企业侧重效率与合规
const TPL = {
  home: [
    { key: 'adult', rule: { kind: 'category', value: 'adult' } },
    { key: 'homeworkGame', rule: { kind: 'group', value: 'game', days: '12345', time_from: '19:00', time_to: '21:00' } },
    { key: 'bedtime', rule: { kind: 'traffic', time_from: '22:00', time_to: '06:00', min_mb: 50 } },
    { key: 'shortVideo', rule: { kind: 'category', value: 'short_video', min_mb: 2 * GB } },
    { key: 'newHost', rule: { kind: 'new_host' } },
  ],
  enterprise: [
    { key: 'workGame', rule: { kind: 'group', value: 'game', days: '12345', time_from: '09:00', time_to: '18:00' } },
    { key: 'jobs', rule: { kind: 'app', value: 'jobs', days: '12345', time_from: '09:00', time_to: '18:00' } },
    { key: 'leak', rule: { kind: 'upload', value: '', min_mb: 2 * GB } },
    { key: 'sharing', rule: { kind: 'sharing' } },
    { key: 'newHost', rule: { kind: 'new_host' } },
    { key: 'lateNight', rule: { kind: 'traffic', time_from: '23:00', time_to: '06:00', min_mb: 500 } },
  ],
}
const TEMPLATES = computed(() => TPL[scene.id] || TPL.home)
const { t, te } = useI18n()
const route = useRoute()
const router = useRouter()
const tab = computed(() => (TABS.value.includes(route.query.tab) ? route.query.tab : 'logs'))
const setTab = k => router.replace({ query: k === 'logs' ? {} : { tab: k } })
const err = ref('')

const sum = ref(null)
const loadSum = async () => { try { sum.value = await http.get('/audit/summary') } catch (e) { /* 顶部计数而已 */ } }

// ---------- 事件 ----------
const ev = ref(null)
async function loadEv() { ev.value = await http.get('/audit/events', { params: { range: ui.range, size: 200 } }) }

// ---------- 规则 ----------
const rules = ref([])
const meta = ref({ groups: [], categories: [], apps: [] })
const hosts = ref([])
const form = ref(null)
const formErr = ref('')
const appQ = ref('')
const hostQ = ref('')
async function loadRules() {
  ;[rules.value, meta.value, hosts.value] = await Promise.all([http.get('/audit/rules'), http.get('/meta'), http.get('/hosts')])
}
const appChoices = computed(() => {
  const s = appQ.value.trim().toLowerCase()
  return meta.value.apps.filter(a => !s || [a.id, a.name, a.name_en].some(v => v && String(v).toLowerCase().includes(s))).slice(0, 200)
})
const hostChoices = computed(() => {
  const s = hostQ.value.trim().toLowerCase()
  return hosts.value.filter(h => !s || [h.name, h.ip, h.mac].some(v => v && v.toLowerCase().includes(s))).slice(0, 100)
})
function edit(r) {
  formErr.value = ''
  appQ.value = hostQ.value = ''
  const base = { id: null, name: '', enabled: true, kind: 'group', value: '', hosts: [], days: '1234567', time_from: '00:00', time_to: '24:00', min_bytes: 0, notify: true, channels: [] }
  const x = { ...base, ...(r || {}) }
  form.value = { ...x, hosts: [...x.hosts], channels: [...(x.channels || [])], min_mb: x.min_mb ?? Math.round((x.min_bytes || 0) / 1048576),
    time_to_ui: x.time_to === '24:00' ? '00:00' : x.time_to }
}
function toggleDay(d) {
  const s = new Set(form.value.days.split(''))
  s.has(String(d)) ? s.delete(String(d)) : s.add(String(d))
  form.value.days = [...s].sort().join('') || '1234567'
}
function toggleHost(k) {
  const i = form.value.hosts.indexOf(k)
  i >= 0 ? form.value.hosts.splice(i, 1) : form.value.hosts.push(k)
}
async function saveRule() {
  formErr.value = ''
  const f = form.value
  // 结束时间 00:00 表示到当天结束
  const to = f.time_to_ui === '00:00' || !f.time_to_ui ? '24:00' : f.time_to_ui
  const body = { name: f.name, enabled: f.enabled, kind: f.kind, value: f.value || null, hosts: f.hosts, days: f.days,
    time_from: f.time_from || '00:00', time_to: to, min_bytes: Math.round((f.min_mb || 0) * 1048576), notify: f.notify,
    channels: f.channels }
  try {
    if (f.id) await http.put(`/audit/rules/${f.id}`, body)
    else await http.post('/audit/rules', body)
    form.value = null
    await loadRules()
  } catch (e) { formErr.value = e.message }
}
async function del(r) {
  if (!confirm(t('common.confirmDelete'))) return
  err.value = ''
  try {
    await http.delete(`/audit/rules/${r.id}`)
    await loadRules()
  } catch (e) { err.value = e.message }
}
function condText(r) {
  if (r.kind === 'upload') {
    const x = r.value && (meta.value.groups.find(g => g.id === r.value) || meta.value.categories.find(c => c.id === r.value))
    return t('audit.cond.upload', { v: x ? catName(x) : t('audit.rule.anyDest'), b: bytes(r.min_bytes) })
  }
  const v = r.kind === 'group' ? groupName(meta.value.groups.find(g => g.id === r.value))
    : r.kind === 'category' ? catName(meta.value.categories.find(c => c.id === r.value) || { name: r.value })
      : r.kind === 'app' ? appName(meta.value.apps.find(a => a.id === r.value) || { name: r.value }) : r.value
  const base = t('audit.cond.' + r.kind, { v })
  return r.min_bytes ? `${base}，${t('audit.cond.over', { b: bytes(r.min_bytes) })}` : base
}
function whenText(r) {
  const days = r.days === '1234567' ? t('audit.rule.everyday') : r.days === '12345' ? t('audit.rule.weekdays')
    : r.days.split('').map(d => t('audit.dow.' + d)).join('、')
  const time = r.time_from === '00:00' && r.time_to === '24:00' ? t('audit.rule.allDay') : `${r.time_from}–${r.time_to}`
  return `${days} ${time}`
}

// ---------- 通知通道 ----------
async function loadEnabled() { enabledCh.value = (await http.get('/audit/notify')).enabled }

// ---------- 报表 ----------
const rep = ref(null)
const repRange = ref('yesterday')
const repErr = ref('')
async function loadRep() { rep.value = await http.get('/audit/report', { params: { range: repRange.value } }) }
async function setRep(k, v) { rep.value.settings = await http.put('/audit/report/settings', { [k]: v }) }
async function pushRep() {
  repErr.value = ''
  try {
    const r = await http.post('/audit/report/push', null, { params: { range: repRange.value }, timeout: 60000 })
    const bad = r.results.filter(x => !x.ok)
    repErr.value = bad.length ? bad.map(x => `${x.name}：${x.error}`).join('；') : ''
    if (!bad.length) alert(t('audit.ch.sent'))
  } catch (e) { repErr.value = e.message }
}
const repHosts = computed(() => rep.value.top_hosts.map(h => ({ key: h.key, label: h.name, sub: h.name !== h.ip ? h.ip : '', value: h.total, up: h.up, down: h.down, online: h.online, to: `/hosts/${enc(h.key)}` })))
const repApps = computed(() => rep.value.top_apps.map(a => ({ key: a.id, label: appName(a), sub: catName(a), value: a.total, up: a.up, down: a.down, color: catColor(a.category), to: `/apps/${enc(a.id)}` })))

// ---------- 操作日志 ----------
const ops = ref(null)
async function loadOps() { ops.value = await http.get('/audit/oplog', { params: { size: 200 } }) }

async function loadTab() {
  err.value = ''
  try {
    if (tab.value === 'events') await loadEv()
    else if (tab.value === 'rules') await Promise.all([loadRules(), loadScene(true), loadEnabled()])
    else if (tab.value === 'sharing') await loadSh()
    else if (tab.value === 'report') await loadRep()
    else if (tab.value === 'oplog') await loadOps()
  } catch (e) { err.value = e.message }
}
onMounted(loadSum)
watch([tab, () => ui.range, repRange], loadTab, { immediate: true })
</script>

<style scoped>
.tabs button { font-size: 15px; padding: 8px 14px 11px; }
.cnt { margin-left: 6px; font-size: 12px; background: var(--bad); color: #fff; border-radius: 9px; padding: 0 6px; }
.head { display: grid; gap: 14px; padding-bottom: 6px; }
.hl { font-weight: 500; }
.hl:hover { color: var(--brand-ink); }
.hit { display: inline-flex; align-items: center; gap: 5px; margin-right: 12px; }
.nowrap { white-space: nowrap; }
.tpls { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 10px; }
.tpl { text-align: left; background: var(--sunk); border: 1px solid transparent; border-radius: 10px; padding: 10px 12px; cursor: pointer; display: grid; gap: 2px; }
.tpl:hover { border-color: var(--brand-ink); }
.chs { display: grid; gap: 10px; }
.chips { display: flex; gap: 6px; flex-wrap: wrap; }
.chip-b { border: 1px solid var(--line); background: var(--panel); color: var(--ink); border-radius: 16px; padding: 3px 11px; font: inherit; font-size: 13px; cursor: pointer; }
.chip-b.on { border-color: var(--brand-ink); background: var(--brand-weak); color: var(--brand-ink); }
.rs { margin-right: 4px; }
.ch { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.ch select { width: 150px; }
.ch input:not(.grow):not([type=checkbox]) { width: 150px; }
.ch .grow { flex: 1; min-width: 220px; }
.acts { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.acts .sp { flex: 1; }
.okc { color: var(--ok); }
.chk { display: inline-flex; gap: 6px; align-items: center; color: var(--muted); font-size: 13px; cursor: pointer; white-space: nowrap; }
.stats4 { margin-bottom: 4px; }
.plain { list-style: none; margin: 8px 0 0; padding: 0; display: grid; gap: 6px; font-size: 14px; }
.nh { grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); column-gap: 16px; max-height: 300px; overflow-y: auto; }
.nh li { display: grid; min-width: 0; }
.nh li > * { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.det { max-width: 420px; overflow: hidden; text-overflow: ellipsis; }
.rf { display: grid; gap: 8px; }
.rf > label { font-size: 13px; color: var(--muted); margin-top: 4px; }
.rf .row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.rf .row.end { justify-content: flex-end; margin-top: 8px; }
.rf .w { width: 130px; }
.rf .days { gap: 12px; }
.hostbox { max-height: 170px; overflow-y: auto; border: 1px solid var(--line); border-radius: 8px; padding: 8px 10px; display: grid; gap: 4px; }
.sec + .tpls, .sec + .hostbox { margin-top: -4px; }
@media (max-width: 640px) { .ch select, .ch input:not([type=checkbox]) { width: 100% !important; } }
</style>
