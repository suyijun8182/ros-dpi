<template>
  <!-- DPI 协议表：应用统计页和「DPI 协议详情」弹窗共用（版式同维盟） -->
  <div class="tbl-wrap">
    <table class="tbl dpi">
      <thead><tr>
        <th class="rk m-hide"><button class="th-b" :title="t('apps.dpi.fixedOrder')" @click="sortBy('')">#<span class="arr" :class="{ on: !sortK }">▲</span></button></th>
        <th v-for="c in COLS" :key="c.k" :class="c.cls" :aria-sort="sortK === c.k ? (sortDesc ? 'descending' : 'ascending') : 'none'">
          <button class="th-b" @click="sortBy(c.k)">{{ t(c.label) }}<span class="arr" :class="{ on: sortK === c.k }">{{ sortK === c.k && !sortDesc ? '▲' : '▼' }}</span></button></th>
        <th class="r">{{ t('common.details') }}</th>
      </tr></thead>
      <tbody>
        <tr v-for="(r, i) in sorted" :key="r.id" class="link" @click="$emit('open', r)">
          <td class="rk num faint m-hide">{{ i + 1 }}</td>
          <td class="nm"><span class="tag"><span class="chip" :style="{ background: r.color }" />{{ r.label }}</span>
            <div class="faint small" v-if="r.sub">{{ r.sub }}</div></td>
          <td class="r num m-hide"><span :class="r.rate_up ? 'up' : 'faint'">{{ rate(r.rate_up) }}</span><span class="sh">{{ share(r.rate_up, sum.rate_up) }}</span></td>
          <td class="r num"><span :class="r.rate_down ? 'down' : 'faint'">{{ rate(r.rate_down) }}</span><span class="sh">{{ share(r.rate_down, sum.rate_down) }}</span></td>
          <td class="r num m-hide">{{ bytes(r.up) }}<span class="sh">{{ share(r.up, sum.up) }}</span></td>
          <td class="r num"><b>{{ bytes(r.down) }}</b><span class="sh">{{ share(r.down, sum.down) }}</span></td>
          <td class="r"><button class="lk more-l" :disabled="r.kind !== 'app' && !r.n" @click.stop="$emit('open', r)">{{ r.kind === 'app' ? t('apps.dpi.appPage') : t('apps.dpi.drill') }}</button></td>
        </tr>
      </tbody>
    </table>
    <div v-if="!rows.length" class="empty">{{ t('common.empty') }}</div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { bytes, pct, rate } from '../format.js'

const props = defineProps({ rows: { type: Array, required: true } })
defineEmits(['open'])
const { t } = useI18n()

const COLS = [
  { k: 'label', label: 'apps.dpi.proto', cls: '' },
  { k: 'rate_up', label: 'apps.dpi.upRateCol', cls: 'r m-hide' },
  { k: 'rate_down', label: 'apps.dpi.downRateCol', cls: 'r' },
  { k: 'up', label: 'apps.dpi.upBytesCol', cls: 'r m-hide' },
  { k: 'down', label: 'apps.dpi.downBytesCol', cls: 'r' },
]
// 默认按识别库里的固定顺序（序号）；点列头按该列排序，再点序号回到固定顺序
const sortK = ref('')
const sortDesc = ref(true)
function sortBy(k) {
  if (!k) { sortK.value = ''; return }
  if (sortK.value === k) sortDesc.value = !sortDesc.value
  else { sortK.value = k; sortDesc.value = k !== 'label' }
}
const sorted = computed(() => {
  const k = sortK.value, dir = sortDesc.value ? -1 : 1
  if (!k) return props.rows
  return [...props.rows].sort((a, b) => (k === 'label' ? a.label.localeCompare(b.label, 'zh') : a[k] - b[k]) * dir)
})
const sum = computed(() => levelSum(props.rows))
const share = (v, total) => ` | ${pct(total ? v / total : 0, 2)}`
</script>

<script>
/** 这一级的合计（上传 / 下载数据与速度） */
export function levelSum(rows) {
  return rows.reduce((o, r) => {
    for (const k of ['up', 'down', 'rate_up', 'rate_down']) o[k] += r[k]
    return o
  }, { up: 0, down: 0, rate_up: 0, rate_down: 0 })
}
</script>

<style scoped>
.nm { font-weight: 500; }
.rk { width: 36px; padding-right: 0; }
.dpi td.num { white-space: nowrap; }
.sh { color: var(--faint); font-size: 12px; }
.th-b { background: none; border: 0; padding: 0; font: inherit; color: inherit; cursor: pointer; display: inline-flex; gap: 4px; align-items: center; }
.arr { font-size: 9px; color: var(--line-strong); }
.arr.on { color: var(--brand-ink); }
.lk { background: none; border: 0; padding: 0; font: inherit; color: var(--brand-ink); cursor: pointer; }
.lk:disabled { color: var(--faint); cursor: default; }
.more-l { font-size: 13px; }
@media (max-width: 640px) { .sh { display: block; } }
</style>
