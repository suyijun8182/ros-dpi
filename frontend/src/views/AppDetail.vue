<template>
  <div>
    <div class="page-h">
      <router-link to="/apps" class="btn sm">← {{ t('common.back') }}</router-link>
      <h1 v-if="d">{{ appName(d) }}</h1>
      <span v-if="d" class="tag"><span class="chip" :style="{ background: catColor(d.category) }" /><span class="faint">{{ groupName(d) }} ·</span> {{ catName(d) }}</span>
      <span class="sp" />
      <RangeTabs />
    </div>
    <div v-if="error" class="err">{{ error }}</div>
    <template v-if="d">
      <div class="grid g4">
        <Stat :label="t('range.today')" :value="bytes(d.totals.today.total)" :up="d.totals.today.up" :down="d.totals.today.down" />
        <Stat :label="t('range.week')" :value="bytes(d.totals.week.total)" :up="d.totals.week.up" :down="d.totals.week.down" />
        <Stat :label="t('range.month')" :value="bytes(d.totals.month.total)" :up="d.totals.month.up" :down="d.totals.month.down" />
        <Stat :label="t('apps.usedBy')" :value="d.hosts.length" :sub="t('range.' + ui.range)" />
      </div>
      <TrafficPanel class="mt" :total="d.range_total" :points="d.trend" :gran="gran" height="280px" />
      <div class="panel mt">
        <div class="panel-h">{{ t('apps.usedBy') }}</div>
        <div class="tbl-wrap">
          <table class="tbl">
            <thead><tr><th class="rk">#</th><th>{{ t('common.name') }}</th><th>{{ t('hosts.ip') }}</th><th class="r">{{ t('common.down') }}</th><th class="r">{{ t('common.up') }}</th><th class="r">{{ t('common.total') }}</th><th class="r">{{ t('common.share') }}</th></tr></thead>
            <tbody>
              <tr v-for="(h, i) in d.hosts" :key="h.key" class="link" @click="$router.push(`/hosts/${enc(h.key)}`)">
                <td class="rk num faint">{{ i + 1 }}</td>
                <td><span class="nm"><span class="dot" :class="{ on: h.online }" />{{ h.name }}</span></td>
                <td class="addr">{{ h.ip }}</td>
                <td class="r num">{{ bytes(h.down) }}</td>
                <td class="r num">{{ bytes(h.up) }}</td>
                <td class="r num"><b>{{ bytes(h.total) }}</b></td>
                <td class="r share"><span class="num muted">{{ pct(h.total / (d.range_total.total || 1)) }}</span>
                  <span class="bar"><i :style="{ width: (h.total / (d.hosts[0].total || 1) * 100) + '%' }" /></span></td>
              </tr>
            </tbody>
          </table>
          <div v-if="!d.hosts.length" class="empty">{{ t('common.empty') }}</div>
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
import RangeTabs from '../components/RangeTabs.vue'
import Stat from '../components/Stat.vue'
import TrafficPanel from '../components/TrafficPanel.vue'
import { appName, bytes, catColor, catName, groupName, pct } from '../format.js'
import { usePoll } from '../poll.js'
import { ui } from '../state.js'

const props = defineProps({ id: String })
const { t } = useI18n()
const d = ref(null)
const { loading, error } = usePoll(async () => {
  d.value = await http.get(`/apps/${enc(props.id)}/detail`, { params: { range: ui.range } })
}, 60000, () => [ui.range, props.id])
const gran = computed(() => (['today', 'yesterday'].includes(ui.range) ? 'hour' : 'day'))
</script>

<style scoped>
.mt { margin-top: 14px; }
.nm { display: inline-flex; align-items: center; gap: 8px; }
.rk { width: 36px; padding-right: 0; }
.share { min-width: 130px; }
.bar { display: block; height: 5px; margin: 5px 0 0 auto; width: 100px; border-radius: 3px; background: color-mix(in srgb, var(--line) 55%, transparent); }
.bar i { display: block; height: 100%; border-radius: 3px; background: var(--down); }
</style>
