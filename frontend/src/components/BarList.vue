<template>
  <ol class="bars">
    <li v-if="!items.length" class="empty">{{ t('common.empty') }}</li>
    <li v-for="it in items" :key="it.key">
      <component :is="it.to ? 'router-link' : 'div'" :to="it.to" class="row">
        <span class="lab">
          <span v-if="it.color" class="chip" :style="{ background: it.color }" />
          <span v-else class="dot" :class="{ on: it.online }" />
          <span class="name">{{ it.label }}</span>
          <span class="sub faint" v-if="it.sub">{{ it.sub }}</span>
        </span>
        <span class="val num">{{ bytes(it.value) }}</span>
        <!-- 长度 = 相对最大项；颜色按上下行拆成蓝/橙两段 -->
        <span class="track" :style="{ width: Math.max(it.value / max * 100, 0.8) + '%' }">
          <i class="d" :style="{ flexGrow: it.down ?? it.value }" />
          <i class="u" :style="{ flexGrow: it.up ?? 0 }" />
        </span>
      </component>
    </li>
  </ol>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { bytes } from '../format.js'

const props = defineProps({ items: { type: Array, default: () => [] } })
const { t } = useI18n()
const max = computed(() => Math.max(1, ...props.items.map(i => i.value)))
</script>

<style scoped>
.bars { list-style: none; margin: 0; padding: 0; }
.row {
  display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; column-gap: 12px; row-gap: 6px;
  padding: 8px 6px 10px; margin: 0 -6px; border-radius: var(--r-sm);
}
a.row:hover { background: var(--sunk); }
a.row:hover .name { text-decoration: underline; text-underline-offset: 3px; }
.lab { display: flex; gap: 8px; align-items: center; min-width: 0; }
.name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-weight: 500; }
.sub { font-size: 13px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.val { font-size: 16px; font-weight: 600; }
.track { grid-column: 1 / -1; display: flex; height: 4px; border-radius: 2px; overflow: hidden; }
.track i { display: block; height: 100%; }
.track .d { background: var(--down); }
.track .u { background: var(--up); }
</style>
