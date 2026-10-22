<template>
  <!-- 统计卡：白色圆角卡片，标签 + 大数字 + 上下行（与其他卡片同一套样式） -->
  <div class="stat panel">
    <div class="lbl">{{ label }}</div>
    <div class="val num"><slot>{{ value }}</slot></div>
    <template v-if="up != null || down != null">
      <div class="sub">
        <span class="num down">↓ {{ fmt(down) }}</span>
        <span class="num up">↑ {{ fmt(up) }}</span>
      </div>
      <span class="pair"><i class="d" :style="{ flexGrow: down || 0 }" /><i class="u" :style="{ flexGrow: up || 0 }" /></span>
    </template>
    <div class="sub muted" v-else-if="sub">{{ sub }}</div>
  </div>
</template>

<script setup>
import { bytes, rate } from '../format.js'

const props = defineProps({ label: String, value: [String, Number], sub: String, up: Number, down: Number, isRate: Boolean })
const fmt = v => (props.isRate ? rate(v) : bytes(v))
</script>

<style scoped>
.stat { padding: 16px 18px 14px; min-width: 0; display: flex; flex-direction: column; gap: 4px; }
.lbl { color: var(--muted); font-size: 13.5px; }
.val { font-size: 30px; font-weight: 600; letter-spacing: -.01em; line-height: 1.15; color: var(--accent); font-variant-numeric: normal; }
.sub { display: flex; gap: 14px; font-size: 13.5px; flex-wrap: wrap; }
.pair { margin-top: 6px; }
</style>
