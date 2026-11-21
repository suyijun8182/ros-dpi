<template>
  <div>
    <div class="page-h">
      <h1>{{ t('sites.allTitle') }}</h1>
      <span class="lead">{{ t('sites.allLead') }}</span>
    </div>

    <div v-if="error" class="err">{{ error }}</div>

    <div class="grid cards">
      <button v-for="s in rows" :key="s.slug" class="panel card" type="button" @click="open(s.slug)"
              :aria-label="t('sites.open', { name: s.name })">
        <div class="panel-h">
          <span class="dot" :class="state(s)" />
          <h2>{{ s.name }}</h2>
          <span class="faint small slug">{{ s.slug }}</span>
          <span class="sp" />
          <span class="pill" :class="{ ok: state(s) === 'on', bad: state(s) === 'bad', grey: state(s) === '' , warn: state(s) === 'warn' }">{{ stateText(s) }}</span>
        </div>
        <div class="panel-b">
          <div class="rates">
            <div><span class="faint small">↓ {{ t('sites.down') }}</span><b class="num">{{ rate(s.rate_down) }}</b></div>
            <div><span class="faint small">↑ {{ t('sites.up') }}</span><b class="num">{{ rate(s.rate_up) }}</b></div>
          </div>
          <dl class="kv">
            <div><dt>{{ t('sites.today') }}</dt><dd class="num">{{ bytes(s.today.total) }}<span class="faint"> · ↓{{ bytes(s.today.down) }} ↑{{ bytes(s.today.up) }}</span></dd></div>
            <div><dt>{{ t('sites.online') }}</dt><dd class="num">{{ s.online }}</dd></div>
            <div v-if="s.identity"><dt>RouterOS</dt><dd>{{ s.identity }}</dd></div>
          </dl>
          <div class="apps" v-if="s.apps.length">
            <div v-for="a in s.apps" :key="a.id" class="app">
              <i :style="{ background: groupColor(a.group) }" /><span class="name">{{ appName(a) }}</span>
              <span class="meter"><i :style="{ width: (a.total / (s.apps[0].total || 1)) * 100 + '%', background: groupColor(a.group) }" /></span>
              <b class="num">{{ bytes(a.total) }}</b>
            </div>
          </div>
          <div v-else class="faint small">{{ t('sites.noTraffic') }}</div>
          <div v-if="s.ros_error" class="err small">{{ s.ros_error }}</div>
        </div>
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import http from '../api.js'
import { appName, bytes, groupColor, rate } from '../format.js'
import { usePoll } from '../poll.js'

const { t } = useI18n()
const router = useRouter()
const rows = ref([])

const { error } = usePoll(async () => { rows.value = (await http.get('/sites/overview')).sites }, 10000)

// 停用：灰；RouterOS 连不上：红；3 分钟没收到流量：黄；正常：绿
function state(s) {
  if (!s.enabled) return ''
  if (s.ros_enabled && !s.ros_ok && s.ros_last_poll) return 'bad'
  return s.receiving ? 'on' : 'warn'
}
function stateText(s) {
  return t('sites.state.' + ({ '': 'off', bad: 'rosDown', warn: 'noFlow', on: 'ok' })[state(s)])
}
const open = slug => router.push({ path: '/', query: { site: slug } })
</script>

<style scoped>
.cards { grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); }
.card { text-align: left; font: inherit; color: inherit; cursor: pointer; padding: 0; border: 1px solid var(--line);
  display: flex; flex-direction: column; justify-content: flex-start; }
.card:hover { border-color: var(--brand-ink); }
.card:focus-visible { outline: 2px solid var(--brand-ink); outline-offset: 2px; }
.panel-h { display: flex; align-items: center; gap: 8px; }
.panel-h h2 { margin: 0; }
.slug { font-family: var(--cond); }
.rates { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 12px; }
.rates div { display: flex; flex-direction: column; gap: 2px; }
.rates b { font: 600 22px/1.1 var(--cond); }
.kv { margin: 0 0 12px; display: grid; gap: 6px; }
.kv div { display: flex; justify-content: space-between; gap: 10px; font-size: 13px; }
.kv dt { color: var(--muted); }
.kv dd { margin: 0; text-align: right; }
.apps { display: grid; gap: 6px; }
.app { display: grid; grid-template-columns: 8px minmax(0, 1fr) 70px auto; align-items: center; gap: 8px; font-size: 13px; }
.app > i { width: 8px; height: 8px; border-radius: 2px; }
.app .name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.app .meter { height: 6px; background: var(--sunk); border-radius: 3px; overflow: hidden; }
.app .meter i { display: block; height: 100%; border-radius: 3px; }
.app b { font-weight: 600; font-size: 12.5px; }
</style>
