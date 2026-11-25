<script setup>
import { shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import http from '../api.js'
import { dashboardTitle } from '../branding.js'

const props = defineProps({ title: { type: String, default: '' } })
const emit = defineEmits(['saved'])
const { t } = useI18n()
const title = shallowRef('')
const busy = shallowRef(false)
const error = shallowRef('')
const saved = shallowRef(false)
watch(() => props.title, value => { title.value = value }, { immediate: true })

async function save() {
  busy.value = true
  error.value = ''
  saved.value = false
  try {
    const settings = await http.put('/settings', { dashboard_title: title.value })
    dashboardTitle.value = settings.dashboard_title
    title.value = settings.dashboard_title
    saved.value = true
    emit('saved', settings)
  } catch (e) { error.value = e.message } finally { busy.value = false }
}
</script>

<template>
  <section class="panel mb">
    <div class="panel-h">{{ t('settings.appearance') }}</div>
    <form class="panel-b branding" @submit.prevent="save">
      <label for="dashboard-title">{{ t('settings.dashboardTitle') }}</label>
      <input id="dashboard-title" class="input" v-model="title" maxlength="64" placeholder="ROS-DPI" :disabled="busy" @input="saved = false" />
      <p class="small faint">{{ t('settings.dashboardTitleHint') }}</p>
      <p v-if="error" class="err" role="alert">{{ error }}</p>
      <div><button class="btn primary" :disabled="busy">{{ t(saved ? 'common.saved' : 'common.save') }}</button></div>
    </form>
  </section>
</template>

<style scoped>
.branding { display: grid; gap: 10px; }
.branding .input { max-width: 440px; }
.branding p { margin: 0; }
</style>
