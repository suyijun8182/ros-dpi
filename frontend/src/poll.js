import { onMounted, onUnmounted, ref, watch } from 'vue'

/** 加载数据并定时刷新（页面不可见时暂停）。deps 变化时立即重新加载。
 *  同一时间只允许一个请求在飞：期间又有触发（定时 / deps 变化）就先记住，跑完立刻补一次。
 *  否则快速切换时间范围这类场景里，慢的旧响应会后到并覆盖新数据。 */
export function usePoll(fn, ms = 30000, deps = null) {
  const loading = ref(true)
  const error = ref('')
  let timer = null
  let seq = 0
  let running = false
  let dirty = false

  async function run() {
    if (running) { dirty = true; return }
    running = true
    const my = ++seq
    try {
      await fn()
      if (my === seq) error.value = ''
    } catch (e) {
      if (my === seq) error.value = e.message
    } finally {
      running = false
      if (my !== seq || dirty) { dirty = false; run() } else loading.value = false
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
