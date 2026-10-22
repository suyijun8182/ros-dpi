<template>
  <!-- 访问目标的世界地图：颜色深浅 = 流量（对数刻度），点击国家只看该国的目标（debug10） -->
  <div class="world">
    <Chart v-if="geo" :option="opt" :maps="{ world: geo }" :height="height" @click="onClick" />
    <div v-else class="empty" :style="{ height }">{{ failed ? t('flow.mapFail') : t('common.loading') }}</div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { mapOption } from '../charts.js'
import { ui } from '../state.js'
import Chart from './Chart.vue'

const props = defineProps({ countries: { type: Array, default: () => [] }, active: String, height: { type: String, default: '340px' } })
const emit = defineEmits(['pick'])
const { t, locale } = useI18n()
const geo = shallowRef(null)  // GeoJSON 很大，不做深层响应
const failed = ref(false)

onMounted(async () => {
  try {
    window.__rosdpiWorld = window.__rosdpiWorld || fetch('/world.json').then(r => r.json())
    geo.value = await window.__rosdpiWorld
  } catch (e) { failed.value = true }
})
const opt = computed(() => (ui.theme, locale.value, mapOption(props.countries.filter(c => c.cc && c.cc !== '-'), props.active)))
function onClick(p) { if (p.name) emit('pick', p.name) }
</script>

<style scoped>
.world { min-width: 0; }
.empty { display: flex; align-items: center; justify-content: center; }
</style>
