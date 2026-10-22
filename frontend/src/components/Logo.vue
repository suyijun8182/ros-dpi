<template>
  <!-- 字标：ROS 钢蓝 + DPI 青绿，粗斜体窄字；sub 时下面加一行中文副标题 -->
  <span class="logo" :class="{ big }">
    <Mark :size="big ? 46 : 28" />
    <span class="wm">
      <b>ROS<i>DPI</i></b>
      <small v-if="sub">{{ t('app.subtitle') }}</small>
    </span>
  </span>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import Mark from './Mark.vue'

defineProps({ big: Boolean, sub: Boolean })
const { t } = useI18n()
</script>

<style scoped>
.logo { display: inline-flex; align-items: center; gap: 10px; }
.wm { display: grid; gap: 2px; }
.wm b { font: italic 800 21px/1 var(--cond); letter-spacing: .01em; color: var(--brand-ink); }
.wm b i { color: var(--accent); }
.big .wm b { font-size: 34px; }
small { font-size: 12px; color: var(--muted); letter-spacing: .14em; }
</style>
