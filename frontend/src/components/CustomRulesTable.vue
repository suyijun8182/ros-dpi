<script setup>
import { computed, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { appName } from '../format.js'

const props = defineProps({ rules: { type: Array, required: true }, apps: { type: Array, required: true }, editable: Boolean })
const emit = defineEmits(['edit', 'delete'])
const { t } = useI18n()
const pattern = shallowRef('')
const target = shallowRef('')
const page = shallowRef(1)
const pageSize = shallowRef(20)
const appsById = computed(() => new Map(props.apps.map(a => [a.id, a])))
const label = id => appsById.value.has(id) ? appName(appsById.value.get(id)) : id
const filtered = computed(() => {
  const p = pattern.value.trim().toLowerCase()
  const q = target.value.trim().toLowerCase()
  return props.rules.filter(r => {
    const app = appsById.value.get(r.app_id)
    return r.pattern.toLowerCase().includes(p) &&
      [r.app_id, app?.name, app?.name_en].some(value => (value || '').toLowerCase().includes(q))
  })
})
const pages = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize.value)))
const rows = computed(() => filtered.value.slice((page.value - 1) * pageSize.value, page.value * pageSize.value))
watch([pattern, target, pageSize], () => { page.value = 1 })
watch(pages, value => { page.value = Math.min(page.value, value) })
</script>

<template>
  <div class="custom-rules">
    <div class="panel-b filters">
      <label>{{ t('rules.pattern') }}<input class="input" v-model="pattern" :placeholder="t('rules.searchPattern')" /></label>
      <label>{{ t('rules.target') }}<input class="input" v-model="target" :placeholder="t('rules.searchTarget')" /></label>
    </div>
    <div class="tbl-wrap">
      <table class="tbl">
        <thead><tr><th>{{ t('rules.kind') }}</th><th>{{ t('rules.pattern') }}</th><th>{{ t('rules.target') }}</th><th /></tr></thead>
        <tbody>
          <tr v-for="r in rows" :key="r.id">
            <td><span class="tag">{{ t('rules.kinds.' + r.kind) }}</span></td>
            <td class="addr">{{ r.pattern }}</td>
            <td>{{ label(r.app_id) }} <span v-if="r.share" class="pill grey" :title="t('rules.cm.share')">{{ t('rules.cm.shared1') }}</span></td>
            <td class="r acts"><template v-if="editable">
              <button class="btn sm" @click="emit('edit', r)">{{ t('common.edit') }}</button>
              <button class="btn sm danger" @click="emit('delete', r)">{{ t('common.delete') }}</button>
            </template></td>
          </tr>
        </tbody>
      </table>
      <div v-if="!rows.length" class="empty">{{ t('common.empty') }}</div>
    </div>
    <div class="panel-b pagination">
      <span class="small muted" role="status">{{ t('rules.pageInfo', { page, pages, n: filtered.length }) }}</span>
      <label>{{ t('rules.pageSize') }}
        <select class="input" v-model.number="pageSize"><option v-for="n in [20, 50, 100]" :key="n" :value="n">{{ n }}</option></select>
      </label>
      <button class="btn sm" :disabled="page <= 1" @click="page--">{{ t('rules.prevPage') }}</button>
      <button class="btn sm" :disabled="page >= pages" @click="page++">{{ t('rules.nextPage') }}</button>
    </div>
  </div>
</template>

<style scoped>
.filters { display: flex; flex-wrap: wrap; gap: 10px; }
.filters label { display: grid; gap: 6px; flex: 1 1 160px; min-width: 0; font-size: 13px; }
.pagination { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; border-top: 1px solid var(--line); }
.pagination label { display: flex; align-items: center; gap: 6px; font-size: 13px; }
.pagination .input { width: 70px; }
.acts { white-space: nowrap; }
</style>
