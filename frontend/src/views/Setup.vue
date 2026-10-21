<template>
  <div class="wrap">
    <div class="panel box">
      <div class="brand">
        <Mark :size="34" />
        <div>
          <div class="b1">ROS-DPI</div>
          <div class="muted b2">{{ t('app.subtitle') }}</div>
        </div>
      </div>

      <!-- 已有配置但暂时连不上：不让用户重填，自动重试 -->
      <template v-if="setupState.present">
        <h2>{{ t('setup.waitTitle') }}</h2>
        <p class="muted">{{ t('setup.waitText') }}</p>
        <div class="err" v-if="error">{{ error }}</div>
        <button class="btn" @click="poll">{{ t('setup.retry') }}</button>
      </template>

      <form v-else @submit.prevent="save">
        <ol class="steps">
          <li class="on">{{ t('setup.step1') }}</li>
          <li>{{ t('setup.step2') }}</li>
        </ol>
        <h2>{{ t('setup.title') }}</h2>
        <p class="muted intro">{{ t('setup.intro') }}</p>

        <div class="row">
          <label class="grow">{{ t('setup.host') }}<input class="input" v-model.trim="f.host" placeholder="192.168.1.10" required /></label>
          <label class="port">{{ t('setup.port') }}<input class="input" type="number" v-model.number="f.port" min="1" max="65535" required /></label>
        </div>
        <label>{{ t('setup.user') }}<input class="input" v-model.trim="f.user" autocomplete="off" required /></label>
        <label>{{ t('setup.password') }}<input class="input" type="password" v-model="f.password" autocomplete="new-password" /></label>
        <label>{{ t('setup.database') }}<input class="input" v-model.trim="f.database" required /></label>
        <p class="faint small">{{ t('setup.hostHint') }}</p>

        <div class="ok" v-if="okMsg">{{ okMsg }}</div>
        <div class="err" v-if="error">{{ error }}</div>

        <div class="acts">
          <button type="button" class="btn" @click="test" :disabled="!!busy || !valid">{{ busy === 'test' ? t('setup.testing') : t('setup.test') }}</button>
          <button class="btn primary" :disabled="!!busy || !valid">{{ busy === 'save' ? t('setup.saving') : t('setup.save') }}</button>
        </div>

        <details class="sql">
          <summary>{{ t('setup.sqlTitle') }}</summary>
          <p class="faint small">{{ t('setup.sqlHint') }}</p>
          <pre class="code">{{ sql }}</pre>
        </details>
      </form>

      <div class="foot">
        <button type="button" class="btn ghost sm" @click="setLang(locale === 'zh' ? 'en' : 'zh')">{{ t('common.lang') }}</button>
        <button type="button" class="btn ghost sm" @click="toggleTheme">{{ t('common.theme') }}</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import http, { checkSetup, setupState } from '../api.js'
import Mark from '../components/Mark.vue'
import { setLang } from '../i18n/index.js'
import { toggleTheme } from '../state.js'

const { t, locale } = useI18n()
const router = useRouter()
const f = reactive({ host: '', port: 3306, user: 'rosdpi', password: '', database: 'rosdpi' })
const busy = ref('')  // '' | 'test' | 'save'
const error = ref('')
const okMsg = ref('')
let timer = null

const valid = computed(() => f.host && f.user && f.database && f.port)
const sql = computed(() => `CREATE DATABASE ${f.database || 'rosdpi'} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER '${f.user || 'rosdpi'}'@'%' IDENTIFIED BY 'your-password';
GRANT ALL PRIVILEGES ON ${f.database || 'rosdpi'}.* TO '${f.user || 'rosdpi'}'@'%';
FLUSH PRIVILEGES;`)

async function poll() {
  error.value = ''
  try {
    await checkSetup()
    if (setupState.configured) router.replace({ name: 'login' })
  } catch (e) { error.value = e.message }
}

onMounted(async () => {
  await poll()
  if (setupState.present) timer = setInterval(poll, 5000)
})
onUnmounted(() => clearInterval(timer))

async function test() {
  error.value = okMsg.value = ''
  busy.value = 'test'
  try { okMsg.value = (await http.post('/setup/test', f)).message } catch (e) { error.value = e.message } finally { busy.value = '' }
}

async function save() {
  error.value = okMsg.value = ''
  busy.value = 'save'
  try {
    await http.post('/setup/save', f)
    Object.assign(setupState, { configured: true, present: true })
    router.replace({ name: 'login' })
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = ''
  }
}
</script>

<style scoped>
.wrap { min-height: 100vh; display: grid; place-items: center; padding: 16px; }
.box { width: 100%; max-width: 460px; padding: 30px 28px 20px; display: flex; flex-direction: column; gap: 16px; border-top: 3px solid var(--pair-blue); }
form { display: flex; flex-direction: column; gap: 14px; }
.brand { display: flex; gap: 12px; align-items: center; }
.b1 { font: 700 24px/1 var(--cond); letter-spacing: .02em; }
.b2 { font-size: 12px; }
h2 { font: 600 20px/1.2 var(--cond); margin: 0; }
.intro { margin: -6px 0 0; font-size: 14px; }
label { display: flex; flex-direction: column; gap: 6px; font-size: 14px; color: var(--muted); }
.row { display: flex; gap: 12px; }
.grow { flex: 1; min-width: 0; }
.port { width: 110px; flex: none; }
.small { font-size: 13px; margin: -4px 0 0; }
.acts { display: flex; gap: 10px; justify-content: flex-end; }
.ok { color: var(--ok); font-size: 14px; }
.foot { display: flex; gap: 8px; justify-content: center; }

/* 两步：连接数据库 → 设置管理员，当前步骤用蓝色线标出 */
.steps { list-style: none; margin: 4px 0 0; padding: 0; display: flex; gap: 6px; counter-reset: s; }
.steps li { flex: 1; font-size: 13px; color: var(--faint); padding-top: 8px; border-top: 3px solid var(--line); counter-increment: s; }
.steps li::before { content: counter(s) ". "; }
.steps li.on { color: var(--ink); border-top-color: var(--pair-blue); }

.sql summary { cursor: pointer; color: var(--pair-blue); font-size: 14px; }
.sql pre { margin-top: 8px; white-space: pre; overflow-x: auto; font-size: 12px; }
</style>
