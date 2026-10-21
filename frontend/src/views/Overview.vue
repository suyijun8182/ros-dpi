<template>
  <div>
    <div class="page-h">
      <h1>{{ t('nav.overview') }}</h1>
      <span class="lead" v-if="d && d.router.identity">{{ d.router.identity }}</span>
      <span class="sp" />
      <RangeTabs />
    </div>

    <div v-if="error" class="err">{{ error }}</div>

    <template v-if="d">
      <div v-if="!d.totals.month.total" class="panel nodata">
        <span>{{ t('overview.noData') }}</span>
        <router-link to="/settings#guide" class="btn sm">{{ t('overview.openGuide') }}</router-link>
      </div>

      <!-- 首屏：本期流量 + 此刻速率 + 流量构成 -->
      <section class="hero">
        <div class="hero-main">
          <div class="hero-lbl">{{ ui.range === 'today' ? t('overview.heroToday') : t('overview.heroRange', { range: t('range.' + ui.range) }) }}</div>
          <div class="hero-num num">{{ big[0] }}<span class="unit">{{ big[1] }}</span></div>
          <div class="hero-sub">
            <span><b class="num down">{{ bytes(d.range_total.down) }}</b> {{ t('common.down') }}</span>
            <span><b class="num up">{{ bytes(d.range_total.up) }}</b> {{ t('common.up') }}</span>
            <span class="pair hero-pair"><i class="d" :style="{ flexGrow: d.range_total.down }" /><i class="u" :style="{ flexGrow: d.range_total.up }" /></span>
          </div>
          <dl class="hero-meta">
            <div v-if="ui.range !== 'today'"><dt>{{ t('range.today') }}</dt><dd class="num">{{ bytes(d.totals.today.total) }}</dd></div>
            <div v-if="ui.range !== 'week'"><dt>{{ t('overview.weekShort') }}</dt><dd class="num">{{ bytes(d.totals.week.total) }}</dd></div>
            <div v-if="ui.range !== 'month'"><dt>{{ t('overview.monthShort') }}</dt><dd class="num">{{ bytes(d.totals.month.total) }}</dd></div>
            <div><dt>{{ t('overview.online') }}</dt><dd class="num">{{ d.online }}<span class="faint"> / {{ d.hosts_total }}</span></dd></div>
            <div><dt>{{ t('overview.identified') }}</dt><dd class="num">{{ pct(d.identified_ratio, 0) }}</dd></div>
          </dl>
        </div>
        <div class="hero-live">
          <div class="hero-lbl"><span class="dot on pulse" />{{ t('overview.live') }}</div>
          <div class="live-row"><span class="arrow down">↓</span><span class="num live-v">{{ rate(liveDown) }}</span></div>
          <div class="live-row"><span class="arrow up">↑</span><span class="num live-v">{{ rate(liveUp) }}</span></div>
          <div class="faint small">{{ wanFrom }}</div>
        </div>
      </section>

      <section class="mix">
        <div class="mix-h"><h2>{{ t('overview.mix') }}</h2></div>
        <Spectrum :cats="d.categories" clickable :height="18" @pick="c => $router.push({ path: '/apps', query: { cat: c } })" />
      </section>

      <div class="grid g-2-1 mt">
        <div class="panel">
          <div class="panel-h"><h2>{{ t('overview.trend') }}</h2><span class="faint small">{{ t('range.' + ui.range) }}</span></div>
          <div class="panel-b"><Chart :option="trendOpt" height="260px" /></div>
        </div>
        <div class="panel">
          <div class="panel-h"><h2>{{ t('overview.realtime') }}</h2></div>
          <div class="panel-b"><Chart :option="rtOpt" height="260px" /></div>
        </div>
      </div>

      <div class="grid g2 mt">
        <div class="panel">
          <div class="panel-h"><h2>{{ t('overview.topApps') }}</h2><span class="sp" /><router-link to="/apps" class="small link">{{ t('common.allApps') }}</router-link></div>
          <div class="panel-b"><BarList :items="appItems" /></div>
        </div>
        <div class="panel">
          <div class="panel-h"><h2>{{ t('overview.topHosts') }}</h2><span class="sp" /><router-link to="/hosts" class="small link">{{ t('common.allHosts') }}</router-link></div>
          <div class="panel-b"><BarList :items="hostItems" /></div>
        </div>
      </div>

      <footer class="router" v-if="d.router.enabled">
        <span class="dot" :class="d.router.ok ? 'on' : 'bad'" />
        <b>{{ d.router.identity || 'RouterOS' }}</b>
        <span class="muted">{{ d.router.board }}</span>
        <span class="muted">RouterOS {{ d.router.version }}</span>
        <span v-if="d.router.cpu_load != null">{{ t('overview.cpu') }} <b class="num">{{ d.router.cpu_load }}%</b></span>
        <span v-if="d.router.mem_total">{{ t('overview.memory') }} <b class="num">{{ pct(1 - d.router.mem_free / d.router.mem_total, 0) }}</b></span>
        <span v-if="d.router.uptime">{{ t('overview.uptime') }} <b class="num">{{ d.router.uptime }}</b></span>
        <span v-if="!d.router.ok" class="err">{{ d.router.error }}</span>
      </footer>
    </template>
    <div v-else-if="loading" class="empty">{{ t('common.loading') }}</div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import http, { enc } from '../api.js'
import { trendOption } from '../charts.js'
import BarList from '../components/BarList.vue'
import Chart from '../components/Chart.vue'
import RangeTabs from '../components/RangeTabs.vue'
import Spectrum from '../components/Spectrum.vue'
import { appName, bytes, catColor, catName, pct, rate } from '../format.js'
import { usePoll } from '../poll.js'
import { ui } from '../state.js'

const { t, locale } = useI18n()
const d = ref(null)
const { loading, error } = usePoll(async () => { d.value = await http.get('/overview', { params: { range: ui.range } }) },
  30000, () => ui.range)

const useWan = computed(() => d.value.router.enabled && d.value.router.ok)
const liveUp = computed(() => (useWan.value ? d.value.rate.wan_up : d.value.rate.flow_up))
const liveDown = computed(() => (useWan.value ? d.value.rate.wan_down : d.value.rate.flow_down))
const wanFrom = computed(() => (useWan.value && d.value.router.wan_interface
  ? t('overview.viaWan', { name: d.value.router.wan_interface }) : t('overview.viaFlow')))
// 大数字拆成 数值 + 单位，单位单独排小号
const big = computed(() => {
  const [v, u] = bytes(d.value.range_total.total).split(' ')
  return [v, u]
})

const gran = computed(() => (['today', 'yesterday'].includes(ui.range) ? 'hour' : 'day'))
const deps = () => [ui.theme, locale.value]
const trendOpt = computed(() => (deps(), trendOption(d.value.trend, gran.value)))
const rtOpt = computed(() => (deps(), trendOption(d.value.realtime, 'minute', true)))

const appItems = computed(() => d.value.top_apps.map(a => ({
  key: a.id, label: appName(a), sub: catName(a), value: a.total, up: a.up, down: a.down,
  color: catColor(a.category), to: `/apps/${enc(a.id)}`,
})))
const hostItems = computed(() => d.value.top_hosts.map(h => ({
  key: h.key, label: h.name, sub: h.name !== h.ip ? h.ip : '', value: h.total, up: h.up, down: h.down,
  online: h.online, to: `/hosts/${enc(h.key)}`,
})))
</script>

<style scoped>
.nodata { padding: 14px 18px; margin-bottom: 20px; display: flex; gap: 14px; align-items: center; flex-wrap: wrap; border-left: 3px solid var(--warn); }

.hero { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 24px 48px; align-items: end; padding: 4px 0 26px; }
.hero-lbl { color: var(--muted); font-size: 14.5px; display: flex; align-items: center; gap: 8px; }
.hero-num { font-size: clamp(64px, 9vw, 112px); font-weight: 600; line-height: .92; letter-spacing: -.035em; margin: 10px 0 14px; }
.unit { font-size: .36em; font-weight: 500; letter-spacing: 0; margin-left: .18em; color: var(--muted); }
.hero-sub { display: flex; align-items: center; gap: 22px; flex-wrap: wrap; font-size: 14.5px; color: var(--muted); }
.hero-sub b { font-size: 20px; font-weight: 600; margin-right: 2px; }
.hero-pair { width: 160px; height: 6px; border-radius: 3px; }
.hero-meta { display: flex; gap: 10px 36px; flex-wrap: wrap; margin: 22px 0 0; }
.hero-meta div { display: flex; flex-direction: column; }
.hero-meta dt { color: var(--muted); font-size: 13px; }
.hero-meta dd { margin: 0; font-size: 22px; font-weight: 600; }

.hero-live { min-width: 240px; padding-left: 28px; border-left: 1px solid var(--line); }
.live-row { display: flex; align-items: baseline; gap: 10px; margin-top: 6px; }
.arrow { font: 600 22px/1 var(--cond); width: 16px; }
.live-v { font-size: 34px; font-weight: 600; letter-spacing: -.01em; }
.hero-live .small { margin-top: 10px; }

/* 唯一的一个动效：在线指示点的呼吸，提示数据是实时的 */
.pulse { animation: pulse 2.4s ease-in-out infinite; }
@keyframes pulse { 50% { opacity: .3; } }

.mix { padding: 18px 0 8px; border-top: 1px solid var(--line); }
.mix-h h2 { font: 600 17px/1.3 var(--cond); margin: 0 0 12px; }

.link { color: var(--pair-blue); }
.link:hover { text-decoration: underline; text-underline-offset: 3px; }

.router { margin-top: 28px; padding-top: 16px; border-top: 1px solid var(--line); display: flex; gap: 8px 22px; align-items: center; flex-wrap: wrap; font-size: 14px; }

@media (max-width: 860px) {
  .hero { grid-template-columns: 1fr; }
  .hero-live { border-left: 0; padding-left: 0; border-top: 1px solid var(--line); padding-top: 16px; }
}
</style>
