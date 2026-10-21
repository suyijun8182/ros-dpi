import { onMounted, onUnmounted, ref, watch } from 'vue'

/** 加载数据并定时刷新（页面不可见时暂停）。deps 变化时立即重新加载。 */
export function usePoll(fn, ms = 30000, deps = null) {
  const loading = ref(true)
  const error = ref('')
  let timer = null
  let seq = 0

  async function run() {
    const my = ++seq
    try {
      await fn()
      if (my === seq) error.value = ''
    } catch (e) {
      if (my === seq) error.value = e.message
    } finally {
      if (my === seq) loading.value = false
    }
  }

  function tick() {
    if (!document.hidden) run()
  }

  onMounted(() => {
    run()
    if (ms) timer = setInterval(tick, ms)
    document.addEventListener('visibilitychange', tick)
  })
  onUnmounted(() => {
    clearInterval(timer)
    document.removeEventListener('visibilitychange', tick)
  })
  if (deps) watch(deps, () => { loading.value = true; run() })
  return { loading, error, reload: run }
}
