<template>
  <!-- 多站点（0.7.0）：一个平台管多台 RouterOS。只有一个站点时只显示一句说明和「添加站点」 -->
  <div class="panel" id="sites">
    <div class="panel-b head">
      <div class="info-bar"><span class="ic">i</span><div><b>{{ t('sites.title') }}</b><span>{{ t(list.length > 1 ? 'sites.infoMulti' : 'sites.infoSingle') }}</span></div></div>
      <div class="sec">{{ t('sites.list') }}<span class="faint small">{{ list.length }}</span><span class="sp" />
        <button class="btn sm primary" :disabled="!loaded" @click="openAdd">{{ t('sites.add') }}</button></div>
    </div>
    <div class="tbl-wrap" v-if="list.length > 1">
      <table class="tbl">
        <thead><tr><th>{{ t('sites.name') }}</th><th>{{ t('sites.status') }}</th><th>{{ t('sites.sources') }}</th>
          <th class="m-hide">{{ t('sites.platformAddr') }}</th><th /></tr></thead>
        <tbody>
          <tr v-for="s in list" :key="s.slug" :class="{ off: !s.enabled }">
            <td><b>{{ s.name }}</b> <span class="faint small slug">{{ s.slug }}</span></td>
            <td><span class="pill" :class="stateCls(s)">{{ stateText(s) }}</span></td>
            <td class="num small">{{ s.sources.join(', ') || '-' }}</td>
            <td class="m-hide num small muted">{{ s.platform_addr || '-' }}</td>
            <td class="r nowrap">
              <button class="btn sm ghost" @click="openEdit(s)">{{ t('common.edit') }}</button>
              <button class="btn sm danger" v-if="s.slug !== 'default'" @click="askDel(s)">{{ t('common.delete') }}</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="err pad" v-if="err">{{ err }}</div>

    <!-- 未登记来源：多站点时，没对上任何站点的 IPFIX / TZSP 包被丢弃 -->
    <div class="panel-b unk" v-if="list.length > 1 && unknown.length">
      <div class="sec">{{ t('sites.unknown') }}<span class="faint small">{{ t('sites.unknownHint') }}</span></div>
      <div class="tbl-wrap">
        <table class="tbl">
          <thead><tr><th>IP</th><th>{{ t('sites.kind') }}</th><th class="r">{{ t('sites.packets') }}</th><th>{{ t('settings.last') }}</th><th /></tr></thead>
          <tbody>
            <tr v-for="u in unknown" :key="u.ip + u.kind">
              <td class="num">{{ u.ip }}</td><td>{{ u.kind === 'ipfix' ? 'IPFIX' : 'TZSP' }}</td>
              <td class="r num">{{ u.packets.toLocaleString() }}</td><td class="small muted">{{ ago(u.last_seen) }}</td>
              <td class="r nowrap">
                <select class="input sm" @change="register(u.ip, $event.target.value); $event.target.value = ''">
                  <option value="">{{ t('sites.registerTo') }}</option>
                  <option v-for="s in list" :key="s.slug" :value="s.slug">{{ s.name }}</option>
                </select>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <Modal :open="!!form" :title="form && form.isNew ? t('sites.add') : t('sites.edit', { name: form ? form.name : '' })" width="520px" @close="form = null">
      <form v-if="form" class="uf" @submit.prevent="save">
        <template v-if="form.isNew">
          <label for="sf-slug">{{ t('sites.slug') }}</label>
          <input id="sf-slug" class="input num" v-model.trim="form.slug" required maxlength="32" pattern="[a-z0-9][a-z0-9\-]*" placeholder="office" autocomplete="off" />
          <div class="faint small">{{ t('sites.slugHint') }}</div>
        </template>
        <label for="sf-name">{{ t('sites.name') }}</label>
        <input id="sf-name" class="input" v-model.trim="form.name" required maxlength="64" :placeholder="t('sites.namePh')" />
        <label for="sf-src">{{ t('sites.sources') }}</label>
        <input id="sf-src" class="input num" v-model="form.sources" placeholder="10.8.0.2" autocomplete="off" />
        <div class="faint small">{{ t('sites.sourcesHint') }}</div>
        <div class="chips" v-if="candidates.length">
          <span class="faint small">{{ t('sites.recent') }}</span>
          <button type="button" class="ipchip" v-for="c in candidates" :key="c.ip" @click="addIp(form, 'sources', c.ip)"
                  :title="c.site ? t('sites.seenAt', { name: siteLabel(c.site) }) : t('sites.unknownShort')">{{ c.ip }}<span class="faint"> · {{ c.site ? siteLabel(c.site) : t('sites.unknownShort') }}</span></button>
        </div>
        <label for="sf-pa">{{ t('sites.platformAddr') }}</label>
        <input id="sf-pa" class="input num" v-model.trim="form.platform_addr" maxlength="255" placeholder="10.8.0.1" autocomplete="off" />
        <div class="faint small">{{ t('sites.platformHint') }}</div>
        <label class="ck" v-if="!form.isNew"><input type="checkbox" v-model="form.enabled" /> {{ t('sites.enabled') }}</label>
        <div class="faint small" v-if="!form.isNew && !form.enabled">{{ t('sites.disabledHint') }}</div>

        <!-- 第二个站点：已有的站点也必须登记源 IP，否则分不清数据是谁的 -->
        <div class="others" v-if="form.isNew && needSources.length">
          <div class="sec small">{{ t('sites.othersNeed') }}</div>
          <div v-for="o in needSources" :key="o.slug" class="other">
            <label :for="'sf-o-' + o.slug">{{ t('sites.sourcesOf', { name: o.name }) }}</label>
            <input :id="'sf-o-' + o.slug" class="input num" v-model="o.sources" placeholder="192.168.88.1" required autocomplete="off" />
            <div class="chips" v-if="seenAt(o.slug).length">
              <button type="button" class="ipchip" v-for="c in seenAt(o.slug)" :key="c.ip" @click="addIp(o, 'sources', c.ip)">{{ c.ip }}<span class="faint"> · {{ c.kind === 'ipfix' ? 'IPFIX' : 'TZSP' }}</span></button>
            </div>
          </div>
        </div>
        <div class="faint small" v-if="form.isNew">{{ t('sites.afterAdd') }}</div>
        <div class="err" v-if="formErr">{{ formErr }}</div>
        <div class="row"><button type="button" class="btn" @click="form = null">{{ t('common.cancel') }}</button>
          <button class="btn primary" :disabled="busy">{{ t('common.save') }}</button></div>
      </form>
    </Modal>

    <Modal :open="!!del" :title="t('sites.delTitle', { name: del ? del.name : '' })" width="440px" @close="del = null">
      <form v-if="del" class="uf" @submit.prevent="doDelete">
        <p>{{ t('sites.delText', { name: del.name }) }}</p>
        <label for="sf-confirm">{{ t('sites.delConfirm', { slug: del.slug }) }}</label>
        <input id="sf-confirm" class="input num" v-model.trim="del.confirm" autocomplete="off" />
        <div class="err" v-if="formErr">{{ formErr }}</div>
        <div class="row"><button type="button" class="btn" @click="del = null">{{ t('common.cancel') }}</button>
          <button class="btn danger" :disabled="del.confirm !== del.slug || busy">{{ t('common.delete') }}</button></div>
      </form>
    </Modal>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import http from '../api.js'
import { ago } from '../format.js'
import { loadSites, pickSite } from '../site.js'
import Modal from './Modal.vue'

const emit = defineEmits(['changed'])
const { t } = useI18n()
const list = ref([])
const unknown = ref([])
const seen = ref([])
const err = ref('')
const form = ref(null)
const formErr = ref('')
const del = ref(null)
const busy = ref(false)
const needSources = ref([])
const loaded = ref(false)

async function load() {
  try {
    const [a, b] = await Promise.all([http.get('/sites'), http.get('/sites/unknown-sources')])
    list.value = a.sites
    unknown.value = b.unknown
    seen.value = b.seen
    loaded.value = true
    err.value = ''
  } catch (e) { err.value = e.message }
}

const siteLabel = slug => (list.value.find(s => s.slug === slug) || {}).name || slug
const seenAt = slug => dedupe(seen.value.filter(x => x.site === slug))
function dedupe(rows) {
  const out = []
  for (const r of rows) if (!out.some(x => x.ip === r.ip)) out.push(r)
  return out.slice(0, 6)
}
// 登记源 IP 时可以点选的地址：没对上站点的来源优先，其次各站点最近实际收到数据的来源
const candidates = computed(() => dedupe([...unknown.value.map(u => ({ ...u, site: '' })), ...seen.value]))

function stateCls(s) {
  if (!s.enabled) return 'grey'
  if (s.ros_enabled && !s.ros_ok && s.ros_last_poll) return 'bad'
  return s.receiving ? 'ok' : 'warn'
}
function stateText(s) {
  return t('sites.state.' + ({ grey: 'off', bad: 'rosDown', warn: 'noFlow', ok: 'ok' })[stateCls(s)])
}
const split = text => (text || '').split(/[\s,，]+/).map(x => x.trim()).filter(Boolean)
function addIp(obj, key, ip) {
  const cur = split(obj[key])
  if (!cur.includes(ip)) obj[key] = [...cur, ip].join(', ')
}

async function openAdd() {
  if (!loaded.value) await load()   // 已有站点要不要补源 IP 取决于站点列表，没加载完不能打开
  formErr.value = ''
  needSources.value = list.value.filter(s => s.enabled && !s.sources.length).map(s => ({ slug: s.slug, name: s.name, sources: '' }))
  form.value = { isNew: true, slug: '', name: '', sources: '', platform_addr: '', enabled: true }
}
function openEdit(s) {
  formErr.value = ''
  needSources.value = []
  form.value = { isNew: false, slug: s.slug, name: s.name, sources: s.sources.join(', '), platform_addr: s.platform_addr, enabled: s.enabled }
}
const body = f => ({ name: f.name, sources: split(f.sources), platform_addr: f.platform_addr || '', enabled: f.enabled })

async function changed() {
  await load()
  await loadSites(http)
  pickSite()
  emit('changed')
}
async function save() {
  formErr.value = ''
  busy.value = true
  const f = form.value
  try {
    if (f.isNew) {
      // 已有站点补的源 IP 和新站点一起提交：后端一起校验、一起保存
      await http.post('/sites', { slug: f.slug, ...body(f), others: needSources.value.map(o => ({ slug: o.slug, sources: split(o.sources) })) })
    } else {
      await http.put(`/sites/${f.slug}`, body(f))
    }
    form.value = null
    await changed()
  } catch (e) { formErr.value = e.message } finally { busy.value = false }
}
async function register(ip, slug) {
  if (!slug) return
  const s = list.value.find(x => x.slug === slug)
  try {
    await http.put(`/sites/${slug}`, { name: s.name, sources: [...s.sources, ip], platform_addr: s.platform_addr || '', enabled: s.enabled })
    await changed()
  } catch (e) { err.value = e.message }
}
function askDel(s) { formErr.value = ''; del.value = { slug: s.slug, name: s.name, confirm: '' } }
async function doDelete() {
  busy.value = true
  try {
    await http.delete(`/sites/${del.value.slug}`, { data: { confirm: del.value.confirm } })
    del.value = null
    await changed()
  } catch (e) { formErr.value = e.message } finally { busy.value = false }
}
onMounted(load)
</script>

<style scoped>
.head { display: grid; gap: 14px; padding-bottom: 6px; }
.nowrap { white-space: nowrap; }
.pad { padding: 0 18px 14px; }
.slug { font-family: var(--cond); }
tr.off td { opacity: .6; }
.unk { border-top: 1px solid var(--line); display: grid; gap: 10px; }
.unk .sec { display: flex; align-items: baseline; gap: 10px; }
.input.sm { height: 30px; padding: 0 8px; font-size: 12.5px; width: auto; }
.uf { display: grid; gap: 8px; }
.uf > label, .other > label { font-size: 13px; color: var(--muted); margin-top: 4px; }
.ck { display: flex; align-items: center; gap: 8px; color: var(--ink) !important; }
.chips { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.ipchip { height: 26px; padding: 0 9px; border-radius: 7px; border: 1px solid var(--line); background: var(--sunk);
  font: 500 12px/1 var(--cond); color: var(--ink); cursor: pointer; white-space: nowrap; flex: none; }
.ipchip:hover { border-color: var(--brand-ink); color: var(--brand-ink); }
.others { display: grid; gap: 8px; padding: 12px; border: 1px dashed var(--line-strong); border-radius: 10px; margin-top: 6px; }
.other { display: grid; gap: 6px; }
.row { display: flex; gap: 10px; justify-content: flex-end; margin-top: 8px; }
</style>
