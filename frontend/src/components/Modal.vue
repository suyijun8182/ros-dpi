<template>
  <Teleport to="body">
    <div v-if="open" class="ov" @click.self="$emit('close')" @keydown.esc="$emit('close')">
      <div class="box" role="dialog" aria-modal="true" :aria-label="title" :style="{ maxWidth: width }">
        <div class="hd"><h2>{{ title }}</h2><span class="sp" /><slot name="tools" />
          <button class="btn ghost x" @click="$emit('close')" :aria-label="t('common.close')"><Icon name="close" /></button></div>
        <div class="bd"><slot /></div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { useI18n } from 'vue-i18n'
import Icon from './Icon.vue'

defineProps({ open: Boolean, title: String, width: { type: String, default: '760px' } })
defineEmits(['close'])
const { t } = useI18n()
</script>

<style scoped>
.ov { position: fixed; inset: 0; background: rgba(12, 18, 28, .42); z-index: 100; display: grid; place-items: center; padding: 16px; }
.box { width: 100%; max-height: calc(100vh - 32px); overflow: auto; background: var(--panel); border-radius: 16px; box-shadow: 0 20px 60px rgba(0, 0, 0, .25); }
.hd { display: flex; align-items: center; gap: 10px; padding: 16px 16px 6px 22px; position: sticky; top: 0; background: var(--panel); z-index: 1; }
.hd h2 { margin: 0; font: 600 17px/1.3 var(--sans); }
.sp { flex: 1; }
.x { width: 34px; padding: 0; }
.bd { padding: 6px 22px 22px; }
</style>
