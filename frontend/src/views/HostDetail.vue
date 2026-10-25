<template>
  <div>
    <div class="page-h">
      <router-link to="/hosts" class="btn sm">← {{ t('common.back') }}</router-link>
      <h1 v-if="d"><span class="dot" :class="{ on: d.online }" /> {{ d.name }}</h1>
      <span class="sp" />
      <button v-if="d && isAdmin" class="btn sm" @click="ctl = true"><Icon name="shield" :size="15" />{{ t('ctl.button') }}</button>
      <RangeTabs v-if="tab !== 'timeline'" />
    </div>
    <div v-if="error" class="err">{{ error }}</div>

    <div class="seg tabs host-tabs" role="tablist" v-if="d">
      <button v-for="k in HTABS" :key="k" role="tab" :aria-selected="tab === k" :class="{ on: tab === k }" @click="setTab(k)">{{ t('audit.htab.' + k) }}</button>
    </div>

    <div class="panel" v-if="d && tab === 'log'"><div class="panel-b head-pad" /><AccessLog :host="hostKey" /></div>
    <div class="panel" v-if="d && tab === 'timeline'"><div class="panel-b head-pad" /><Timeline :host="hostKey" /></div>

    <template v-if="d && tab === 'overview'">
      <div class="panel info">
        <div><span class="k">{{ t('hosts.ip') }}</span><span class="addr">{{ d.ip || '-' }}</span></div>
        <div><span class="k">{{ t('hosts.mac') }}</span><span class="addr">{{ d.mac || '-' }}</span></div>
        <div><span class="k">{{ t('hosts.hostname') }}</span>{{ d.hostname || '-' }}</div>
        <div><span class="k">{{ t('hosts.firstSeen') }}</span>{{ datetime(d.first_seen) }}</div>
        <div><span class="k">{{ t('hosts.lastSeen') }}</span>{{ ago(d.last_seen) }}</div>
        <div><span class="k">{{ t('common.rate') }}</span><span class="num"><span class="up">↑{{ rate(d.rate_up) }}</span> <span class="down">↓{{ rate(d.rate_down) }}</span></span></div>
        <div><span class="k">{{ t('people.dtype') }}</span>
          <select v-if="isAdmin" class="input sel" :value="d.dtype_manual || ''" :aria-label="t('people.dtype')" @change="setDtype($event.target)">
            <option value="">{{ t('people.dtypeAuto', { t: t('dev.' + (d.dtype_auto || 'unknown')) }) }}</option>
            <option v-for="x in DTYPES" :key="x" :value="x">{{ t('dev.' + x) }}</option></select>
          <span v-else><Icon :name="'dev-' + (d.dtype || 'unknown')" :size="15" /> {{ t('dev.' + (d.dtype || 'unknown')) }}</span>
          <span class="faint small" v-if="d.vendor"> {{ d.vendor }}</span></div>
        <div><span class="k">{{ L('person') }}</span>
          <select v-if="isAdmin" class="input sel" :value="d.person ? d.person.id : ''" :aria-label="L('person')" @change="setPerson($event.target)">
            <option value="">—</option>
            <option v-for="p in scene.people" :key="p.id" :value="p.id">{{ p.name }}</option></select>
          <router-link v-else-if="d.person" :to="`/people/${d.person.id}`" class="link">{{ d.person.name }}</router-link><span v-else>-</span>
          <router-link v-if="isAdmin && d.person" :to="`/people/${d.person.id}`" class="link small"> {{ t('common.details') }} ›</router-link></div>
        <div class="err" v-if="infoErr">{{ t('common.saveFail') }}：{{ infoErr }}</div>
        <div class="alias" v-if="isAdmin">
          <span class="k">{{ t('hosts.alias') }}</span>
          <input class="input" v-model="alias" :placeholder="t('hosts.aliasPlaceholder')" @keyup.enter="saveAlias" />
          <div class="seg by" role="radiogroup" :aria-label="t('hosts.nameBy')">
            <button v-for="k in ['mac', 'ip']" :key="k" type="button" role="radio" :aria-checked="by === k" :class="{ on: by === k }"
                    :disabled="k === 'mac' && !d.mac" :title="t('hosts.byHint.' + k)" @click="by = k">{{ t('hosts.by.' + k) }}</button>
          </div>
          <button class="btn sm" @click="saveAlias" :disabled="alias === (d.alias || '') && by === (d.alias_by || defBy)">{{ saved ? t('common.saved') : t('common.save') }}</button>
          <span class="faint small hint">{{ t('hosts.byHint.' + by) }}</span>
          <div class="err" v-if="aliasErr">{{ aliasErr }}</div>
        </div>
      </div>

      <div class="grid mt" :class="extraRange ? 'g4' : 'g3'">
        <Stat :label="t('range.today')" :value="bytes(d.totals.today.total)" :up="d.totals.today.up" :down="d.totals.today.down" />
        <Stat :label="t('range.week')" :value="bytes(d.totals.week.total)" :up="d.totals.week.up" :down="d.totals.week.down" />
        <Stat :label="t('range.month')" :value="bytes(d.totals.month.total)" :up="d.totals.month.up" :down="d.totals.month.down" />
        <Stat v-if="extraRange" :label="t('range.' + ui.range)" :value="bytes(d.range_total.total)" :up="d.range_total.up" :down="d.range_total.down" />
      </div>

      <div class="grid g-2-3 mt">
        <div class="panel">
          <div class="panel-h"><h2>{{ t('overview.mix') }}</h2><span class="sp" />
            <button v-if="openGroup" class="more" @click="openGroup = ''">{{ t('apps.showAll') }}</button></div>
          <div class="panel-b"><Composition :groups="d.groups" clickable drill :active="openGroup" height="300px"
                                            @pick="p => (openGroup = p.group)" /></div>
        </div>
        <TrafficPanel :total="d.range_total" :live="{ up: d.rate_up, down: d.rate_down }" :points="d.trend" :groups="d.trend_groups"
                      :gran="gran" height="254px" />
      </div>

      <div class="grid g2-wide mt">
        <div class="panel">
          <div class="panel-h">{{ t('nav.apps') }}<button v-if="openGroup" class="btn sm" @click="openGroup = ''">{{ t('apps.showAll') }}</button></div>
          <div class="tbl-wrap">
            <table class="tbl">
              <thead><tr><th>{{ t('apps.app') }}</th><th class="m-hide">{{ t('common.category') }}</th><th class="r">{{ t('common.down') }}</th><th class="r m-hide">{{ t('common.up') }}</th><th class="r">{{ t('common.share') }}</th></tr></thead>
              <tbody>
                <tr v-for="a in appsShown" :key="a.id" class="link" @click="$router.push(`/apps/${enc(a.id)}`)">
                  <td>{{ appName(a) }}</td>
                  <td class="m-hide"><span class="tag"><span class="chip" :style="{ background: catColor(a.category) }" />{{ catName(a) }}</span></td>
                  <td class="r num">{{ bytes(a.down) }}</td>
                  <td class="r num m-hide">{{ bytes(a.up) }}</td>
                  <td class="r num muted">{{ pct(a.total / (d.range_total.total || 1)) }}</td>
                </tr>
              </tbody>
            </table>
            <div v-if="!appsShown.length" class="empty">{{ t('common.empty') }}</div>
          </div>
        </div>
        <div class="panel">
          <div class="panel-h">{{ t('hosts.domains') }}</div>
          <div class="tbl-wrap dom">
            <table class="tbl">
              <thead><tr><th>{{ t('hosts.domain') }}</th><th class="m-hide">{{ t('apps.app') }}</th><th class="r">{{ t('common.total') }}</th></tr></thead>
              <tbody>
                <tr v-for="x in d.domains" :key="x.domain">
                  <td class="dn" :title="x.domain">{{ x.domain }}</td>
                  <td class="m-hide"><span class="tag"><span class="chip" :style="{ background: catColor(x.app.category) }" />{{ appName(x.app) }}</span></td>
                  <td class="r num">{{ bytes(x.bytes) }}</td>
                </tr>
              </tbody>
            </table>
            <div v-if="!d.domains.length" class="empty">{{ t('common.empty') }}</div>
          </div>
        </div>
      </div>
    </template>
    <div v-else-if="loading" class="empty">{{ t('common.loading') }}</div>
    <ControlModal :open="ctl" target="host" :target-id="hostKey" :name="d ? d.name : ''" @close="ctl = false" />
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import AccessLog from '../components/AccessLog.vue'
import ControlModal from '../components/ControlModal.vue'
import Icon from '../components/Icon.vue'
import { L, loadScene, scene } from '../scenario.js'
import Timeline from '../components/Timeline.vue'
import http, { enc, isAdmin } from '../api.js'
import Composition from '../components/Composition.vue'
import RangeTabs from '../components/RangeTabs.vue'
import Stat from '../components/Stat.vue'
import TrafficPanel from '../components/TrafficPanel.vue'
import { ago, appName, bytes, catColor, catName, datetime, pct, rate } from '../format.js'
import { usePoll } from '../poll.js'
import { ui } from '../state.js'

// 参数不能叫 key（Vue 保留属性，不会作为 prop 传入）
const props = defineProps({ hostKey: String })
const { t } = useI18n()
const d = ref(null)
const alias = ref('')
const by = ref('mac')
const saved = ref(false)
const aliasErr = ref('')
const openGroup = ref('')
const ctl = ref(false)
const DTYPES = ['phone', 'tablet', 'computer', 'tv', 'console', 'camera', 'iot', 'nas', 'network', 'unknown']
loadScene()
// 下拉框改完立即保存；失败时把下拉框退回原值（:value 绑定的数据没变，DOM 不会自己回去）
const infoErr = ref('')
async function setDtype(el) {
  infoErr.value = ''
  try {
    const r = await http.put(`/hosts/${enc(props.hostKey)}/dtype`, { dtype: el.value || null })
    Object.assign(d.value, { dtype: r.dtype, dtype_manual: r.dtype_manual })
  } catch (e) { el.value = d.value.dtype_manual || ''; infoErr.value = e.message }
}
async function setPerson(el) {
  infoErr.value = ''
  try {
    const r = await http.put('/devices/bind', { host: props.hostKey, person_id: el.value ? +el.value : null })
    d.value.person = r.person
  } catch (e) { el.value = d.value.person ? d.value.person.id : ''; infoErr.value = e.message }
}
const HTABS = ['overview', 'log', 'timeline']
const route = useRoute()
const router = useRouter()
const tab = computed(() => (HTABS.includes(route.query.tab) ? route.query.tab : 'overview'))
const setTab = k => router.replace({ query: k === 'overview' ? {} : { tab: k } })

const defBy = computed(() => (d.value && d.value.mac ? 'mac' : 'ip'))
const { loading, error } = usePoll(async () => {
  const first = !d.value
  d.value = await http.get(`/hosts/${enc(props.hostKey)}/detail`, { params: { range: ui.range } })
  if (first) {
    alias.value = d.value.alias || ''
    by.value = d.value.alias_by || defBy.value
  }
}, 30000, () => [ui.range, props.hostKey])

// 今日/本周/本月 已有固定卡片，只有选其他范围时才多显示一张
const extraRange = computed(() => !['today', 'week', 'month'].includes(ui.range))
const gran = computed(() => (['today', 'yesterday'].includes(ui.range) ? 'hour' : 'day'))
const appsShown = computed(() => d.value.apps.filter(a => !openGroup.value || a.group === openGroup.value))

async function saveAlias() {
  aliasErr.value = ''
  try {
    const r = await http.patch(`/hosts/${enc(props.hostKey)}`, { alias: alias.value, by: by.value })
    Object.assign(d.value, { alias: r.alias, alias_by: r.alias_by, name: r.name })
    saved.value = true
    setTimeout(() => (saved.value = false), 1500)
  } catch (e) { aliasErr.value = e.message }
}
</script>

<style scoped>
.mt { margin-top: 14px; }
.host-tabs { margin-bottom: 14px; }
.host-tabs button { font-size: 15px; padding: 8px 14px 11px; }
.head-pad { padding-bottom: 0; }
h1 { display: flex; align-items: center; gap: 10px; }
.info { padding: 14px 16px; display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 10px 20px; font-size: 13px; }
.info > div { display: flex; gap: 10px; align-items: center; min-width: 0; }
.k { color: var(--muted); flex: none; min-width: 64px; }
.alias { grid-column: 1 / -1; flex-wrap: wrap; }
.alias .input { max-width: 280px; flex: 1 1 180px; }
.by { border-bottom: 0; }
.by button { padding: 4px 8px 6px; font-size: 13px; }
.by button:disabled { opacity: .4; cursor: not-allowed; }
.hint { flex-basis: 100%; padding-left: 74px; }
.dom { max-height: 520px; overflow-y: auto; }
.g-2-3 { grid-template-columns: minmax(0, 2fr) minmax(0, 3fr); }
@media (max-width: 1100px) { .g-2-3 { grid-template-columns: 1fr; } }
@media (max-width: 640px) { .hint { padding-left: 0; } }
.dn { max-width: 320px; overflow: hidden; text-overflow: ellipsis; }
</style>
