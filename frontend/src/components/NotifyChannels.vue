<template>
  <!-- 通知渠道（参照 EasySub）：上面一排磁贴选渠道（绿点 = 已启用），下面是该渠道的配置面板；可以用还没保存的配置测试 -->
  <div class="panel">
    <div class="panel-h"><h2>{{ t('nc.title') }}</h2><span class="faint small">{{ t('nc.hint') }}</span><span class="sp" />
      <button class="btn sm primary" @click="save" :disabled="!cfg">{{ saved ? t('common.saved') : t('nc.save') }}</button></div>
    <div class="panel-b" v-if="cfg">
      <div class="tiles">
        <button v-for="k in types" :key="k" class="tile" :class="{ on: cur === k }" @click="cur = k">
          <span>{{ t('nc.types.' + k) }}</span><i class="st" :class="{ ok: cfg[k].enabled, bad: last[k] && !last[k].ok }" /></button>
      </div>

      <div class="pane">
        <div class="pane-h">
          <h3>{{ t('nc.enableX', { x: t('nc.types.' + cur) }) }}</h3><span class="sp" />
          <button class="btn sm" @click="test" :disabled="testing">{{ testing ? t('nc.testing') : t('nc.test') }}</button>
          <label class="sw"><input type="checkbox" v-model="c.enabled" /><span /></label>
        </div>
        <div class="help small muted">{{ t('nc.help.' + cur) }}</div>

        <!-- 单个地址的群机器人 -->
        <template v-if="['wecom', 'dingtalk', 'feishu', 'discord', 'slack'].includes(cur)">
          <label :for="'nc-url'">{{ t('nc.f.url') }}</label>
          <input id="nc-url" class="input addr" v-model="c.url" :placeholder="t('nc.ph.' + cur)" />
          <template v-if="cur === 'dingtalk' || cur === 'feishu'">
            <label for="nc-secret">{{ t('nc.f.signSecret') }}</label>
            <input id="nc-secret" class="input addr" v-model="c.secret" :placeholder="t('nc.f.optional')" />
          </template>
          <template v-if="cur === 'wecom'">
            <label>{{ t('nc.f.msgType') }}</label>
            <div class="seg"><button v-for="m in ['text', 'markdown']" :key="m" type="button" :class="{ on: c.msg_type === m }" @click="c.msg_type = m">{{ t('nc.msg.' + m) }}</button></div>
          </template>
        </template>

        <!-- 多个地址 -->
        <template v-if="cur === 'bark' || cur === 'webhook'">
          <label>{{ t('nc.f.urls') }}</label>
          <div v-for="(u, i) in c.urls" :key="i" class="row">
            <input class="input addr grow" v-model="c.urls[i]" :placeholder="t('nc.ph.' + cur)" :aria-label="t('nc.f.urls')" />
            <button class="btn sm ghost" @click="c.urls.splice(i, 1)" :aria-label="t('common.delete')"><Icon name="close" :size="14" /></button>
          </div>
          <div v-if="!c.urls.length" class="dash small faint">{{ t('nc.noUrl') }}</div>
          <div><button class="btn sm" @click="c.urls.push('')">+ URL</button></div>
        </template>
        <div class="two" v-if="cur === 'bark'">
          <div><label for="nc-group">{{ t('nc.f.group') }}</label><input id="nc-group" class="input" v-model="c.group" /></div>
          <div><label for="nc-level">{{ t('nc.f.level') }}</label>
            <select id="nc-level" class="input" v-model="c.level"><option v-for="l in ['active', 'timeSensitive', 'passive', 'critical']" :key="l" :value="l">{{ l }}</option></select></div>
        </div>
        <template v-if="cur === 'webhook'">
          <label for="nc-wsec">{{ t('nc.f.hmac') }}</label>
          <input id="nc-wsec" class="input addr" v-model="c.secret" :placeholder="t('nc.f.optional')" />
          <label>{{ t('nc.f.headers') }}</label>
          <div v-for="(h, i) in c.headers" :key="i" class="row">
            <input class="input" v-model="h.key" placeholder="Header" aria-label="Header" />
            <input class="input grow" v-model="h.value" placeholder="Value" aria-label="Value" />
            <button class="btn sm ghost" @click="c.headers.splice(i, 1)" :aria-label="t('common.delete')"><Icon name="close" :size="14" /></button>
          </div>
          <div><button class="btn sm" @click="c.headers.push({ key: '', value: '' })">+ Header</button></div>
          <label for="nc-tpl">{{ t('nc.f.template') }}</label>
          <textarea id="nc-tpl" class="input code" rows="3" v-model="c.template" placeholder="{{subject}}: {{text}}" />
          <div class="faint small">{{ t('nc.tplHint') }}</div>
          <label for="nc-retry">{{ t('nc.f.retries') }}</label>
          <input id="nc-retry" class="input w" type="number" min="0" max="5" v-model.number="c.retries" />
        </template>

        <template v-if="cur === 'telegram'">
          <div class="two">
            <div><label for="nc-tok">Bot Token</label><input id="nc-tok" class="input addr" v-model="c.bot_token" placeholder="123456:ABC-DEF…" /></div>
            <div><label for="nc-chat">Chat ID</label><input id="nc-chat" class="input addr" v-model="c.chat_id" placeholder="123456789" /></div>
          </div>
          <label for="nc-api">{{ t('nc.f.apiBase') }}</label>
          <input id="nc-api" class="input addr" v-model="c.api_base" placeholder="https://api.telegram.org" />
        </template>

        <template v-if="cur === 'email'">
          <div class="three">
            <div><label for="nc-host">{{ t('nc.f.smtpHost') }}</label><input id="nc-host" class="input addr" v-model="c.host" placeholder="smtp.qq.com" /></div>
            <div><label for="nc-port">{{ t('nc.f.port') }}</label><input id="nc-port" class="input" type="number" v-model.number="c.port" /></div>
            <div><label for="nc-sec">{{ t('nc.f.security') }}</label>
              <select id="nc-sec" class="input" v-model="c.security"><option value="ssl">SSL</option><option value="starttls">STARTTLS</option><option value="none">{{ t('nc.f.none') }}</option></select></div>
          </div>
          <div class="two">
            <div><label for="nc-user">{{ t('login.username') }}</label><input id="nc-user" class="input" v-model="c.username" autocomplete="off" /></div>
            <div><label for="nc-pw">{{ t('login.password') }}</label><input id="nc-pw" class="input" type="password" v-model="c.password" :placeholder="t('nc.f.authCode')" autocomplete="new-password" /></div>
          </div>
          <label for="nc-from">{{ t('nc.f.from') }}</label><input id="nc-from" class="input" v-model="c.from_addr" :placeholder="t('nc.f.fromHint')" />
          <label for="nc-to">{{ t('nc.f.to') }}</label><input id="nc-to" class="input" v-model="c.to" placeholder="a@example.com; b@example.com" />
        </template>

        <template v-if="cur === 'pushplus'">
          <div class="two">
            <div><label for="nc-pt">Token</label><input id="nc-pt" class="input addr" v-model="c.token" /></div>
            <div><label for="nc-topic">{{ t('nc.f.topic') }}</label><input id="nc-topic" class="input" v-model="c.topic" :placeholder="t('nc.f.optional')" /></div>
          </div>
        </template>
        <template v-if="cur === 'serverchan'">
          <label for="nc-sk">SendKey</label><input id="nc-sk" class="input addr" v-model="c.sendkey" placeholder="SCT… / sctp…" />
        </template>
        <template v-if="cur === 'ntfy'">
          <div class="three">
            <div><label for="nc-ns">{{ t('nc.f.server') }}</label><input id="nc-ns" class="input addr" v-model="c.server" /></div>
            <div><label for="nc-nt">{{ t('nc.f.topic') }}</label><input id="nc-nt" class="input" v-model="c.topic" /></div>
            <div><label for="nc-nk">Token</label><input id="nc-nk" class="input addr" v-model="c.token" :placeholder="t('nc.f.optional')" /></div>
          </div>
        </template>
        <template v-if="cur === 'gotify'">
          <div class="three">
            <div><label for="nc-gs">{{ t('nc.f.server') }}</label><input id="nc-gs" class="input addr" v-model="c.server" placeholder="https://gotify.example.com" /></div>
            <div><label for="nc-gt">{{ t('nc.f.appToken') }}</label><input id="nc-gt" class="input addr" v-model="c.token" /></div>
            <div><label for="nc-gp">{{ t('nc.f.priority') }}</label><input id="nc-gp" class="input" type="number" min="0" max="10" v-model.number="c.priority" /></div>
          </div>
        </template>

        <div class="res small" v-if="msg" :class="msgOk ? 'okc' : 'err'">{{ msg }}</div>
        <div class="res small faint" v-else-if="last[cur]">{{ t('nc.last', { t: ago(last[cur].ts) }) }}：<span :class="last[cur].ok ? 'okc' : 'err'">{{ last[cur].ok ? t('nc.ok') : last[cur].error }}</span></div>
      </div>

      <div class="quiet">
        <b>{{ t('nc.quiet') }}</b>
        <input class="input w" type="time" v-model="quiet.from" :aria-label="t('audit.rule.from')" /><span>–</span>
        <input class="input w" type="time" v-model="quiet.to" :aria-label="t('audit.rule.to')" />
        <span class="faint small">{{ t('nc.quietHint') }}</span>
      </div>
      <div class="err" v-if="err">{{ err }}</div>
    </div>
    <div v-else class="empty">{{ t('common.loading') }}</div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import http from '../api.js'
import { ago } from '../format.js'
import Icon from './Icon.vue'

const emit = defineEmits(['saved'])
const { t } = useI18n()
const cfg = ref(null)
const types = ref([])
const last = ref({})
const cur = ref('wecom')
const quiet = reactive({ from: '', to: '' })
const err = ref('')
const saved = ref(false)
const testing = ref(false)
const msg = ref('')
const msgOk = ref(false)
const c = computed(() => cfg.value[cur.value])
watch(cur, () => { msg.value = '' })

function fill(r) {
  cfg.value = r.config
  types.value = r.types
  last.value = r.last || {}
  quiet.from = r.quiet_from || ''
  quiet.to = r.quiet_to || ''
  // 默认停在第一个已启用的渠道
  if (!r.config[cur.value] || !r.config[cur.value].enabled) cur.value = r.enabled[0] || cur.value
}
async function load() { fill(await http.get('/audit/notify')) }
async function save() {
  err.value = ''
  try {
    fill(await http.put('/audit/notify', { config: cfg.value, quiet_from: quiet.from, quiet_to: quiet.to }))
    saved.value = true
    setTimeout(() => (saved.value = false), 1500)
    emit('saved', Object.keys(cfg.value).filter(k => cfg.value[k].enabled))
  } catch (e) { err.value = e.message }
}
async function test() {
  msg.value = ''
  testing.value = true
  try {
    await http.post('/audit/notify/test', { channel: cur.value, config: c.value }, { timeout: 60000 })
    msg.value = '✓ ' + t('nc.sent')
    msgOk.value = true
  } catch (e) {
    msg.value = '⚠ ' + e.message
    msgOk.value = false
  } finally {
    testing.value = false
    setTimeout(() => (msg.value = ''), 6000)
  }
}
onMounted(load)
</script>

<style scoped>
.tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(124px, 1fr)); gap: 8px; }
.tile { position: relative; display: flex; align-items: center; justify-content: space-between; gap: 6px; background: var(--sunk); border: 1px solid transparent;
  border-radius: 10px; padding: 9px 12px; font: inherit; font-size: 13px; color: var(--ink); cursor: pointer; text-align: left; }
.tile.on { border-color: var(--brand-ink); background: var(--brand-weak); color: var(--brand-ink); }
.st { width: 8px; height: 8px; border-radius: 50%; background: var(--line-strong); flex: none; }
.st.ok { background: var(--ok); }
.st.bad { box-shadow: 0 0 0 2px color-mix(in srgb, var(--bad) 45%, transparent); }
.pane { margin-top: 14px; border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px; display: grid; gap: 8px; }
.pane-h { display: flex; align-items: center; gap: 10px; }
.pane-h h3 { margin: 0; font-size: 15px; }
.pane-h .sp { flex: 1; }
.pane > label, .pane label[for] { font-size: 13px; color: var(--muted); }
.two, .three { display: grid; gap: 10px; }
.two { grid-template-columns: 1fr 1fr; }
.three { grid-template-columns: 2fr 1fr 1fr; }
.two > div, .three > div { display: grid; gap: 4px; min-width: 0; }
.row { display: flex; gap: 8px; align-items: center; }
.grow { flex: 1; min-width: 0; }
.w { width: 120px; }
.dash { border: 1px dashed var(--line-strong); border-radius: 8px; padding: 10px; text-align: center; }
.help { line-height: 1.6; }
.res { margin-top: 4px; }
.okc { color: var(--ok); }
.code { font-family: var(--mono, monospace); font-size: 12px; }
.sw { position: relative; width: 38px; height: 22px; flex: none; cursor: pointer; }
.sw input { opacity: 0; width: 0; height: 0; }
.sw span { position: absolute; inset: 0; background: var(--line-strong); border-radius: 11px; transition: background .15s; }
.sw span::after { content: ""; position: absolute; left: 3px; top: 3px; width: 16px; height: 16px; border-radius: 50%; background: #fff; transition: transform .15s; }
.sw input:checked + span { background: var(--ok); }
.sw input:checked + span::after { transform: translateX(16px); }
.sw input:focus-visible + span { outline: 2px solid var(--brand-ink); outline-offset: 2px; }
.quiet { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-top: 14px; }
@media (max-width: 640px) {
  .tiles { grid-template-columns: repeat(2, 1fr); }
  .two, .three { grid-template-columns: 1fr; }
}
</style>
