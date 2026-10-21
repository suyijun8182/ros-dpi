<template>
  <div class="stat">
    <div class="lbl">{{ label }}</div>
    <div class="val num"><slot>{{ value }}</slot></div>
    <template v-if="up != null || down != null">
      <div class="sub">
        <span><span class="num down">↓ {{ fmt(down) }}</span></span>
        <span><span class="num up">↑ {{ fmt(up) }}</span></span>
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
/* 不做卡片：顶部一条细线分隔，数字本身就是视觉重点 */
.stat { padding: 12px 0 4px; border-top: 2px solid var(--ink); min-width: 0; }
.lbl { color: var(--muted); font-size: 14px; }
.val { font-size: 34px; font-weight: 600; margin: 2px 0 6px; letter-spacing: -.02em; line-height: 1.1; }
.sub { display: flex; gap: 16px; font-size: 14.5px; flex-wrap: wrap; margin-bottom: 8px; }
</style>
