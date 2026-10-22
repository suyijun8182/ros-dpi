<template>
  <!-- 访问日志表格：审计页（全部终端）和终端详情（固定一台终端）共用 -->
  <div>
    <div class="flt">
      <input id="al-q" class="input q" v-model="q" :placeholder="t('audit.log.search')" :aria-label="t('audit.log.search')" @keyup.enter="load(1)" />
      <select id="al-group" class="input sel" v-model="group" :aria-label="t('apps.group')" @change="load(1)">
        <option value="">{{ t('audit.log.allGroups') }}</option>
        <option v-for="g in groups" :key="g.id" :value="g.id">{{ groupName(g) }}</option>
      </select>
      <span class="sp" />
      <span class="faint small" v-if="d">{{ t('audit.log.count', { n: d.total.toLocaleString() }) }}</span>
      <button class="btn sm" @click="exportCsv" :disabled="!d || !d.total || exporting"><Icon name="download" :size="15" />{{ t('common.export') }}</button>
    </div>
    <div class="tbl-wrap">
      <table class="tbl">
        <thead><tr>
          <th>{{ t('audit.log.time') }}</th><th v-if="!host" class="m-hide">{{ t('flow.host') }}</th><th>{{ t('flow.dest') }}</th>
          <th class="m-hide">{{ t('apps.app') }}</th><th class="r">{{ t('flow.bytes') }}</th><th class="r m-hide">{{ t('hosts.conns') }}</th><th class="m-hide">{{ t('flow.source') }}</th>
        </tr></thead>
        <tbody v-if="d">
          <tr v-for="r in d.rows" :key="r.id">
            <td class="num small tm">{{ clock(r.ts_start) }}<span class="faint m-hide"> – {{ clock(r.ts_end, r.ts_start) }}</span>
              <div class="faint">{{ duration(r.ts_end - r.ts_start, locale === 'zh') }}</div></td>
            <td v-if="!host" class="m-hide"><router-link :to="`/hosts/${enc(r.host)}?tab=log`" class="hl">{{ r.host_name }}</router-link>
              <div class="faint addr small">{{ r.host_ip }}</div></td>
            <td class="rm"><div class="dn" :title="r.dest">{{ r.dest }}</div>
              <div class="faint addr small" v-if="r.remote && r.remote !== r.dest">{{ r.remote }}<span v-if="r.port">:{{ r.port }}</span></div>
              <div class="m-only faint small">{{ appName(r.app) }}<template v-if="!host"> · {{ r.host_name }}</template></div></td>
            <td class="m-hide"><span class="tag"><span class="chip" :style="{ background: catColor(r.app.category) }" />{{ appName(r.app) }}</span></td>
            <td class="r num small"><span class="down">↓{{ bytes(r.down) }}</span><br /><span class="up">↑{{ bytes(r.up) }}</span></td>
            <td class="r num m-hide">{{ r.conns }}</td>
            <td class="m-hide"><span class="pill" :class="r.source === 'conn' || r.source === 'proxy' ? 'ok' : r.source === 'none' ? 'warn' : 'grey'">{{ t('flow.src.' + (r.source || 'none')) }}</span></td>
          </tr>
        </tbody>
      </table>
      <div v-if="d && !d.rows.length" class="empty">{{ t('audit.log.empty') }}</div>
      <div v-if="!d" class="empty">{{ t('common.loading') }}</div>
    </div>
    <div class="pager" v-if="d && d.total > d.size">
      <button class="btn sm" :disabled="page <= 1" @click="load(page - 1)">‹</button>
      <span class="num small">{{ page }} / {{ pages }}</span>
      <button class="btn sm" :disabled="page >= pages" @click="load(page + 1)">›</button>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import http, { enc } from '../api.js'
import { downloadBlob, duration } from '../csv.js'
import { appName, bytes, catColor, groupName } from '../format.js'
import { ui } from '../state.js'
import Icon from './Icon.vue'

const props = defineProps({ host: String })
const { t, locale } = useI18n()
const d = ref(null)
const q = ref('')
const group = ref('')
const page = ref(1)
const groups = ref([])
const exporting = ref(false)
const pages = computed(() => (d.value ? Math.max(1, Math.ceil(d.value.total / d.value.size)) : 1))

const pad = n => String(n).padStart(2, '0')
// 同一天只显示时:分:秒；跨天的结束时间带上日期
function clock(ts, ref0) {
  const x = new Date(ts * 1000)
  const s = `${pad(x.getHours())}:${pad(x.getMinutes())}:${pad(x.getSeconds())}`
  const base = new Date((ref0 || Date.now() / 1000) * 1000)
  return x.toDateString() === base.toDateString() || ref0 ? s : `${x.getMonth() + 1}/${x.getDate()} ${s}`
}

const params = () => ({ range: ui.range, host: props.host || undefined, q: q.value.trim() || undefined, group: group.value || undefined })
async function load(p = page.value) {
  page.value = p
  d.value = await http.get('/audit/logs', { params: { ...params(), page: p, size: 50 } })
}
async function exportCsv() {
  exporting.value = true
  try {
    const blob = await http.get('/audit/logs.csv', { params: params(), responseType: 'blob', timeout: 120000 })
    downloadBlob(blob, `rosdpi-access-log.csv`)
  } finally { exporting.value = false }
}
onMounted(async () => {
  try { groups.value = (await http.get('/meta')).groups.filter(g => g.id !== 'unknown') } catch (e) { /* 只影响筛选 */ }
})
watch([() => ui.range, () => props.host], () => load(1), { immediate: true })
</script>

<style scoped>
.flt { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; padding: 0 18px 12px; }
.q { width: 260px; height: 32px; }
.sel { width: 160px; height: 32px; }
.sp { flex: 1; }
.tm { line-height: 1.4; }
.hl { font-weight: 500; }
.hl:hover { color: var(--brand-ink); }
.rm { max-width: 360px; }
@media (max-width: 640px) { .rm { max-width: 170px; } }
.dn { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pager { display: flex; justify-content: center; align-items: center; gap: 12px; padding: 12px; }
@media (max-width: 640px) { .q, .sel { width: 100%; } }
</style>
