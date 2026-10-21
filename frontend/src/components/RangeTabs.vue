<template>
  <div class="seg">
    <button v-for="r in list" :key="r" :class="{ on: ui.range === r }" @click="ui.range = r">{{ t('range.' + r) }}</button>
  </div>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import { RANGES, ui } from '../state.js'

defineProps({ list: { type: Array, default: () => RANGES } })
const { t } = useI18n()
</script>
