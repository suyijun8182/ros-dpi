<template>
  <!-- 抓包采样（0.6.29，仅管理员）：存 pcap + 识别结果，给 nDPI 等工具离线对照 -->
  <div class="panel mt">
    <div class="panel-h"><h2>{{ t('diag.cap.title') }}</h2><span class="pill grey">{{ t('diag.cap.beta') }}</span></div>
    <div class="panel-b">
      <p class="muted hint">{{ t('diag.cap.intro') }}</p>
      <details class="small">
        <summary>{{ t('diag.cap.rosTitle') }}</summary>
        <p class="faint">{{ t('diag.cap.rosHint') }}</p>
        <pre class="num">{{ rosCmd }}</pre>
        <p class="faint">{{ t('diag.cap.rosRemove') }}</p>
        <pre class="num">/ip firewall mangle remove [find comment=ROSDPI-SAMPLE]
/ipv6 firewall mangle remove [find comment=ROSDPI-SAMPLE]</pre>
      </details>
      <div class="cap-row" v-if="st">
        <template v-if="st.active">
          <span class="pill ok">{{ t('diag.cap.running') }}</span>
          <span class="num small">{{ t('diag.cap.progress', { n: st.packets.toLocaleString(), b: bytes(st.bytes), m: Math.ceil(st.remaining / 60) }) }}</span>
          <button class="btn sm" @click="stop">{{ t('diag.cap.stop') }}</button>
        </template>
        <template v-else>
          <select class="input sm-in" v-model.number="minutes"><option v-for="n in [5, 10, 20, 30]" :key="n" :value="n">{{ t('diag.acc.mins', { n }) }}</option></select>
          <button class="btn primary sm" @click="start">{{ t('diag.cap.start') }}</button>
        </template>
      </div>
      <p class="faint small">{{ t('diag.cap.privacy') }}</p>
      <div class="err" v-if="err">{{ err }}</div>
    </div>
    <div class="tbl-wrap" v-if="st && st.files.length">
      <table class="tbl">
        <thead><tr><th>{{ t('diag.cap.file') }}</th><th class="r">{{ t('diag.cap.packets') }}</th><th class="r m-hide">{{ t('diag.cap.conns') }}</th>
          <th class="r">{{ t('diag.cap.size') }}</th><th /></tr></thead>
        <tbody>
          <tr v-for="x in st.files" :key="x.name">
            <td class="num small"><b>{{ x.name }}</b><div class="faint">{{ datetime(x.started) }} · {{ t('diag.acc.mins', { n: Math.max(1, Math.round((x.ended - x.started) / 60)) }) }}</div></td>
            <td class="r num">{{ (x.packets || 0).toLocaleString() }}</td>
            <td class="r num m-hide">{{ (x.connections || 0).toLocaleString() }}</td>
            <td class="r num">{{ bytes(x.bytes) }}</td>
            <td class="r nowrap">
              <button class="btn sm" v-for="k in ['pcap', 'labels.csv', 'json']" :key="k" @click="download(x.name, k)">{{ k }}</button>
              <button class="btn sm danger" @click="del(x.name)">{{ t('common.delete') }}</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p class="panel-b faint small" v-if="st && st.files.length">{{ t('diag.cap.evalHint') }}</p>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import http from '../api.js'
import { bytes, datetime } from '../format.js'

const { t } = useI18n()
const st = ref(null)
const minutes = ref(10)
const err = ref('')
let timer

// 临时规则：除 DNS 和 443（已有规则）以外，所有端口每条连接开头约 4KB；采完记得删掉
const rosCmd = computed(() => {
  const ip = (st.value && st.value.target) || location.hostname
  const port = (st.value && st.value.target_port) || 37008
  const tail = `connection-bytes=0-4000 action=sniff-tzsp sniff-target=${ip} sniff-target-port=${port} comment=ROSDPI-SAMPLE`
  return ['ip', 'ipv6'].flatMap(v => [
    `/${v} firewall mangle add chain=forward protocol=tcp dst-port=1-442,444-65535 ${tail}`,
    `/${v} firewall mangle add chain=forward protocol=udp dst-port=1-52,54-442,444-65535 ${tail}`,
  ]).join('\n')
})

async function load() {
  try { st.value = await http.get('/diag/capture'); err.value = '' } catch (e) { err.value = e.message }
  clearTimeout(timer)
  if (st.value && st.value.active) timer = setTimeout(load, 5000)
}
async function start() {
  try { await http.post('/diag/capture/start', { minutes: minutes.value }); await load() } catch (e) { err.value = e.message }
}
async function stop() {
  try { await http.post('/diag/capture/stop'); await load() } catch (e) { err.value = e.message }
}
async function del(name) {
  try { await http.delete(`/diag/capture/${name}`); await load() } catch (e) { err.value = e.message }
}
async function download(name, kind) {
  // 带登录令牌下载：走 axios 拿 blob，再交给浏览器保存
  try {
    const blob = await http.get(`/diag/capture/${name}/${kind}`, { responseType: 'blob', timeout: 300000 })
    // 不用 csv.js 的 downloadBlob：它会在文件名里加时间，三个文件就对不上同一个前缀了（ndpi_eval.py 按前缀找）
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${name}.${kind}`
    document.body.appendChild(a)
    a.click()
    setTimeout(() => { URL.revokeObjectURL(a.href); a.remove() }, 0)
  } catch (e) { err.value = e.message }
}

onMounted(load)
onUnmounted(() => clearTimeout(timer))
</script>

<style scoped>
.hint { margin: 0 0 8px; }
pre { white-space: pre-wrap; word-break: break-all; background: var(--line); padding: 8px 10px; border-radius: 6px; margin: 6px 0; }
.cap-row { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin: 10px 0 6px; }
.sm-in { width: auto; }
.nowrap { white-space: nowrap; }
.nowrap .btn { margin-left: 4px; }
</style>
