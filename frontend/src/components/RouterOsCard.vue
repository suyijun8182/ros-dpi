<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import http, { isAdmin } from '../api.js'
import { ago } from '../format.js'
import Modal from './Modal.vue'

const props = defineProps({ status: { type: Object, required: true }, config: Object })
const emit = defineEmits(['saved'])
const { t } = useI18n()
const form = reactive({ url: '', user: '', password: '', verify_tls: false })
const busy = ref('')
const message = ref('')
const failed = ref(false)
const confirmDisable = ref(false)

watch(() => props.config, cfg => {
  if (cfg) Object.assign(form, { url: cfg.url, user: cfg.user, verify_tls: cfg.verify_tls, password: '' })
}, { immediate: true })

const originChanged = computed(() => {
  if (!form.url) return false
  try {
    return new URL(form.url).origin !== new URL(props.config?.url).origin
  } catch {
    return true
  }
})
const canConnect = computed(() => isAdmin.value && props.config && !busy.value && form.url &&
  (!originChanged.value || !!form.password))
const passwordHint = computed(() => {
  if (originChanged.value) return t('settings.rosPasswordRequired')
  return props.config?.has_password ? t('settings.rosPasswordSaved') : ''
})

const changes = computed(() => {
  const body = {}
  for (const key of ['url', 'user', 'verify_tls']) {
    if (form[key] !== props.config?.[key]) body['ros_' + key] = form[key]
  }
  if (form.password) body.ros_password = form.password
  return body
})

async function test() {
  busy.value = 'test'
  message.value = ''
  try {
    const body = { url: form.url, user: form.user, verify_tls: form.verify_tls }
    if (form.password) body.password = form.password
    const result = await http.post('/ros/test', body)
    failed.value = !result.ok
    message.value = result.ok ? t('settings.rosConnected', result) : result.error
  } catch (e) {
    failed.value = true
    message.value = e.message
  } finally { busy.value = '' }
}

async function save(body) {
  busy.value = 'save'
  message.value = ''
  confirmDisable.value = false
  try {
    const settings = await http.put('/settings', body)
    form.password = ''
    failed.value = false
    message.value = t('common.saved')
    emit('saved', settings)
  } catch (e) {
    failed.value = true
    message.value = e.message
  } finally { busy.value = '' }
}
</script>

<template>
  <section id="ros-api" class="panel-b router-card" aria-labelledby="ros-api-title">
    <div class="status">
      <span class="dot" :class="status.enabled ? (status.ok ? 'on' : 'bad') : ''" />
      <h2 id="ros-api-title">{{ t('settings.ros') }}</h2>
      <span class="pill grey">{{ t('settings.rosSource.' + status.source) }}</span>
      <span v-if="status.identity">{{ status.identity }} · {{ status.version }}</span>
      <span v-if="status.enabled" class="muted small">{{ t('settings.last') }} · {{ ago(status.last_poll) }}</span>
    </div>
    <p v-if="status.error" class="err">{{ status.error }}</p>
    <p v-if="!status.enabled" class="muted small">{{ t(isAdmin ? 'settings.rosHint' : 'settings.rosViewerHint') }}</p>
    <p v-if="config?.source === 'env'" class="muted small">{{ t('settings.rosEnvHint') }}</p>
    <form @submit.prevent="save(changes)" @input="message = ''">
      <fieldset :disabled="!isAdmin || !config || !!busy">
        <label>{{ t('settings.rosAddress') }}
          <input v-model.trim="form.url" type="url" class="input" required maxlength="255" :placeholder="isAdmin ? 'https://192.168.88.1' : '—'" />
          <small v-if="isAdmin" class="faint">{{ t('settings.rosAddressHint') }}</small>
        </label>
        <label>{{ t('login.username') }}
          <input v-model="form.user" class="input" maxlength="64" :placeholder="isAdmin ? 'rosdpi' : '—'" />
        </label>
        <label>{{ t('login.password') }}
          <input v-model="form.password" type="password" class="input" autocomplete="new-password" maxlength="255"
                 :required="originChanged" :placeholder="passwordHint" />
        </label>
        <label class="tls"><span><input v-model="form.verify_tls" :indeterminate="!config" type="checkbox" /> {{ t('settings.rosTls') }}</span>
          <small v-if="isAdmin" class="faint">{{ t('settings.rosTlsHint') }}</small>
        </label>
      </fieldset>
      <div v-if="isAdmin" class="actions">
        <button type="button" class="btn sm" :disabled="!canConnect" @click="test">{{ t(busy === 'test' ? 'setup.testing' : 'settings.test') }}</button>
        <button class="btn sm primary" :disabled="!canConnect || !Object.keys(changes).length">{{ t('common.save') }}</button>
        <button v-if="config?.source === 'web' && config.url" type="button" class="btn sm danger" :disabled="!!busy" @click="confirmDisable = true">{{ t('settings.rosDisable') }}</button>
        <span role="status" :class="failed ? 'err' : 'muted'">{{ message }}</span>
      </div>
    </form>
    <Modal :open="confirmDisable" :title="t('settings.rosDisableConfirm')" width="400px" @close="confirmDisable = false">
      <p>{{ t('settings.rosDisableHint') }}</p>
      <div class="actions">
        <button class="btn" @click="confirmDisable = false">{{ t('common.cancel') }}</button>
        <button class="btn danger" @click="save({ ros_url: '' })">{{ t('settings.rosDisable') }}</button>
      </div>
    </Modal>
  </section>
</template>

<style scoped>
.router-card { border-top: 1px solid var(--line); scroll-margin-top: 16px; }
.status, .actions { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; }
h2, p { margin: 0; }
h2 { font-size: 15px; }
p, .actions { margin-top: 8px; }
fieldset { display: grid; grid-template-columns: 2fr 1fr 1fr; align-items: start; gap: 12px; border: 0; margin: 14px 0; padding: 0; }
label { display: grid; gap: 5px; min-width: 0; font-size: 13px; }
small { line-height: 1.5; }
.tls { grid-column: 1 / -1; }
@media (max-width: 760px) { fieldset { grid-template-columns: 1fr; } }
</style>
