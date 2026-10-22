<template>
  <!-- 应用构成的矩形树图：大类分块、块内按小类细分，面积 = 流量。比饼图更省地方，一眼能看两层（debug10） -->
  <div>
    <Chart v-if="data.length" :option="opt" :height="height" @click="onClick" />
    <div v-else class="empty">{{ t('common.empty') }}</div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { treemapOption } from '../charts.js'
import { catHex, catName, groupHex, groupName } from '../format.js'
import { ui } from '../state.js'
import Chart from './Chart.vue'

const props = defineProps({
  groups: { type: Array, default: () => [] },   // [{id, total, children: [{id, total, ...}]}]
  group: String,                                 // 只画这个大类（下钻后）
  height: { type: String, default: '320px' },
})
const emit = defineEmits(['pick'])
const { t, locale } = useI18n()
const data = computed(() => {
  const gs = props.groups.filter(g => g.total > 0 && (!props.group || g.id === props.group))
  return gs.map(g => ({
    id: g.id, kind: 'group', name: groupName(g), value: g.total, color: groupHex(g.id),
    children: (g.children || []).filter(c => c.total > 0)
      .map(c => ({ id: c.id, kind: 'cat', group: g.id, name: catName(c), value: c.total, color: catHex(c.id) })),
  }))
})
const opt = computed(() => (ui.theme, locale.value, treemapOption(data.value)))

function onClick(p) {
  const d = p.data
  if (!d) return
  emit('pick', d.kind === 'cat' ? { group: d.group, cat: d.id } : { group: d.id })
}
</script>
