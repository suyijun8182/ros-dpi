<template>
  <div>
    <div class="page-h">
      <div class="seg tabs" role="tablist">
        <button v-for="k in TABS" :key="k" role="tab" :aria-selected="tab === k" :class="{ on: tab === k }" @click="setTab(k)">
          {{ t('settings.tab.' + (k === 'system' && !isAdmin ? 'account' : k)) }}<span v-if="badge[k]" class="dot bad tdot" /></button>
      </div>
      <span class="sp" /><span class="faint small" v-if="sys">{{ t('settings.version') }} {{ sys.version }}</span>
    </div>

    <div class="panel" v-if="sys && tab === 'status'">
      <div class="panel-h">{{ t('settings.status') }}<span class="sp" /><button class="btn sm" @click="loadSys">{{ t('common.refresh') }}</button></div>
      <div class="panel-b grid g3">
        <div class="stc">
          <div class="st-h"><span class="dot" :class="sys.collector.flow_ok ? 'on' : 'warn'" />{{ t('settings.collector') }}
            <span class="faint">udp/{{ s?.ports.ipfix }}</span></div>
          <div class="kv"><span>{{ t('settings.flows') }}</span><b class="num">{{ sys.collector.flows.toLocaleString() }}</b></div>
          <div class="kv"><span>{{ t('settings.dropped') }}</span><span class="num">{{ sys.collector.flows_dropped.toLocaleString() }}</span></div>
          <div class="kv"><span>{{ t('settings.exporters') }}</span><span class="num">{{ Object.keys(sys.collector.exporters).join(', ') || '-' }}</span></div>
          <div class="kv"><span>{{ t('settings.last') }}</span><span>{{ ago(sys.collector.last_flow) }}</span></div>
        </div>
        <div class="stc">
          <div class="st-h"><span class="dot" :class="sys.dns.ok || sys.sni.ok ? 'on' : 'warn'" />{{ t('settings.dns') }}
            <span class="faint">udp/{{ s?.ports.tzsp }}</span></div>
          <div class="kv"><span>{{ t('settings.dnsAnswers') }}</span><b class="num">{{ sys.dns.answers.toLocaleString() }}</b></div>
          <div class="kv"><span>{{ t('settings.dnsEntries') }}</span><span class="num">{{ sys.dns.entries.toLocaleString() }}</span></div>
          <div class="kv"><span>{{ t('settings.last') }}</span><span>{{ ago(sys.dns.last) }}</span></div>
          <div class="kv" v-if="sys.dns.servers && sys.dns.servers.length"><span>{{ t('settings.dnsServers') }}</span>
            <span class="srv"><span v-for="x in sys.dns.servers.slice(0, 4)" :key="x.ip" class="num">{{ x.ip }} <span class="faint">{{ x.lan ? t('settings.dnsLan') : t('settings.dnsUpstream') }} · {{ x.answers.toLocaleString() }}</span></span></span></div>
          <div class="kv"><span>{{ t('settings.sni') }}</span><span class="num">TLS {{ sys.sni.tls.toLocaleString() }} · QUIC {{ sys.sni.quic.toLocaleString() }}</span></div>
          <div class="kv"><span>{{ t('settings.last') }} SNI</span><span>{{ ago(sys.sni.last) }}</span></div>
          <p class="faint small what">{{ t('settings.dnsWhat') }}</p>
        </div>
        <div class="stc">
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
      <div class="panel-b match" v-if="matchTotal">
        <div class="st-h">{{ t('settings.match') }}<span class="faint small">{{ t('settings.matchHint') }}</span></div>
        <div class="mbar"><i v-for="m in matchParts" :key="m.k" :class="m.k" :style="{ flexGrow: m.v }" :title="`${t('settings.matchKind.' + m.k)} ${pct(m.v / matchTotal)}`" /></div>
        <ul class="mlg"><li v-for="m in matchParts" :key="m.k"><span class="sw" :class="m.k" />{{ t('settings.matchKind.' + m.k) }} <b class="num">{{ pct(m.v / matchTotal) }}</b></li></ul>
      </div>
    </div>

    <!-- 运行状态加载失败：给出错误和重试，而不是空白面板 -->
    <div class="panel" v-else-if="sysErr && tab === 'status'">
      <div class="panel-b"><div class="err">{{ sysErr }}</div>
        <button class="btn sm mt" @click="loadSys">{{ t('common.refresh') }}</button></div>
    </div>

    <!-- 接入自检：读取 RouterOS 的 sniff-tzsp 规则（只读），检查目标端口 / 地址、是否停用、命中数 -->
    <div class="panel" v-if="sys && sys.ros_check && tab === 'access'" id="check">
      <div class="panel-h"><h2>{{ t('check.title') }}</h2><span class="faint small">{{ t('check.hint') }}</span></div>
      <div class="panel-b">
        <div v-if="!sys.ros_check.checked" class="muted small">{{ t('check.needRos') }}</div>
        <template v-else>
          <div class="tbl-wrap">
            <table class="tbl ck">
              <thead><tr><th>{{ t('check.rule') }}</th><th>{{ t('check.use') }}</th><th>{{ t('check.target') }}</th>
                <th class="r">{{ t('check.packets') }}</th><th>{{ t('check.state') }}</th></tr></thead>
              <tbody>
                <tr v-for="r in sys.ros_check.rules" :key="r.family + r.id">
                  <td><b>{{ r.comment || r.id }}</b> <span class="faint small">{{ r.family === 'ipv6' ? 'IPv6 ' : '' }}{{ r.chain }} · {{ r.protocol }}</span></td>
                  <td>{{ t('check.kind.' + r.kind) }}</td>
                  <td class="addr">{{ r.target }}:{{ r.target_port }}</td>
                  <td class="r num">{{ r.packets.toLocaleString() }}</td>
                  <td><span v-if="!r.problems.length" class="pill ok">{{ t('check.ok') }}</span>
                    <span v-for="p in r.problems" :key="p" class="pill bad">{{ t('check.problem.' + p) }}</span></td>
                </tr>
              </tbody>
            </table>
            <div v-if="!sys.ros_check.rules.length" class="empty">{{ t('check.none') }}</div>
          </div>
          <div v-if="fixes.length || sys.ros_check.issues.length" class="fixes">
            <div class="sec">{{ t('check.fixTitle') }}<span class="sp" />
              <button v-if="fixes.length" class="btn sm" @click="copyFix">{{ fixCopied ? t('settings.copied') : t('settings.copy') }}</button></div>
            <ul class="iss">
              <li v-for="c in sys.ros_check.issues.filter(c => c !== 'rule_problem')" :key="c">{{ t('check.issue.' + c) }}</li>
            </ul>
            <pre class="code" v-if="fixes.length">{{ fixes.join('\n') }}</pre>
          </div>
        </template>
      </div>
    </div>

    <!-- 外部数据源：旁路代理 sing-box、内网 DNS MosDNS（可选，地址每个人不同，由用户填写） -->
    <div class="panel" v-if="s && tab === 'sources'" id="sources">
      <div class="panel-h"><h2>{{ t('sources.title') }}</h2><span class="faint small">{{ t('sources.hint') }}</span></div>
      <div class="panel-b src">
        <form class="src-form" @submit.prevent="saveSources">
          <div class="src-box">
            <div class="sec">sing-box / Clash API<span class="sp" />
              <span v-if="sys && sys.singbox.enabled" class="pill" :class="sys.singbox.ok ? 'ok' : 'bad'">{{ sys.singbox.ok ? t('sources.connected') : t('sources.failed') }}</span>
              <span v-else class="pill grey">{{ t('sources.off') }}</span></div>
            <p class="faint small">{{ t('sources.sbWhy') }}</p>
            <label for="sb-url">{{ t('sources.sbUrl') }}</label>
            <input id="sb-url" class="input addr" v-model.trim="src.singbox_url" placeholder="http://192.168.1.2:9090" autocomplete="off" />
            <label for="sb-secret">{{ t('sources.sbSecret') }}</label>
            <div class="row">
              <input id="sb-secret" class="input" type="password" v-model="src.singbox_secret" autocomplete="new-password"
                     :placeholder="s.integrations.has_secret ? t('sources.secretKept') : t('sources.secretNone')" />
              <button v-if="s.integrations.has_secret" type="button" class="btn sm" @click="clearSecret">{{ t('sources.clearSecret') }}</button>
            </div>
            <label for="sb-ips">{{ t('sources.proxyIps') }}</label>
            <input id="sb-ips" class="input addr" v-model.trim="src.proxy_ips" :placeholder="s.integrations.proxy_auto ? t('sources.proxyAuto', { ip: s.integrations.proxy_auto }) : '192.168.1.2'" />
            <div class="faint small">{{ t('sources.proxyIpsHint') }}</div>
            <div v-if="sys && sys.singbox.enabled" class="st small">
              <span>{{ t('settings.last') }} {{ ago(sys.singbox.last) }}</span>
              <span v-if="sys.singbox.version">{{ sys.singbox.version }}</span>
              <span>{{ t('sources.conns', { n: sys.singbox.conns }) }}</span>
              <span>{{ t('sources.counted', { b: bytes(sys.singbox.bytes) }) }}</span>
              <span class="err" v-if="sys.singbox.error">{{ sys.singbox.error }}</span>
            </div>
          </div>
          <div class="src-box">
            <div class="sec">MosDNS<span class="sp" />
              <span v-if="sys && sys.mosdns.enabled" class="pill" :class="sys.mosdns.ok ? 'ok' : 'bad'">{{ sys.mosdns.ok ? t('sources.connected') : t('sources.failed') }}</span>
              <span v-else class="pill grey">{{ t('sources.off') }}</span></div>
            <p class="faint small">{{ t('sources.mdWhy') }}</p>
            <label for="md-url">{{ t('sources.mdUrl') }}</label>
            <input id="md-url" class="input addr" v-model.trim="src.mosdns_url" placeholder="http://192.168.1.3:9099" autocomplete="off" />
            <div v-if="sys && sys.mosdns.enabled" class="st small">
              <span>{{ t('settings.last') }} {{ ago(sys.mosdns.last) }}</span>
              <span>{{ t('sources.answers', { n: sys.mosdns.answers.toLocaleString() }) }}</span>
              <span class="err" v-if="sys.mosdns.error">{{ sys.mosdns.error }}</span>
            </div>
            <div class="sec asn">{{ t('sources.asn') }}<span class="sp" />
              <span class="pill" :class="sys && sys.asn.rows ? 'ok' : 'grey'">{{ sys && sys.asn.rows ? t('sources.asnOn') : t('sources.off') }}</span></div>
            <p class="faint small">{{ t('sources.asnWhy') }}
              <span v-if="sys && sys.asn.rows"> {{ t('sources.asnRows', { n: sys.asn.rows.toLocaleString(), d: datetime(sys.asn.updated) }) }}</span>
              <span v-else-if="sys && sys.asn.error" class="err"> {{ sys.asn.error }}</span></p>
          </div>
          <div class="src-box">
            <div class="sec">AdGuard Home<span class="sp" />
              <span v-if="sys && sys.adguard && sys.adguard.enabled" class="pill" :class="sys.adguard.ok ? 'ok' : 'bad'">{{ sys.adguard.ok ? t('sources.connected') : t('sources.failed') }}</span>
              <span v-else class="pill grey">{{ t('sources.off') }}</span></div>
            <p class="faint small">{{ t('sources.agWhy') }}</p>
            <label for="ag-url">{{ t('sources.agUrl') }}</label>
            <input id="ag-url" class="input addr" v-model.trim="src.adguard_url" placeholder="http://192.168.9.2:3000" autocomplete="off" />
            <label for="ag-user">{{ t('sources.agUser') }}</label>
            <input id="ag-user" class="input" v-model.trim="src.adguard_username" autocomplete="off" />
            <label for="ag-password">{{ t('sources.agPassword') }}</label>
            <div class="row">
              <input id="ag-password" class="input" type="password" v-model="src.adguard_password" autocomplete="new-password"
                     :placeholder="s.integrations.has_adguard_password ? t('sources.agKept') : t('sources.agNone')" />
              <button v-if="s.integrations.has_adguard_password" type="button" class="btn sm" @click="clearAdguardPassword">{{ t('sources.agClear') }}</button>
            </div>
            <div class="faint small">{{ t('sources.agHint') }}</div>
            <div v-if="sys && sys.adguard && sys.adguard.enabled" class="st small">
              <span>{{ t('settings.last') }} {{ ago(sys.adguard.last) }}</span>
              <span>{{ t('sources.answers', { n: sys.adguard.answers.toLocaleString() }) }}</span>
              <span class="err" v-if="sys.adguard.error">{{ sys.adguard.error }}</span>
            </div>
          </div>
          <div class="src-box">
            <div class="sec">{{ t('sources.shareTitle') }}<span class="sp" />
              <span v-if="s.share_hub" class="pill ok">{{ t('sources.shareHubOn') }}</span>
              <span v-if="!s.share_enabled" class="pill grey">{{ t('sources.off') }}</span>
              <template v-else-if="!src.share_url"><span class="pill grey">{{ t('sources.shareNoUrl') }}</span></template>
              <template v-else>
                <span v-if="deploys && deploys.sync && deploys.sync.ts" class="pill" :class="deploys.sync.ok ? 'ok' : 'bad'">
                  {{ deploys.sync.ok ? t('sources.connected') : t('sources.failed') }}</span>
                <span v-else class="pill grey">{{ t('sources.shareWait') }}</span>
              </template>
              <span v-if="s.share_hub" class="pill ok">{{ t('sources.shareHubOn') }}</span></div>
            <p class="faint small">{{ t('sources.shareWhy') }}</p>
            <label class="chk" style="display:flex;gap:6px;align-items:center;cursor:pointer">
              <input type="checkbox" :checked="s.share_enabled" @change="src.share_enabled = $event.target.checked" /> {{ t('sources.shareEnabled') }}
            </label>
            <label for="share-url">{{ t('sources.shareUrl') }}</label>
            <input id="share-url" class="input addr" v-model.trim="src.share_url" placeholder="https://share.example.com" autocomplete="off" />
            <label class="chk" style="display:flex;gap:6px;align-items:center;cursor:pointer;margin-top:8px">
              <input id="share-hub" type="checkbox" :checked="s.share_hub" @change="src.share_hub = $event.target.checked" /> {{ t('sources.shareHub') }}
            </label>
            <div class="faint small">{{ t('sources.shareHint') }}</div>
            <div class="small" style="margin-top:8px" v-if="deploys && deploys.sync && deploys.sync.ts">
              <b>{{ t('sources.communitySize') }}</b>：{{ t('sources.communityDetail', { ip: (deploys.sync.community_ips || 0).toLocaleString(), dom: (deploys.sync.community_domains || 0).toLocaleString() }) }}
              <span class="faint small">（{{ t('settings.last') }} {{ ago(deploys.sync.ts) }}）</span>
            </div>
            <div class="small" style="margin-top:8px" v-if="deploys && (s.share_hub || deploys.total)">
              <b>{{ t('sources.deploys') }}</b>：{{ t('sources.deployed', { n: deploys.total }) }} ·
              <span style="color:var(--up)">{{ t('sources.online', { n: deploys.online }) }}</span> ·
              {{ t('sources.offline', { n: deploys.offline }) }}
              <span class="faint small">（{{ t('sources.deployHint') }}）</span>
              <div v-if="(deploys.relays || []).length" class="faint small" style="margin-top:4px">
                {{ t('sources.relaysLabel') }}：
                <a v-for="r in deploys.relays" :key="r" href="javascript:void(0)" class="link"
                   style="margin-right:8px" @click="src.share_url = r">{{ r }}</a>
              </div>
            </div>
          </div>
          <div class="acts">
            <span class="err" v-if="srcErr">{{ srcErr }}</span><span class="sp" />
            <button type="button" class="btn" @click="testSources" :disabled="testing">{{ testing ? t('setup.testing') : t('settings.test') }}</button>
            <button class="btn primary">{{ srcSaved ? t('common.saved') : t('common.save') }}</button>
          </div>
        </form>
      </div>
    </div>

    <UsersPanel v-if="tab === 'users'" />
    <CompliancePanel v-if="tab === 'compliance'" />

    <ScenePicker v-if="isAdmin && tab === 'system'" class="scene-pick" />
    <div class="panel" v-if="isAdmin && tab === 'system'" id="update">
      <div class="panel-h"><h2>{{ t('upd.title') }}</h2>
        <span class="pill" :class="upd && upd.available ? 'ok' : 'grey'">
          {{ upd ? (upd.available ? t('upd.available', { v: upd.latest }) : t('upd.uptodate')) : '…' }}</span></div>
      <div class="panel-b form">
        <div class="small muted">{{ t('upd.current', { v: upd ? upd.current : '-' }) }}<span v-if="upd && !upd.supported"> · {{ t('upd.docker') }}</span></div>
        <div class="acts">
          <span class="err" v-if="updErr">{{ updErr }}</span><span class="muted small" v-if="updMsg">{{ updMsg }}</span><span class="sp" />
          <button class="btn primary" :disabled="!upd || !upd.available || !upd.supported || updating" @click="doUpdate">
            {{ updating ? t('upd.running') : t('upd.btn') }}</button>
        </div>
      </div>
    </div>
    <div class="grid g2 sys" v-if="tab === 'system'">
      <div class="panel" v-if="s">
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

    <div class="panel mt" id="guide" v-if="tab === 'access'">
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
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import http, { auth, isAdmin } from '../api.js'
import UsersPanel from '../components/UsersPanel.vue'
import ScenePicker from '../components/ScenePicker.vue'
import CompliancePanel from '../components/CompliancePanel.vue'
import { ago, bytes, datetime, pct } from '../format.js'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const s = ref(null)
const sys = ref(null)
const sysErr = ref('')
const lan = ref('')
const wan = ref('')
const saved = ref(false)
const saveErr = ref('')
const pw = reactive({ old: '', new: '' })
const pwErr = ref('')
const pwOk = ref(false)
const copied = ref(false)
const hostIp = ref(location.hostname)

// 子标签写在地址栏 ?tab=；旧链接 /settings#guide 打开“接入与自检”
const TABS = computed(() => (isAdmin.value ? ['status', 'access', 'sources', 'system', 'compliance', 'users'] : ['status', 'system']))
const tab = computed(() => {
  const k = TABS.value.includes(route.query.tab) ? route.query.tab
    : route.hash === '#guide' || route.hash === '#check' ? 'access' : route.hash === '#sources' ? 'sources' : 'status'
  return TABS.value.includes(k) ? k : 'status'
})
const setTab = k => router.replace({ query: k === 'status' ? {} : { tab: k } })
// 有问题的标签页上标一个红点
const badge = computed(() => ({
  access: !!(sys.value && sys.value.ros_check && sys.value.ros_check.checked && sys.value.ros_check.rules.some(r => r.problems.length)),
  sources: !!(sys.value && ((sys.value.singbox.enabled && !sys.value.singbox.ok) || (sys.value.mosdns.enabled && !sys.value.mosdns.ok) || (sys.value.adguard && sys.value.adguard.enabled && !sys.value.adguard.ok))),
}))

async function loadSys() {
  sysErr.value = ''
  try {
    sys.value = await http.get('/system')
    // 接入向导的 HOST_IP：优先用 RouterOS 上已经在正常工作的 DNS 镜像规则的目标地址
    const tgt = sys.value.ros_check && sys.value.ros_check.target
    if (tgt && hostIp.value === location.hostname) hostIp.value = tgt
  } catch (e) { sysErr.value = e.message }
}
const matchParts = computed(() => (sys.value ? ['proxy', 'conn', 'pair', 'ip', 'none'].map(k => ({ k, v: sys.value.match[k] || 0 })) : []))
const matchTotal = computed(() => matchParts.value.reduce((n, m) => n + m.v, 0))
onMounted(async () => {
  loadSys()
  if (!isAdmin.value) return  // 普通用户看不到系统配置
  s.value = await http.get('/settings')
  lan.value = s.value.lan_cidrs.split(',').join('\n')
  wan.value = s.value.wan_interface
  fillSources()
})

// ---------- 外部数据源 ----------
const src = reactive({ singbox_url: '', singbox_secret: '', proxy_ips: '', mosdns_url: '', adguard_url: '', adguard_username: '', adguard_password: '', share_url: '', share_enabled: true, share_hub: false })
const deploys = ref(null)
const srcErr = ref('')
const srcSaved = ref(false)
const testing = ref(false)
function fillSources() {
  const i = s.value.integrations
  Object.assign(src, { singbox_url: i.singbox_url, singbox_secret: '', proxy_ips: i.proxy_ips, mosdns_url: i.mosdns_url,
                       adguard_url: i.adguard_url, adguard_username: i.adguard_username, adguard_password: '',
                       share_url: i.share_url, share_enabled: !!s.value.share_enabled, share_hub: !!s.value.share_hub })
}
async function saveSources() {
  srcErr.value = ''
  try {
    // 密钥留空表示不修改；要清除用“清除密钥/密码”按钮
    const body = { singbox_url: src.singbox_url, proxy_ips: src.proxy_ips, mosdns_url: src.mosdns_url,
                   adguard_url: src.adguard_url, adguard_username: src.adguard_username,
                   share_url: src.share_url, share_enabled: !!src.share_enabled, share_hub: !!src.share_hub }
    if (src.singbox_secret) body.singbox_secret = src.singbox_secret
    if (src.adguard_password) body.adguard_password = src.adguard_password
    s.value = await http.put('/settings', body)
    fillSources()
    srcSaved.value = true
    setTimeout(() => (srcSaved.value = false), 1500)
    await testSources()
  } catch (e) { srcErr.value = e.message }
}
async function clearSecret() {
  try { s.value = await http.put('/settings', { singbox_secret: '' }); fillSources() } catch (e) { srcErr.value = e.message }
}
async function clearAdguardPassword() {
  try { s.value = await http.put('/settings', { adguard_password: '' }); fillSources() } catch (e) { srcErr.value = e.message }
}
async function testSources() {
  testing.value = true
  try {
    const r = await http.post('/integrations/test')
    if (sys.value) Object.assign(sys.value, r)
  } catch (e) { srcErr.value = e.message } finally { testing.value = false }
}

watch(() => route.query.tab, v => { if (v === 'system' && isAdmin) { loadUpdate(); loadDeploys() } }, { immediate: true })

async function save() {
  saveErr.value = ''
  try {
    s.value = await http.put('/settings', { lan_cidrs: lan.value, wan_interface: wan.value })
    saved.value = true
    setTimeout(() => (saved.value = false), 1500)
  } catch (e) { saveErr.value = e.message }
}

// ---------- 版本更新（debug18：Linux 二进制一键自更新） ----------
const upd = ref(null)
const updErr = ref('')
const updMsg = ref('')
const updating = ref(false)
async function loadUpdate() {
  try { upd.value = await http.get('/system/update') } catch (e) { upd.value = { supported: false, available: false } }
}
async function loadDeploys() {
  try { deploys.value = await http.get('/system/deployments') } catch (e) { deploys.value = null }
}
async function doUpdate() {
  if (!confirm(t('upd.confirm'))) return
  updating.value = true
  updErr.value = ''
  updMsg.value = ''
  try {
    const r = await http.post('/system/update')
    updMsg.value = r.message || t('upd.done')
  } catch (e) { updErr.value = e.message } finally { updating.value = false }
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

# 3. SNI 识别（推荐）：镜像每条 HTTPS / QUIC 连接开头的握手包，按连接认出访问的域名
#    终端用加密 DNS（DoH）时 DNS 嗅探失效，靠它补上；同一个 CDN IP 上的不同网站也能分清
/ip firewall mangle add chain=forward protocol=tcp dst-port=443 connection-bytes=0-4000 action=sniff-tzsp sniff-target=${ip} sniff-target-port=${p.tzsp} comment=ROSDPI-SNI
/ip firewall mangle add chain=forward protocol=udp dst-port=443 connection-bytes=0-4000 action=sniff-tzsp sniff-target=${ip} sniff-target-port=${p.tzsp} comment=ROSDPI-SNI

# 4. 只读 API 账号（可选，用于主机名、WAN 速率）
/user group add name=rosdpi policy=read,rest-api,api,!write,!policy,!sensitive
/user add name=rosdpi group=rosdpi password=<强密码> address=${ip}`
})

// 按自检结果生成修改命令：有注释时按注释定位，没有就用规则编号
const fixes = computed(() => {
  const c = sys.value?.ros_check
  if (!c || !c.checked) return []
  const out = []
  for (const r of c.rules) {
    if (!r.problems.length) continue
    const base = r.family === 'ipv6' ? '/ipv6 firewall mangle' : '/ip firewall mangle'
    const sel = r.comment ? `[find comment="${r.comment}"]` : r.id
    if (r.problems.includes('disabled')) out.push(`${base} enable ${sel}`)
    const sets = []
    if (r.problems.includes('port')) sets.push(`sniff-target-port=${c.port}`)
    if (r.problems.includes('target') && c.target) sets.push(`sniff-target=${c.target}`)
    if (sets.length) out.push(`${base} set ${sel} ${sets.join(' ')}`)
  }
  const tgt = c.target || hostIp.value || '<HOST_IP>'
  const tail = `action=sniff-tzsp sniff-target=${tgt} sniff-target-port=${c.port} comment=ROSDPI-SNI`
  if (c.issues.includes('no_sni')) {
    out.push(`/ip firewall mangle add chain=forward protocol=tcp dst-port=443 connection-bytes=0-4000 ${tail}`)
    out.push(`/ip firewall mangle add chain=forward protocol=udp dst-port=443 connection-bytes=0-4000 ${tail}`)
  } else if (c.issues.includes('no_quic')) {
    out.push(`/ip firewall mangle add chain=forward protocol=udp dst-port=443 connection-bytes=0-4000 ${tail}`)
  }
  return [...new Set(out)]
})
const fixCopied = ref(false)
async function copyFix() {
  try {
    await navigator.clipboard.writeText(fixes.value.join('\n'))
    fixCopied.value = true
    setTimeout(() => (fixCopied.value = false), 1500)
  } catch (e) { /* 非 https 下剪贴板不可用 */ }
}

async function copy() {
  try {
    await navigator.clipboard.writeText(guide.value)
    copied.value = true
    setTimeout(() => (copied.value = false), 1500)
  } catch (e) { /* 非 https 下剪贴板不可用 */ }
}
</script>

<style scoped>
.scene-pick { margin-bottom: 16px; }
.mt { margin-top: 14px; }
.small { font-size: 12.5px; }
.stc { display: flex; flex-direction: column; gap: 6px; font-size: 13px; min-width: 0; }
.tdot { width: 6px; height: 6px; margin-left: 4px; vertical-align: top; }
.sys { align-items: start; }
.st-h { display: flex; align-items: center; gap: 8px; font-weight: 600; margin-bottom: 4px; }
.kv { display: flex; justify-content: space-between; gap: 12px; color: var(--muted); }
.kv > :last-child { color: var(--text); text-align: right; overflow: hidden; text-overflow: ellipsis; }
.srv { display: flex; flex-direction: column; align-items: flex-end; }
.what { margin: 6px 0 0; line-height: 1.5; }
.src-form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px 28px; }
.src-box { display: flex; flex-direction: column; gap: 7px; min-width: 0; }
.src-box p { margin: 0; line-height: 1.55; }
.src-box label { font-size: 13px; color: var(--muted); margin-top: 4px; }
.src-box .row { display: flex; gap: 8px; }
.src-box .st { display: flex; flex-wrap: wrap; gap: 4px 14px; color: var(--muted); margin-top: 4px; }
.src-box .asn { margin-top: 12px; }
.acts { grid-column: 1 / -1; display: flex; gap: 10px; align-items: center; }
.acts .sp { flex: 1; }
@media (max-width: 860px) { .src-form { grid-template-columns: 1fr; } }
.ck .pill { margin-right: 4px; }
.fixes { margin-top: 14px; display: grid; gap: 10px; }
.iss { margin: 0; padding-left: 20px; display: grid; gap: 4px; font-size: 13.5px; }
.match { border-top: 1px solid var(--line); margin-top: 4px; }
.match .st-h { gap: 10px; }
.mbar { display: flex; gap: 2px; height: 10px; margin: 6px 0 8px; }
.mbar i { display: block; border-radius: 3px; min-width: 2px; }
.mlg { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 4px 20px; font-size: 13px; color: var(--muted); }
.mlg li { display: flex; align-items: center; gap: 6px; }
.mlg b { color: var(--ink); font-weight: 600; }
.sw { width: 10px; height: 10px; border-radius: 3px; }
/* 由准到粗：深 → 浅，"无域名"用中性灰 */
.proxy { background: var(--brand); }
.conn { background: var(--g-social); }
.pair { background: color-mix(in srgb, var(--g-social) 62%, var(--panel)); }
.ip { background: color-mix(in srgb, var(--g-social) 32%, var(--panel)); }
.none { background: var(--line-strong); }
.form { display: flex; flex-direction: column; gap: 8px; }
.form label { font-size: 13px; color: var(--muted); margin-top: 4px; }
.guide { margin: 0 0 10px; }
.ipin { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; max-width: 320px; }
</style>
