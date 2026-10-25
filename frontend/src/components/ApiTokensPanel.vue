<template>
  <!-- 只读 API 令牌（0.6.25，仅管理员）：给 Home Assistant 等外部程序长期读取数据；原文只在创建时显示一次 -->
  <div class="panel">
    <div class="panel-b head">
      <div class="info-bar"><span class="ic">i</span><div><b>{{ t('tokens.title') }}</b><span>{{ t('tokens.info') }}</span></div></div>
      <div class="sec">{{ t('tokens.list') }}<span class="faint small">{{ list.length }}</span><span class="sp" />
        <button class="btn sm primary" @click="openAdd">{{ t('tokens.add') }}</button></div>
    </div>
    <div class="tbl-wrap" v-if="list.length">
      <table class="tbl">
        <thead><tr><th>{{ t('tokens.name') }}</th><th class="m-hide">{{ t('tokens.prefix') }}</th><th class="m-hide">{{ t('users.created') }}</th>
          <th>{{ t('tokens.lastUsed') }}</th><th /></tr></thead>
        <tbody>
          <tr v-for="k in list" :key="k.id">
            <td><b>{{ k.name }}</b></td>
            <td class="m-hide num small muted">{{ k.prefix }}…</td>
            <td class="m-hide num small muted">{{ k.created ? datetime(k.created) : '-' }}</td>
            <td class="num small muted">{{ k.last_used ? ago(k.last_used) : t('common.never') }}</td>
            <td class="r"><button class="btn sm danger" @click="ask = k">{{ t('common.delete') }}</button></td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="faint small pad" v-else>{{ t('tokens.empty') }}</div>
    <div class="err pad" v-if="err">{{ err }}</div>

    <Modal :open="!!form" :title="t('tokens.add')" width="520px" @close="closeForm">
      <form v-if="form && !form.token" class="uf" @submit.prevent="create">
        <label for="tk-name">{{ t('tokens.name') }}</label>
        <input id="tk-name" class="input" v-model.trim="form.name" required maxlength="64" :placeholder="t('tokens.namePh')" />
        <div class="err" v-if="formErr">{{ formErr }}</div>
        <div class="row"><button type="button" class="btn" @click="closeForm">{{ t('common.cancel') }}</button>
          <button class="btn primary">{{ t('tokens.create') }}</button></div>
      </form>
      <div v-else-if="form" class="uf">
        <p class="small">{{ t('tokens.once') }}</p>
        <div class="tok num">{{ form.token }}</div>
        <div class="faint small">{{ t('tokens.usage') }}</div>
        <pre class="num small">Authorization: Bearer {{ form.token.slice(0, 10) }}…
GET {{ origin }}/api/ha/summary</pre>
        <div class="row"><button class="btn" @click="copy">{{ copied ? t('tokens.copied') : t('tokens.copy') }}</button>
          <button class="btn primary" @click="closeForm">{{ t('tokens.done') }}</button></div>
      </div>
    </Modal>

    <Modal :open="!!ask" :title="t('tokens.delTitle')" width="420px" @close="ask = null">
      <div v-if="ask" class="uf">
        <p>{{ t('tokens.delText', { name: ask.name }) }}</p>
        <div class="row"><button class="btn" @click="ask = null">{{ t('common.cancel') }}</button>
          <button class="btn danger" @click="del">{{ t('common.delete') }}</button></div>
      </div>
    </Modal>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import http from '../api.js'
import { ago, datetime } from '../format.js'
import Modal from './Modal.vue'

const { t } = useI18n()
const list = ref([])
const err = ref('')
const form = ref(null)
const formErr = ref('')
const ask = ref(null)
const copied = ref(false)
const origin = location.origin

async function load() {
  try { list.value = await http.get('/auth/tokens'); err.value = '' } catch (e) { err.value = e.message }
}
function openAdd() { formErr.value = ''; copied.value = false; form.value = { name: 'Home Assistant', token: '' } }
function closeForm() { form.value = null; copied.value = false }
async function create() {
  formErr.value = ''
  try {
    const r = await http.post('/auth/tokens', { name: form.value.name })
    form.value = { name: r.name, token: r.token }
    await load()
  } catch (e) { formErr.value = e.message }
}
async function copy() {
  try { await navigator.clipboard.writeText(form.value.token); copied.value = true } catch (e) { formErr.value = e.message }
}
async function del() {
  try { await http.delete(`/auth/tokens/${ask.value.id}`); ask.value = null; await load() } catch (e) { err.value = e.message; ask.value = null }
}
onMounted(load)
</script>

<style scoped>
.head { display: grid; gap: 14px; padding-bottom: 6px; }
.pad { padding: 0 18px 14px; }
.uf { display: grid; gap: 8px; }
.uf > label { font-size: 13px; color: var(--muted); margin-top: 4px; }
.uf p { margin: 0; }
.tok { padding: 10px 12px; border: 1px solid var(--brand-ink); border-radius: 8px; background: var(--brand-weak); word-break: break-all; user-select: all; }
pre { margin: 0; padding: 8px 10px; border-radius: 8px; background: var(--bg-soft, rgba(127,127,127,.08)); white-space: pre-wrap; word-break: break-all; }
.row { display: flex; gap: 10px; justify-content: flex-end; margin-top: 8px; }
</style>
