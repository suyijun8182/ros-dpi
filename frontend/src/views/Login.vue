<template>
  <div class="wrap">
    <form class="panel box" @submit.prevent="submit">
      <div class="brand">
        <Mark :size="34" />
        <div>
          <div class="b1">ROS-DPI</div>
          <div class="muted b2">{{ t('app.subtitle') }}</div>
        </div>
      </div>
      <h2>{{ setup ? t('login.setupTitle') : t('login.title') }}</h2>
      <label>{{ t('login.username') }}<input class="input" v-model="username" autocomplete="username" /></label>
      <label>{{ t('login.password') }}<input class="input" type="password" v-model="password" :autocomplete="setup ? 'new-password' : 'current-password'" /></label>
      <label v-if="setup">{{ t('login.password2') }}<input class="input" type="password" v-model="password2" autocomplete="new-password" /></label>
      <div class="err" v-if="error">{{ error }}</div>
      <button class="btn primary full" :disabled="busy">{{ setup ? t('login.setup') : t('login.submit') }}</button>
      <div class="foot">
        <button type="button" class="btn ghost sm" @click="setLang(locale === 'zh' ? 'en' : 'zh')">{{ t('common.lang') }}</button>
        <button type="button" class="btn ghost sm" @click="toggleTheme">{{ t('common.theme') }}</button>
      </div>
    </form>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import http, { setAuth } from '../api.js'
import Mark from '../components/Mark.vue'
import { setLang } from '../i18n/index.js'
import { toggleTheme } from '../state.js'

const { t, locale } = useI18n()
const route = useRoute()
const router = useRouter()
const setup = ref(false)
const username = ref('admin')
const password = ref('')
const password2 = ref('')
const error = ref('')
const busy = ref(false)

onMounted(async () => {
  try { setup.value = !(await http.get('/auth/status')).initialized } catch (e) { error.value = e.message }
})

async function submit() {
  error.value = ''
  if (setup.value) {
    if (password.value.length < 6) return (error.value = t('login.tooShort'))
    if (password.value !== password2.value) return (error.value = t('login.mismatch'))
  }
  busy.value = true
  try {
    const r = await http.post(setup.value ? '/auth/setup' : '/auth/login', { username: username.value, password: password.value })
    setAuth(r.token, r.username)
    router.replace(route.query.next || '/')
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
  }
}
</script>

<style scoped>
.wrap { min-height: 100vh; display: grid; place-items: center; padding: 16px; }
.box { width: 100%; max-width: 380px; padding: 32px 28px 22px; display: flex; flex-direction: column; gap: 16px; border-top: 3px solid var(--pair-blue); }
.brand { display: flex; gap: 12px; align-items: center; }
.b1 { font: 700 24px/1 var(--cond); letter-spacing: .02em; }
.b2 { font-size: 12px; }
h2 { font: 600 20px/1.2 var(--cond); margin: 10px 0 0; }
label { display: flex; flex-direction: column; gap: 6px; font-size: 14px; color: var(--muted); }
.full { width: 100%; justify-content: center; height: 38px; }
.foot { display: flex; gap: 8px; justify-content: center; }
</style>
