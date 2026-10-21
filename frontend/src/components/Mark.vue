<template>
  <!-- 品牌标记：RJ45 的四对线色（橙、绿、蓝、棕） -->
  <svg :width="size" :height="size" viewBox="0 0 24 24" aria-hidden="true">
    <rect x="3" y="4" width="3" height="16" rx="1.5" fill="var(--pair-orange)" />
    <rect x="8" y="7" width="3" height="13" rx="1.5" fill="var(--pair-green)" />
    <rect x="13" y="2" width="3" height="18" rx="1.5" fill="var(--pair-blue)" />
    <rect x="18" y="10" width="3" height="10" rx="1.5" fill="var(--pair-brown)" />
  </svg>
</template>

<script setup>
defineProps({ size: { type: Number, default: 24 } })
</script>
