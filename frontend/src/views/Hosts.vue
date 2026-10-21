<template>
  <div>
    <div class="page-h">
      <h1>{{ t('hosts.title') }}</h1>
      <span class="muted" v-if="rows.length">{{ t('hosts.count', { n: rows.length, m: onlineN }) }}</span>
      <span class="sp" />
      <label class="chk"><input type="checkbox" v-model="onlineOnly" /> {{ t('hosts.onlineOnly') }}</label>
      <input class="input search" v-model="q" :placeholder="t('hosts.search')" />
    </div>
    <div v-if="error" class="err">{{ error }}</div>
    <div class="panel">
      <div class="tbl-wrap">
        <table class="tbl">
          <thead>
            <tr>
              <th class="sort" @click="sortBy('name')">{{ t('common.name') }} {{ arrow('name') }}</th>
              <th class="sort" @click="sortBy('ip')">{{ t('hosts.ip') }} {{ arrow('ip') }}</th>
              <th>{{ t('hosts.mac') }}</th>
              <th class="r sort" @click="sortBy('rate')">{{ t('common.rate') }} {{ arrow('rate') }}</th>
              <th class="r sort" @click="sortBy('today')">{{ t('range.today') }} {{ arrow('today') }}</th>
              <th class="r sort" @click="sortBy('week')">{{ t('range.week') }} {{ arrow('week') }}</th>
              <th class="r sort" @click="sortBy('month')">{{ t('range.month') }} {{ arrow('month') }}</th>
              <th>{{ t('hosts.topApp') }}</th>
              <th class="sort" @click="sortBy('last')">{{ t('hosts.lastSeen') }} {{ arrow('last') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="h in shown" :key="h.key" class="link" @click="$router.push(`/hosts/${enc(h.key)}`)">
              <td><span class="nm"><span class="dot" :class="{ on: h.online }" />{{ h.name }}</span>
                <span class="faint hn" v-if="h.alias && h.hostname">{{ h.hostname }}</span></td>
              <td class="addr">{{ h.ip }}</td>
              <td class="addr faint">{{ h.mac || '-' }}</td>
              <td class="r num small"><span class="down">↓{{ rate(h.rate_down) }}</span><br /><span class="up">↑{{ rate(h.rate_up) }}</span></td>
              <td class="r num">{{ bytes(h.today.total) }}</td>
              <td class="r num">{{ bytes(h.week.total) }}</td>
              <td class="r num">{{ bytes(h.month.total) }}</td>
              <td><span v-if="h.top_app" class="tag"><span class="chip" :style="{ background: catColor(h.top_app.category) }" />{{ appName(h.top_app) }}</span></td>
              <td class="muted small">{{ ago(h.last_seen) }}</td>
            </tr>
          </tbody>
        </table>
        <div v-if="!shown.length" class="empty">{{ loading ? t('common.loading') : t('common.empty') }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import http, { enc } from '../api.js'
import { ago, appName, bytes, catColor, rate } from '../format.js'
import { usePoll } from '../poll.js'

const { t } = useI18n()
const rows = ref([])
const q = ref('')
const onlineOnly = ref(false)
const sort = ref({ key: 'today', desc: true })
const { loading, error } = usePoll(async () => { rows.value = await http.get('/hosts') }, 30000)

const onlineN = computed(() => rows.value.filter(h => h.online).length)
const ipNum = ip => (ip || '').split('.').reduce((s, x) => s * 256 + (+x || 0), 0)
const keyFn = {
  name: h => (h.name || '').toLowerCase(), ip: h => ipNum(h.ip), rate: h => h.rate_up + h.rate_down,
  today: h => h.today.total, week: h => h.week.total, month: h => h.month.total, last: h => h.last_seen || 0,
}

const shown = computed(() => {
  const s = q.value.trim().toLowerCase()
  let list = rows.value.filter(h => (!onlineOnly.value || h.online) &&
    (!s || [h.name, h.ip, h.mac, h.hostname, h.alias].some(v => v && v.toLowerCase().includes(s))))
  const f = keyFn[sort.value.key]
  const dir = sort.value.desc ? -1 : 1
  return [...list].sort((a, b) => (f(a) > f(b) ? dir : f(a) < f(b) ? -dir : 0))
})

function sortBy(k) {
  sort.value = { key: k, desc: sort.value.key === k ? !sort.value.desc : k !== 'name' && k !== 'ip' }
}
const arrow = k => (sort.value.key === k ? (sort.value.desc ? '↓' : '↑') : '')
</script>

<style scoped>
.search { width: 240px; }
.chk { display: flex; gap: 6px; align-items: center; color: var(--muted); font-size: 13px; cursor: pointer; }
.nm { display: inline-flex; align-items: center; gap: 8px; }
.hn { margin-left: 8px; font-size: 12px; }
.small { font-size: 12px; line-height: 1.35; }
@media (max-width: 640px) { .search { width: 100%; } }
</style>
