<template>
  <!-- 流量构成条：按分类占比横向切分，像一束线缆的截面 -->
  <div class="spec">
    <div class="bar" role="img" :aria-label="aria">
      <component :is="clickable ? 'button' : 'span'" v-for="c in segs" :key="c.id" class="seg-i"
                 :style="{ flexGrow: c.total, background: catColor(c.id) }"
                 :title="`${catName(c)}  ${bytes(c.total)}  ${pct(c.total / sum)}`"
                 @click="clickable && $emit('pick', c.id)" />
      <span v-if="!segs.length" class="seg-i none" />
    </div>
    <ul class="legend" v-if="legend && segs.length">
      <li v-for="c in segs.slice(0, legendMax)" :key="c.id">
        <component :is="clickable ? 'button' : 'span'" class="lg" @click="clickable && $emit('pick', c.id)">
          <span class="chip" :style="{ background: catColor(c.id) }" />
          <span>{{ catName(c) }}</span>
          <span class="num faint">{{ pct(c.total / sum, 0) }}</span>
        </component>
      </li>
    </ul>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { bytes, catColor, catName, pct } from '../format.js'

const props = defineProps({
  cats: { type: Array, default: () => [] },
  legend: { type: Boolean, default: true },
  legendMax: { type: Number, default: 12 },
  clickable: Boolean,
  height: { type: Number, default: 14 },
})
defineEmits(['pick'])
const segs = computed(() => props.cats.filter(c => c.total > 0))
const sum = computed(() => segs.value.reduce((s, c) => s + c.total, 0) || 1)
const aria = computed(() => segs.value.slice(0, 6).map(c => `${catName(c)} ${pct(c.total / sum.value, 0)}`).join(', '))
</script>

<style scoped>
.bar { display: flex; gap: 2px; height: v-bind('props.height + "px"'); }
.seg-i { min-width: 3px; height: 100%; border: 0; padding: 0; border-radius: 2px; display: block; }
button.seg-i { cursor: pointer; }
button.seg-i:hover { filter: brightness(1.12); }
.seg-i.none { flex: 1; background: var(--line); }
.legend { list-style: none; margin: 12px 0 0; padding: 0; display: flex; flex-wrap: wrap; gap: 6px 18px; }
.lg { display: inline-flex; align-items: center; gap: 7px; font-size: 13.5px; background: none; border: 0; padding: 0; color: var(--ink); }
button.lg { cursor: pointer; }
button.lg:hover { text-decoration: underline; text-underline-offset: 3px; }
</style>
