<template>
  <!-- 用户管理（仅管理员）：管理员可以改所有设置；普通用户只能查看，不能改设置、规则和名称 -->
  <div class="panel">
    <div class="panel-b head">
      <div class="info-bar"><span class="ic">i</span><div><b>{{ t('users.title') }}</b><span>{{ t('users.info') }}</span></div></div>
      <div class="sec">{{ t('users.list') }}<span class="faint small">{{ list.length }}</span><span class="sp" />
        <button class="btn sm primary" @click="openAdd">{{ t('users.add') }}</button></div>
    </div>
    <div class="tbl-wrap">
      <table class="tbl">
        <thead><tr><th>{{ t('login.username') }}</th><th>{{ t('users.role') }}</th><th class="m-hide">{{ t('users.created') }}</th>
          <th class="m-hide">{{ t('users.lastLogin') }}</th><th /></tr></thead>
        <tbody>
          <tr v-for="u in list" :key="u.id">
            <td><b>{{ u.username }}</b><span v-if="u.username === auth.username" class="faint small"> · {{ t('users.me') }}</span></td>
            <td><span class="pill" :class="u.role === 'admin' ? 'ok' : 'grey'">{{ t('users.roles.' + u.role) }}</span></td>
            <td class="m-hide num small muted">{{ u.created ? datetime(u.created) : '-' }}</td>
            <td class="m-hide num small muted">{{ u.last_login ? ago(u.last_login) : t('common.never') }}</td>
            <td class="r nowrap">
              <button class="btn sm ghost" @click="openEdit(u)">{{ t('common.edit') }}</button>
              <button class="btn sm danger" v-if="u.username !== auth.username" @click="ask = u">{{ t('common.delete') }}</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="err pad" v-if="err">{{ err }}</div>

    <Modal :open="!!form" :title="form && form.id ? t('users.edit', { name: form.username }) : t('users.add')" width="460px" @close="form = null">
      <form v-if="form" class="uf" @submit.prevent="save">
        <template v-if="!form.id">
          <label for="uf-name">{{ t('login.username') }}</label>
          <input id="uf-name" class="input" v-model.trim="form.username" required maxlength="64" autocomplete="off" pattern="[A-Za-z0-9_.@\-]+" :title="t('users.nameRule')" />
        </template>
        <label>{{ t('users.role') }}</label>
        <div class="roles">
          <label v-for="r in ['user', 'admin']" :key="r" class="role" :class="{ on: form.role === r }">
            <input type="radio" :value="r" v-model="form.role" />
            <b>{{ t('users.roles.' + r) }}</b><span class="faint small">{{ t('users.roleHint.' + r) }}</span>
          </label>
        </div>
        <label for="uf-pw">{{ form.id ? t('users.resetPw') : t('login.password') }}</label>
        <input id="uf-pw" class="input" type="password" v-model="form.password" :required="!form.id" minlength="6" autocomplete="new-password"
               :placeholder="form.id ? t('users.resetPwHint') : t('login.tooShort')" />
        <div class="err" v-if="formErr">{{ formErr }}</div>
        <div class="row"><button type="button" class="btn" @click="form = null">{{ t('common.cancel') }}</button>
          <button class="btn primary">{{ t('common.save') }}</button></div>
      </form>
    </Modal>

    <Modal :open="!!ask" :title="t('users.delTitle')" width="420px" @close="ask = null">
      <div v-if="ask" class="uf">
        <p>{{ t('users.delText', { name: ask.username }) }}</p>
        <div class="row"><button class="btn" @click="ask = null">{{ t('common.cancel') }}</button>
          <button class="btn danger" @click="del">{{ t('common.delete') }}</button></div>
      </div>
    </Modal>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import http, { auth } from '../api.js'
import { ago, datetime } from '../format.js'
import Modal from './Modal.vue'

const { t } = useI18n()
const list = ref([])
const err = ref('')
const form = ref(null)
const formErr = ref('')
const ask = ref(null)

async function load() {
  try { list.value = await http.get('/auth/users'); err.value = '' } catch (e) { err.value = e.message }
}
function openAdd() { formErr.value = ''; form.value = { id: null, username: '', role: 'user', password: '' } }
function openEdit(u) { formErr.value = ''; form.value = { id: u.id, username: u.username, role: u.role, password: '' } }
async function save() {
  formErr.value = ''
  const f = form.value
  try {
    if (f.id) await http.put(`/auth/users/${f.id}`, { role: f.role, password: f.password || null })
    else await http.post('/auth/users', { username: f.username, role: f.role, password: f.password })
    form.value = null
    await load()
  } catch (e) { formErr.value = e.message }
}
async function del() {
  try { await http.delete(`/auth/users/${ask.value.id}`); ask.value = null; await load() } catch (e) { err.value = e.message; ask.value = null }
}
onMounted(load)
</script>

<style scoped>
.head { display: grid; gap: 14px; padding-bottom: 6px; }
.nowrap { white-space: nowrap; }
.pad { padding: 0 18px 14px; }
.uf { display: grid; gap: 8px; }
.uf > label { font-size: 13px; color: var(--muted); margin-top: 4px; }
.roles { display: grid; gap: 8px; }
.role { display: grid; grid-template-columns: auto 1fr; column-gap: 8px; align-items: center; padding: 10px 12px;
  border: 1px solid var(--line); border-radius: 10px; cursor: pointer; }
.role.on { border-color: var(--brand-ink); background: var(--brand-weak); }
.role .small { grid-column: 2; }
.row { display: flex; gap: 10px; justify-content: flex-end; margin-top: 8px; }
</style>
