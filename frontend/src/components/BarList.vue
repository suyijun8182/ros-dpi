<template>
  <ol class="bars">
    <li v-if="!items.length" class="empty">{{ t('common.empty') }}</li>
    <li v-for="(it, i) in items" :key="it.key">
      <component :is="it.to ? 'router-link' : 'div'" :to="it.to" class="row">
        <span class="rk num" :class="{ top: i < 3 }">{{ i + 1 }}</span>
        <span class="lab">
          <span v-if="it.color" class="chip" :style="{ background: it.color }" />
          <span v-else class="dot" :class="{ on: it.online }" />
          <span class="name">{{ it.label }}</span>
          <span class="sub faint" v-if="it.sub">{{ it.sub }}</span>
        </span>
        <span class="val"><b class="num">{{ bytes(it.value) }}</b><span v-if="total" class="pc num">{{ pct(it.value / total) }}</span></span>
        <!-- 长度 = 相对最大项；颜色按上下行拆成蓝/橙两段 -->
        <span class="rail">
          <span class="track" :style="{ width: Math.max(it.value / max * 100, 0.8) + '%' }">
            <i class="d" :style="{ flexGrow: it.down ?? it.value }" />
            <i class="u" :style="{ flexGrow: it.up ?? 0 }" />
          </span>
        </span>
      </component>
    </li>
  </ol>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { bytes, pct } from '../format.js'

const props = defineProps({ items: { type: Array, default: () => [] }, total: Number })
const { t } = useI18n()
const max = computed(() => Math.max(1, ...props.items.map(i => i.value)))
</script>

<style scoped>
.bars { list-style: none; margin: 0; padding: 0; }
.row {
  display: grid; grid-template-columns: 22px minmax(0, 1fr) auto; align-items: center; column-gap: 10px; row-gap: 5px;
  padding: 7px 6px 9px; margin: 0 -6px; border-radius: var(--r-sm);
}
a.row:hover { background: var(--sunk); }
a.row:hover .name { text-decoration: underline; text-underline-offset: 3px; }
.rk { grid-row: 1 / 3; align-self: start; padding-top: 1px; color: var(--faint); font-size: 14px; font-weight: 600; text-align: center; }
.rk.top { color: var(--ink); }
.lab { display: flex; gap: 8px; align-items: center; min-width: 0; }
.name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 500; }
.sub { font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.val { display: flex; align-items: baseline; gap: 10px; }
.val b { font-size: 16px; font-weight: 600; }
.pc { color: var(--muted); font-size: 13px; min-width: 44px; text-align: right; }
.rail { grid-column: 2 / -1; height: 5px; border-radius: 3px; background: color-mix(in srgb, var(--line) 55%, transparent); }
.track { display: flex; height: 100%; border-radius: 3px; overflow: hidden; }
.track i { display: block; height: 100%; }
.track .d { background: var(--down); }
.track .u { background: var(--up); }
@media (max-width: 480px) { .sub { display: none; } }
</style>
