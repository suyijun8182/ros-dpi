<template>
  <!-- 行为标签：高档红、中档黄；悬停看依据 -->
  <span class="tags">
    <span v-for="x in shown" :key="x.id" class="pill" :class="x.level === 'high' ? 'bad' : 'warn'" :title="detail(x)">{{ t('tag.' + x.id) }}</span>
    <span v-if="tags.length > max" class="faint small">+{{ tags.length - max }}</span>
    <span v-if="!tags.length" class="faint small">-</span>
  </span>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { appName } from '../format.js'
import { hours } from '../scenario.js'

const props = defineProps({ tags: { type: Array, default: () => [] }, max: { type: Number, default: 6 } })
const { t } = useI18n()
const shown = computed(() => props.tags.slice(0, props.max))
const detail = x => {
  const v = x.unit === 'days' ? t('people.days', { n: x.value }) : hours(x.value)
  const apps = (x.apps || []).map(a => `${appName(a)} ${hours(a.seconds)}`).join('、')
  return `${t('tag.' + x.id)}：${v}${apps ? '（' + apps + '）' : ''}`
}
</script>

<style scoped>
.tags { display: inline-flex; gap: 4px; flex-wrap: wrap; align-items: center; }
.tags .pill { height: 20px; font-size: 11px; }
</style>
