<template>
  <!-- 字标：ROS 钢蓝 + DPI 青绿，粗斜体窄字；sub 时下面加一行中文副标题 -->
  <span class="logo" :class="{ big }">
    <Mark :size="big ? 46 : 28" />
    <span class="wm">
      <b v-if="title" class="custom" :title="title">{{ title }}</b>
      <b v-else>ROS<i>DPI</i></b>
      <small v-if="sub">{{ t('app.subtitle') }}</small>
    </span>
  </span>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import Mark from './Mark.vue'

defineProps({ big: Boolean, sub: Boolean, title: String })
const { t } = useI18n()
</script>

<style scoped>
.logo { display: inline-flex; align-items: center; gap: 10px; min-width: 0; max-width: 100%; }
.logo > :first-child { flex-shrink: 0; }
.wm { display: grid; gap: 2px; min-width: 0; }
.wm .custom { font: 600 16px/1.3 var(--sans); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.wm b { font: italic 800 21px/1 var(--cond); letter-spacing: .01em; color: var(--brand-ink); }
.wm b i { color: var(--accent); }
.big .wm b { font-size: 34px; }
small { font-size: 12px; color: var(--muted); letter-spacing: .14em; }
</style>
