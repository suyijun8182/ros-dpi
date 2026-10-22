<template>
  <div class="panel">
    <div class="panel-h">
      <h2>{{ title }}</h2><span v-if="sub" class="faint small">{{ sub }}</span>
      <span class="sp" />
      <div class="seg" v-if="groups && groups.series.length" role="tablist">
        <button v-for="m in ['groups', 'pair']" :key="m" :class="{ on: mode === m }" role="tab" :aria-selected="mode === m"
                @click="ui.trendMode = m">{{ t('chart.mode.' + m) }}</button>
      </div>
    </div>
    <div class="panel-b"><Chart :option="opt" :height="height" /></div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { stackedOption, trendOption } from '../charts.js'
import { ui } from '../state.js'
import Chart from './Chart.vue'

const props = defineProps({
  title: String, sub: String,
  points: { type: Array, default: () => [] },  // [{ts, up, down}]
  groups: Object,                              // trend_groups：{ts, series, gran}
  gran: { type: String, default: 'hour' },
  height: { type: String, default: '280px' },
})
const { t, locale } = useI18n()
const mode = computed(() => (props.groups && props.groups.series.length ? ui.trendMode : 'pair'))
const opt = computed(() => (ui.theme, locale.value,
  mode.value === 'groups' ? stackedOption(props.groups) : trendOption(props.points, props.gran)))
</script>

<style scoped>
.seg button { font-size: 13px; padding: 4px 8px 6px; }
</style>
