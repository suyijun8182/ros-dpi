<template>
  <div>
    <div class="page-h">
      <router-link to="/people" class="btn sm">← {{ t('common.back') }}</router-link>
      <h1 v-if="d"><span class="dot" :class="{ on: online }" /> {{ d.name }}</h1>
      <span v-if="d && d.dept" class="pill grey">{{ d.dept }}</span>
      <span class="sp" />
      <template v-if="d && isAdmin">
        <router-link :to="`/people?edit=${id}`" class="btn sm"><Icon name="edit" :size="15" />{{ t('common.edit') }}</router-link>
        <button class="btn sm danger" @click="delPerson">{{ t('common.delete') }}</button>
        <button class="btn sm" @click="ctl = true"><Icon name="shield" :size="15" />{{ t('ctl.button') }}</button>
      </template>
      <RangeTabs v-if="tab !== 'timeline'" />
    </div>
    <div v-if="err" class="err">{{ err }}</div>

    <div class="seg tabs sub-tabs" role="tablist" v-if="d">
      <button v-for="k in ['overview', 'log', 'timeline']" :key="k" role="tab" :aria-selected="tab === k" :class="{ on: tab === k }" @click="setTab(k)">{{ t('audit.htab.' + k) }}</button>
    </div>
    <div class="panel" v-if="d && tab === 'log'"><div class="panel-b pad0" /><AccessLog :person="id" /></div>
    <div class="panel" v-if="d && tab === 'timeline'"><div class="panel-b pad0" /><Timeline :person="id" /></div>

    <template v-if="d && tab === 'overview'">
      <!-- 设备 -->
      <div class="panel">
        <div class="panel-h"><h2>{{ t('people.devices') }}</h2><span class="faint small">{{ t('people.nDevices', { n: d.devices.length }) }}</span><span class="sp" />
          <template v-if="isAdmin">
            <select class="input sel" :aria-label="t('people.addDevice')" @change="addDevice($event)">
              <option value="">{{ t('people.addDevice') }}</option>
              <option v-for="h in freeHosts" :key="h.key" :value="h.key">{{ h.name }} {{ h.ip || '' }}</option>
            </select></template></div>
        <div class="panel-b devs">
          <div v-for="h in d.devices" :key="h.key" class="dev">
            <Icon :name="'dev-' + (h.dtype || 'unknown')" :size="26" class="di" :class="{ on: h.online }" />
            <div class="dm"><router-link :to="`/hosts/${enc(h.key)}`" class="hl"><b>{{ h.name }}</b></router-link>
              <span class="faint small">{{ t('dev.' + (h.dtype || 'unknown')) }}<template v-if="h.vendor"> · {{ h.vendor }}</template></span>
              <span class="faint addr small">{{ h.ip }}<template v-if="h.mac"> · {{ h.mac }}</template></span></div>
            <button v-if="isAdmin" class="btn sm ghost" :title="t('people.unbind')" :aria-label="t('people.unbind')" @click="unbind(h.key)"><Icon name="close" :size="14" /></button>
          </div>
          <div v-if="!d.devices.length" class="faint">{{ t('people.noDevice') }}</div>
        </div>
      </div>

      <div class="grid g4 mt">
        <Stat :label="t('range.' + ui.range) + ' · ' + t('flow.bytes')" :value="bytes(d.range_total.total)" :up="d.range_total.up" :down="d.range_total.down" />
        <Stat :label="t('people.online')" :value="hours(d.usage.online)" :sub="t('people.nightShort') + ' ' + hours(d.usage.night)" />
        <Stat :label="L('workOnline')" :value="hours(d.usage.work_online)" :sub="L('leisureShare') + ' ' + (d.usage.work_online ? pct(d.usage.leisure_work / d.usage.work_online, 0) : '-')" />
        <Stat :label="t('range.month')" :value="bytes(d.totals.month.total)" :up="d.totals.month.up" :down="d.totals.month.down" />
      </div>

      <div class="grid g2-wide mt">
        <!-- 最近 7 天 -->
        <div class="panel">
          <div class="panel-h"><h2>{{ t('people.last7') }}</h2><span class="sp" />
            <span class="lg"><i class="o" />{{ t('people.online') }}</span><span class="lg"><i class="l" />{{ L('leisureInWork') }}</span>
            <span class="lg" v-if="d.scenario === 'home'"><i class="n" />{{ t('people.night') }}</span></div>
          <div class="panel-b">
            <div class="days7">
              <div v-for="x in d.week.days" :key="x.ts" class="dcol" :title="dayTip(x)">
                <div class="dbar"><i class="o" :style="{ height: hpct(x.online) }" /><i class="l" :style="{ height: hpct(x.leisure_work) }" />
                  <i v-if="d.scenario === 'home'" class="n" :style="{ height: hpct(x.night) }" />
                  <span v-if="limit && x.online > limit" class="over" :style="{ bottom: hpct(limit) }" /></div>
                <span class="num small">{{ (x.online / 3600).toFixed(1) }}h</span><span class="faint small">{{ dayLabel(x.ts) }}</span>
              </div>
            </div>
            <div class="sec mt">{{ t('people.tags') }}<span class="faint small">{{ t('people.last7') }}</span></div>
            <ul class="tl">
              <li v-for="x in d.week.tags" :key="x.id"><span class="pill" :class="x.level === 'high' ? 'bad' : 'warn'">{{ t('tag.' + x.id) }}</span>
                <span class="num">{{ x.unit === 'days' ? t('people.days', { n: x.value }) : hours(x.value) }}</span>
                <span class="faint small" v-if="x.apps.length">{{ x.apps.map(a => appName(a) + ' ' + hours(a.seconds)).join('、') }}</span></li>
              <li v-if="!d.week.tags.length" class="faint">{{ t('people.noTags') }}</li>
            </ul>
          </div>
        </div>
        <!-- 应用使用时长 -->
        <div class="panel">
          <div class="panel-h"><h2>{{ t('people.appTime') }}</h2><span class="faint small">{{ t('range.' + ui.range) }}</span></div>
          <div class="tbl-wrap">
            <table class="tbl">
              <thead><tr><th>{{ t('apps.app') }}</th><th class="r">{{ t('people.duration') }}</th><th class="r m-hide">{{ L('workTimeShort') }}</th></tr></thead>
              <tbody>
                <tr v-for="a in d.usage.apps.slice(0, appN)" :key="a.id">
                  <td><span class="tag"><span class="chip" :style="{ background: catColor(a.category) }" />{{ appName(a) }}</span>
                    <span v-if="a.leisure" class="pill grey ls">{{ t('people.leisureTag') }}</span></td>
                  <td class="r num">{{ hours(a.seconds) }}</td><td class="r num m-hide muted">{{ hours(a.work_seconds) }}</td>
                </tr>
              </tbody>
            </table>
            <div v-if="!d.usage.apps.length" class="empty">{{ t('common.empty') }}</div>
            <div v-else-if="d.usage.apps.length > appN" class="more-row"><button class="btn sm" @click="appN += 20">{{ t('flow.showMore') }}</button></div>
          </div>
        </div>
      </div>

      <div class="panel mt">
        <div class="panel-h"><h2>{{ t('overview.mix') }}</h2></div>
        <div class="panel-b"><Treemap :groups="d.groups" height="240px" @pick="p => $router.push({ path: '/apps', query: p.cat ? { cat: p.cat } : { group: p.group } })" /></div>
      </div>
      <div class="mt"><TrafficPanel :total="d.range_total" :points="d.trend" :groups="d.trend_groups" :gran="gran" height="232px" /></div>
    </template>
    <div v-else-if="!d && !err" class="empty">{{ t('common.loading') }}</div>

    <ControlModal :open="ctl" target="person" :target-id="id" :name="d ? d.name : ''" @close="ctl = false" />
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import http, { enc, isAdmin } from '../api.js'
import AccessLog from '../components/AccessLog.vue'
import Treemap from '../components/Treemap.vue'
import ControlModal from '../components/ControlModal.vue'
import Icon from '../components/Icon.vue'
import RangeTabs from '../components/RangeTabs.vue'
import Stat from '../components/Stat.vue'
import Timeline from '../components/Timeline.vue'
import TrafficPanel from '../components/TrafficPanel.vue'
import { appName, bytes, catColor, pct } from '../format.js'
import { hours, L, scene, syncScene } from '../scenario.js'
import { ui } from '../state.js'

const props = defineProps({ id: String })
const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const d = ref(null)
const err = ref('')
const ctl = ref(false)
const appN = ref(10)
const free = ref([])
const tab = computed(() => (['log', 'timeline'].includes(route.query.tab) ? route.query.tab : 'overview'))
const setTab = k => router.replace({ query: k === 'overview' ? {} : { tab: k } })
const gran = computed(() => (['today', 'yesterday'].includes(ui.range) ? 'hour' : 'day'))
const online = computed(() => d.value && d.value.devices.some(h => h.online))
const limit = computed(() => (d.value && d.value.scenario === 'home' ? d.value.config.limits.screen : 0))

async function load() {
  try {
    d.value = await http.get(`/people/${props.id}/detail`, { params: { range: ui.range } })
    syncScene(d.value.scenario)
    err.value = ''
  } catch (e) { err.value = e.message }
}
async function delPerson() {
  if (!confirm(t('people.confirmDel', { name: d.value.name }))) return
  try {
    await http.delete(`/people/${props.id}`)
    router.push('/people')
  } catch (e) { err.value = e.message }
}
async function loadFree() {
  if (!isAdmin.value) return
  try {
    const r = await http.get('/people', { params: { range: 'today' } })
    free.value = r.unassigned
  } catch (e) { err.value = e.message }
}
const freeHosts = computed(() => free.value)
async function addDevice(ev) {
  const k = ev.target.value
  ev.target.value = ''
  if (!k) return
  err.value = ''
  try {
    await http.put('/devices/bind', { host: k, person_id: +props.id })
    await Promise.all([load(), loadFree()])
  } catch (e) { err.value = e.message }
}
async function unbind(k) {
  err.value = ''
  try {
    await http.put('/devices/bind', { host: k, person_id: null })
    await Promise.all([load(), loadFree()])
  } catch (e) { err.value = e.message }
}
const maxDay = computed(() => Math.max(3600, ...(d.value ? d.value.week.days.map(x => x.online) : [0]), limit.value || 0))
const hpct = s => Math.min(100, (s || 0) / maxDay.value * 100) + '%'
const dayLabel = ts => { const x = new Date(ts * 1000); return `${x.getMonth() + 1}/${x.getDate()}` }
const dayTip = x => `${dayLabel(x.ts)}  ${t('people.online')} ${hours(x.online)} · ${L('leisureInWork')} ${hours(x.leisure_work)} · ${t('people.night')} ${hours(x.night)}`
  + (d.value.scenario === 'home' ? ` · ${t('people.game')} ${hours(x.game)} · ${t('people.shortVideo')} ${hours(x.short_video)}` : '')

watch([() => props.id, () => ui.range], load, { immediate: true })
watch(() => props.id, loadFree, { immediate: true })
</script>

<style scoped>
.mt { margin-top: 14px; }
.page-h h1 { display: inline-flex; align-items: center; gap: 8px; }
.sub-tabs { margin-bottom: 14px; }
.sub-tabs button { font-size: 15px; padding: 8px 14px 11px; }
.pad0 { padding-bottom: 0; }
.sel { height: 30px; max-width: 220px; }
.devs { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 10px; }
.dev { display: flex; gap: 12px; align-items: center; background: var(--sunk); border-radius: 12px; padding: 10px 12px; min-width: 0; }
.di { color: var(--faint); flex: none; }
.di.on { color: var(--ok); }
.dm { display: grid; gap: 1px; min-width: 0; flex: 1; }
.dm > * { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.hl:hover { color: var(--brand-ink); }
.lg { display: inline-flex; align-items: center; gap: 5px; font-size: 12px; color: var(--muted); margin-left: 12px; }
.lg i, .dbar i { display: block; border-radius: 3px; }
.lg i { width: 10px; height: 10px; }
.o { background: color-mix(in srgb, var(--accent) 35%, var(--panel)); }
.l { background: var(--warn); }
.n { background: var(--g-http, #7a5bd6); }
.days7 { display: grid; grid-template-columns: repeat(auto-fit, minmax(36px, 1fr)); gap: 8px; align-items: end; }
.dcol { display: grid; justify-items: center; gap: 2px; }
.dbar { position: relative; width: 100%; max-width: 34px; height: 130px; background: var(--sunk); border-radius: 6px; overflow: hidden; }
.dbar i { position: absolute; left: 0; right: 0; bottom: 0; border-radius: 0; }
.dbar .l { right: 40%; }
.dbar .n { left: 60%; }
.over { position: absolute; left: -2px; right: -2px; border-top: 2px dashed var(--bad); }
.tl { list-style: none; margin: 8px 0 0; padding: 0; display: grid; gap: 8px; }
.tl li { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; font-size: 14px; }
.more-row { display: flex; justify-content: center; padding: 10px; }
.ls { height: 18px; font-size: 10px; margin-left: 6px; }
</style>
