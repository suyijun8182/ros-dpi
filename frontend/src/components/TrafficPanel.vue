<template>
  <!-- 维盟式流量卡片：标签（实时流量 / 历史流量 / 历史用户）+ 右上角下拉框 + 累计 / 实时两行数字 + 折线图 -->
  <div class="panel tp">
    <div class="tp-h">
      <div class="seg" role="tablist">
        <button v-for="k in tabs" :key="k" role="tab" :aria-selected="tab === k" :class="{ on: tab === k }" @click="tab = k">{{ t('traffic.tab.' + k) }}</button>
      </div>
      <span class="sp" />
      <select v-if="tab === 'live'" id="tp-unit" class="sel" v-model="ui.rateUnit" :aria-label="t('traffic.unit')">
        <option value="bit">bit/s</option><option value="byte">Byte/s</option>
      </select>
      <select v-if="tab === 'history' && groups && groups.series.length" id="tp-view" class="sel" v-model="ui.trendMode" :aria-label="t('traffic.view')">
        <option value="pair">{{ t('traffic.all') }}</option><option value="groups">{{ t('chart.mode.groups') }}</option>
      </select>
    </div>
    <div class="tp-b">
      <dl class="stats" v-if="tab !== 'online'">
        <div><dt>{{ t('traffic.upTotal') }}:</dt><dd class="num up">{{ bytes(total.up) }}</dd></div>
        <div><dt>{{ t('traffic.downTotal') }}:</dt><dd class="num down">{{ bytes(total.down) }}</dd></div>
        <div v-if="live"><dt>{{ t('traffic.upRate') }}:</dt><dd class="num up">{{ speed(live.up) }}</dd></div>
        <div v-if="live"><dt>{{ t('traffic.downRate') }}:</dt><dd class="num down">{{ speed(live.down) }}</dd></div>
      </dl>
      <dl class="stats" v-else>
        <div><dt>{{ t('traffic.onlineNow') }}:</dt><dd class="num">{{ onlineNow }}</dd></div>
        <div><dt>{{ t('traffic.onlinePeak') }}:</dt><dd class="num">{{ onlinePeak }}</dd></div>
      </dl>
      <div class="note faint" v-if="tab === 'live' && rt">{{ rt.source === 'wan' ? t('traffic.fromWan', { name: rt.interface }) : t('traffic.fromFlow') }}</div>
      <Chart :option="opt" :height="height" />
    </div>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import http from '../api.js'
import { groupsOption, onlineOption, trendOption } from '../charts.js'
import { bytes, rate } from '../format.js'
import { ui } from '../state.js'
import Chart from './Chart.vue'

const props = defineProps({
  total: { type: Object, default: () => ({ up: 0, down: 0 }) },  // 本期累计 {up, down}
  live: Object,                 // 此刻速率 {up, down}，B/s
  points: { type: Array, default: () => [] },   // 历史流量 [{ts, up, down}]
  groups: Object,               // 按应用大类的历史流量 trend_groups
  online: Array,                // 历史在线终端 [{ts, n}]
  gran: { type: String, default: 'hour' },
  realtime: Boolean,            // 显示“实时流量”标签（每 5 秒读 /api/realtime）
  height: { type: String, default: '300px' },
})
const { t, locale } = useI18n()
const tabs = computed(() => [props.realtime && 'live', 'history', props.online && 'online'].filter(Boolean))
const tab = ref(props.realtime ? 'live' : 'history')

const speed = v => (ui.rateUnit === 'byte' ? `${bytes(v)}/s` : rate(v))
const onlineNow = computed(() => (props.online && props.online.length ? props.online[props.online.length - 1].n : 0))
const onlinePeak = computed(() => Math.max(0, ...(props.online || []).map(p => p.n)))

// 实时流量：有 RouterOS API 时是 WAN 口秒级采样，否则是每分钟的流量记录
const rt = ref(null)
let timer = null
async function loadRt() {
  if (tab.value !== 'live' || document.hidden) return
  try { rt.value = await http.get('/realtime') } catch (e) { /* 保留上一次的曲线 */ }
}
onMounted(() => { if (props.realtime) { loadRt(); timer = setInterval(loadRt, 5000) } })
onBeforeUnmount(() => clearInterval(timer))
watch(tab, loadRt)

const opt = computed(() => {
  ui.theme; locale.value
  if (tab.value === 'live') {
    const pts = rt.value ? rt.value.points : []
    return trendOption(pts, rt.value && rt.value.source === 'wan' ? 'second' : 'minute', { asRate: true, unit: ui.rateUnit })
  }
  if (tab.value === 'online') return onlineOption(props.online || [], props.gran)
  if (ui.trendMode === 'groups' && props.groups && props.groups.series.length) return groupsOption(props.groups)
  return trendOption(props.points, props.gran)
})
</script>

<style scoped>
.tp { display: flex; flex-direction: column; min-width: 0; }
.tp-h { display: flex; align-items: center; gap: 10px; padding: 10px 18px 0; border-bottom: 1px solid var(--line); margin: 0 0 0; flex-wrap: wrap; }
.tp-h .seg button { font-size: 15px; padding: 8px 12px 11px; }
.sp { flex: 1; }
.sel {
  height: 32px; padding: 0 30px 0 14px; border-radius: 16px; border: 1px solid var(--brand-ink); color: var(--brand-ink);
  background: var(--panel) url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%238a96a3' stroke-width='2.4'%3E%3Cpath d='m6 9 6 6 6-6'/%3E%3C/svg%3E") no-repeat right 11px center;
  appearance: none; font-size: 13px; cursor: pointer; margin-bottom: 8px;
}
.tp-b { padding: 12px 18px 14px; display: flex; flex-direction: column; gap: 6px; flex: 1; }
.stats { margin: 0; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 4px 16px; font-size: 14px; }
.stats div { display: flex; gap: 6px; align-items: baseline; min-width: 0; }
.stats dt { color: var(--muted); white-space: nowrap; }
.stats dd { margin: 0; color: var(--brand-ink); font-size: 16px; white-space: nowrap; }
.note { font-size: 12px; }
@media (max-width: 640px) { .stats { grid-template-columns: 1fr; } }
</style>
