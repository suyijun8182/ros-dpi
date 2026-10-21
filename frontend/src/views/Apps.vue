<template>
  <div>
    <div class="page-h">
      <h1>{{ t('apps.title') }}</h1>
      <span class="lead" v-if="d">{{ bytes(d.range_total.total) }}</span>
      <span class="sp" />
      <RangeTabs />
    </div>
    <div v-if="error" class="err">{{ error }}</div>
    <template v-if="d">
      <section class="mix">
        <Spectrum :cats="d.categories" clickable :height="18" :legend-max="30" @pick="pick" />
      </section>

      <div class="panel mt">
        <div class="panel-h">
          {{ cat ? catLabel : t('apps.byApp') }}
          <button v-if="cat" class="btn sm" @click="pick('')">{{ t('apps.showAll') }}</button>
          <span class="sp" />
          <input class="input search" v-model="q" :placeholder="t('common.search')" :aria-label="t('common.search')" />
        </div>
        <div class="tbl-wrap">
          <table class="tbl">
            <thead><tr>
              <th>{{ t('apps.app') }}</th><th>{{ t('common.category') }}</th>
              <th class="r">{{ t('common.down') }}</th><th class="r">{{ t('common.up') }}</th><th class="r">{{ t('common.total') }}</th>
              <th class="r">{{ t('common.share') }}</th><th class="r">{{ t('apps.usedBy') }}</th><th class="r">{{ t('common.flows') }}</th>
            </tr></thead>
            <tbody>
              <tr v-for="a in shown" :key="a.id" class="link" @click="$router.push(`/apps/${enc(a.id)}`)">
                <td class="nm">{{ appName(a) }}</td>
                <td><span class="tag"><span class="chip" :style="{ background: catColor(a.category) }" />{{ catName(a) }}</span></td>
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
import RangeTabs from '../components/RangeTabs.vue'
import Spectrum from '../components/Spectrum.vue'
import { appName, bytes, catColor, catName, pct } from '../format.js'
import { usePoll } from '../poll.js'
import { ui } from '../state.js'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const d = ref(null)
const q = ref('')
const cat = computed(() => route.query.cat || '')
const { loading, error } = usePoll(async () => { d.value = await http.get('/apps', { params: { range: ui.range } }) },
  60000, () => ui.range)

function pick(c) {
  router.replace({ query: c && c !== cat.value ? { cat: c } : {} })
}

const shown = computed(() => {
  const s = q.value.trim().toLowerCase()
  return d.value.apps.filter(a => (!cat.value || a.category === cat.value) &&
    (!s || [a.id, a.name, a.name_en].some(v => v && v.toLowerCase().includes(s))))
})
const catLabel = computed(() => {
  const c = d.value.categories.find(x => x.id === cat.value)
  return c ? catName(c) : cat.value
})
</script>

<style scoped>
.mix { padding-bottom: 4px; }
.search { width: 220px; height: 32px; }
.nm { font-weight: 500; }
.share { min-width: 110px; }
.share .pair { margin-top: 5px; width: 90px; margin-left: auto; }
@media (max-width: 640px) { .search { width: 100%; } }
</style>
