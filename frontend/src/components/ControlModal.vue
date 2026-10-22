<template>
  <!-- 管控命令：按人员 / 设备生成 RouterOS 命令，复制到路由器执行。ROS-DPI 自己不写路由器 -->
  <Modal :open="open" :title="t('ctl.title', { name })" width="720px" @close="$emit('close')">
    <div class="cf">
      <div class="info-bar"><span class="ic">i</span><div><span>{{ t('ctl.info') }}</span></div></div>
      <div class="seg" role="radiogroup" :aria-label="t('ctl.action')">
        <button v-for="a in ['block_app', 'block_all', 'limit']" :key="a" type="button" role="radio" :aria-checked="f.action === a"
                :class="{ on: f.action === a }" @click="f.action = a; res = null">{{ t('ctl.actions.' + a) }}</button>
      </div>
      <template v-if="f.action === 'block_app'">
        <label>{{ t('apps.group') }} / {{ t('common.category') }}</label>
        <div class="chips">
          <button v-for="g in choices" :key="g.id" type="button" class="chip-b" :class="{ on: f.groups.includes(g.id) }" @click="toggle(f.groups, g.id)">{{ catName(g) }}</button>
        </div>
        <label for="cf-app">{{ t('apps.app') }}</label>
        <input id="cf-app" class="input" v-model="appQ" :placeholder="t('common.search')" />
        <div class="chips" v-if="appQ.trim()">
          <button v-for="a in appChoices" :key="a.id" type="button" class="chip-b" :class="{ on: f.apps.includes(a.id) }" @click="toggle(f.apps, a.id)">{{ appName(a) }}</button>
        </div>
        <div class="chips" v-if="f.apps.length"><span v-for="id in f.apps" :key="id" class="chip-b on" @click="toggle(f.apps, id)">{{ appName(appMap[id] || { name: id }) }} ✕</span></div>
        <label class="chk"><input type="checkbox" v-model="f.block_quic" /> {{ t('ctl.quic') }}</label>
      </template>
      <template v-if="f.action === 'limit'">
        <div class="row"><label class="lim">{{ t('common.up') }} <input class="input num" type="number" min="0" step="0.5" v-model.number="f.up_mbps" /> Mbps</label>
          <label class="lim">{{ t('common.down') }} <input class="input num" type="number" min="0" step="0.5" v-model.number="f.down_mbps" /> Mbps</label></div>
      </template>
      <template v-else>
        <label>{{ t('audit.rule.when') }}</label>
        <div class="row days"><label v-for="x in 7" :key="x" class="chk"><input type="checkbox" :checked="f.days.includes(String(x))" @change="toggleDay(x)" /> {{ t('audit.dow.' + x) }}</label></div>
        <div class="row"><input class="input w" type="time" v-model="f.time_from" :aria-label="t('audit.rule.from')" /><span>–</span>
          <input class="input w" type="time" v-model="f.time_to" :aria-label="t('audit.rule.to')" /><span class="faint small">{{ t('audit.rule.timeHint') }}</span></div>
      </template>
      <div class="err" v-if="err">{{ err }}</div>
      <div class="row end"><button class="btn primary" @click="gen" :disabled="busy">{{ t('ctl.generate') }}</button></div>
      <template v-if="res">
        <div class="sec">{{ t('ctl.script') }}<span class="sp" /><button class="btn sm" @click="copy(res.script, 's')"><Icon name="copy" :size="14" />{{ copied === 's' ? t('ctl.copied') : t('ctl.copy') }}</button></div>
        <pre class="code">{{ res.script }}</pre>
        <ul class="notes"><li v-for="n in res.notes" :key="n" class="small muted">{{ n }}</li></ul>
        <div class="sec">{{ t('ctl.undo') }}<span class="sp" /><button class="btn sm" @click="copy(res.undo, 'u')"><Icon name="copy" :size="14" />{{ copied === 'u' ? t('ctl.copied') : t('ctl.copy') }}</button></div>
        <pre class="code">{{ res.undo }}</pre>
      </template>
    </div>
  </Modal>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import http from '../api.js'
import { appName, catName } from '../format.js'
import Icon from './Icon.vue'
import Modal from './Modal.vue'

const props = defineProps({ open: Boolean, target: String, targetId: [String, Number], name: String })
defineEmits(['close'])
const { t } = useI18n()
const f = reactive({ action: 'block_app', groups: [], apps: [], days: '1234567', time_from: '00:00', time_to: '00:00', block_quic: true, up_mbps: 0, down_mbps: 0 })
const meta = ref({ groups: [], categories: [], apps: [] })
const appQ = ref('')
const res = ref(null)
const err = ref('')
const busy = ref(false)
const copied = ref('')
watch(() => props.open, async o => {
  if (o && !meta.value.apps.length) meta.value = await http.get('/meta')
  res.value = null
  err.value = ''
})
const choices = computed(() => meta.value.groups.filter(g => !['base', 'unknown', 'work'].includes(g.id))
  .concat(meta.value.categories.filter(c => ['short_video', 'live', 'mobile_game', 'shopping', 'adult', 'stock'].includes(c.id))))
const appMap = computed(() => Object.fromEntries(meta.value.apps.map(a => [a.id, a])))
const appChoices = computed(() => {
  const s = appQ.value.trim().toLowerCase()
  return meta.value.apps.filter(a => [a.id, a.name, a.name_en].some(v => v && String(v).toLowerCase().includes(s))).slice(0, 30)
})
function toggle(arr, id) {
  const i = arr.indexOf(id)
  i >= 0 ? arr.splice(i, 1) : arr.push(id)
}
function toggleDay(x) {
  const s = new Set(f.days.split(''))
  s.has(String(x)) ? s.delete(String(x)) : s.add(String(x))
  f.days = [...s].sort().join('') || '1234567'
}
async function gen() {
  err.value = ''
  busy.value = true
  try {
    res.value = await http.post('/control/script', { target: props.target, target_id: String(props.targetId), ...f,
      time_to: f.time_to === '00:00' ? '24:00' : f.time_to })
  } catch (e) { err.value = e.message } finally { busy.value = false }
}
async function copy(text, k) {
  try { await navigator.clipboard.writeText(text) } catch (e) { /* 浏览器不允许时手动选中复制 */ }
  copied.value = k
  setTimeout(() => (copied.value = ''), 1500)
}
</script>

<style scoped>
.cf { display: grid; gap: 10px; }
.cf > label { font-size: 13px; color: var(--muted); margin-top: 4px; }
.chips { display: flex; gap: 6px; flex-wrap: wrap; }
.chip-b { border: 1px solid var(--line); background: var(--panel); color: var(--ink); border-radius: 16px; padding: 3px 11px; font: inherit; font-size: 13px; cursor: pointer; }
.chip-b.on { border-color: var(--brand-ink); background: var(--brand-weak); color: var(--brand-ink); }
.row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.row.end { justify-content: flex-end; }
.days { gap: 14px; }
.w { width: 130px; }
.chk { display: inline-flex; gap: 6px; align-items: center; font-size: 13px; color: var(--muted); cursor: pointer; }
.lim { display: inline-flex; gap: 8px; align-items: center; font-size: 13px; }
.lim input { width: 90px; }
.sec { display: flex; align-items: center; }
.sec .sp { flex: 1; }
.code { max-height: 240px; overflow: auto; white-space: pre; font-size: 12px; }
.notes { margin: 0; padding-left: 18px; display: grid; gap: 4px; }
</style>
