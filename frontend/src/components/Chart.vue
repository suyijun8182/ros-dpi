<template>
  <div ref="el" class="chart" :style="{ height }" />
</template>

<script setup>
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, EffectScatterChart, GaugeChart, LineChart, LinesChart, MapChart, PieChart, ScatterChart, TreemapChart } from 'echarts/charts'
import { GeoComponent, GridComponent, LegendComponent, TooltipComponent, VisualMapComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { ui } from '../state.js'

echarts.use([LineChart, PieChart, BarChart, GaugeChart, TreemapChart, MapChart, LinesChart, ScatterChart, EffectScatterChart, GridComponent, TooltipComponent, LegendComponent,
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

// option 由父组件的 computed 生成（每次重算都是新对象），浅比较即可；deep 遍历整个配置纯属浪费
watch(() => props.option, render)
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
