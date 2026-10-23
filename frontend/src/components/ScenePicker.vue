<template>
  <!-- 使用场景（全局）：家庭 / 企业。切换后菜单、人员页、审计模板的称呼和默认值一起变 -->
  <div class="panel">
    <div class="panel-h"><h2>{{ t('people.scenario') }}</h2><span class="faint small">{{ t('people.scenarioHint') }}</span></div>
    <div class="panel-b">
      <div class="scn" role="radiogroup" :aria-label="t('people.scenario')">
        <label v-for="k in ['home', 'enterprise']" :key="k" class="scn-c" :class="{ on: scene.id === k }">
          <input type="radio" name="scene" :value="k" :checked="scene.id === k" :disabled="busy" @change="pick(k)" />
          <Icon :name="k === 'home' ? 'people' : 'users'" :size="22" />
          <div>
            <b>{{ t('scn.' + k + '.name') }}</b>
            <span class="faint small">{{ t('scn.' + k + '.desc') }}</span>
            <span class="small words">{{ t('scn.' + k + '.nav') }} · {{ t('scn.' + k + '.dept') }} · {{ t('scn.' + k + '.workTime') }}</span>
          </div>
        </label>
      </div>
      <div class="small okc" v-if="done" role="status">{{ t('people.sceneSwitched', { x: t('scn.' + scene.id + '.name') }) }}</div>
      <div class="err" v-if="err">{{ err }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { scene, setScene } from '../scenario.js'
import Icon from './Icon.vue'

const emit = defineEmits(['changed'])
const { t } = useI18n()
const busy = ref(false)
const done = ref(false)
const err = ref('')

async function pick(k) {
  if (k === scene.id) return
  err.value = ''
  busy.value = true
  try {
    emit('changed', await setScene(k))
    done.value = true
    setTimeout(() => (done.value = false), 3000)
  } catch (e) { err.value = e.message } finally { busy.value = false }
}
</script>

<style scoped>
.scn { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; }
.scn-c { display: flex; gap: 12px; align-items: flex-start; border: 1px solid var(--line); border-radius: 12px; padding: 14px; cursor: pointer; }
.scn-c input { position: absolute; opacity: 0; pointer-events: none; }
.scn-c:focus-within { outline: 2px solid var(--brand-ink); outline-offset: 2px; }
.scn-c :deep(svg) { color: var(--brand-ink); flex: none; margin-top: 2px; }
.scn-c div { display: grid; gap: 4px; }
.scn-c.on { border-color: var(--brand-ink); background: var(--brand-weak); }
.words { color: var(--muted); }
.okc { color: var(--ok); margin-top: 10px; }
.err { margin-top: 10px; }
</style>
