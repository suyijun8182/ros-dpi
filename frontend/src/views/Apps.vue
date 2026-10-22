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
        <div class="panel-h"><h2>{{ t('apps.byGroup') }}</h2><span class="faint small">{{ t('apps.byGroupHint') }}</span></div>
        <div class="panel-b"><Composition :groups="d.groups" clickable :active="group" :active-cat="cat" @pick="pick" /></div>
      </div>

      <div class="panel mt">
        <div class="panel-h">
          <h2>{{ filterLabel || t('apps.byApp') }}</h2>
          <span class="faint small" v-if="filterLabel">{{ bytes(shownTotal) }} · {{ pct(shownTotal / (d.range_total.total || 1)) }}</span>
          <button v-if="group || cat" class="btn sm" @click="pick({})">{{ t('apps.showAll') }}</button>
          <span class="sp" />
          <input class="input search" v-model="q" :placeholder="t('common.search')" :aria-label="t('common.search')" />
        </div>
        <div class="tbl-wrap">
          <table class="tbl">
            <thead><tr>
              <th class="rk">#</th><th>{{ t('apps.app') }}</th><th>{{ t('common.category') }}</th>
              <th class="r">{{ t('common.down') }}</th><th class="r">{{ t('common.up') }}</th><th class="r">{{ t('common.total') }}</th>
              <th class="r">{{ t('common.share') }}</th><th class="r">{{ t('apps.usedBy') }}</th><th class="r">{{ t('common.flows') }}</th>
            </tr></thead>
            <tbody>
              <tr v-for="(a, i) in shown" :key="a.id" class="link" @click="$router.push(`/apps/${enc(a.id)}`)">
                <td class="rk num faint">{{ i + 1 }}</td>
                <td class="nm">{{ appName(a) }}</td>
                <td><span class="tag"><span class="chip" :style="{ background: catColor(a.category) }" /><span class="faint">{{ groupName(a) }} ·</span> {{ catName(a) }}</span></td>
                <td class="r num">{{ bytes(a.down) }}</td>
                <td class="r num">{{ bytes(a.up) }}</td>
                <td class="r num"><b>{{ bytes(a.total) }}</b></td>
                <td class="r share">
                  <span class="num muted">{{ pct(a.total / (d.range_total.total || 1)) }}</span>
                  <span class="pair"><i class="d" :style="{ flexGrow: a.down }" /><i class="u" :style="{ flexGrow: a.up }" /></span>
                </td>
                <td class="r num">{{ a.hosts }}</td>
                <td class="r num muted">{{ a.flows.toLocaleString() }}</td>
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
import RangeTabs from '../components/RangeTabs.vue'
import { appName, bytes, CAT_GROUP, catColor, catName, groupName, pct } from '../format.js'
import { usePoll } from '../poll.js'
import { ui } from '../state.js'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const d = ref(null)
const q = ref('')
// 筛选写在地址栏里：?group=media 或 ?cat=short_video（小类隐含所属大类）
const cat = computed(() => route.query.cat || '')
const group = computed(() => route.query.group || CAT_GROUP[cat.value] || '')
const { loading, error } = usePoll(async () => { d.value = await http.get('/apps', { params: { range: ui.range } }) },
  60000, () => ui.range)

function pick(p) {
  const same = p.cat ? p.cat === cat.value : p.group && p.group === group.value && !cat.value
  router.replace({ query: same || (!p.cat && !p.group) ? {} : p.cat ? { cat: p.cat } : { group: p.group } })
}

const shown = computed(() => {
  const s = q.value.trim().toLowerCase()
  return d.value.apps.filter(a => (!cat.value || a.category === cat.value) && (!group.value || a.group === group.value) &&
    (!s || [a.id, a.name, a.name_en].some(v => v && v.toLowerCase().includes(s))))
})
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
.share .pair { margin-top: 5px; width: 90px; margin-left: auto; }
@media (max-width: 640px) { .search { width: 100%; } }
</style>
