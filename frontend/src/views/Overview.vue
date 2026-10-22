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

      <!-- 第一行：路由器 / 健康指数 / 在线终端 / DHCP 分配 -->
      <div class="grid g4 row1">
        <div class="panel card">
          <div class="panel-h"><h2>{{ t('overview.router') }}</h2><span class="sp" /><router-link to="/settings" class="more">{{ t('common.details') }} ›</router-link></div>
          <div class="panel-b">
            <template v-if="d.router.enabled">
              <div class="rt"><span class="dot" :class="d.router.ok ? 'on' : 'bad'" /><b>{{ d.router.identity || 'RouterOS' }}</b></div>
              <dl class="kv">
                <div><dt>{{ t('overview.model') }}</dt><dd>{{ d.router.board || '-' }}</dd></div>
                <div><dt>{{ t('overview.rosVersion') }}</dt><dd class="num">{{ d.router.version || '-' }}</dd></div>
                <div><dt>{{ t('overview.uptime') }}</dt><dd class="num">{{ d.router.uptime || '-' }}</dd></div>
              </dl>
              <div class="bars" v-if="d.router.ok">
                <div><span>{{ t('overview.cpu') }}</span><span class="meter" :class="lvl(d.router.cpu_load / 100)"><i :style="{ width: (d.router.cpu_load || 0) + '%' }" /></span><b class="num">{{ d.router.cpu_load ?? '-' }}%</b></div>
                <div v-if="d.router.mem_total"><span>{{ t('overview.memory') }}</span><span class="meter" :class="lvl(memUsed)"><i :style="{ width: memUsed * 100 + '%' }" /></span><b class="num">{{ pct(memUsed, 0) }}</b></div>
              </div>
              <div v-else class="err small">{{ d.router.error }}</div>
            </template>
            <div v-else class="hint">{{ t('overview.rosOff') }} <router-link to="/settings#guide" class="link">{{ t('overview.openGuide') }}</router-link></div>
          </div>
        </div>

        <div class="panel card">
          <div class="panel-h"><h2>{{ t('overview.health') }}</h2><span class="sp" /><button class="more" @click="showHealth = true">{{ t('common.details') }} ›</button></div>
          <div class="gauge">
            <Chart :option="gaugeOpt" height="172px" />
            <div class="lv" :class="d.health.level">{{ t('health.level.' + d.health.level) }}<span v-if="issues.length"> · {{ t('health.issues', { n: issues.length }) }}</span></div>
          </div>
        </div>

        <div class="panel card">
          <div class="panel-h"><h2>{{ t('overview.online') }}</h2><span class="sp" /><router-link to="/hosts" class="more">{{ t('common.details') }} ›</router-link></div>
          <div class="panel-b">
            <div class="big"><b class="num accent">{{ d.online }}</b><span class="num faint"> / {{ d.hosts_total }}</span></div>
            <div class="muted small">{{ t('overview.newToday', { n: d.new_today }) }}</div>
            <Chart class="spark" :option="sparkOpt" height="58px" />
          </div>
        </div>

        <div class="panel card">
          <div class="panel-h"><h2>{{ t('overview.dhcp') }}</h2><span class="sp" /><router-link to="/hosts?tab=dhcp" class="more">{{ t('overview.leases') }} ›</router-link></div>
          <div class="panel-b">
            <template v-if="pool">
              <div class="pool">
                <div><span class="muted small">{{ t('overview.poolFree') }}</span><b class="num accent">{{ pool.size - pool.used }}</b></div>
                <div><span class="muted small">{{ t('overview.poolSize') }}</span><b class="num">{{ pool.size }}</b></div>
              </div>
              <div class="meter" :class="lvl(pool.used / (pool.size || 1))"><i :style="{ width: pool.used / (pool.size || 1) * 100 + '%' }" /></div>
              <div class="faint small pool-sub">{{ pool.server }} · {{ pool.used }} / {{ pool.size }}（{{ pct(pool.used / (pool.size || 1), 0) }}）<span v-if="d.pools.length > 1"> · {{ t('overview.morePools', { n: d.pools.length - 1 }) }}</span></div>
            </template>
            <div v-else class="hint">{{ d.router.enabled ? t('overview.noPool') : t('overview.rosOff') }}</div>
          </div>
        </div>
      </div>

      <!-- 第二行：全网状态 -->
      <div class="panel mt">
        <div class="panel-h"><h2>{{ t('overview.status') }}</h2><span class="faint small">{{ t('overview.statusHint') }}</span></div>
        <div class="panel-b tiles" :style="{ '--cols': Math.min(wanTiles.length + 3, 4) }">
          <div v-for="w in wanTiles" :key="w.name" class="tile">
            <div class="t-h"><Icon name="wan" /><b>{{ w.comment || w.name }}</b>
              <span class="pill" :class="w.running ? 'ok' : 'bad'">{{ w.running ? t('overview.wanUp') : t('overview.wanDown') }}</span></div>
            <div class="t-v num">{{ w.ip || '-' }}</div>
            <div class="t-s"><span class="pill grey">{{ t('overview.wanType.' + w.type) }}</span>
              <span class="num up">↑{{ rate(w.rate_up) }}</span><span class="num down">↓{{ rate(w.rate_down) }}</span></div>
          </div>
          <div class="tile">
            <div class="t-h"><Icon name="gauge" /><b>{{ t('overview.live') }}</b><span class="faint small">{{ wanFrom }}</span></div>
            <div class="t-rate"><span class="num up">↑ {{ rate(liveUp) }}</span><span class="num down">↓ {{ rate(liveDown) }}</span></div>
          </div>
          <div class="tile">
            <div class="t-h"><Icon name="overview" /><b>{{ ui.range === 'today' ? t('overview.heroToday') : t('overview.heroRange', { range: t('range.' + ui.range) }) }}</b></div>
            <div class="t-v num accent">{{ bytes(d.range_total.total) }}</div>
            <div class="t-s"><span class="num down">↓{{ bytes(d.range_total.down) }}</span><span class="num up">↑{{ bytes(d.range_total.up) }}</span>
              <span class="faint" v-if="ui.range !== 'month'">{{ t('overview.monthShort') }} {{ bytes(d.totals.month.total) }}</span></div>
          </div>
          <div class="tile">
            <div class="t-h"><Icon name="apps" /><b>{{ t('overview.identified') }}</b></div>
            <div class="t-v num accent">{{ pct(d.identified_ratio, 0) }}</div>
            <div class="t-s"><span class="faint">{{ t('overview.appsN', { n: d.apps_count, lib: (d.apps_library || 0).toLocaleString() }) }}</span></div>
          </div>
        </div>
      </div>

      <!-- 第三行：DPI 应用构成（实心饼图）+ 流量卡片（实时流量 / 历史流量 / 历史用户），版式同维盟首页 -->
      <div class="grid g-2-3 mt">
        <div class="panel">
          <div class="panel-h"><h2>{{ t('overview.mix') }}</h2><span class="sp" /><router-link to="/apps" class="more">{{ t('common.details') }} ›</router-link></div>
          <div class="panel-b"><Composition :groups="d.groups" clickable height="356px"
            @pick="p => $router.push({ path: '/apps', query: p.cat ? { cat: p.cat } : { group: p.group } })" /></div>
        </div>
        <TrafficPanel realtime :total="d.range_total" :live="{ up: liveUp, down: liveDown }" :points="d.trend"
                      :groups="d.trend_groups" :online="d.online_trend" :gran="gran" height="292px" />
      </div>

      <div class="grid g2 mt">
        <div class="panel">
          <div class="panel-h"><h2>{{ t('overview.topApps') }}</h2><span class="sp" /><router-link to="/apps" class="more">{{ t('common.allApps') }} ›</router-link></div>
          <div class="panel-b"><BarList :items="appItems" :total="d.range_total.total" /></div>
        </div>
        <div class="panel">
          <div class="panel-h"><h2>{{ t('overview.topHosts') }}</h2><span class="sp" /><router-link to="/hosts" class="more">{{ t('common.allHosts') }} ›</router-link></div>
          <div class="panel-b"><BarList :items="hostItems" :total="d.range_total.total" /></div>
        </div>
      </div>

      <Modal :open="showHealth" :title="t('overview.health')" @close="showHealth = false">
        <div class="hh"><b class="num">{{ d.health.score }}</b><span>{{ t('health.level.' + d.health.level) }}</span><span class="faint small">{{ t('health.hint') }}</span></div>
        <ul class="hl">
          <li v-for="it in d.health.items" :key="it.code" :class="{ bad: !it.ok }">
            <span class="dot" :class="it.ok ? 'on' : it.deduct >= 10 ? 'bad' : 'warn'" />
            <div class="hl-b">
              <div class="hl-t"><b>{{ t('health.' + it.code + '.title') }}</b><span v-if="!it.ok" class="num ded">-{{ it.deduct }}</span></div>
              <div class="muted small">{{ healthText(it) }}</div>
              <div v-if="!it.ok" class="fix small">{{ t('health.' + it.code + '.fix', it.params) }}</div>
            </div>
          </li>
        </ul>
      </Modal>
    </template>
    <div v-else-if="loading" class="empty">{{ t('common.loading') }}</div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import http, { enc } from '../api.js'
import { gaugeOption, onlineOption } from '../charts.js'
import BarList from '../components/BarList.vue'
import Chart from '../components/Chart.vue'
import Composition from '../components/Composition.vue'
import Icon from '../components/Icon.vue'
import Modal from '../components/Modal.vue'
import RangeTabs from '../components/RangeTabs.vue'
import TrafficPanel from '../components/TrafficPanel.vue'
import { appName, bytes, catColor, catName, groupName, pct, rate } from '../format.js'
import { usePoll } from '../poll.js'
import { ui } from '../state.js'

const { t, locale } = useI18n()
const d = ref(null)
const showHealth = ref(false)
const { loading, error } = usePoll(async () => { d.value = await http.get('/overview', { params: { range: ui.range } }) },
  30000, () => ui.range)

const useWan = computed(() => d.value.router.enabled && d.value.router.ok)
const liveUp = computed(() => (useWan.value ? d.value.rate.wan_up : d.value.rate.flow_up))
const liveDown = computed(() => (useWan.value ? d.value.rate.wan_down : d.value.rate.flow_down))
const wanFrom = computed(() => (useWan.value && d.value.router.wan_interface
  ? t('overview.viaWan', { name: d.value.router.wan_interface }) : t('overview.viaFlow')))
const memUsed = computed(() => (d.value.router.mem_total ? 1 - d.value.router.mem_free / d.value.router.mem_total : 0))
const lvl = x => (x >= 0.9 ? 'bad' : x >= 0.75 ? 'warn' : '')
// 地址池：显示最满的一个
const pool = computed(() => [...(d.value.pools || [])].filter(p => p.size).sort((a, b) => b.used / b.size - a.used / a.size)[0])
// 没配 ROS API 时，全网状态里不显示 WAN 线路卡
const wanTiles = computed(() => (d.value.router.enabled ? d.value.wans || [] : []))
const issues = computed(() => d.value.health.items.filter(i => !i.ok))

const gran = computed(() => (['today', 'yesterday'].includes(ui.range) ? 'hour' : 'day'))
const deps = () => [ui.theme, locale.value]
const gaugeOpt = computed(() => (deps(), gaugeOption(d.value.health.score)))
const sparkOpt = computed(() => (deps(), onlineOption(d.value.online_realtime, 'minute', true)))

function healthText(it) {
  const p = { ...it.params }
  if (p.ratio != null) p.ratio = pct(p.ratio, 0)
  if (p.used != null && p.size == null) p.used = pct(p.used, 0)
  if (p.down) p.down = p.down.join('、')
  if (Array.isArray(p.wrong)) p.wrong = p.wrong.join('、')
  if (it.code === 'proxy' && p.share != null) p.share = pct(p.share, 0)
  return t(`health.${it.code}.${it.ok ? 'ok' : 'bad'}`, p)
}

const appItems = computed(() => d.value.top_apps.map(a => ({
  key: a.id, label: appName(a), sub: `${groupName(a)} · ${catName(a)}`, value: a.total, up: a.up, down: a.down,
  color: catColor(a.category), to: `/apps/${enc(a.id)}`,
})))
const hostItems = computed(() => d.value.top_hosts.map(h => ({
  key: h.key, label: h.name, sub: h.name !== h.ip ? h.ip : '', value: h.total, up: h.up, down: h.down,
  online: h.online, to: `/hosts/${enc(h.key)}`,
})))
</script>

<style scoped>
.nodata { padding: 14px 18px; margin-bottom: 14px; display: flex; gap: 14px; align-items: center; flex-wrap: wrap; border-left: 3px solid var(--warn); }
.card { display: flex; flex-direction: column; min-height: 214px; }
@media (max-width: 640px) { .card { min-height: 0; } }
.card .panel-b { flex: 1; display: flex; flex-direction: column; gap: 8px; }
.rt { display: flex; align-items: center; gap: 8px; font-size: 16px; }
.kv { margin: 0; display: grid; gap: 3px; font-size: 13px; }
.kv div { display: flex; justify-content: space-between; gap: 10px; }
.kv dt { color: var(--muted); }
.kv dd { margin: 0; text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bars { display: grid; gap: 6px; margin-top: auto; font-size: 12.5px; }
.bars div { display: grid; grid-template-columns: 36px 1fr 40px; align-items: center; gap: 8px; color: var(--muted); }
.bars b { color: var(--ink); text-align: right; font-weight: 600; }
.hint { color: var(--muted); font-size: 13px; line-height: 1.6; }
.gauge { position: relative; padding: 0 12px 12px; }
.lv { text-align: center; font-weight: 600; margin-top: -18px; }
.lv.excellent { color: var(--accent); }
.lv.good { color: var(--pair-blue); }
.lv.fair { color: var(--warn); }
.lv.poor { color: var(--bad); }
.lv span { color: var(--muted); font-weight: 400; font-size: 13px; }
.big b { font-size: 46px; font-weight: 600; line-height: 1; }
.big span { font-size: 22px; }
.spark { margin-top: auto; }
.pool { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.pool div { display: grid; }
.pool b { font-size: 38px; font-weight: 600; line-height: 1.1; }
.pool-sub { margin-top: 2px; }

/* 小卡按实际个数排列，不出现落单的一张：桌面最多 4 列，平板 2 列，手机 1 列 */
.tiles { display: grid; grid-template-columns: repeat(var(--cols, 4), minmax(0, 1fr)); gap: 12px; }
@media (max-width: 1180px) { .tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 560px) { .tiles { grid-template-columns: 1fr; } }
.tile { background: var(--sunk); border-radius: 12px; padding: 14px 16px; display: grid; gap: 6px; align-content: start; min-width: 0; }
.t-h { display: flex; align-items: center; gap: 8px; font-size: 14px; min-width: 0; }
.t-h :deep(svg) { color: var(--brand-ink); flex: none; }
.t-h b { font-weight: 600; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.t-h .pill { margin-left: auto; }
.t-h .small { margin-left: auto; white-space: nowrap; }
.t-v { font-size: 26px; font-weight: 600; line-height: 1.15; overflow: hidden; text-overflow: ellipsis; }
.t-s { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; font-size: 13px; }
.t-rate { display: grid; gap: 2px; font-size: 22px; font-weight: 600; }

.g-2-3 { grid-template-columns: minmax(0, 2fr) minmax(0, 3fr); }
@media (max-width: 1180px) { .g-2-3 { grid-template-columns: 1fr; } }

.hh { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; padding-bottom: 10px; border-bottom: 1px solid var(--line); }
.hh b { font-size: 40px; font-weight: 600; color: var(--accent); }
.hh > span:first-of-type { font-weight: 600; }
.hl { list-style: none; margin: 0; padding: 0; }
.hl li { display: flex; gap: 12px; padding: 12px 0; border-bottom: 1px solid var(--line); }
.hl li:last-child { border-bottom: 0; }
.hl .dot { margin-top: 7px; }
.hl-b { flex: 1; min-width: 0; display: grid; gap: 2px; }
.hl-t { display: flex; gap: 10px; align-items: baseline; }
.ded { color: var(--bad); font-weight: 600; }
.fix { color: var(--brand-ink); }
</style>
