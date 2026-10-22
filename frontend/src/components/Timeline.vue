<template>
  <!-- 终端一天的上网时间线：顶部是合并后的在线时段，下面每行一个应用（颜色 = 应用大类），横轴 0 到 24 点 -->
  <div class="tl">
    <div class="tl-h">
      <button class="btn sm" @click="shift(-1)" :aria-label="t('audit.tl.prev')">‹</button>
      <input id="tl-day" class="input day" type="date" v-model="day" :max="today" />
      <button class="btn sm" @click="shift(1)" :disabled="day >= today" :aria-label="t('audit.tl.next')">›</button>
      <span class="sp" />
      <template v-if="d && d.first">
        <span class="kv">{{ t('audit.tl.first') }} <b class="num">{{ hm(d.first) }}</b></span>
        <span class="kv">{{ t('audit.tl.last') }} <b class="num">{{ hm(d.last) }}</b></span>
        <span class="kv">{{ t('audit.tl.active') }} <b class="num">{{ duration(d.active_seconds, locale === 'zh') }}</b></span>
      </template>
    </div>
    <div v-if="!d" class="empty">{{ t('common.loading') }}</div>
    <div v-else-if="!d.apps.length" class="empty">{{ t('audit.tl.empty') }}</div>
    <div v-else class="grid-tl">
      <div class="axis"><span class="lab" /><div class="track ticks"><span v-for="h in [0, 3, 6, 9, 12, 15, 18, 21, 24]" :key="h" :style="{ left: h / 24 * 100 + '%' }">{{ h }}</span></div></div>
      <div class="row online"><span class="lab"><b>{{ t('audit.tl.online') }}</b></span>
        <div class="track"><i v-for="(s, i) in d.online" :key="i" class="seg on" :style="seg(s)" :title="`${hm(s[0])} – ${hm(s[1])}`" /></div></div>
      <div class="row" v-for="a in d.apps.slice(0, max)" :key="a.app.id">
        <span class="lab" :title="a.dests.join('\n')"><span class="chip" :style="{ background: catColor(a.app.category) }" />{{ appName(a.app) }}
          <span class="faint num small">{{ bytes(a.bytes) }}</span></span>
        <div class="track"><i v-for="(s, i) in a.segments" :key="i" class="seg" :style="{ ...seg(s), background: catColor(a.app.category) }"
                              :title="`${appName(a.app)}  ${hm(s[0])} – ${hm(s[1])}  ${bytes(s[2])}`" /></div>
      </div>
      <button v-if="d.apps.length > max" class="btn sm ghost more-apps" @click="max += 20">{{ t('audit.tl.moreApps', { n: d.apps.length - max }) }}</button>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import http from '../api.js'
import { duration } from '../csv.js'
import { appName, bytes, catColor } from '../format.js'

const props = defineProps({ host: String, person: [Number, String] })
const { t, locale } = useI18n()
const pad = n => String(n).padStart(2, '0')
const fmtDay = x => `${x.getFullYear()}-${pad(x.getMonth() + 1)}-${pad(x.getDate())}`
const today = fmtDay(new Date())
const day = ref(today)
const d = ref(null)
const max = ref(12)

const hm = ts => { const x = new Date(ts * 1000); return `${pad(x.getHours())}:${pad(x.getMinutes())}` }
const seg = s => {
  const span = d.value.end - d.value.start
  const l = (s[0] - d.value.start) / span * 100
  return { left: l + '%', width: Math.max((s[1] - s[0]) / span * 100, 0.25) + '%' }
}
function shift(n) {
  const x = new Date(day.value + 'T12:00:00')
  x.setDate(x.getDate() + n)
  day.value = fmtDay(x)
}
watch([day, () => props.host, () => props.person], async () => {
  d.value = null
  max.value = 12
  d.value = await http.get('/audit/timeline', { params: { host: props.host || undefined, person: props.person || undefined, day: day.value } })
}, { immediate: true })
</script>

<style scoped>
.tl-h { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; padding: 0 18px 12px; }
.day { width: 160px; height: 30px; }
.sp { flex: 1; }
.kv { font-size: 13px; color: var(--muted); margin-left: 12px; }
.kv b { color: var(--ink); font-weight: 600; margin-left: 4px; }
.grid-tl { padding: 0 18px 16px; display: grid; gap: 6px; }
.row, .axis { display: grid; grid-template-columns: 200px minmax(0, 1fr); align-items: center; gap: 12px; }
.lab { display: flex; align-items: center; gap: 7px; font-size: 13px; min-width: 0; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.lab .small { margin-left: auto; }
.track { position: relative; height: 18px; background: var(--sunk); border-radius: 4px; }
.ticks { background: none; height: 16px; }
.ticks span { position: absolute; transform: translateX(-50%); font: 500 11px/16px var(--cond); color: var(--faint); }
.ticks span:first-child { transform: none; }
.ticks span:last-child { transform: translateX(-100%); }
.seg { position: absolute; top: 3px; bottom: 3px; border-radius: 3px; min-width: 2px; }
.seg.on { background: var(--accent); top: 2px; bottom: 2px; }
.online .track { height: 20px; }
.more-apps { justify-self: start; margin-left: 212px; }
@media (max-width: 640px) {
  .row, .axis { grid-template-columns: 110px minmax(0, 1fr); gap: 8px; }
  .lab .small { display: none; }
  .more-apps { margin-left: 0; }
}
</style>
