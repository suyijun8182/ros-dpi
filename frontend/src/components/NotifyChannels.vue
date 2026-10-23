<template>
  <!-- 通知渠道（照搬 EasySub）：上面一排磁贴选渠道（绿点 = 已启用），下面是该渠道的配置面板；可以用还没保存的配置测试 -->
  <div class="panel">
    <div class="panel-h"><h2>{{ t('nc.title') }}</h2><span class="faint small">Telegram / 飞书 / QQ / Bark / Email / Pushplus / Webhook</span><span class="sp" />
      <button class="btn sm primary" @click="save" :disabled="!cfg || saving">{{ saved ? t('common.saved') : t('nc.save') }}</button></div>
    <div class="panel-b" v-if="cfg">
      <p class="faint small hint">{{ t('nc.hint') }}</p>
      <div class="tiles" role="tablist">
        <button v-for="k in types" :key="k" type="button" role="tab" class="tile" :class="{ on: cur === k }" :aria-selected="cur === k" @click="cur = k">
          <span class="tile-n">{{ t('nc.types.' + k) }}</span><i class="st" :class="{ ok: cfg[k].enabled, bad: last[k] && !last[k].ok }" /></button>
      </div>

      <div class="pane" role="tabpanel">
        <div class="pane-h">
          <h3>{{ t('nc.enable.' + cur) }}</h3><span class="sp" />
          <button class="btn sm" @click="test" :disabled="testing">{{ testing ? t('nc.testing') : t('nc.test') }}</button>
          <label class="sw" :title="t('nc.enable.' + cur)"><input type="checkbox" v-model="c.enabled" :aria-label="t('nc.enable.' + cur)" /><span /></label>
        </div>

        <!-- Telegram -->
        <template v-if="cur === 'telegram'">
          <div class="f"><label for="nc-tok">BOT TOKEN</label><input id="nc-tok" class="input addr" v-model="c.bot_token" placeholder="123456:ABC-..." /></div>
          <div class="two">
            <div class="f"><label for="nc-chat">CHAT ID</label><input id="nc-chat" class="input" v-model="c.chat_id" :placeholder="t('nc.ph.chatId')" /></div>
            <div class="f"><label for="nc-admin">ADMIN ID</label><input id="nc-admin" class="input" v-model="c.admin_id" /></div>
          </div>
          <div class="f"><label for="nc-api">{{ t('nc.f.tgApiBase') }}</label><input id="nc-api" class="input addr" v-model="c.api_base" placeholder="api.telegram.org" /></div>
          <div class="f"><label for="nc-proxy">{{ t('nc.f.httpProxy') }}</label><input id="nc-proxy" class="input addr" v-model="c.proxy" placeholder="http://127.0.0.1:7890" /></div>
          <div class="row">
            <button class="btn sm" type="button" @click="tgAction('me')">{{ t('nc.checkBot') }}</button>
            <button class="btn sm" type="button" @click="tgAction('updates')">{{ t('nc.getUpdates') }}</button>
          </div>
        </template>

        <!-- 飞书 -->
        <template v-else-if="cur === 'feishu'">
          <div class="two">
            <div class="f"><label for="nc-fid">APP ID</label><input id="nc-fid" class="input" v-model="c.app_id" placeholder="cli_xxxx" /></div>
            <div class="f"><label for="nc-fsec">APP SECRET</label><input id="nc-fsec" class="input" type="password" v-model="c.app_secret" autocomplete="new-password" /></div>
          </div>
          <div class="f"><label for="nc-fchat">CHAT IDS</label><input id="nc-fchat" class="input addr" v-model="c.chat_ids" :placeholder="t('nc.ph.feishuChats')" />
            <small class="faint">{{ t('nc.h.feishu') }}</small></div>
        </template>

        <!-- QQ -->
        <template v-else-if="cur === 'qq'">
          <div class="two">
            <div class="f"><label for="nc-qid">APP ID</label><input id="nc-qid" class="input" v-model="c.app_id" placeholder="QQ Bot App ID" /></div>
            <div class="f"><label for="nc-qsec">APP SECRET</label><input id="nc-qsec" class="input" type="password" v-model="c.app_secret" autocomplete="new-password" /></div>
          </div>
          <div class="two">
            <div class="f"><label for="nc-qg">{{ t('nc.f.qqGroups') }}</label><input id="nc-qg" class="input" v-model="c.group_ids" :placeholder="t('nc.ph.qqGroups')" /></div>
            <div class="f"><label for="nc-qu">{{ t('nc.f.qqUsers') }}</label><input id="nc-qu" class="input" v-model="c.user_ids" :placeholder="t('nc.ph.qqUsers')" /></div>
          </div>
          <small class="faint">{{ t('nc.h.qq') }}</small>
        </template>

        <!-- Bark -->
        <template v-else-if="cur === 'bark'">
          <div class="f">
            <div class="f-h"><label>{{ t('nc.f.targetUrls') }}</label><button class="btn sm" type="button" @click="c.urls.push('')">+ URL</button></div>
            <div v-if="!c.urls.length" class="dash small faint">{{ t('nc.noBarkUrl') }}</div>
            <div v-for="(u, i) in c.urls" :key="i" class="row">
              <input class="input addr grow" v-model="c.urls[i]" :placeholder="t('nc.ph.bark')" :aria-label="t('nc.f.targetUrls')" />
              <button class="btn sm ghost" type="button" @click="c.urls.splice(i, 1)" :aria-label="t('common.delete')"><Icon name="close" :size="14" /></button>
            </div>
          </div>
          <div class="two">
            <div class="f"><label for="nc-group">{{ t('nc.f.barkGroup') }}</label><input id="nc-group" class="input" v-model="c.group" placeholder="ROS-DPI" /></div>
            <div class="f"><label for="nc-level">{{ t('nc.f.barkLevel') }}</label>
              <select id="nc-level" class="input" v-model="c.level"><option v-for="l in ['active', 'timeSensitive', 'passive', 'critical']" :key="l" :value="l">{{ l }}</option></select></div>
          </div>
          <div class="f"><label for="nc-icon">ICON</label><input id="nc-icon" class="input addr" v-model="c.icon" :placeholder="t('nc.ph.icon')" /></div>
        </template>

        <!-- Email -->
        <template v-else-if="cur === 'email'">
          <div class="three">
            <div class="f"><label for="nc-host">SMTP {{ t('nc.f.host') }}</label><input id="nc-host" class="input addr" v-model="c.host" placeholder="smtp.example.com" /></div>
            <div class="f"><label for="nc-port">SMTP {{ t('nc.f.port') }}</label><input id="nc-port" class="input" type="number" v-model.number="c.port" /></div>
            <div class="f"><label>SSL/TLS</label><label class="sw"><input type="checkbox" v-model="c.ssl" aria-label="SSL/TLS" /><span /></label></div>
          </div>
          <div class="two">
            <div class="f"><label for="nc-user">{{ t('nc.f.username') }}</label><input id="nc-user" class="input" v-model="c.username" :placeholder="t('nc.ph.mailUser')" autocomplete="off" /></div>
            <div class="f"><label for="nc-pw">{{ t('nc.f.password') }}</label><input id="nc-pw" class="input" type="password" v-model="c.password" :placeholder="t('nc.ph.mailPw')" autocomplete="new-password" /></div>
          </div>
          <div class="f"><label for="nc-from">{{ t('nc.f.from') }}</label><input id="nc-from" class="input" v-model="c.from" placeholder="noreply@example.com" /></div>
          <div class="f"><label for="nc-to">{{ t('nc.f.to') }}</label><input id="nc-to" class="input" v-model="c.to" :placeholder="t('nc.ph.mailTo')" /></div>
        </template>

        <!-- Pushplus -->
        <template v-else-if="cur === 'pushplus'">
          <div class="f"><label for="nc-pt">TOKEN</label><input id="nc-pt" class="input addr" v-model="c.token" :placeholder="t('nc.ph.ppToken')" /></div>
          <div class="two">
            <div class="f"><label for="nc-topic">{{ t('nc.f.ppTopic') }}</label><input id="nc-topic" class="input" v-model="c.topic" :placeholder="t('nc.ph.ppTopic')" /></div>
            <div class="f"><label for="nc-ppc">{{ t('nc.f.ppChannel') }}</label>
              <select id="nc-ppc" class="input" v-model="c.channel">
                <option value="wechat">{{ t('nc.pp.wechat') }}</option><option value="mail">{{ t('nc.pp.mail') }}</option>
                <option value="webhook">Webhook</option><option value="cp">{{ t('nc.pp.cp') }}</option>
              </select></div>
          </div>
        </template>

        <!-- Server酱 -->
        <template v-else-if="cur === 'serverchan'">
          <div class="f"><label for="nc-sk">SENDKEY</label><input id="nc-sk" class="input addr" v-model="c.sendkey" placeholder="SCT... / SendKey" />
            <small class="faint">{{ t('nc.h.serverchan') }}</small></div>
        </template>

        <!-- 企业微信：群机器人 / 自建应用 -->
        <template v-else-if="cur === 'wecom'">
          <div class="f">
            <label>{{ t('nc.wc.mode') }}</label>
            <div class="seg wide">
              <button type="button" :class="{ on: c.mode !== 'app' }" @click="c.mode = 'webhook'">{{ t('nc.wc.robot') }}</button>
              <button type="button" :class="{ on: c.mode === 'app' }" @click="c.mode = 'app'">{{ t('nc.wc.app') }}</button>
            </div>
            <small class="faint">{{ c.mode === 'app' ? t('nc.wc.appTip') : t('nc.wc.robotTip') }}</small>
          </div>
          <template v-if="c.mode !== 'app'">
            <div class="f"><label for="nc-wurl">{{ t('nc.f.robotUrl') }}</label>
              <input id="nc-wurl" class="input addr" v-model="c.url" placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..." />
              <small class="faint">{{ t('nc.h.wecom') }}</small></div>
          </template>
          <template v-else>
            <div class="f"><label for="nc-corp">{{ t('nc.wc.corpId') }}</label><input id="nc-corp" class="input" v-model="c.corp_id" placeholder="ww1234567890abcdef" />
              <small class="faint">{{ t('nc.wc.corpIdHint') }}</small></div>
            <div class="two">
              <div class="f"><label for="nc-agent">{{ t('nc.wc.agentId') }}</label><input id="nc-agent" class="input" v-model="c.agent_id" placeholder="1000002" /></div>
              <div class="f"><label for="nc-wsecret">{{ t('nc.wc.secret') }}</label><input id="nc-wsecret" class="input" type="password" v-model="c.secret" :placeholder="t('nc.wc.secret')" autocomplete="new-password" /></div>
            </div>
            <small class="faint pull-up">{{ t('nc.wc.agentHint') }}</small>
            <div class="f"><label for="nc-wproxy">{{ t('nc.wc.proxy') }}</label><input id="nc-wproxy" class="input addr" v-model="c.proxy_base" :placeholder="t('nc.ph.wcProxy')" />
              <small class="faint">{{ t('nc.wc.proxyHint') }}</small></div>
            <div class="three e">
              <div class="f"><label for="nc-tu">{{ t('nc.wc.toUser') }}</label><input id="nc-tu" class="input" v-model="c.to_user" :placeholder="t('nc.ph.toUser')" /></div>
              <div class="f"><label for="nc-tp">{{ t('nc.wc.toParty') }}</label><input id="nc-tp" class="input" v-model="c.to_party" :placeholder="t('nc.ph.toParty')" /></div>
              <div class="f"><label for="nc-tt">{{ t('nc.wc.toTag') }}</label><input id="nc-tt" class="input" v-model="c.to_tag" :placeholder="t('nc.ph.toTag')" /></div>
            </div>
          </template>
          <div class="two">
            <div class="f"><label for="nc-mt">{{ t('nc.wc.msgType') }}</label>
              <select id="nc-mt" class="input" v-model="c.msg_type">
                <option value="text">{{ t('nc.wc.msgText') }}</option>
                <option value="markdown">{{ t('nc.wc.msgMd') }}</option>
                <option value="textcard">{{ t('nc.wc.msgCard') }}</option>
              </select></div>
            <div class="f" v-if="c.msg_type === 'textcard'"><label for="nc-card">{{ t('nc.wc.cardUrl') }}</label>
              <input id="nc-card" class="input addr" v-model="c.card_url" :placeholder="t('nc.ph.cardUrl')" /></div>
          </div>
          <div class="row" v-if="c.mode === 'app'">
            <button class="btn sm" type="button" :disabled="checking" @click="wecomCheck">{{ t('nc.wc.check') }}</button>
          </div>

          <!-- 配置说明 -->
          <div class="help" :class="{ open: wecomHelp }">
            <button type="button" class="help-h" :aria-expanded="wecomHelp" @click="wecomHelp = !wecomHelp">
              <span>{{ t('nc.wc.guide') }}</span><Icon name="chevron" :size="14" class="chev" />
            </button>
            <div v-show="wecomHelp" class="help-b">
              <!-- 说明文案含 <b> 标记，来自 i18n 静态词条（非用户输入），故用 v-html 渲染 -->
              <ol><li v-for="(s, i) in wecomSteps" :key="i" v-html="s" /></ol>
              <template v-if="c.mode === 'app'">
                <p class="warn">{{ t('nc.wc.ipWarn') }}</p>
                <details>
                  <summary>{{ t('nc.wc.proxyExample') }}</summary>
                  <pre>{{ nginxSnippet }}</pre>
                  <p class="faint">{{ t('nc.wc.socatTip') }}</p>
                  <pre>{{ socatSnippet }}</pre>
                </details>
                <p class="faint">{{ t('nc.wc.aesTip') }}</p>
              </template>
              <p class="faint">{{ t('nc.wc.ref') }}
                <a class="link" href="https://github.com/guyue2005/CMSHelp/wiki/8.%E6%B6%88%E6%81%AF%E9%85%8D%E7%BD%AE" target="_blank" rel="noreferrer">CMSHelp Wiki · 消息配置</a></p>
            </div>
          </div>
        </template>

        <!-- 钉钉 -->
        <template v-else-if="cur === 'dingtalk'">
          <div class="f"><label for="nc-durl">{{ t('nc.f.robotUrl') }}</label><input id="nc-durl" class="input addr" v-model="c.url" placeholder="https://oapi.dingtalk.com/robot/send?access_token=..." /></div>
          <div class="f"><label for="nc-dsec">{{ t('nc.f.signSecret') }}</label><input id="nc-dsec" class="input addr" v-model="c.secret" :placeholder="t('nc.ph.dingSecret')" />
            <small class="faint">{{ t('nc.h.dingtalk') }}</small></div>
        </template>

        <!-- Discord / Slack -->
        <template v-else-if="cur === 'discord' || cur === 'slack'">
          <div class="f"><label for="nc-hook">Webhook URL</label>
            <input id="nc-hook" class="input addr" v-model="c.url" :placeholder="cur === 'discord' ? 'https://discord.com/api/webhooks/...' : 'https://hooks.slack.com/services/...'" />
            <small class="faint">{{ t('nc.h.' + cur) }}</small></div>
        </template>

        <!-- ntfy -->
        <template v-else-if="cur === 'ntfy'">
          <div class="two">
            <div class="f"><label for="nc-ns">{{ t('nc.f.server') }}</label><input id="nc-ns" class="input addr" v-model="c.server" placeholder="https://ntfy.sh" /></div>
            <div class="f"><label for="nc-nt">Topic</label><input id="nc-nt" class="input" v-model="c.topic" placeholder="your-topic" /></div>
          </div>
          <div class="f"><label for="nc-nk">{{ t('nc.f.tokenOptional') }}</label><input id="nc-nk" class="input addr" v-model="c.token" :placeholder="t('nc.ph.ntfyToken')" />
            <small class="faint">{{ t('nc.h.ntfy') }}</small></div>
        </template>

        <!-- Gotify -->
        <template v-else-if="cur === 'gotify'">
          <div class="two">
            <div class="f"><label for="nc-gs">{{ t('nc.f.server') }}</label><input id="nc-gs" class="input addr" v-model="c.server" placeholder="https://gotify.example.com" /></div>
            <div class="f"><label for="nc-gt">App Token</label><input id="nc-gt" class="input addr" v-model="c.token" :placeholder="t('nc.ph.gotifyToken')" /></div>
          </div>
          <div class="f narrow"><label for="nc-gp">{{ t('nc.f.priority') }}</label><input id="nc-gp" class="input" type="number" v-model.number="c.priority" /></div>
        </template>

        <!-- Webhook -->
        <template v-else-if="cur === 'webhook'">
          <div class="f">
            <div class="f-h"><label>{{ t('nc.f.targetUrls') }}</label><button class="btn sm" type="button" @click="c.urls.push('')">+ URL</button></div>
            <div v-if="!c.urls.length" class="dash small faint">{{ t('nc.noWebhookUrl') }}</div>
            <div v-for="(u, i) in c.urls" :key="i" class="row">
              <input class="input addr grow" v-model="c.urls[i]" placeholder="https://example.com/hook" :aria-label="t('nc.f.targetUrls')" />
              <button class="btn sm ghost" type="button" @click="c.urls.splice(i, 1)" :aria-label="t('common.delete')"><Icon name="close" :size="14" /></button>
            </div>
          </div>
          <div class="f"><label for="nc-wsec">{{ t('nc.f.whSecret') }}</label><input id="nc-wsec" class="input addr" v-model="c.secret" :placeholder="t('nc.ph.whSecret')" />
            <small class="faint">{{ t('nc.h.whSecret') }}</small></div>
          <div class="f">
            <div class="f-h"><label>{{ t('nc.f.whHeaders') }}</label><button class="btn sm" type="button" @click="c.headers.push({ key: '', value: '' })">+ Header</button></div>
            <div v-for="(h, i) in c.headers" :key="i" class="row">
              <input class="input" v-model="h.key" placeholder="Authorization" aria-label="Header" />
              <input class="input grow" v-model="h.value" :placeholder="t('nc.ph.value')" aria-label="Value" />
              <button class="btn sm ghost" type="button" @click="c.headers.splice(i, 1)" :aria-label="t('common.delete')"><Icon name="close" :size="14" /></button>
            </div>
          </div>
          <div class="f"><label for="nc-tpl">{{ t('nc.f.whTemplate') }}</label>
            <textarea id="nc-tpl" class="input code" rows="2" v-model="c.template" :placeholder="tplPlaceholder" />
            <small class="faint">{{ t('nc.h.whTemplate') }}</small></div>
          <div class="two">
            <div class="f"><label for="nc-to-ms">{{ t('nc.f.whTimeout') }}</label><input id="nc-to-ms" class="input" type="number" v-model.number="c.timeout_ms" /></div>
            <div class="f"><label for="nc-retry">{{ t('nc.f.whRetries') }}</label><input id="nc-retry" class="input" type="number" min="0" max="10" v-model.number="c.max_retries" /></div>
          </div>
        </template>

        <div class="res small" v-if="msg" role="status" :class="msgOk ? 'okc' : 'err'">{{ msg }}</div>
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
const cur = ref('telegram')
const quiet = reactive({ from: '', to: '' })
const err = ref('')
const saved = ref(false)
const saving = ref(false)
const testing = ref(false)
const checking = ref(false)
const wecomHelp = ref(false)
const msg = ref('')
const msgOk = ref(false)
const c = computed(() => cfg.value[cur.value])
const tplPlaceholder = '{{subject}} {{text}}'
const wecomSteps = computed(() => (c.value.mode === 'app' ? [1, 2, 3, 4, 5, 6].map(i => t(`nc.wc.step${i}`)) : [1, 2, 3].map(i => t(`nc.wc.rstep${i}`))))
const nginxSnippet = `location ^~ /cgi-bin/gettoken       { proxy_pass https://qyapi.weixin.qq.com; }
location ^~ /cgi-bin/message/send   { proxy_pass https://qyapi.weixin.qq.com; }
location ^~ /cgi-bin/agent/get      { proxy_pass https://qyapi.weixin.qq.com; }`
const socatSnippet = `services:
  wxproxy:
    image: alpine/socat
    command: TCP-LISTEN:9090,fork,reuseaddr TCP:qyapi.weixin.qq.com:443
    ports: ["8543:9090"]
    restart: always`
watch(cur, () => { msg.value = '' })

function flash(good, text) {
  msgOk.value = good
  msg.value = (good ? '✓ ' : '⚠ ') + text
  setTimeout(() => (msg.value = ''), 6000)
}
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
  saving.value = true
  try {
    fill(await http.put('/audit/notify', { config: cfg.value, quiet_from: quiet.from, quiet_to: quiet.to }))
    saved.value = true
    setTimeout(() => (saved.value = false), 1500)
    emit('saved', Object.keys(cfg.value).filter(k => cfg.value[k].enabled))
  } catch (e) { err.value = e.message } finally { saving.value = false }
}
async function test() {
  msg.value = ''
  testing.value = true
  try {
    await http.post('/audit/notify/test', { channel: cur.value, config: c.value }, { timeout: 60000 })
    flash(true, t('nc.sent'))
  } catch (e) { flash(false, e.message) } finally { testing.value = false }
}
async function tgAction(kind) {
  msg.value = ''
  try {
    const r = await http.post(`/audit/notify/telegram/${kind}`, { channel: 'telegram', config: c.value })
    if (kind === 'me') return flash(true, `${t('nc.botOk')}: @${r.result && r.result.username}`)
    const ids = (r.result || []).map(u => (u.message || u.channel_post || {}).chat).filter(Boolean).map(x => x.id)
    if (!ids.length) return flash(false, t('nc.noUpdates'))
    c.value.chat_id = String(ids[ids.length - 1])
    flash(true, 'Chat IDs: ' + [...new Set(ids)].join(', '))
  } catch (e) { flash(false, e.message) }
}
async function wecomCheck() {
  msg.value = ''
  checking.value = true
  try {
    const a = (await http.post('/audit/notify/wecom/check', { channel: 'wecom', config: c.value })).agent || {}
    flash(true, `${t('nc.wc.checkOk')}「${a.name}」· AgentId ${a.agentid} · ${t('nc.wc.scope')}: ${a.users} / ${a.parties} / ${a.tags}`)
  } catch (e) { flash(false, e.message) } finally { checking.value = false }
}
onMounted(load)
</script>

<style scoped>
.hint { margin: 0 0 10px; }
.tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(124px, 1fr)); gap: 8px; }
.tile { position: relative; display: flex; align-items: center; justify-content: space-between; gap: 6px; background: var(--sunk); border: 1px solid transparent;
  border-radius: 10px; padding: 9px 12px; font: inherit; font-size: 13px; color: var(--ink); cursor: pointer; text-align: left; min-height: 40px; }
.tile.on { border-color: var(--brand-ink); background: var(--brand-weak); color: var(--brand-ink); }
.tile-n { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.st { width: 8px; height: 8px; border-radius: 50%; background: var(--line-strong); flex: none; }
.st.ok { background: var(--ok); }
.st.bad { box-shadow: 0 0 0 2px color-mix(in srgb, var(--bad) 45%, transparent); }
.pane { margin-top: 14px; border: 1px solid var(--line); border-radius: 12px; padding: 14px 16px; display: flex; flex-direction: column; gap: 12px; }
.pane-h { display: flex; align-items: center; gap: 10px; padding-bottom: 12px; border-bottom: 1px solid var(--line); flex-wrap: wrap; }
.pane-h h3 { margin: 0; font-size: 15px; }
.pane-h .sp { flex: 1; }
.f { display: flex; flex-direction: column; gap: 5px; min-width: 0; }
.f label { font-size: 13px; color: var(--muted); }
.f small, .pane > small { font-size: 12.5px; line-height: 1.55; overflow-wrap: anywhere; }
.f.narrow { max-width: 160px; }
.f-h { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.pull-up { margin-top: -6px; }
.two, .three { display: grid; gap: 12px; }
.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
.three { grid-template-columns: minmax(0, 2fr) minmax(0, 1fr) auto; align-items: end; }
.three.e { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.grow { flex: 1; min-width: 0; }
.w { width: 120px; }
.dash { border: 1px dashed var(--line-strong); border-radius: 8px; padding: 10px; text-align: center; }
.res { margin-top: 2px; overflow-wrap: anywhere; }
.okc { color: var(--ok); }
.code { font-family: var(--mono, monospace); font-size: 12px; }
.seg.wide { display: flex; width: 100%; }
.seg.wide button { flex: 1; white-space: normal; line-height: 1.3; }
.sw { position: relative; width: 38px; height: 22px; flex: none; cursor: pointer; display: inline-block; }
.sw input { opacity: 0; width: 0; height: 0; }
.sw span { position: absolute; inset: 0; background: var(--line-strong); border-radius: 11px; transition: background .15s; }
.sw span::after { content: ""; position: absolute; left: 3px; top: 3px; width: 16px; height: 16px; border-radius: 50%; background: #fff; transition: transform .15s; }
.sw input:checked + span { background: var(--ok); }
.sw input:checked + span::after { transform: translateX(16px); }
.sw input:focus-visible + span { outline: 2px solid var(--brand-ink); outline-offset: 2px; }
.help { border: 1px solid var(--line); border-radius: 10px; }
.help-h { width: 100%; display: flex; justify-content: space-between; align-items: center; gap: 8px; min-height: 40px; border: 0; background: transparent;
  padding: 0 14px; cursor: pointer; font: inherit; font-size: 13px; color: var(--muted); text-align: left; }
.help-h:hover { color: var(--ink); }
.help .chev { transition: transform .2s; }
.help.open .chev { transform: rotate(90deg); }
.help-b { padding: 2px 14px 14px; font-size: 13px; line-height: 1.75; color: var(--muted); overflow-wrap: anywhere; }
.help-b ol { margin: 0 0 10px; padding-left: 20px; }
.help-b :deep(b) { color: var(--ink); font-weight: 600; }
.help-b .warn { margin: 0 0 10px; padding: 9px 11px; border-radius: 8px; background: color-mix(in srgb, var(--warn, #d97706) 14%, transparent); color: var(--ink); }
.help-b summary { cursor: pointer; color: var(--ink); min-height: 32px; display: flex; align-items: center; }
.help-b pre { margin: 8px 0; padding: 10px 12px; border-radius: 8px; background: var(--sunk); border: 1px solid var(--line); overflow-x: auto;
  font-size: 12px; line-height: 1.6; color: var(--ink); white-space: pre; font-family: var(--mono, monospace); max-width: 100%; }
.help-b p { margin: 6px 0 0; }
.quiet { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-top: 14px; }
@media (max-width: 640px) {
  .tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .two, .three, .three.e { grid-template-columns: minmax(0, 1fr); }
  .f.narrow { max-width: none; }
}
</style>
