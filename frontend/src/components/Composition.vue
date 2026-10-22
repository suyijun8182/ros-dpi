<template>
  <!-- 流量构成：左侧双层环图（大类 / 小类），右侧是带数值的排行表，环图只负责"一眼看比例" -->
  <div class="comp" :class="{ compact }">
    <div class="ring">
      <Chart v-if="gs.length" :option="opt" :height="compact ? '200px' : '236px'" @click="onChart" />
      <div v-else class="ring-empty" />
      <div class="center">
        <div class="c-v num">{{ bytes(sum) }}</div>
        <div class="c-l">{{ centerLabel || t('overview.mix') }}</div>
      </div>
    </div>
    <table class="lg" v-if="gs.length">
      <tbody>
        <template v-for="(g, i) in gs" :key="g.id">
          <tr class="g" :class="{ link: clickable, on: active === g.id }" @click="clickable && $emit('pick', { group: g.id })">
            <td class="nm"><span class="sw" :style="{ background: groupColor(g.id) }" />{{ groupName(g) }}</td>
            <td class="r num">{{ bytes(g.total) }}</td>
            <td class="r num pc">{{ pct(g.total / sum) }}</td>
            <td class="bar"><i :style="{ width: (g.total / max * 100) + '%', background: groupColor(g.id) }" /></td>
          </tr>
          <!-- 小类明细：宽面板里展开前 4 个大类，其余点开再看，避免表格过长 -->
          <tr class="sub" v-if="compact ? active === g.id : (i < 4 || active === g.id)">
            <td colspan="4">
              <component :is="clickable ? 'button' : 'span'" v-for="c in g.children.filter(x => x.total > 0).slice(0, compact ? 8 : 5)" :key="c.id"
                         class="cat" :class="{ on: activeCat === c.id }" @click.stop="clickable && $emit('pick', { group: g.id, cat: c.id })">
                <span class="chip" :style="{ background: catColor(c.id) }" />{{ catName(c) }} <span class="faint num">{{ pct(c.total / sum, 0) }}</span>
              </component>
            </td>
          </tr>
        </template>
      </tbody>
    </table>
    <div v-else class="empty">{{ t('common.empty') }}</div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { donutOption } from '../charts.js'
import { bytes, catColor, catName, groupColor, groupName, pct } from '../format.js'
import { ui } from '../state.js'
import Chart from './Chart.vue'

const props = defineProps({
  groups: { type: Array, default: () => [] },
  clickable: Boolean,
  compact: Boolean,       // 窄面板里用：小类只在选中大类时展开
  active: String,         // 当前筛选的大类
  activeCat: String,
  centerLabel: String,
})
const emit = defineEmits(['pick'])
const { t, locale } = useI18n()
const gs = computed(() => props.groups.filter(g => g.total > 0))
const sum = computed(() => gs.value.reduce((s, g) => s + g.total, 0) || 0)
const max = computed(() => Math.max(1, ...gs.value.map(g => g.total)))
const opt = computed(() => (ui.theme, locale.value, donutOption(gs.value)))

function onChart(p) {
  if (!props.clickable || !p.data) return
  if (p.data.kind === 'group') emit('pick', { group: p.data.id })
  else {
    const g = gs.value.find(x => x.children.some(c => c.id === p.data.id))
    emit('pick', { group: g && g.id, cat: p.data.id })
  }
}
</script>

<style scoped>
.comp { display: grid; grid-template-columns: 236px minmax(0, 1fr); gap: 12px 28px; align-items: center; }
.comp.compact { grid-template-columns: 200px minmax(0, 1fr); gap: 8px 18px; }
.ring { position: relative; }
.ring-empty { height: 200px; border-radius: 50%; border: 18px solid var(--line); margin: 18px; }
/* 环心：总量。pointer-events 关掉，不挡住环图的悬停 */
.center { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; pointer-events: none; text-align: center; }
.c-v { font-size: 20px; font-weight: 600; line-height: 1.1; font-variant-numeric: normal; }
.compact .c-v { font-size: 17px; }
.c-l { color: var(--muted); font-size: 12px; margin-top: 2px; }

.lg { width: 100%; border-collapse: collapse; font-size: 14px; }
.lg td { padding: 3px 6px; white-space: nowrap; }
.lg tr.g td { padding-top: 5px; }
.lg tr.g.link { cursor: pointer; }
.lg tr.g.link:hover td { background: var(--sunk); }
.lg tr.g.on td { background: var(--sunk); }
.lg tr.g td:first-child { border-radius: var(--r-sm) 0 0 var(--r-sm); }
.lg tr.g td:last-child { border-radius: 0 var(--r-sm) var(--r-sm) 0; }
.nm { font-weight: 500; display: flex; align-items: center; gap: 8px; }
.sw { width: 10px; height: 10px; border-radius: 3px; flex: none; }
.r { text-align: right; }
.pc { color: var(--muted); width: 56px; }
.bar { width: 26%; min-width: 60px; }
.bar i { display: block; height: 6px; border-radius: 3px; min-width: 2px; }
.sub td { padding: 0 6px 3px 24px; white-space: normal; line-height: 1.4; }
.cat { display: inline-flex; align-items: center; gap: 5px; margin: 0 14px 0 0; font-size: 12.5px; color: var(--muted); background: none; border: 0; padding: 0; font-family: inherit; }
button.cat { cursor: pointer; }
button.cat:hover, .cat.on { color: var(--ink); text-decoration: underline; text-underline-offset: 3px; }
.cat .chip { height: 10px; width: 4px; }

@media (max-width: 640px) {
  .comp, .comp.compact { grid-template-columns: 1fr; }
  .ring { max-width: 260px; margin: 0 auto; width: 100%; }
  .bar { display: none; }
}
</style>
