<template>
  <div>
    <div class="page-h">
      <h1>{{ t('apps.title') }}</h1>
      <span class="lead" v-if="d">{{ bytes(d.range_total.total) }} · {{ t('apps.count', { n: d.apps.length }) }}</span>
      <span class="sp" />
      <RangeTabs />
    </div>
    <div v-if="error" class="err">{{ error }}</div>
    <template v-if="d">
      <div class="panel">
        <div class="panel-h"><h2>{{ t('apps.byGroup') }}</h2><span class="faint small">{{ t('apps.byGroupHint') }}</span><span class="sp" />
          <button v-if="group" class="more" @click="pick({})">{{ t('apps.showAll') }}</button></div>
        <div class="panel-b"><Composition :groups="d.groups" clickable drill :active="group" height="340px" @pick="pick" /></div>
      </div>

      <div class="panel mt">
        <div class="panel-h">
          <h2>{{ filterLabel || t('apps.byApp') }}</h2>
          <span class="faint small" v-if="filterLabel">{{ bytes(shownTotal) }} · {{ pct(shownTotal / (d.range_total.total || 1)) }}</span>
          <button v-if="group || cat" class="btn sm" @click="pick({})">{{ t('apps.showAll') }}</button>
          <span class="sp" />
          <div class="seg" role="radiogroup" :aria-label="t('apps.sortBy')">
            <button v-for="m in ['total', 'live']" :key="m" role="radio" :aria-checked="order === m" :class="{ on: order === m }" @click="order = m">{{ t('apps.order.' + m) }}</button>
          </div>
          <input class="input search" v-model="q" :placeholder="t('common.search')" :aria-label="t('common.search')" />
          <button class="btn sm" @click="exportApps"><Icon name="download" :size="15" />{{ t('common.export') }}</button>
        </div>
        <div class="tbl-wrap">
          <table class="tbl">
            <thead><tr>
              <th class="rk m-hide">#</th><th>{{ t('apps.app') }}</th><th class="m-hide">{{ t('common.category') }}</th>
              <th class="r m-hide">{{ t('common.down') }}</th><th class="r m-hide">{{ t('common.up') }}</th><th class="r">{{ t('common.total') }}</th>
              <th class="r m-hide">{{ t('common.share') }}</th><th class="r">{{ t('apps.live') }}</th><th class="r m-hide">{{ t('apps.usedBy') }}</th><th class="r m-hide">{{ t('common.flows') }}</th>
            </tr></thead>
            <tbody>
              <tr v-for="(a, i) in shown" :key="a.id" class="link" @click="$router.push(`/apps/${enc(a.id)}`)">
                <td class="rk num faint m-hide">{{ i + 1 }}</td>
                <td class="nm">{{ appName(a) }}<div class="m-only faint small">{{ catName(a) }} · {{ pct(a.total / (d.range_total.total || 1)) }}</div></td>
                <td class="m-hide"><span class="tag"><span class="chip" :style="{ background: catColor(a.category) }" /><span class="faint">{{ groupName(a) }} ·</span> {{ catName(a) }}</span></td>
                <td class="r num m-hide">{{ bytes(a.down) }}</td>
                <td class="r num m-hide">{{ bytes(a.up) }}</td>
                <td class="r num"><b>{{ bytes(a.total) }}</b></td>
                <td class="r share m-hide">
                  <span class="num muted">{{ pct(a.total / (d.range_total.total || 1)) }}</span>
                  <span class="pair"><i class="d" :style="{ flexGrow: a.down }" /><i class="u" :style="{ flexGrow: a.up }" /></span>
                </td>
                <td class="r num small live"><span class="up">↑{{ rate(a.rate_up) }}</span><br /><span class="down">↓{{ rate(a.rate_down) }}</span></td>
                <td class="r num m-hide">{{ a.hosts }}</td>
                <td class="r num muted m-hide">{{ a.flows.toLocaleString() }}</td>
              </tr>
            </tbody>
          </table>
          <div v-if="!shown.length" class="empty">{{ t('common.empty') }}</div>
        </div>
      </div>
    </template>
    <div v-else-if="loading" class="empty">{{ t('common.loading') }}</div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import http, { enc } from '../api.js'
import Composition from '../components/Composition.vue'
import Icon from '../components/Icon.vue'
import { exportCsv } from '../csv.js'
import RangeTabs from '../components/RangeTabs.vue'
import { appName, bytes, CAT_GROUP, catColor, catName, groupName, pct, rate } from '../format.js'
import { usePoll } from '../poll.js'
import { ui } from '../state.js'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const d = ref(null)
const q = ref('')
const order = ref('total')  // total 按累计流量 | live 按此刻速率
// 筛选写在地址栏里：?group=media 或 ?cat=short_video（小类隐含所属大类）
const cat = computed(() => route.query.cat || '')
const group = computed(() => route.query.group || CAT_GROUP[cat.value] || '')
const { loading, error } = usePoll(async () => { d.value = await http.get('/apps', { params: { range: ui.range } }) },
  15000, () => ui.range)

function pick(p) {
  const same = p.cat ? p.cat === cat.value : p.group && p.group === group.value && !cat.value
  router.replace({ query: same || (!p.cat && !p.group) ? {} : p.cat ? { cat: p.cat } : { group: p.group } })
}

const shown = computed(() => {
  const s = q.value.trim().toLowerCase()
  const list = d.value.apps.filter(a => (!cat.value || a.category === cat.value) && (!group.value || a.group === group.value) &&
    (!s || [a.id, a.name, a.name_en].some(v => v && v.toLowerCase().includes(s))))
  return order.value === 'live' ? [...list].sort((a, b) => b.rate_up + b.rate_down - a.rate_up - a.rate_down) : list
})

function exportApps() {
  exportCsv('rosdpi-apps', [
    { label: t('apps.app'), value: a => appName(a) }, { label: t('apps.group'), value: a => groupName(a) },
    { label: t('common.category'), value: a => catName(a) },
    { label: t('common.down') + ' (B)', value: a => a.down }, { label: t('common.up') + ' (B)', value: a => a.up },
    { label: t('common.total') + ' (B)', value: a => a.total }, { label: t('common.share'), value: a => pct(a.total / (d.value.range_total.total || 1)) },
    { label: t('common.up') + ' bps', value: a => Math.round(a.rate_up * 8) }, { label: t('common.down') + ' bps', value: a => Math.round(a.rate_down * 8) },
    { label: t('apps.usedBy'), value: a => a.hosts }, { label: t('common.flows'), value: a => a.flows },
  ], shown.value)
}
const shownTotal = computed(() => shown.value.reduce((n, a) => n + a.total, 0))
const filterLabel = computed(() => {
  const g = d.value.groups.find(x => x.id === group.value)
  if (!g) return ''
  const c = cat.value && g.children.find(x => x.id === cat.value)
  return c ? `${groupName(g)} · ${catName(c)}` : groupName(g)
})
</script>

<style scoped>
.search { width: 220px; height: 32px; }
.nm { font-weight: 500; }
.rk { width: 36px; padding-right: 0; }
.share { min-width: 110px; }
.live { line-height: 1.35; font-size: 12.5px; }
.share .pair { margin-top: 5px; width: 90px; margin-left: auto; }
@media (max-width: 640px) { .search { width: 100%; } }
</style>
