<template>
  <!-- 品牌标记“七层”：三层网络分层叠起来，最上面的应用层点亮（青绿）。颜色固定，深浅主题下保持一致 -->
  <svg :width="size" :height="size" viewBox="0 0 64 64" aria-hidden="true">
    <rect x="2" y="2" width="60" height="60" rx="15" fill="#2b6583" />
    <!-- 底层：IP -->
    <path d="M12 42.5 L32 52 L32 56 L12 46.5 Z" fill="#c4d8e2" />
    <path d="M32 52 L52 42.5 L52 46.5 L32 56 Z" fill="#a3c1d0" />
    <path d="M32 33 L52 42.5 L32 52 L12 42.5 Z" fill="#eaf2f6" />
    <!-- 中层：传输 -->
    <path d="M12 30.5 L32 40 L32 44 L12 34.5 Z" fill="#477f9d" />
    <path d="M32 40 L52 30.5 L52 34.5 L32 44 Z" fill="#3a6f8b" />
    <path d="M32 21 L52 30.5 L32 40 L12 30.5 Z" fill="#6aa0bd" />
    <!-- 顶层：应用 -->
    <path d="M12 18.5 L32 28 L32 32 L12 22.5 Z" fill="#2db3b4" />
    <path d="M32 28 L52 18.5 L52 22.5 L32 32 Z" fill="#22999b" />
    <path d="M32 9 L52 18.5 L32 28 L12 18.5 Z" fill="#4fd0cf" />
    <circle cx="32" cy="18.5" r="3.4" fill="#ffffff" />
  </svg>
</template>

<script setup>
defineProps({ size: { type: Number, default: 24 } })
</script>
