<template>
  <!-- 未识别域名的归类 / 忽略弹窗，也用来修改已有规则归到的应用（debug26） -->
  <Modal :open="open" :title="title" width="640px" @close="$emit('close')">
    <form v-if="open" class="cf" @submit.prevent="save">
      <p class="lead muted small">{{ mode === 'ignore' ? t('rules.cm.ignoreLead') : mode === 'edit' ? t('rules.cm.editLead') : t('rules.cm.lead') }}</p>

      <!-- 匹配范围：每个域名一行；只有一个时带流量和终端数 -->
      <div class="sec">{{ mode === 'edit' ? t('rules.pattern') : t('rules.cm.scope') }}</div>
      <div v-if="mode === 'edit'" class="addr pat">{{ rule.pattern }}</div>
      <div v-else class="doms">
        <div v-for="it in items" :key="it.domain" class="dom">
          <div class="dh"><b class="addr">{{ it.domain }}</b>
            <span v-if="it.bytes != null" class="faint small">{{ bytes(it.bytes) }} · {{ t('rules.cm.hosts', { n: it.hosts }) }}</span></div>
          <div v-if="!it.s" class="faint small">{{ t('common.loading') }}</div>
          <div v-else class="opts">
            <label v-if="it.s.base !== it.s.domain" class="opt"><input type="radio" v-model="it.scope" value="base" />
              <span>{{ t('rules.cm.base') }} <b class="addr">{{ it.s.base }}</b><span class="faint">{{ t(mode === 'ignore' ? 'rules.cm.baseHintIgnore' : 'rules.cm.baseHint') }}</span></span></label>
            <label class="opt"><input type="radio" v-model="it.scope" value="full" />
              <span>{{ t('rules.cm.full') }} <b class="addr">{{ it.s.domain }}</b><span class="faint">{{ t('rules.cm.fullHint') }}</span></span></label>
            <p v-if="it.s.shared" class="warn-t small">{{ t('rules.cm.shared', { s: it.s.shared }) }}</p>
          </div>
        </div>
        <p v-if="merged.length < items.length" class="faint small">{{ t('rules.cm.merged', { n: merged.length }) }}</p>
      </div>

      <template v-if="mode !== 'ignore'">
        <div class="sec">{{ t('rules.target') }}</div>
        <div class="seg">
          <button type="button" :class="{ on: !newApp }" @click="newApp = false">{{ t('rules.existingApp') }}</button>
          <button type="button" :class="{ on: newApp }" @click="newApp = true">{{ t('rules.newApp') }}</button>
        </div>
        <template v-if="!newApp">
          <div v-if="cands.length" class="cands">
            <span class="faint small">{{ t('rules.cm.suggest') }}</span>
            <button v-for="c in cands" :key="c.app.id" type="button" class="cand" :class="{ on: app && app.id === c.app.id }"
                    @click="pick(c.app.id)" :title="t('rules.cm.src.' + c.source)">
              {{ appName(c.app) }}<span class="faint">{{ t('rules.cm.src.' + c.source) }}</span></button>
          </div>
          <div class="picker">
            <input class="input" v-model="q" :placeholder="t('rules.cm.search')" autocomplete="off" />
            <div v-if="q.trim()" class="res">
              <button v-for="a in found" :key="a.id" type="button" class="ri" :class="{ on: app && app.id === a.id }" @click="pick(a.id)">
                <span>{{ appName(a) }}</span><span class="faint small">{{ catOf(a) }}</span></button>
              <div v-if="!found.length" class="faint small none">{{ t('rules.cm.noApp') }}</div>
            </div>
          </div>
          <div v-if="app" class="picked"><span class="faint small">{{ t('rules.cm.picked') }}</span>
            <b>{{ appName(app) }}</b><span class="faint small">{{ catOf(app) }}</span></div>
        </template>
        <template v-else>
          <input class="input" v-model.trim="nf.app_name" :placeholder="t('rules.appName')" maxlength="64" />
          <input class="input" v-model.trim="nf.app_id" :placeholder="t('rules.appId')" maxlength="48" />
          <select class="input" v-model="nf.category">
            <option v-for="c in meta.categories" :key="c.id" :value="c.id">{{ catLabel(c) }}</option>
          </select>
        </template>

        <label v-if="canShare" class="chk"><input type="checkbox" v-model="share" /> {{ t('rules.cm.share') }}
          <span class="faint small">{{ t('rules.cm.shareHint') }}</span></label>
        <p v-else-if="isSelfhost" class="faint small">{{ t('rules.cm.noShareSelf') }}</p>
      </template>

      <div class="info-bar after"><span class="ic">i</span><div>
        <span>{{ mode === 'ignore' ? t('rules.cm.ignoreAfter') : mode === 'edit' ? t('rules.cm.editAfter') : t('rules.cm.after') }}</span></div></div>
      <div class="err" v-if="err">{{ err }}</div>
      <div class="ft">
        <button type="button" class="btn" @click="$emit('close')">{{ t('common.cancel') }}</button>
        <button class="btn primary" :disabled="!ready || busy">{{ busy ? t('common.loading') : okText }}</button>
      </div>
    </form>
  </Modal>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import http from '../api.js'
import { appName, bytes, catName, groupName } from '../format.js'
import Modal from './Modal.vue'

// mode: classify（归类，rows = 未识别域名行）/ ignore（忽略）/ edit（修改 rule 归到的应用）
const props = defineProps({ open: Boolean, mode: { type: String, default: 'classify' }, rows: { type: Array, default: () => [] },
  rule: Object, meta: { type: Object, required: true } })
const emit = defineEmits(['close', 'saved'])
const { t } = useI18n()

const items = ref([])
const cands = ref([])
const q = ref('')
const appId = ref('')
const newApp = ref(false)
const nf = reactive({ app_id: '', app_name: '', category: 'web' })
const share = ref(false)
const err = ref('')
const busy = ref(false)

const title = computed(() => props.mode === 'edit' ? t('rules.cm.editTitle')
  : t(props.mode === 'ignore' ? 'rules.cm.ignoreTitle' : 'rules.cm.title', { n: props.rows.length }))
const byId = computed(() => Object.fromEntries(props.meta.apps.map(a => [a.id, a])))
const app = computed(() => (newApp.value ? null : byId.value[appId.value] || null))
const catOf = a => {
  const c = props.meta.categories.find(x => x.id === a.category)
  return c ? catLabel(c) : a.category
}
const catLabel = c => `${groupName(props.meta.groups.find(g => g.id === c.group))} · ${catName(c)}`

// 搜索：名称、英文名、ID 都能搜，名字开头匹配的排前面
const found = computed(() => {
  const s = q.value.trim().toLowerCase()
  if (!s) return []
  const hit = []
  for (const a of props.meta.apps) {
    const keys = [a.name, a.name_en, a.id].map(x => String(x || '').toLowerCase())
    if (keys.some(k => k.includes(s))) hit.push([keys.some(k => k.startsWith(s)) ? 0 : 1, a])
    if (hit.length > 400) break
  }
  // 同样匹配时 ID 短的（主应用）排前面：搜 bili 时 bilibili 排在 bili_live 前
  return hit.sort((x, y) => x[0] - y[0] || x[1].id.length - y[1].id.length).slice(0, 30).map(x => x[1])
})

// 主域名相同的合并成一条
const merged = computed(() => [...new Set(items.value.filter(it => it.s).map(it => (it.scope === 'base' ? it.s.base : it.s.domain)))])
const isSelfhost = computed(() => (newApp.value ? nf.category === 'selfhost' : !!app.value && app.value.category === 'selfhost'))
// 只有内置应用能贡献：自定义应用社区主站不认得；自建服务是自家的域名
const canShare = computed(() => !newApp.value && !!app.value && !app.value.custom && !isSelfhost.value)
const ready = computed(() => {
  if (props.mode !== 'edit' && (!items.value.length || items.value.some(it => !it.s))) return false
  if (props.mode === 'ignore') return true
  if (props.mode === 'edit' && !newApp.value && appId.value === props.rule.app_id &&
      (canShare.value && share.value) === !!props.rule.share) return false   // 没改
  return newApp.value ? !!(nf.app_id && nf.app_name && nf.category) : !!app.value
})
const okText = computed(() => {
  if (props.mode === 'ignore') return t('rules.cm.ignoreOk')
  if (props.mode === 'edit') return t('common.save')
  const a = newApp.value ? nf.app_name : app.value ? appName(app.value) : ''
  return a ? t('rules.cm.ok', { app: a }) : t('common.save')
})

function pick(id) { appId.value = id; q.value = '' }

watch(() => props.open, async open => {
  if (!open) return
  err.value = ''
  q.value = ''
  newApp.value = false
  Object.assign(nf, { app_id: '', app_name: '', category: 'web' })
  cands.value = []
  if (props.mode === 'edit') {
    items.value = []
    appId.value = props.rule.app_id
    share.value = !!props.rule.share
    return
  }
  appId.value = ''
  share.value = false
  items.value = props.rows.map(r => reactive({ domain: r.domain, bytes: r.bytes, hosts: r.hosts, s: null, scope: 'base' }))
  const res = await Promise.all(items.value.map(it => http.get('/rules/suggest', { params: { domain: it.domain } }).catch(() => null)))
  const seen = new Set()
  res.forEach((s, i) => {
    const it = items.value[i]
    it.s = s || { domain: it.domain, base: it.domain, default: 'full', shared: null, candidates: [] }
    it.scope = it.s.default
    for (const c of it.s.candidates) {
      if (!seen.has(c.app.id)) { seen.add(c.app.id); cands.value.push(c) }
    }
  })
  cands.value = cands.value.slice(0, 3)
  if (cands.value.length && props.mode === 'classify') appId.value = cands.value[0].app.id
})

async function save() {
  if (!ready.value) return
  err.value = ''
  busy.value = true
  try {
    if (props.mode === 'ignore') {
      await http.post('/rules/ignore', { patterns: merged.value })
      emit('saved', t('rules.cm.ignored', { n: merged.value.length }))
      return
    }
    const body = { ...(newApp.value ? { ...nf } : { app_id: app.value.id }), share: canShare.value && share.value }
    // 只重算这条规则涉及的历史，一般几秒；数据多时给足时间
    const r = props.mode === 'edit' ? await http.put(`/rules/${props.rule.id}`, body, { timeout: 120000 })
      : await http.post('/rules/classify', { ...body, patterns: merged.value }, { timeout: 120000 })
    const a = newApp.value ? nf.app_name : appName(app.value)
    emit('saved', t(r.bytes_moved ? 'rules.cm.done' : 'rules.cm.done0', { app: a, b: bytes(r.bytes_moved) }))
  } catch (e) { err.value = e.message } finally { busy.value = false }
}
</script>

<style scoped>
.cf { display: flex; flex-direction: column; gap: 10px; }
.lead { margin: 0; line-height: 1.6; }
.sec { margin-top: 6px; }
.pat { font-size: 14px; }
.doms { display: flex; flex-direction: column; gap: 10px; max-height: 280px; overflow: auto; }
.dom { border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px; }
.dh { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; margin-bottom: 6px; }
.dh b { word-break: break-all; }
.opts { display: flex; flex-direction: column; gap: 6px; }
.opt { display: flex; gap: 8px; align-items: flex-start; cursor: pointer; font-size: 13.5px; line-height: 1.5; }
.opt input { margin-top: 4px; }
.opt b { word-break: break-all; }
.opt .faint { display: block; font-size: 12.5px; }
.warn-t { margin: 2px 0 0; color: var(--warn); line-height: 1.5; }
.cands { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.cand { display: inline-flex; gap: 6px; align-items: center; height: 30px; padding: 0 11px; border-radius: 15px; border: 1px solid var(--line);
  background: var(--panel); color: var(--ink); font-size: 13px; cursor: pointer; }
.cand .faint { font-size: 11.5px; }
.cand.on, .cand:hover { border-color: var(--brand-ink); color: var(--brand-ink); }
.cand.on { background: var(--brand-weak); }
.picker { position: relative; }
.res { margin-top: 6px; border: 1px solid var(--line); border-radius: 10px; max-height: 220px; overflow: auto; }
.ri { display: flex; justify-content: space-between; gap: 10px; width: 100%; padding: 8px 12px; border: 0; border-bottom: 1px solid var(--line);
  background: none; color: var(--ink); font-size: 13.5px; text-align: left; cursor: pointer; }
.ri:last-child { border-bottom: 0; }
.ri:hover, .ri.on { background: var(--sunk); }
.none { padding: 10px 12px; }
.picked { display: flex; gap: 8px; align-items: baseline; flex-wrap: wrap; }
.chk { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; font-size: 13.5px; cursor: pointer; }
.after { margin-top: 4px; }
.after span { font-size: 12.5px; line-height: 1.6; }
.ft { display: flex; justify-content: flex-end; gap: 8px; margin-top: 4px; }
</style>
