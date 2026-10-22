<template>
  <div>
    <div class="page-h">
      <router-link to="/hosts" class="btn sm">← {{ t('common.back') }}</router-link>
      <h1 v-if="d"><span class="dot" :class="{ on: d.online }" /> {{ d.name }}</h1>
      <span class="sp" />
      <RangeTabs />
    </div>
    <div v-if="error" class="err">{{ error }}</div>

    <template v-if="d">
      <div class="panel info">
        <div><span class="k">{{ t('hosts.ip') }}</span><span class="addr">{{ d.ip || '-' }}</span></div>
        <div><span class="k">{{ t('hosts.mac') }}</span><span class="addr">{{ d.mac || '-' }}</span></div>
        <div><span class="k">{{ t('hosts.hostname') }}</span>{{ d.hostname || '-' }}</div>
        <div><span class="k">{{ t('hosts.firstSeen') }}</span>{{ datetime(d.first_seen) }}</div>
        <div><span class="k">{{ t('hosts.lastSeen') }}</span>{{ ago(d.last_seen) }}</div>
        <div><span class="k">{{ t('common.rate') }}</span><span class="num"><span class="down">↓{{ rate(d.rate_down) }}</span> <span class="up">↑{{ rate(d.rate_up) }}</span></span></div>
        <div class="alias">
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
          <div class="panel-h"><h2>{{ t('overview.mix') }}</h2></div>
          <div class="panel-b"><Composition :groups="d.groups" compact clickable :active="openGroup" :center-label="t('range.' + ui.range)"
                                            @pick="p => (openGroup = openGroup === p.group && !p.cat ? '' : p.group)" /></div>
        </div>
        <TrendPanel :title="t('overview.trend')" :sub="t('range.' + ui.range)" :points="d.trend" :groups="d.trend_groups" :gran="gran" height="260px" />
      </div>

      <div class="grid g2 mt">
        <div class="panel">
          <div class="panel-h">{{ t('nav.apps') }}<button v-if="openGroup" class="btn sm" @click="openGroup = ''">{{ t('apps.showAll') }}</button></div>
          <div class="tbl-wrap">
            <table class="tbl">
              <thead><tr><th>{{ t('apps.app') }}</th><th>{{ t('common.category') }}</th><th class="r">{{ t('common.down') }}</th><th class="r">{{ t('common.up') }}</th><th class="r">{{ t('common.share') }}</th></tr></thead>
              <tbody>
                <tr v-for="a in appsShown" :key="a.id" class="link" @click="$router.push(`/apps/${enc(a.id)}`)">
                  <td>{{ appName(a) }}</td>
                  <td><span class="tag"><span class="chip" :style="{ background: catColor(a.category) }" />{{ catName(a) }}</span></td>
                  <td class="r num">{{ bytes(a.down) }}</td>
                  <td class="r num">{{ bytes(a.up) }}</td>
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
              <thead><tr><th>{{ t('hosts.domain') }}</th><th>{{ t('apps.app') }}</th><th class="r">{{ t('common.total') }}</th></tr></thead>
              <tbody>
                <tr v-for="x in d.domains" :key="x.domain">
                  <td class="dn" :title="x.domain">{{ x.domain }}</td>
                  <td><span class="tag"><span class="chip" :style="{ background: catColor(x.app.category) }" />{{ appName(x.app) }}</span></td>
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
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import http, { enc } from '../api.js'
import Composition from '../components/Composition.vue'
import RangeTabs from '../components/RangeTabs.vue'
import Stat from '../components/Stat.vue'
import TrendPanel from '../components/TrendPanel.vue'
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
