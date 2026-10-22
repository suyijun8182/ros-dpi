<template>
  <div>
    <div class="page-h"><h1>{{ t('rules.title') }}</h1></div>
    <p class="muted intro">{{ t('rules.intro') }}</p>

    <div class="grid g2">
      <div class="panel">
        <div class="panel-h">{{ t('common.add') }}</div>
        <form class="panel-b form" @submit.prevent="add">
          <div class="seg">
            <button type="button" v-for="k in ['domain', 'cidr', 'port']" :key="k" :class="{ on: f.kind === k }" @click="f.kind = k">{{ t('rules.kinds.' + k) }}</button>
          </div>
          <input class="input" v-model="f.pattern" :placeholder="t('rules.patternHint.' + f.kind)" />
          <div class="seg">
            <button type="button" :class="{ on: !newApp }" @click="newApp = false">{{ t('rules.existingApp') }}</button>
            <button type="button" :class="{ on: newApp }" @click="newApp = true">{{ t('rules.newApp') }}</button>
          </div>
          <select v-if="!newApp" class="input" v-model="f.app_id">
            <optgroup v-for="c in meta.categories" :key="c.id" :label="catLabel(c)">
              <option v-for="a in meta.apps.filter(x => x.category === c.id)" :key="a.id" :value="a.id">{{ appName(a) }}</option>
            </optgroup>
          </select>
          <template v-else>
            <input class="input" v-model="f.app_id" :placeholder="t('rules.appId')" />
            <input class="input" v-model="f.app_name" :placeholder="t('rules.appName')" />
            <select class="input" v-model="f.category">
              <option v-for="c in meta.categories" :key="c.id" :value="c.id">{{ catLabel(c) }}</option>
            </select>
          </template>
          <div class="err" v-if="formErr">{{ formErr }}</div>
          <div><button class="btn primary" :disabled="!f.pattern || !f.app_id">{{ t('common.add') }}</button></div>
        </form>
        <div class="panel-b test">
          <input class="input" v-model="testDomain" :placeholder="t('rules.test')" @keyup.enter="test" />
          <button class="btn" @click="test">{{ t('rules.test') }}</button>
          <span v-if="testRes" class="muted">{{ testRes.app ? t('rules.testResult', { app: appName(testRes.app) }) : t('rules.testNone') }}</span>
        </div>
      </div>

      <div class="panel">
        <div class="panel-h">{{ t('rules.custom') }} <span class="faint">{{ rules.length }}</span></div>
        <div class="tbl-wrap">
          <table class="tbl">
            <thead><tr><th>{{ t('rules.kind') }}</th><th>{{ t('rules.pattern') }}</th><th>{{ t('rules.target') }}</th><th /></tr></thead>
            <tbody>
              <tr v-for="r in rules" :key="r.id">
                <td><span class="tag">{{ t('rules.kinds.' + r.kind) }}</span></td>
                <td class="addr">{{ r.pattern }}</td>
                <td>{{ appLabel(r.app_id) }}</td>
                <td class="r"><button class="btn sm danger" @click="del(r)">{{ t('common.delete') }}</button></td>
              </tr>
            </tbody>
          </table>
          <div v-if="!rules.length" class="empty">{{ t('common.empty') }}</div>
        </div>
      </div>
    </div>

    <div class="panel mt">
      <div class="panel-h">{{ t('rules.unknown') }}<span class="sp" /><RangeTabs :list="['today', 'week', 'month']" /></div>
      <p class="panel-b muted hint">{{ t('rules.unknownHint') }}</p>
      <div class="tbl-wrap">
        <table class="tbl">
          <thead><tr><th>{{ t('hosts.domain') }}</th><th class="r">{{ t('rules.bytes') }}</th><th class="r">{{ t('common.hosts') }}</th><th /></tr></thead>
          <tbody>
            <tr v-for="u in unknown" :key="u.domain">
              <td>{{ u.domain }}</td>
              <td class="r num">{{ bytes(u.bytes) }}</td>
              <td class="r num">{{ u.hosts }}</td>
              <td class="r"><button class="btn sm" @click="classify(u.domain)">{{ t('rules.classify') }}</button></td>
            </tr>
          </tbody>
        </table>
        <div v-if="!unknown.length" class="empty">{{ t('common.empty') }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import http from '../api.js'
import RangeTabs from '../components/RangeTabs.vue'
import { appName, bytes, catName, groupName } from '../format.js'
import { ui } from '../state.js'

const { t } = useI18n()
const meta = ref({ groups: [], categories: [], apps: [] })
const rules = ref([])
const unknown = ref([])
const newApp = ref(false)
const f = reactive({ kind: 'domain', pattern: '', app_id: '', app_name: '', category: 'web' })
const formErr = ref('')
const testDomain = ref('')
const testRes = ref(null)

const unknownRange = () => (['today', 'week', 'month'].includes(ui.range) ? ui.range : 'week')

async function load() {
  ;[meta.value, rules.value] = await Promise.all([http.get('/meta'), http.get('/rules')])
}
async function loadUnknown() {
  unknown.value = await http.get('/rules/unknown-domains', { params: { range: unknownRange() } })
}
onMounted(() => { load(); loadUnknown() })
watch(() => ui.range, loadUnknown)

// 下拉框里分类带上所属大类，例如"影音娱乐 · 短视频"
const catLabel = c => `${groupName(meta.value.groups.find(g => g.id === c.group))} · ${catName(c)}`

function appLabel(id) {
  const a = meta.value.apps.find(x => x.id === id)
  return a ? appName(a) : id
}

// 取注册域名（简单处理：最后两段；.com.cn 这类取三段）
function baseDomain(d) {
  const p = d.split('.')
  const n = /^(com|net|org|gov|edu)\.[a-z]{2}$/.test(p.slice(-2).join('.')) ? 3 : 2
  return p.slice(-n).join('.')
}

function classify(domain) {
  f.kind = 'domain'
  f.pattern = baseDomain(domain)
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

async function add() {
  formErr.value = ''
  try {
    await http.post('/rules', { ...f, app_name: newApp.value ? f.app_name : null, category: newApp.value ? f.category : null })
    f.pattern = ''
    await load()
    await loadUnknown()
  } catch (e) { formErr.value = e.message }
}

async function del(r) {
  if (!confirm(t('common.confirmDelete'))) return
  await http.delete(`/rules/${r.id}`)
  await load()
}

async function test() {
  if (testDomain.value.trim()) testRes.value = await http.get('/rules/test', { params: { domain: testDomain.value.trim() } })
}
</script>

<style scoped>
.intro { margin: -6px 0 14px; }
.mt { margin-top: 14px; }
.form { display: flex; flex-direction: column; gap: 10px; }
.test { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; border-top: 1px solid var(--line); }
.test .input { flex: 1; min-width: 160px; }
.hint { margin: 0; padding-bottom: 4px; font-size: 13px; }
</style>
