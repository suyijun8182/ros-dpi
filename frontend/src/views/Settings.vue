<template>
  <div>
    <div class="page-h"><h1>{{ t('settings.title') }}</h1><span class="sp" /><span class="faint" v-if="sys">{{ t('settings.version') }} {{ sys.version }}</span></div>

    <div class="panel" v-if="sys">
      <div class="panel-h">{{ t('settings.status') }}<span class="sp" /><button class="btn sm" @click="loadSys">{{ t('common.refresh') }}</button></div>
      <div class="panel-b grid g3">
        <div class="st">
          <div class="st-h"><span class="dot" :class="sys.collector.flow_ok ? 'on' : 'warn'" />{{ t('settings.collector') }}
            <span class="faint">udp/{{ s?.ports.ipfix }}</span></div>
          <div class="kv"><span>{{ t('settings.flows') }}</span><b class="num">{{ sys.collector.flows.toLocaleString() }}</b></div>
          <div class="kv"><span>{{ t('settings.dropped') }}</span><span class="num">{{ sys.collector.flows_dropped.toLocaleString() }}</span></div>
          <div class="kv"><span>{{ t('settings.exporters') }}</span><span class="num">{{ Object.keys(sys.collector.exporters).join(', ') || '-' }}</span></div>
          <div class="kv"><span>{{ t('settings.last') }}</span><span>{{ ago(sys.collector.last_flow) }}</span></div>
        </div>
        <div class="st">
          <div class="st-h"><span class="dot" :class="sys.dns.ok ? 'on' : 'warn'" />{{ t('settings.dns') }}
            <span class="faint">udp/{{ s?.ports.tzsp }}</span></div>
          <div class="kv"><span>{{ t('settings.dnsAnswers') }}</span><b class="num">{{ sys.dns.answers.toLocaleString() }}</b></div>
          <div class="kv"><span>{{ t('settings.dnsEntries') }}</span><span class="num">{{ sys.dns.entries.toLocaleString() }}</span></div>
          <div class="kv"><span>{{ t('settings.last') }}</span><span>{{ ago(sys.dns.last) }}</span></div>
          <div class="kv" v-if="sys.dns.servers && sys.dns.servers.length"><span>{{ t('settings.dnsServers') }}</span>
            <span class="srv"><span v-for="x in sys.dns.servers.slice(0, 4)" :key="x.ip" class="num">{{ x.ip }} <span class="faint">{{ x.lan ? t('settings.dnsLan') : t('settings.dnsUpstream') }} · {{ x.answers.toLocaleString() }}</span></span></span></div>
          <p class="faint small what">{{ t('settings.dnsWhat') }}</p>
        </div>
        <div class="st">
          <div class="st-h"><span class="dot" :class="!sys.router.enabled ? '' : sys.router.ok ? 'on' : 'bad'" />{{ t('settings.ros') }}
            <button v-if="sys.router.enabled" class="btn sm" @click="testRos">{{ t('settings.test') }}</button></div>
          <template v-if="sys.router.enabled">
            <div class="kv"><span>URL</span><span class="num">{{ s?.ros_url }}</span></div>
            <div class="kv"><span>{{ t('login.username') }}</span><span>{{ s?.ros_user }}</span></div>
            <div class="kv" v-if="sys.router.identity"><span>Identity</span><span>{{ sys.router.identity }} · {{ sys.router.version }}</span></div>
            <div class="kv"><span>{{ t('settings.last') }}</span><span>{{ ago(sys.router.last_poll) }}</span></div>
            <div class="err" v-if="sys.router.error">{{ sys.router.error }}</div>
          </template>
          <div v-else class="muted small">{{ t('settings.rosHint') }}</div>
        </div>
      </div>
    </div>

    <div class="grid g2 mt" v-if="s">
      <div class="panel">
        <div class="panel-h">{{ t('settings.network') }}</div>
        <div class="panel-b form">
          <label>{{ t('settings.lan') }}</label>
          <textarea class="input" rows="5" v-model="lan" />
          <div class="faint small">{{ t('settings.lanHint') }}</div>
          <div v-if="s.lan_auto.length" class="small"><span class="muted">{{ t('settings.lanAuto') }}：</span>
            <span class="num faint">{{ s.lan_auto.join(', ') }}</span></div>
          <label>{{ t('settings.wan') }}</label>
          <select class="input" v-model="wan">
            <option value="">{{ t('settings.wanAuto') }}</option>
            <option v-for="i in s.interfaces" :key="i" :value="i">{{ i }}</option>
            <option v-if="wan && !s.interfaces.includes(wan)" :value="wan">{{ wan }}</option>
          </select>
          <div class="faint small">{{ t('settings.wanHint') }} <span v-if="s.wan_detected">{{ t('settings.wanDetected', { name: s.wan_detected }) }}</span></div>
          <div class="err" v-if="saveErr">{{ saveErr }}</div>
          <div><button class="btn primary" @click="save">{{ saved ? t('common.saved') : t('common.save') }}</button></div>
          <div class="faint small">{{ t('settings.retention') }}：{{ t('settings.retentionText', s.retention) }}</div>
          <div class="faint small" v-if="s.database">{{ t('settings.dbInfo', { db: `${s.database.user}@${s.database.host || ''}${s.database.port ? ':' + s.database.port : ''}/${s.database.database}` }) }}（{{ s.database.source === 'env' ? t('settings.dbFromEnv') : t('settings.dbFromWizard') }}）</div>
        </div>
      </div>

      <div class="panel">
        <div class="panel-h">{{ t('settings.password') }}</div>
        <form class="panel-b form" @submit.prevent="changePw">
          <input type="text" autocomplete="username" :value="auth.username" hidden />
          <input class="input" type="password" v-model="pw.old" :placeholder="t('settings.oldPw')" autocomplete="current-password" />
          <input class="input" type="password" v-model="pw.new" :placeholder="t('settings.newPw')" autocomplete="new-password" />
          <div class="err" v-if="pwErr">{{ pwErr }}</div>
          <div><button class="btn" :disabled="!pw.old || pw.new.length < 6">{{ pwOk ? t('common.saved') : t('common.save') }}</button></div>
        </form>
      </div>
    </div>

    <div class="panel mt" id="guide">
      <div class="panel-h">{{ t('settings.guide') }}<span class="sp" /><button class="btn sm" @click="copy">{{ copied ? t('settings.copied') : t('settings.copy') }}</button></div>
      <div class="panel-b">
        <p class="muted guide">{{ t('settings.guideIntro', { ip: '<HOST_IP>' }) }}</p>
        <div class="ipin"><span class="muted small">HOST_IP</span><input class="input num" v-model="hostIp" /></div>
        <pre class="code">{{ guide }}</pre>
        <p class="faint small">{{ t('settings.guideNote') }}</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import http, { auth } from '../api.js'
import { ago } from '../format.js'

const { t } = useI18n()
const s = ref(null)
const sys = ref(null)
const lan = ref('')
const wan = ref('')
const saved = ref(false)
const saveErr = ref('')
const pw = reactive({ old: '', new: '' })
const pwErr = ref('')
const pwOk = ref(false)
const copied = ref(false)
const hostIp = ref(location.hostname)

async function loadSys() { sys.value = await http.get('/system') }
onMounted(async () => {
  s.value = await http.get('/settings')
  lan.value = s.value.lan_cidrs.split(',').join('\n')
  wan.value = s.value.wan_interface
  loadSys()
})

async function save() {
  saveErr.value = ''
  try {
    s.value = await http.put('/settings', { lan_cidrs: lan.value, wan_interface: wan.value })
    saved.value = true
    setTimeout(() => (saved.value = false), 1500)
  } catch (e) { saveErr.value = e.message }
}

async function testRos() {
  try { sys.value.router = await http.post('/ros/test') } catch (e) { sys.value.router.error = e.message }
}

async function changePw() {
  pwErr.value = ''
  try {
    await http.post('/auth/password', { old_password: pw.old, new_password: pw.new })
    pw.old = pw.new = ''
    pwOk.value = true
    setTimeout(() => (pwOk.value = false), 1500)
  } catch (e) { pwErr.value = e.message }
}

const guide = computed(() => {
  const ip = hostIp.value || '<HOST_IP>'
  const p = s.value?.ports || { ipfix: 2055, tzsp: 37008 }
  return `# 1. 流量采集（IPFIX）
/ip traffic-flow set enabled=yes interfaces=all active-flow-timeout=1m inactive-flow-timeout=15s
/ip traffic-flow target add dst-address=${ip} port=${p.ipfix} version=ipfix

# 2. DNS 嗅探（应用识别）：只镜像 DNS 应答，用来知道"远端 IP 是哪个域名"
#    output：路由器自己当 DNS 服务器时发给终端的应答
#    forward：终端直连外部 DNS 的应答；内网自建 DNS（AdGuard/Pi-hole 等）向上游查询拿到的应答也走这里
#    内网自建 DNS 的上游必须是普通 DNS（udp/53），上游用 DoH/DoT 时路由器看不到域名
/ip firewall mangle add chain=output protocol=udp src-port=53 action=sniff-tzsp sniff-target=${ip} sniff-target-port=${p.tzsp} comment=ROSDPI-DNS
/ip firewall mangle add chain=forward protocol=udp src-port=53 action=sniff-tzsp sniff-target=${ip} sniff-target-port=${p.tzsp} comment=ROSDPI-DNS

# 3. 只读 API 账号（可选，用于主机名、WAN 速率）
/user group add name=rosdpi policy=read,rest-api,api,!write,!policy,!sensitive
/user add name=rosdpi group=rosdpi password=<强密码> address=${ip}`
})

async function copy() {
  try {
    await navigator.clipboard.writeText(guide.value)
    copied.value = true
    setTimeout(() => (copied.value = false), 1500)
  } catch (e) { /* 非 https 下剪贴板不可用 */ }
}
</script>

<style scoped>
.mt { margin-top: 14px; }
.small { font-size: 12.5px; }
.st { display: flex; flex-direction: column; gap: 6px; font-size: 13px; }
.st-h { display: flex; align-items: center; gap: 8px; font-weight: 600; margin-bottom: 4px; }
.kv { display: flex; justify-content: space-between; gap: 12px; color: var(--muted); }
.kv > :last-child { color: var(--text); text-align: right; overflow: hidden; text-overflow: ellipsis; }
.srv { display: flex; flex-direction: column; align-items: flex-end; }
.what { margin: 6px 0 0; line-height: 1.5; }
.form { display: flex; flex-direction: column; gap: 8px; }
.form label { font-size: 13px; color: var(--muted); margin-top: 4px; }
.guide { margin: 0 0 10px; }
.ipin { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; max-width: 320px; }
</style>
