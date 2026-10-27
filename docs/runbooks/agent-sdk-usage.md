# AI Agent SDK 接入手册

本文说明第三方网站如何接入 `xxai-agent`，包括 Embed Client 配置、短期 token 获取、浏览器初始化和常用操作。

## 一、接入前准备

平台管理员需要先完成：

1. 创建 Embed Client，记录 `client_id` 和只展示一次的 `client_secret`。
2. 配置允许的页面 Origin，例如 `https://shop.example.com`。
3. 将目标 Agent 绑定到 Embed Client，记录 `agent_id`。
4. 确认 WebSocket 地址，例如 `wss://ai.example.com/api/v1/ws/agents/11`。

`client_secret` 是服务端凭据，不能写进前端代码、`.env` 前端变量、NPM 包配置或浏览器 Local Storage。

## 二、理解两个身份

### `external_user_id`

这是接入方业务系统里的终端用户 ID，例如业务系统的 `user_123`、租户内用户编号或匿名访客会话 ID。

它必须由接入方后端从已验证的登录态或匿名会话中取得。它不是 AI Base 后台用户表的 ID，也不应由浏览器通过表单参数任意指定。

### Embed Access Token

这是 AI Base 为一次短期 SDK 会话签发的访问令牌，默认有效期为 10 分钟，绑定平台、Agent、Embed Client、Origin 和终端用户。

SDK 的 `getToken` 获取的就是这个短期 token，不是模型 API Key，也不是 `client_secret`。SDK 在连接和重连时都会重新调用 `getToken`。

## 三、实现服务端 token 代理

推荐让浏览器请求接入方自己的 `/api/agent-session`，由接入方服务端读取当前登录用户，再调用 AI Base 的 `POST /api/v1/embed/tokens`。

下面是 Python/FastAPI 风格示例，`current_user.id` 来自接入方自己的登录鉴权：

```python
import httpx
from fastapi import APIRouter, Depends

router = APIRouter()

@router.post("/api/agent-session")
async def create_agent_session(current_user=Depends(get_current_user)):
    payload = {
        "client_id": settings.ai_agent_client_id,
        "client_secret": settings.ai_agent_client_secret,
        "agent_id": settings.ai_agent_id,
        "external_user_id": str(current_user.id),
        "display_name": current_user.name,
        "origin": "https://shop.example.com",
        "host_tool_names": ["open_order_page"],
    }
    async with httpx.AsyncClient(base_url=settings.ai_base_url) as client:
        response = await client.post("/api/v1/embed/tokens", json=payload)
        response.raise_for_status()
        result = response.json()

    # 当前后端响应统一包装在 data 中。
    return {"token": result["data"]["access_token"]}
```

上面的示例使用固定的默认 Agent（`settings.ai_agent_id`）；同一服务需要接入多个 Agent 时，见第八节。

服务端必须校验：

- 当前用户已经登录，或匿名会话由服务端创建并持有；
- `agent_id` 是服务端配置，不接受浏览器覆盖；
- `origin` 是服务端配置，不接受浏览器覆盖；
- `client_secret` 只从服务端密钥配置读取；
- `host_tool_names` 只允许服务端明确配置的工具名称。

## 四、安装并初始化 SDK

```bash
npm install xxai-agent
```

在页面中初始化：

```typescript
import { createAgentClient } from 'xxai-agent'
import 'xxai-agent/style.css'

const agent = createAgentClient({
  endpoint: 'wss://ai.example.com/api/v1/ws/agents/11',
  platformId: 'platform_123',
  agentId: '11',

  // 该 user 只作为 token provider 上下文，不负责认证。
  user: {
    id: 'user_123',
    displayName: 'Alice'
  },

  // 浏览器只请求接入方后端，不接触 client_secret。
  getToken: async () => {
    const response = await fetch('/api/agent-session', {
      method: 'POST',
      credentials: 'include'
    })
    if (!response.ok) {
      throw new Error('获取 Agent 会话 token 失败')
    }
    const result = await response.json()
    return result.token
  },

  ui: {
    mode: 'floating',
    position: 'right',
    theme: 'auto',
    locale: 'zh-CN',
    // 可选：悬浮窗拖拽/缩放范围（CSS 像素），省略时使用默认值。
    // 默认 430×680，最小 320×480，最大不超过视口留白。
    window: {
      width: 480,
      height: 720,
      minWidth: 340,
      minHeight: 500,
      maxWidth: 720,
      maxHeight: 900
    }
  }
})

await agent.connect()
agent.open()
```

`user.id` 可以用于页面展示或让 token provider 识别上下文，但接入方后端不能信任浏览器传来的这个值作为身份。真正的 `external_user_id` 必须由服务端登录态确定。

## 五、常用操作

```typescript
agent.open()                  // 打开聊天窗口
agent.close()                 // 关闭聊天窗口
agent.toggle()                // 切换聊天窗口
await agent.sendMessage('查询我的订单')
agent.cancelMessage()         // 停止当前回答
agent.clearMessages()         // 清空本地消息
agent.disconnect()            // 断开连接
agent.destroy()               // 释放连接、定时器、DOM 和事件监听
```

无 UI 模式适合自行实现聊天界面：

```typescript
const agent = createAgentClient({
  // endpoint、platformId、agentId、getToken 同上
  ui: { mode: 'headless' }
})

agent.on('message', (message) => {
  renderMessage(message)
})

agent.on('message_updating', (message) => {
  renderStreamingMessage(message)
})

agent.on('connection_state', (state) => {
  updateConnectionIndicator(state)
})

agent.on('citation', (citation) => {
  renderCitation(citation)
})

agent.on('error', (error) => {
  showError(error.message)
})
```

自绘界面时可以读每轮用量（形状见 [`agent-sdk-flow.md`](../design/agent-sdk-flow.md) 8.1 节）：

```typescript
agent.on('message', (message) => {
  const usage = message.metadata?.usage as
    | { prompt_tokens: number; completion_tokens: number; total_tokens: number; cache_read_tokens?: number }
    | undefined
  if (usage) {
    renderUsageChip(`${usage.total_tokens} tokens`)
  }
})

// 历史消息同样带 metadata.usage；上线前的老消息没有该字段。
const messages = await agent.openConversation(conversationId)
const sessionTotal = messages.reduce(
  (sum, message) =>
    sum + Number((message.metadata?.usage as { total_tokens?: number } | undefined)?.total_tokens ?? 0),
  0
)
```

官方 Vue UI（`createChatUI()`）已内置这件事：每条 assistant 消息底部有「用量 … tok」chip，点开是逐轮明细；消息列表末尾一行是本会话累计。缓存字段缺失时 chip 只显示总量与输出，不显示「缓存命中」。

## 六、注册页面工具

页面工具在浏览器中执行，适合打开业务页面、读取当前页面状态或提交受控操作：

```typescript
agent.registerTool({
  name: 'open_order_page',
  description: '打开订单详情页',
  inputSchema: {
    type: 'object',
    properties: {
      orderId: { type: 'string' }
    },
    required: ['orderId'],
    additionalProperties: false
  },
  sideEffect: 'navigation',
  async execute(input) {
    const { orderId } = input as { orderId: string }
    window.location.assign(`/orders/${encodeURIComponent(orderId)}`)
    return { opened: true }
  }
})
```

工具还必须在服务端 Embed Client 白名单中配置。对于跳转、写入、支付或外部调用等副作用操作，SDK 和后端可能要求用户确认。

### 临时内存工具

对于只在当前页面临时使用的工具，请先在 Embed Client 管理中开启“允许临时页面工具”。SDK 侧不需要额外配置：

```typescript
const agent = createAgentClient({
  endpoint: 'wss://ai.example.com/api/v1/ws/agents/11',
  platformId: 'platform_123',
  agentId: '11',
  getToken: async () => {
    const response = await fetch('/api/agent-session', { credentials: 'include' })
    return (await response.json()).token
  }
})

agent.registerTools([temporaryToolA, temporaryToolB])
```

该 Embed Client 开关开启后，token 请求不要求维护 `host_tool_names`，临时工具也不会写入工具策略表；SDK 会在首次连接和每次重连后自动发送内存中的工具定义。SDK 不需要感知这个后端开关。

## 七、本地 Demo

本地 Demo 可以使用后端的便捷代理接口：

```text
GET /api/agent-token?external_user_id=demo-user
```

该接口从环境变量读取 `EMBED_CLIENT_SECRET`，只适合本地联调。生产环境不能让浏览器任意传入 `external_user_id`，必须改为接入方服务端从登录态取得用户 ID。

```bash
cd apps/ai-sdk
npm install
npm run build
npm run demo
```

## 八、一个服务如何接入多个 Agent

`EMBED_AGENT_ID`（示例中的 `settings.ai_agent_id`）只是「默认 Agent」配置，不表示一个服务只能用一个 Agent。Embed Client 是信任边界，不是单 Agent 绑定：一个 Embed Client 可以绑定多个 Agent，token 接口按请求体中的 `agent_id` 签发，只要该 Agent 已绑定到当前 Client 就会被允许。

### 模式 A：单 Embed Client + 多 Agent（同一服务内按场景路由）

适合同一个接入方服务、同一个域名下需要多个 Agent 的场景，例如按租户、按业务页面、按入口渠道切换不同 Agent。

服务端 token 代理按业务上下文选择 `agent_id`，其余配置不变：

```python
# 示例：按业务入口选择 Agent，映射表放在服务端配置，浏览器不能直接覆盖。
AGENT_BY_ENTRY = {
    "after-sale": 11,
    "consultant": 12,
}

@router.post("/api/agent-session")
async def create_agent_session(entry: str = "default", current_user=Depends(get_current_user)):
    agent_id = AGENT_BY_ENTRY.get(entry, settings.ai_agent_default_id)
    payload = {
        "client_id": settings.ai_agent_client_id,
        "client_secret": settings.ai_agent_client_secret,
        "agent_id": agent_id,
        "external_user_id": str(current_user.id),
        "display_name": current_user.name,
        "origin": "https://shop.example.com",
        "host_tool_names": ["open_order_page"],
    }
    async with httpx.AsyncClient(base_url=settings.ai_base_url) as client:
        response = await client.post("/api/v1/embed/tokens", json=payload)
        response.raise_for_status()
        result = response.json()
    return {"token": result["data"]["access_token"]}
```

前端每个 Agent 一个 SDK 实例，`endpoint` 与 `agentId` 一一对应：

```typescript
const afterSaleAgent = createAgentClient({
  endpoint: 'wss://ai.example.com/api/v1/ws/agents/11',
  platformId: 'platform_123',
  agentId: '11',
  getToken: async () => {
    const response = await fetch('/api/agent-session?entry=after-sale', {
      method: 'POST',
      credentials: 'include'
    })
    return (await response.json()).token
  },
  ui: { mode: 'headless' }
})

const consultantAgent = createAgentClient({
  endpoint: 'wss://ai.example.com/api/v1/ws/agents/12',
  platformId: 'platform_123',
  agentId: '12',
  getToken: async () => {
    const response = await fetch('/api/agent-session?entry=consultant', {
      method: 'POST',
      credentials: 'include'
    })
    return (await response.json()).token
  },
  ui: { mode: 'floating' }
})
```

要点：

- `agent_id` 的选择逻辑必须在服务端（路由、租户、页面配置），token 代理不接受浏览器直接传入 `agent_id` 覆盖。
- 模式 A 下多个 Agent 共享同一个 Embed Client 的 origin、工具白名单、token TTL 和配额策略；需要隔离时改用模式 B。
- SDK 按 `platformId + agentId + user.id` 隔离本地存储（消息历史等），同一页面可以同时运行多个 Agent 实例，互不串扰。

### 模式 B：多 Embed Client（按服务或域名隔离）

适合不同业务系统、不同域名，或需要不同工具白名单、不同配额、不同管理员的场景：每个服务创建自己的 Embed Client，并绑定各自的 Agent。

- 每个 Embed Client 独立配置 `allowed_origins`、工具白名单、token TTL 和限流配额。
- 每个服务各自持有 `client_id` / `client_secret`，互不共用。
- 前端接入方式不变，仍然按 Agent 实例化 SDK，`endpoint` 与 `agentId` 对应；Agent 绑定到哪个 Client 由平台管理端配置。

### 注意事项

- token 与 Agent 强绑定：JWT 内含 `agent_id`，WebSocket 路径 `/ws/agents/{agent_id}` 必须与 token 一致，不能用 A Agent 的 token 连接 B Agent 的 endpoint。
- 「允许临时页面工具」等开关是 Embed Client 级别配置，模式 A 下多个 Agent 共用同一个开关。
- 无论哪种模式，`EMBED_AGENT_ID` 都只作为本地联调便捷接口的默认值；生产接入的多 Agent 选择逻辑全部在服务端 token 代理中实现。

## 九、安全检查清单

- 浏览器网络请求中没有 `client_secret`。
- WebSocket URL 中没有 token。
- token 只通过连接建立后的 `auth` 消息传递。
- Embed Token 使用短 TTL，过期或重连时重新获取。
- `external_user_id` 来自接入方后端登录态。
- token 代理不允许浏览器覆盖 `platform_id`、`agent_id`、`origin` 和工具白名单。
- 不把 token 写入 Local Storage 或日志。
