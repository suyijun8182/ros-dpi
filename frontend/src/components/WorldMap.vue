<template>
  <!-- 访问目标的流向图：从本地飞向各国，线和气泡越粗越大流量越多；流量最大的几个国家直接标名字（debug11） -->
  <div class="world">
    <Chart v-if="geo" :option="opt" :maps="{ world: geo }" :height="narrow ? '230px' : height" @click="onClick" />
    <div v-else class="empty" :style="{ height }">{{ failed ? t('flow.mapFail') : t('common.loading') }}</div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { flowMapOption } from '../charts.js'
import { countryName } from '../format.js'
import { ui } from '../state.js'
import Chart from './Chart.vue'

const props = defineProps({
  countries: { type: Array, default: () => [] },   // [{cc, bytes}]
  home: { type: String, default: 'CN' },
  active: String,
  height: { type: String, default: '340px' },
})
const emit = defineEmits(['pick'])
const { t, locale } = useI18n()
const geo = shallowRef(null)  // GeoJSON 很大，不做深层响应
const failed = ref(false)
// 窄屏：地图矮一些，标签放到气泡上方、只写国家名，免得被右边裁掉
const mq = window.matchMedia('(max-width: 640px)')
const narrow = ref(mq.matches)
const onMq = e => (narrow.value = e.matches)
onMounted(() => mq.addEventListener('change', onMq))
onUnmounted(() => mq.removeEventListener('change', onMq))

// 形状特殊的国家手工给中心点（海外领土、跨日期变更线、狭长国家）
const FIX = { US: [-98, 39], RU: [96, 61], CN: [104, 34.5], FR: [2.4, 46.6], NO: [9.5, 61], CA: [-102, 57], GB: [-1.8, 52.8],
  NL: [5.5, 52.2], DK: [9.4, 56], NZ: [173, -41.5], JP: [138.5, 36.5], ID: [117, -2], MY: [102, 4], CL: [-71, -33], AU: [134, -25],
  IT: [12.5, 42.8], GR: [22, 39.3], PH: [122, 12], SE: [16, 62.5], FI: [26, 63.5], IN: [79, 22], VN: [106, 16], KR: [127.8, 36.3] }

function centroid(ring) {
  let a = 0, x = 0, y = 0
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const f = ring[j][0] * ring[i][1] - ring[i][0] * ring[j][1]
    a += f
    x += (ring[j][0] + ring[i][0]) * f
    y += (ring[j][1] + ring[i][1]) * f
  }
  return a ? [x / (3 * a), y / (3 * a)] : ring[0]
}
const centers = computed(() => {
  const out = {}
  for (const f of (geo.value && geo.value.features) || []) {
    const g = f.geometry
    const polys = g.type === 'Polygon' ? [g.coordinates] : g.coordinates
    let best = null, size = -1
    for (const p of polys) {
      const xs = p[0].map(c => c[0]), ys = p[0].map(c => c[1])
      const s = (Math.max(...xs) - Math.min(...xs)) * (Math.max(...ys) - Math.min(...ys))
      if (s > size) { size = s; best = p[0] }
    }
    out[f.properties.name] = FIX[f.properties.name] || centroid(best)
  }
  return out
})

onMounted(async () => {
  try {
    window.__rosdpiWorld = window.__rosdpiWorld || fetch('/world.json').then(r => r.json())
    geo.value = await window.__rosdpiWorld
  } catch (e) { failed.value = true }
})
const opt = computed(() => (ui.theme, locale.value, flowMapOption(
  props.countries.filter(c => c.cc && c.cc !== '-').map(c => ({ ...c, name: countryName(c.cc) || c.cc })),
  props.home, centers.value, props.active, countryName(props.home) || props.home, narrow.value)))
function onClick(p) {
  const cc = p.data && p.data.cc ? p.data.cc : p.componentType === 'geo' ? p.name : null
  if (cc) emit('pick', cc)
}
</script>

<style scoped>
.world { min-width: 0; }
.empty { display: flex; align-items: center; justify-content: center; }
</style>
