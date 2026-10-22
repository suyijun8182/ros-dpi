<template>
  <!-- 日志与留存：Syslog 外发、各类数据的保留天数、数据库占用（参照深信服 AC 的日志中心 / 合规要求） -->
  <div v-if="c" class="grid g2 cp">
    <div class="panel">
      <div class="panel-h"><h2>{{ t('cp.syslog') }}</h2><span class="sp" />
        <label class="sw" :title="t('nc.enable')"><input type="checkbox" v-model="c.syslog.enabled" :aria-label="t('cp.syslog')" /><span /></label></div>
      <div class="panel-b form">
        <div class="faint small">{{ t('cp.syslogHint') }}</div>
        <div class="row">
          <input class="input grow addr" v-model="c.syslog.host" :placeholder="t('cp.host')" :aria-label="t('cp.host')" />
          <input class="input w num" type="number" min="1" max="65535" v-model.number="c.syslog.port" :aria-label="t('cp.port')" />
          <select class="input w" v-model="c.syslog.proto" :aria-label="t('cp.proto')"><option value="udp">UDP</option><option value="tcp">TCP</option></select>
        </div>
        <div class="row">
          <label class="chk"><input type="checkbox" v-model="c.syslog.access" /> {{ t('cp.sendAccess') }}</label>
          <label class="chk"><input type="checkbox" v-model="c.syslog.events" /> {{ t('cp.sendEvents') }}</label>
        </div>
        <div class="faint small">{{ t('cp.format') }}</div>
        <div class="row"><button class="btn sm" @click="test" :disabled="!c.syslog.host">{{ t('nc.test') }}</button>
          <span class="small" :class="msgOk ? 'okc' : 'err'" v-if="msg">{{ msg }}</span><span class="sp" />
          <button class="btn sm primary" @click="save('syslog')">{{ saved === 'syslog' ? t('common.saved') : t('common.save') }}</button></div>
      </div>
    </div>
    <div class="panel">
      <div class="panel-h"><h2>{{ t('cp.retention') }}</h2></div>
      <div class="panel-b form">
        <div class="faint small">{{ t('cp.retentionHint') }}</div>
        <div class="ret">
          <label v-for="k in KEYS" :key="k">{{ t('cp.r.' + k) }}
            <span><input class="input num" type="number" min="1" v-model.number="c.retention[k]" /> {{ t('cp.days') }}</span></label>
        </div>
        <div class="row"><span class="sp" /><button class="btn sm primary" @click="save('retention')">{{ saved === 'retention' ? t('common.saved') : t('common.save') }}</button></div>
        <div class="sec">{{ t('cp.usage') }}<span class="faint small" v-if="c.usage.total">{{ bytes(c.usage.total) }}</span></div>
        <table class="tbl mini">
          <thead><tr><th>{{ t('cp.table') }}</th><th class="r">{{ t('cp.rows') }}</th><th class="r" v-if="c.usage.dialect !== 'sqlite'">{{ t('cp.size') }}</th></tr></thead>
          <tbody><tr v-for="x in c.usage.tables.slice(0, 10)" :key="x.table"><td class="addr small">{{ x.table }}</td>
            <td class="r num">{{ x.rows.toLocaleString() }}</td><td class="r num" v-if="c.usage.dialect !== 'sqlite'">{{ bytes(x.bytes || 0) }}</td></tr></tbody>
        </table>
      </div>
    </div>
    <div class="err" v-if="err">{{ err }}</div>
  </div>
  <div v-else class="empty">{{ t('common.loading') }}</div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import http from '../api.js'
import { bytes } from '../format.js'

const KEYS = ['log', 'event', 'minute', 'hour', 'day', 'domain']
const { t } = useI18n()
const c = ref(null)
const err = ref('')
const saved = ref('')
const msg = ref('')
const msgOk = ref(false)
async function load() { c.value = await http.get('/compliance') }
async function save(k) {
  err.value = ''
  try {
    c.value = await http.put('/compliance', { [k]: c.value[k] })
    saved.value = k
    setTimeout(() => (saved.value = ''), 1500)
  } catch (e) { err.value = e.message }
}
async function test() {
  msg.value = ''
  try { await http.post('/compliance/syslog-test', c.value.syslog); msg.value = '✓ ' + t('nc.sent'); msgOk.value = true } catch (e) { msg.value = e.message; msgOk.value = false }
}
onMounted(load)
</script>

<style scoped>
.cp { align-items: start; }
.form { display: grid; gap: 10px; }
.row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.row .sp { flex: 1; }
.grow { flex: 1; min-width: 160px; }
.w { width: 96px; }
.chk { display: inline-flex; gap: 6px; align-items: center; font-size: 13px; color: var(--muted); cursor: pointer; }
.okc { color: var(--ok); }
.ret { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 8px 16px; }
.ret label { display: grid; gap: 4px; font-size: 13px; color: var(--muted); }
.ret span { display: flex; gap: 6px; align-items: center; color: var(--ink); }
.ret input { width: 90px; }
.mini td, .mini th { padding: 6px 8px; }
.sw { position: relative; width: 38px; height: 22px; flex: none; cursor: pointer; }
.sw input { opacity: 0; width: 0; height: 0; }
.sw span { position: absolute; inset: 0; background: var(--line-strong); border-radius: 11px; transition: background .15s; }
.sw span::after { content: ""; position: absolute; left: 3px; top: 3px; width: 16px; height: 16px; border-radius: 50%; background: #fff; transition: transform .15s; }
.sw input:checked + span { background: var(--ok); }
.sw input:checked + span::after { transform: translateX(16px); }
.sw input:focus-visible + span { outline: 2px solid var(--brand-ink); outline-offset: 2px; }
</style>
