<template>
  <div ref="el" class="chart" :style="{ height }" />
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, GaugeChart, LineChart, MapChart, PieChart, TreemapChart } from 'echarts/charts'
import { GeoComponent, GridComponent, LegendComponent, TooltipComponent, VisualMapComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { ui } from '../state.js'

echarts.use([LineChart, PieChart, BarChart, GaugeChart, TreemapChart, MapChart, GridComponent, TooltipComponent, LegendComponent,
  GeoComponent, VisualMapComponent, CanvasRenderer])

// maps：要用的地图 GeoJSON（{名字: geojson}），在这里注册，保证和画图用的是同一个 echarts
const props = defineProps({ option: Object, height: { type: String, default: '260px' }, maps: Object })
const emit = defineEmits(['click'])
const el = ref(null)
let chart = null
let ro = null

function render() {
  if (!chart || !props.option) return
  for (const [name, geo] of Object.entries(props.maps || {})) if (!echarts.getMap(name)) echarts.registerMap(name, geo)
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
