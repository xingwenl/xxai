import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { initializeLedger } from './lib/store'
import { installLedgerTools } from './lib/tools'
import './styles.css'

// 先挂宿主监听再启动仓库：宿主可能在本脚本执行后立刻注入 SDK 并派发 desktop-ready
installLedgerTools()
void initializeLedger()

const container = document.getElementById('root')
if (!container) throw new Error('页面缺少 #root 挂载点')

createRoot(container).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
