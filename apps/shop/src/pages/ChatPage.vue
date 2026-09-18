<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { createAgentClient, registerCustomComponent } from 'xxai-agent'
import type { AgentClient } from 'xxai-agent'
import ShopList from '../components/ShopList.vue'
import { clearSession, loadSession } from '../lib/session'

const router = useRouter()
const session = loadSession()
const chatRoot = ref<HTMLElement | null>(null)
const statusText = ref('连接中…')
const displayName = ref(session?.displayName ?? session?.shopUserId ?? '')

const agentId = import.meta.env.VITE_AGENT_ID ?? '1'
const platformId = import.meta.env.VITE_PLATFORM_ID ?? '1'

let agent: AgentClient | null = null
 
// const host = '8.153.87.79:8088'
onMounted(async () => {
  if (!session || !agentId) {
    await router.replace('/login')
    return
  }
  registerCustomComponent('ShopList', ShopList)

  const wsProtocol = location.protocol === 'https:' ? 'wss' : 'ws'
  const host = location.host
  // const host = '127.0.0.1:8000'
  agent = createAgentClient({
    endpoint: `${wsProtocol}://${host}/api/v1/ws/agents/${agentId}`,
    baseUrl: `${location.origin}/api/v1`,
    platformId,
    agentId,
    user: { id: session.shopUserId, displayName: session.displayName },
    getToken: async () => {
      // 浏览器只持有店铺系统 token，ai-base 侧完成校验并签发短期 embed token。
      const response = await fetch(`/api/v1/shop-agent/session?origin=${location.origin}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          shopToken: session.shopToken,
          shopUserId: session.shopUserId,
        }),
      })
      const body = await response.json().catch(() => null)
      if (!response.ok || !body?.success || !body?.data?.access_token) {
        throw new Error(body?.message || '获取智能体会话失败，请重新登录店铺系统')
      }
      return body.data.access_token as string
    },
    ui: { mode: 'embedded', container: chatRoot.value ?? undefined, theme: 'auto' },
  })

  agent.on('connection_state', (state) => {
    statusText.value = state === 'connected' ? '已连接' : `连接状态：${state}`
  })
  agent.on('error', (error) => {
    statusText.value = error?.message || '发生错误'
  })

  await agent.connect()
  agent.open()
})

function logout() {
  clearSession()
  agent?.destroy()
  agent = null
  void router.replace('/login')
}

onBeforeUnmount(() => {
  agent?.destroy()
  agent = null
})
</script>

<template>
  <div class="chat-page">
    <header class="chat-header">
      <div>
        <strong>店铺运营智能助手</strong>
        <span class="user-tag">{{ displayName }}</span>
      </div>
      <div class="actions">
        <span class="status">{{ statusText }}</span>
        <button type="button" class="logout" @click="logout">退出登录</button>
      </div>
    </header>
    <main ref="chatRoot" class="chat-root"></main>
  </div>
</template>

<style scoped>
.chat-page {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 20px;
  background: #fff;
  border-bottom: 1px solid #e8eaed;
}

.user-tag {
  margin-left: 10px;
  padding: 2px 10px;
  border-radius: 999px;
  background: #e6f4f1;
  color: #0f766e;
  font-size: 12px;
}

.actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.status {
  font-size: 12px;
  color: #8a919f;
}

.logout {
  height: 32px;
  padding: 0 14px;
  border: 1px solid #d8dce3;
  border-radius: 8px;
  background: #fff;
  color: #4b5563;
  cursor: pointer;
}

.chat-root {
  flex: 1;
  min-height: 0;
  background: #fff;
}
</style>
