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
          <button class="btn sm" @click="saveAlias" :disabled="alias === (d.alias || '')">{{ saved ? t('common.saved') : t('common.save') }}</button>
        </div>
      </div>

      <div class="grid mt" :class="extraRange ? 'g4' : 'g3'">
        <Stat :label="t('range.today')" :value="bytes(d.totals.today.total)" :up="d.totals.today.up" :down="d.totals.today.down" />
        <Stat :label="t('range.week')" :value="bytes(d.totals.week.total)" :up="d.totals.week.up" :down="d.totals.week.down" />
        <Stat :label="t('range.month')" :value="bytes(d.totals.month.total)" :up="d.totals.month.up" :down="d.totals.month.down" />
        <Stat v-if="extraRange" :label="t('range.' + ui.range)" :value="bytes(d.range_total.total)" :up="d.range_total.up" :down="d.range_total.down" />
      </div>

      <section class="mix mt">
        <h2>{{ t('overview.mix') }}</h2>
        <Spectrum :cats="d.categories" />
      </section>

      <div class="panel mt">
        <div class="panel-h">{{ t('overview.trend') }}</div>
        <div class="panel-b"><Chart :option="trendOpt" height="240px" /></div>
      </div>

      <div class="grid g2 mt">
        <div class="panel">
          <div class="panel-h">{{ t('nav.apps') }}</div>
          <div class="tbl-wrap">
            <table class="tbl">
              <thead><tr><th>{{ t('apps.app') }}</th><th>{{ t('common.category') }}</th><th class="r">{{ t('common.down') }}</th><th class="r">{{ t('common.up') }}</th><th class="r">{{ t('common.share') }}</th></tr></thead>
              <tbody>
                <tr v-for="a in d.apps" :key="a.id" class="link" @click="$router.push(`/apps/${enc(a.id)}`)">
                  <td>{{ appName(a) }}</td>
                  <td><span class="tag"><span class="chip" :style="{ background: catColor(a.category) }" />{{ catName(a) }}</span></td>
                  <td class="r num">{{ bytes(a.down) }}</td>
                  <td class="r num">{{ bytes(a.up) }}</td>
                  <td class="r num muted">{{ pct(a.total / (d.range_total.total || 1)) }}</td>
                </tr>
              </tbody>
            </table>
            <div v-if="!d.apps.length" class="empty">{{ t('common.empty') }}</div>
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
import { trendOption } from '../charts.js'
import Chart from '../components/Chart.vue'
import RangeTabs from '../components/RangeTabs.vue'
import Spectrum from '../components/Spectrum.vue'
import Stat from '../components/Stat.vue'
import { ago, appName, bytes, catColor, catName, datetime, pct, rate } from '../format.js'
import { usePoll } from '../poll.js'
import { ui } from '../state.js'

// 参数不能叫 key（Vue 保留属性，不会作为 prop 传入）
const props = defineProps({ hostKey: String })
const { t, locale } = useI18n()
const d = ref(null)
const alias = ref('')
const saved = ref(false)

const { loading, error } = usePoll(async () => {
  const first = !d.value
  d.value = await http.get(`/hosts/${enc(props.hostKey)}/detail`, { params: { range: ui.range } })
  if (first) alias.value = d.value.alias || ''
}, 30000, () => [ui.range, props.hostKey])

// 今日/本周/本月 已有固定卡片，只有选其他范围时才多显示一张
const extraRange = computed(() => !['today', 'week', 'month'].includes(ui.range))
const deps = () => [ui.theme, locale.value]
const trendOpt = computed(() => (deps(), trendOption(d.value.trend, ['today', 'yesterday'].includes(ui.range) ? 'hour' : 'day')))

async function saveAlias() {
  await http.patch(`/hosts/${enc(props.hostKey)}`, { alias: alias.value })
  d.value.alias = alias.value || null
  d.value.name = alias.value || d.value.hostname || d.value.ip
  saved.value = true
  setTimeout(() => (saved.value = false), 1500)
}
</script>

<style scoped>
.mt { margin-top: 14px; }
h1 { display: flex; align-items: center; gap: 10px; }
.info { padding: 14px 16px; display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 10px 20px; font-size: 13px; }
.info > div { display: flex; gap: 10px; align-items: center; min-width: 0; }
.k { color: var(--muted); flex: none; min-width: 64px; }
.alias { grid-column: 1 / -1; max-width: 520px; }
.dom { max-height: 520px; overflow-y: auto; }
.mix h2 { font: 600 17px/1.3 var(--cond); margin: 0 0 10px; }
.dn { max-width: 320px; overflow: hidden; text-overflow: ellipsis; }
</style>
