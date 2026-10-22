import { createApp } from 'vue'
import '@fontsource/barlow/latin-400.css'
import '@fontsource/barlow/latin-500.css'
import '@fontsource/barlow/latin-600.css'
import '@fontsource/barlow-semi-condensed/latin-500.css'
import '@fontsource/barlow-semi-condensed/latin-600.css'
import '@fontsource/barlow-semi-condensed/latin-700.css'
import '@fontsource/barlow-semi-condensed/latin-800-italic.css'
import App from './App.vue'
import router from './router.js'
import { i18n } from './i18n/index.js'
import './style.css'

createApp(App).use(router).use(i18n).mount('#app')
