<template>
  <div ref="el" class="chart" :style="{ height }" />
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart, SankeyChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { ui } from '../state.js'

echarts.use([LineChart, PieChart, BarChart, SankeyChart, GridComponent, TooltipComponent, LegendComponent, CanvasRenderer])

const props = defineProps({ option: Object, height: { type: String, default: '260px' } })
const emit = defineEmits(['click'])
const el = ref(null)
let chart = null
let ro = null

function render() {
  if (!chart || !props.option) return
  chart.setOption(props.option, true)
}

onMounted(() => {
  chart = echarts.init(el.value, null, { renderer: 'canvas' })
  chart.on('click', p => emit('click', p))
  render()
  ro = new ResizeObserver(() => chart && chart.resize())
  ro.observe(el.value)
})

watch(() => props.option, render, { deep: true })
watch(() => ui.theme, render)

onBeforeUnmount(() => {
  ro && ro.disconnect()
  chart && chart.dispose()
  chart = null
})
</script>

<style scoped>
.chart { width: 100%; }
</style>
