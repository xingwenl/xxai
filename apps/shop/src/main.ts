import { createApp } from 'vue'
import App from './App.vue'
import { router } from './router'
import 'xxai-agent/style.css'
import './style.css'

createApp(App).use(router).mount('#app')
