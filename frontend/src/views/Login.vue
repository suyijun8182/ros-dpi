<template>
  <AuthLayout>
    <form class="box" @submit.prevent="submit">
      <ol class="steps" v-if="setup">
        <li class="done">{{ t('setup.step1') }}</li>
        <li class="on">{{ t('setup.step2') }}</li>
      </ol>
      <h2>{{ setup ? t('login.setupTitle') : t('login.title') }}</h2>
      <label>{{ t('login.username') }}<input class="input" v-model="username" autocomplete="username" /></label>
      <label>{{ t('login.password') }}<input class="input" type="password" v-model="password" :autocomplete="setup ? 'new-password' : 'current-password'" /></label>
      <label v-if="setup">{{ t('login.password2') }}<input class="input" type="password" v-model="password2" autocomplete="new-password" /></label>
      <div class="err" v-if="error">{{ error }}</div>
      <button class="btn primary full" :disabled="busy">{{ setup ? t('login.setup') : t('login.submit') }}</button>
    </form>
  </AuthLayout>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute, useRouter } from 'vue-router'
import http, { setAuth } from '../api.js'
import AuthLayout from '../components/AuthLayout.vue'

const { t } = useI18n()
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
h2 { font: 600 19px/1.3 var(--sans); margin: 0; }
label { display: flex; flex-direction: column; gap: 6px; font-size: 14px; color: var(--muted); }
.full { width: 100%; justify-content: center; height: 40px; font-size: 15px; }
.steps { list-style: none; margin: 4px 0 0; padding: 0; display: flex; gap: 6px; counter-reset: s; }
.steps li { flex: 1; font-size: 13px; color: var(--faint); padding-top: 8px; border-top: 3px solid var(--line); counter-increment: s; }
.steps li::before { content: counter(s) ". "; }
.steps li.done { color: var(--muted); border-top-color: var(--pair-green); }
.steps li.on { color: var(--ink); border-top-color: var(--brand-ink); }
</style>
