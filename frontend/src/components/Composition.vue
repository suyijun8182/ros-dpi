<template>
  <!-- 流量构成：维盟式实心饼图 + 右侧竖排可翻页图例。drill 时选中大类后改画它的小类 -->
  <div class="comp">
    <Chart v-if="items.length" :option="opt" :height="height" @click="onChart" />
    <div v-else class="empty">{{ t('common.empty') }}</div>
    <div v-if="drill && group" class="crumb">
      <span class="sw" :style="{ background: groupColor(group.id) }" />{{ groupName(group) }}
      <span class="faint">{{ bytes(group.total) }} · {{ pct(group.total / sum) }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { pieOption } from '../charts.js'
import { bytes, CAT_GROUP, catHex, catName, GROUPS, groupColor, groupHex, groupName, pct } from '../format.js'
import { ui } from '../state.js'
import Chart from './Chart.vue'

const props = defineProps({
  groups: { type: Array, default: () => [] },
  clickable: Boolean,
  active: String,                       // 当前选中的大类
  drill: Boolean,                       // 选中大类后显示它的小类
  height: { type: String, default: '300px' },
})
const emit = defineEmits(['pick'])
const { t, locale } = useI18n()
const gs = computed(() => props.groups.filter(g => g.total > 0))
const sum = computed(() => gs.value.reduce((s, g) => s + g.total, 0) || 1)
const group = computed(() => (props.drill && props.active ? gs.value.find(g => g.id === props.active) : null))
// 和维盟一样按固定顺序画（不按大小排）：配色是 9 色循环，同色的两个大类相隔 9 位，扇区不会挨在一起
const CAT_ORDER = Object.keys(CAT_GROUP)
const byOrder = (list, order) => [...list].sort((x, y) => order.indexOf(x.id) - order.indexOf(y.id))
const items = computed(() => (group.value
  ? byOrder(group.value.children.filter(c => c.total > 0), CAT_ORDER).map(c => ({ id: c.id, kind: 'cat', name: catName(c), value: c.total, color: catHex(c.id) }))
  : byOrder(gs.value, GROUPS).map(g => ({ id: g.id, kind: 'group', name: groupName(g), value: g.total, color: groupHex(g.id) }))))
const mq = window.matchMedia('(max-width: 640px)')
const narrow = ref(mq.matches)
const onMq = e => (narrow.value = e.matches)
onMounted(() => mq.addEventListener('change', onMq))
onUnmounted(() => mq.removeEventListener('change', onMq))
const opt = computed(() => (ui.theme, locale.value, pieOption(items.value, { narrow: narrow.value })))

function onChart(p) {
  if (!props.clickable || !p.data) return
  if (group.value) emit('pick', { group: group.value.id, cat: p.data.id })
  else emit('pick', { group: p.data.id })
}
</script>

<style scoped>
.comp { position: relative; max-width: 760px; }
.crumb { display: flex; align-items: center; gap: 8px; font-size: 13px; margin-top: -4px; }
.sw { width: 10px; height: 10px; border-radius: 3px; }
</style>
