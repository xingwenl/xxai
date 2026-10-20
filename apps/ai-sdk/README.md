# xxai-agent

`xxai-agent` 是用于在第三方网页中嵌入 AI Agent 的 JavaScript SDK，支持悬浮聊天窗口、无 UI 模式、流式消息和页面工具调用。

本文是完整的使用和接入手册。SDK 的协议边界和后端流程见 [AI Agent SDK 流程与变更指南](../../docs/design/agent-sdk-flow.md)。

## 1. 接入前准备

在 AI Base 管理后台完成以下配置：

1. 创建 Embed Client，保存 `client_id` 和只展示一次的 `client_secret`。
2. 配置允许的页面 Origin，例如 `https://shop.example.com`。
3. 将目标 Agent 绑定到 Embed Client，记录 `agent_id`。
4. 确认 WebSocket 地址，例如 `wss://ai.example.com/api/v1/ws/agents/11`。

`client_secret` 是长期服务端凭据，只能保存在接入项目的服务端。不能写入前端代码、前端环境变量、SDK 配置、浏览器 Local Storage 或 URL。

## 2. 先确定 Token 获取方式

SDK 的 `getToken` 返回的是 AI Base 签发的短期 Embed Access Token，不是模型 API Key，也不是 `client_secret`。默认有效期为 10 分钟，远短于接入项目的登录态，因此托管方必须按「随时可能被再次调用」来实现 `getToken`：SDK 会缓存 token 但按 JWT 的 `exp` 判断新鲜度（提前 30 秒视为过期），缓存不可用时才调用；服务端以 `401` 或 WS `embed_token` 错误拒绝时，SDK 会作废缓存并重换一次。

| 场景 | 方式 | 是否适合生产 |
| --- | --- | --- |
| 已有业务后端和登录态 | 接入项目后端代理 `POST /api/v1/embed/tokens` | 推荐 |
| 本地 Demo | `npm run demo` 启动的 dev server 同源代理 `/demo-api/agent-token` | 仅开发联调 |
| 纯浏览器、没有后端 | 当前版本没有安全的生产方案 | 不推荐 |

### 2.1 生产方式：接入项目提供 Token 代理

浏览器请求接入项目自己的 `/api/agent-session`，接入项目服务端从已验证的登录态取得 `external_user_id`，再使用服务端保存的 `client_secret` 请求 AI Base：

```text
浏览器 -> 接入项目 /api/agent-session
接入项目服务端从登录态取得 external_user_id
接入项目服务端 -- client_id + client_secret + agent_id --> AI Base /api/v1/embed/tokens
AI Base -> 接入项目 -> 浏览器：短期 access_token
SDK 使用 access_token 建立 WebSocket
```

AI Base Token Exchange 接口契约：

```http
POST /api/v1/embed/tokens
Content-Type: application/json
```

```json
{
  "client_id": "client_xxx",
  "client_secret": "仅保存在服务端的密钥",
  "agent_id": 11,
  "external_user_id": "user_123",
  "display_name": "Alice",
  "origin": "https://shop.example.com",
  "host_tool_names": ["open_order_page"]
}
```

成功响应：

```json
{
  "success": true,
  "code": 0,
  "message": "embed token issued",
  "data": {
    "access_token": "eyJ...",
    "token_type": "bearer",
    "expires_in": 600,
    "jti": "token-id"
  },
  "meta": null
}
```

接入项目的 FastAPI 代理接口可以按下面方式封装：

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

    return {"token": result["data"]["access_token"]}
```

服务端必须保证：

- `current_user` 来自已验证的登录态，或由服务端创建并持有的匿名会话；
- `agent_id`、`origin` 和工具白名单来自服务端配置，不接受浏览器覆盖；
- `external_user_id` 不从浏览器传入的 `user.id`、查询参数或表单直接读取；
- 响应只返回短期 `access_token`，不返回 `client_secret`；
- 不把 token 写入日志、数据库或 Local Storage。

### 2.2 本地 Demo 方式

本地 Demo 页面（`demo/*.html`、根目录 `index.html`）只请求**同源** `POST /demo-api/agent-token`，由 vite dev server 代理到 AI Base：

```bash
cd apps/ai-sdk
EMBED_CLIENT_ID=<client_id> \
EMBED_CLIENT_SECRET=<client_secret> \
EMBED_AGENT_ID=1 \
EMBED_ORIGIN=http://localhost:5174 \
npm run demo
```

代理读取的环境变量：

| 变量 | 含义 |
| --- | --- |
| `EMBED_CLIENT_ID` / `EMBED_CLIENT_SECRET` | 必填，服务端保存的 Embed Client 凭据 |
| `EMBED_AGENT_ID` | 缺省 Agent；页面也可以显式传 `agent_id` |
| `EMBED_ORIGIN` | 缺省 Origin；页面不传时用请求头 `Origin` |
| `AGENT_API_BASE` | AI Base 地址，默认 `http://127.0.0.1:8000` |

`client_secret` 只存在于启动 demo 的那个 shell 环境与 dev server 进程内，不写入 HTML、不进入浏览器。

AI Base 另有一个后台登录态接口 `GET /api/agent-token`（默认 `http://127.0.0.1:8000/api/agent-token`）。它**要求后台登录态**；非生产环境下可以用查询参 `external_user_id` 覆盖 token 主体以便模拟不同终端用户，**生产环境忽略该覆盖**并强制使用当前登录用户 id。

### 2.3 不提供后端代理时

当前版本没有“浏览器直接使用 `client_secret` 换 token”的安全用法。把 `client_secret` 放入前端等同于公开密钥，任何访问页面的人都可以签发其他用户的 token。

如果确实需要纯浏览器接入，应后续增加 Public Client/OIDC 方案：浏览器携带接入项目签发的、可由 AI Base 校验的 JWT，AI Base 通过 `issuer`、`audience` 和 JWKS 校验身份后再签发 Embed Token。该方案涉及新的鉴权和 API 契约，当前 SDK 不默认支持，不能用现有 `/api/v1/embed/tokens` 直接替代。

## 3. 安装

```bash
npm install xxai-agent
```

使用悬浮聊天 UI 时引入样式：

```typescript
import 'xxai-agent/style.css'
```

## 4. 最小接入示例

```typescript
import { createAgentClient } from 'xxai-agent'
import 'xxai-agent/style.css'

const agent = createAgentClient({
  endpoint: 'wss://ai.example.com/api/v1/ws/agents/11',
  // HTTP API 根路径；不配置时 SDK 会从 endpoint 推导。
  baseUrl: 'https://ai.example.com/api/v1',
  platformId: 'platform_123',
  agentId: '11',

  // user 只作为 token provider 上下文，不负责认证。
  user: { id: 'user_123', displayName: 'Alice' },

  // 浏览器只请求接入项目后端，不接触 client_secret。
  getToken: async () => {
    const response = await fetch('/api/agent-session', {
      method: 'POST',
      credentials: 'include',
    })
    if (!response.ok) throw new Error('获取 Agent 会话 token 失败')
    return (await response.json()).token
  },

  ui: {
    mode: 'floating',
    position: 'right',
    theme: 'auto',
  },
})

await agent.connect()
agent.open()
```

`getToken` 的上下文类型：

```typescript
type TokenProviderContext = {
  platformId: string
  agentId: string
  user?: { id: string; displayName?: string }
}
```

SDK 不生成、不拼接、不通过 WebSocket 发送 `external_user_id`。接入项目后端必须以自己的登录态为准。

## 5. 初始化参数

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `endpoint` | `string` | 是 | WebSocket 地址 |
| `baseUrl` | `string` | 否 | HTTP API 根路径，用于附件上传、状态查询、删除和资源下载；未提供时从 `endpoint` 推导 |
| `platformId` | `string` | 是 | 平台 ID |
| `agentId` | `string` | 是 | Agent ID |
| `getToken` | `(context) => Promise<string>` | 是 | 获取短期 Embed Access Token；首次使用、缓存临近过期（提前 30 秒）、以及被服务端 401 / WS `embed_token` 拒绝时调用 |
| `user` | `{ id: string; displayName?: string }` | 否 | 传给 token provider 的业务上下文，不负责认证 |
| `ui` | `UIOptions` | 否 | `floating` 或 `headless` 等 UI 配置 |
| `systemPrompt` | `string` | 否 | 随每次消息发送给后端并作为调用方补充系统提示词参与回答 |
| `messages` | `Message[]` | 否 | 初始消息列表 |
| `storageKey` | `string` | 否 | 本地消息和会话 ID 的存储键；默认按平台、Agent 和用户隔离 |
| `callbacks` | `AgentCallbacks` | 否 | 回调配置 |
| `transport` | `'websocket'` | 否 | 默认使用 WebSocket |
| `pageTools` | `PageToolsOptions` | 否 | 页面自动发现工具，默认关闭 |

## 6. 生命周期和消息

```typescript
await agent.connect()
agent.open()
await agent.sendMessage('查询我的订单')
agent.cancelMessage()
agent.close()
agent.disconnect()
agent.destroy()
```

常用方法：

| 方法 | 说明 |
| --- | --- |
| `connect()` / `disconnect()` | 建立或断开连接 |
| `open()` / `close()` / `toggle()` | 控制悬浮窗口 |
| `sendMessage(text)` | 发送消息 |
| `cancelMessage()` | 停止当前生成 |
| `getMessages()` / `addMessage()` / `clearMessages()` | 管理内存消息 |
| `clearLocalHistory()` | 清除本地消息和会话 ID，下一次发送开启新会话 |
| `compactContext(instructions?)` | 手动触发服务端上下文压缩；没有当前会话时抛错 |
| `setSystemPrompt()` / `getSystemPrompt()` | 管理参与模型回答的调用方提示词 |
| `destroy()` | 释放 WebSocket、定时器、DOM 和事件监听 |

工具和确认方法：

| 方法 | 说明 |
| --- | --- |
| `registerTool(tool)` / `registerTools(tools)` | 注册一个或多个页面工具 |
| `unregisterTool(name)` | 注销工具 |
| `getTool(name)` / `getToolNames()` | 查询已注册工具 |
| `clearCustomTools()` | 清除自定义工具 |
| `resolveToolCall(callId, approved)` | 允许或拒绝等待确认的工具调用 |

事件：

```typescript
agent.on('message', (message) => renderMessage(message))
agent.on('message_updating', (message) => renderStreamingMessage(message))
agent.on('connection_state', (state) => updateConnectionIndicator(state))
agent.on('citation', (citation) => renderCitation(citation))
agent.on('error', (error) => showError(error.message))
agent.on('context_usage', (usage) => updateContextRing(usage))
agent.on('context_compacted', (result) => noticeCompaction(result))
```

### 上下文占用与压缩

每轮模型调用结束后，后端推送一次 `context_usage`，携带当前会话的上下文占用：

```typescript
agent.on('context_usage', (usage) => {
  // usage: { usedTokens, windowTokens, percent, source, lastCompactedAt }
  renderContextRing(usage.usedTokens, usage.windowTokens)
})
```

| 字段 | 说明 |
| --- | --- |
| `usedTokens` | 当前上下文已占用的 token 数 |
| `windowTokens` | 模型窗口大小；后端拿不到时为 `null` |
| `percent` | 0–100 的占用百分比；窗口未知时为 `null` |
| `source` | `provider` 表示模型回传的真实用量，`estimated` 表示后端估算 |
| `lastCompactedAt` | 上次压缩完成时间（ISO 8601）；从未压缩过或窗口未知时为 `null` |

除了订阅事件，也可以直接读 `agent.contextUsage` 拿到同一份快照（尚未收到推送时为 `null`，切换会话或新建会话后会清空）。两种消费方式等价，任选其一即可；同时订阅时二者拿到的是同一个对象。`callbacks.onContextUsage` / `onContextCompacted` 与对应的 `on(...)` 事件也是这个关系。

**窗口未知时的降级**：`windowTokens === null` 时没有百分比可算，请只显示绝对 token 数，不要画占用环。SDK 自带的 widget 就是这么处理的，并导出了同一套纯函数供自定义 UI 复用：

```typescript
import { contextRingState, formatTokens } from 'xxai-agent'

const ring = contextRingState(agent.contextUsage?.usedTokens, agent.contextUsage?.windowTokens)
// ring === null：窗口未知，退化为 formatTokens(agent.contextUsage?.usedTokens ?? 0) 文本
// ring 非空：{ ratio, color, text, detail }
//   ratio 是 0–100 的百分比（超出窗口时截断到 100）
//   color 按占用分档：<70% 主题色、70–90% #F59E0B、>=90% #EF4444
//   text 是环旁边那行极简文本，形如 "11%"；有占用但不足 0.5% 时为 "<1%"
//   detail 是完整口径 "12.3K / 1.0M"，建议只放进 title 提示，不要和 text 一起平铺
```

需要用户手动触发压缩时调用 `compactContext()`，它请求 `POST /embed/conversations/{conversationId}/context/compact`（使用 `getToken` 返回的 embed token）：

```typescript
const result = await agent.compactContext('优先保留接口变更')
if (!result?.compacted) {
  // reason === 'nothing_to_compact'：没有可压缩的内容，属于幂等成功
} else if (!result.ok) {
  // reason === 'summary_failed' / 'summary_truncated'：压缩未生效
}
```

返回值是 `ContextCompactResult`（在 `ContextCompacted` 之上加一个 `compacted` 标志）：

| 字段 | 说明 |
| --- | --- |
| `compacted` | 本次是否真的发生了压缩；`false` 时 `reason` 通常是 `nothing_to_compact` |
| `trigger` | 本方法发起的压缩固定为 `manual`；后端自动压缩推送的事件为 `auto` |
| `ok` / `reason` | 压缩是否成功；失败时 `reason` 形如 `summary_failed`、`summary_truncated` |
| `tokensBefore` / `tokensAfter` | 压缩前后的上下文 token 数；失败时两者相等 |
| `windowTokens` / `percent` | 压缩后的窗口大小与占用百分比；窗口未知时为 `null` |
| `summaryChars` | 摘要字符数；REST 接口未返回该字段，本方法固定为 `0` |

调用成功后 SDK 会同步更新 `contextUsage`，并派发 `context_usage` 与 `context_compacted` 两条本地事件（不会额外触发 `callbacks.onContextUsage` / `onContextCompacted`，它们只对应服务端推送）。

失败语义：

- 没有当前会话（尚未发送过消息或处于新建态）时抛 `Error`，提示无法压缩；
- HTTP 非 2xx 时抛 `AgentError`，`message` 取自服务端返回（404 表示会话不存在或不属于当前主体，401 表示鉴权失败），可直接展示；
- 「没有可压缩的内容」不是失败：HTTP 200 + `compacted: false`，请按上面的分支提示用户。

后端自动压缩完成后同样会推送 `context_compacted`（`trigger` 为 `auto`），`agent.contextUsage` 也会随之更新为压缩后的占用。

### 错误处理

所有失败都以 `AgentError` 暴露：它仍是 `Error` 的实例（`error.message` 等既有用法不变），额外带四个结构化字段，便于按码分支与决定是否重试。

```typescript
import { isAgentError, type AgentError } from 'xxai-agent'

function showError(error: AgentError) {
  toast(error.message)
  if (error.code === 'chat_model_unavailable') {
    // 稳定错误码可直接分支
  }
  if (error.retryable) scheduleRetry()
}
```

| 字段 | 说明 |
| --- | --- |
| `code` | 稳定业务错误码，例如 `chat_model_unavailable`、`unsupported_sdk_version`；无码时为 `undefined` |
| `retryable` | 是否值得重试（版本不兼容等为 `false`；REST 的 5xx/429 按状态码推断） |
| `requestId` | 关联请求 ID，便于与服务端日志对齐 |
| `details` | 附加诊断信息，例如版本不兼容时的 `minimumSdkVersion`/`supportedProtocolVersion` |

同一个失败在 `onError`、`agent.on('error')` 与 `connect()` 的 reject 拿到的是**同一个对象**，不会出现一处有码、一处没有。版本不兼容时另有一条 `compatibility_error` 事件；`agent.on('error')` 仍会收到一次（不重复），未订阅 `compatibility_error` 也不会漏。用 `isAgentError(value)` 可在 `catch` 里安全收窄类型。

## 7. UI 模式

### 悬浮模式

```typescript
const agent = createAgentClient({
  // endpoint、platformId、agentId、getToken 同上
  ui: { mode: 'floating', position: 'right', theme: 'auto' },
})
```

可以通过 `colors` 覆盖主要颜色：

```typescript
const agent = createAgentClient({
  // endpoint、platformId、agentId、getToken 同上
  ui: {
    mode: 'floating',
    position: 'right',
    theme: 'light',
    colors: {
      primary: '#0f766e',
      primaryForeground: '#ffffff',
      userMessageBackground: '#0f766e',
      userMessageForeground: '#ffffff',
    },
  },
})
```

### Headless 模式

Headless 模式不渲染聊天 UI，适合自行实现消息列表和输入框：

```typescript
const agent = createAgentClient({
  // endpoint、platformId、agentId、getToken 同上
  ui: { mode: 'headless' },
})

agent.on('message', (message) => renderMessage(message))
agent.on('message_updating', (message) => renderStreamingMessage(message))
```

### 嵌入式模式（Embedded）

嵌入式模式把聊天 UI 直接渲染进宿主页面指定的容器，聊天窗口默认展开并填满容器，适合侧栏、内容区等固定区域。传入 `container` 即进入嵌入式模式；不传则保持上面的悬浮窗行为，两种模式互不影响。

```html
<div id="chat-root" style="height: 600px"></div>
```

```typescript
const agent = createAgentClient({
  // endpoint、platformId、agentId、getToken 同上
  ui: {
    mode: 'embedded',
    container: document.getElementById('chat-root')!,
  },
})
```

嵌入式模式的约定：

- 容器必须有确定高度（如 `height: 600px`、`height: 100%` 或 flex/grid 拉伸后的固定高度），否则窗口高度会塌陷；宽度默认铺满容器。
- 不渲染悬浮按钮、窗口拖拽与缩放手柄，头部也没有返回/关闭按钮，`open()` / `close()` / `toggle()` 不会产生开关效果。
- `position` 与 `window`（拖拽/缩放尺寸配置）在嵌入式模式下不生效。
- 样式隔离沿用悬浮模式的方案（`.xxai-reset` + `--xxai-*` CSS 变量），`colors` 配置同样生效。

### PC 双栏与会话列表（`layout: 'desktop'`）

PC 页面接入时可以让 SDK 同时提供左侧会话列表：传入 `ui.layout: 'desktop'` 后，面板够宽时渲染为「左侧会话列表 + 右侧对话区」，点击列表项即可切换会话并加载该会话的历史消息。**悬浮模式与嵌入式模式都支持**该布局。

```typescript
const agent = createAgentClient({
  // endpoint、platformId、agentId、getToken 同上
  ui: {
    mode: 'embedded',
    container: document.getElementById('chat-root')!,
    layout: 'desktop',
    sidebar: { width: 260 }, // 可选，默认 260，会被限制在 200–360
  },
})
```

悬浮模式同样可用，但悬浮窗默认只有 430px 宽，放不下 260px 的常驻列表，因此默认走抽屉形态；把窗口拉宽（或配置 `window.width`）后列表才常驻：

```typescript
const agent = createAgentClient({
  // endpoint、platformId、agentId、getToken 同上
  ui: {
    mode: 'floating',
    layout: 'desktop',
    window: { width: 900, height: 640 }, // 够宽时左侧列表常驻
  },
})
```

`layout` 与 `sidebar` 的约定：

- `layout` 缺省为 `'single'`，即既有的单栏消息流；不传这两个字段时行为与升级前完全一致。
- **断点按「聊天面板自身宽度」判断**（悬浮窗的窗口宽度、嵌入式的容器宽度），不是浏览器视口宽度：因此一个很宽的页面上、430px 的悬浮窗依然会自动降级，不会把对话区挤没。
- 面板窄于 768px 时退化为单栏，会话列表改为抽屉。
- **header 头像左侧有一个会话列表开关**：宽屏时收起/展开常驻列表——收起后宽度全部让给对话区，按钮仍留在头部可再次展开；窄屏时点它展开抽屉，抽屉沿用既有交互关闭（点遮罩，或选中/新建会话）。按钮只在 `layout: 'desktop'` 下渲染，且带 `aria-label` 与 `aria-expanded`（文案在「隐藏会话列表」/「显示会话列表」之间切换）。
- 列表收放带过渡动画（宽度收缩 + 内容淡出；窄屏抽屉为位移滑入 + 遮罩淡入），并遵循系统「减少动态效果」：`prefers-reduced-motion: reduce` 下一律瞬时切换。收起后的列表宽度为 0 且 `visibility: hidden`，不会被键盘 Tab 命中。
- 悬浮窗拖拽缩放改变宽度后会重新判断断点，拉宽即出现常驻列表。
- 断点判断以渲染宽度为准，因此嵌入式宿主容器需要有确定的宽度。

会话相关 API：

```typescript
const page = await agent.listConversations({ page: 1, pageSize: 20 })
await agent.openConversation(page.items[0].id) // 切换并加载历史消息
agent.startNewConversation()                   // 开新会话
await agent.deleteConversation(conversationId) // 软删除（见下）
agent.currentConversationId                    // 当前会话 ID，新会话为 undefined
agent.on('conversations_changed', () => {/* 刷新列表 */})
```

`openConversation` 会先重置本地流式与请求状态再渲染历史消息，避免上一个会话的回答与历史叠加。

删除是不可逆操作，UI 与「清除聊天记录」统一采用**两步确认**：第一次点击只让对应按钮变成「确认？」，3 秒内对同一条再点一次才真正调用 `deleteConversation()`；超时、切换目标或列表刷新都会自动取消。直接调用 `agent.deleteConversation(id)` API 时没有这层确认，需要宿主自行控制。

### 思考模式与过程卡片开关

两个开关都**默认关闭**，需要在接入处显式传 `true` 才开启：

```typescript
const agent = createAgentClient({
  // endpoint、platformId、agentId、getToken 同上
  // 开启思考模式：随每次请求下发给后端，由后端翻译为上游厂商参数
  thinking: true,
  ui: {
    mode: 'floating',
    // 展示思考 / 工具调用 / 技能 / 知识库等过程卡片
    showAgentSteps: true,
  },
})
```

| 开关 | 位置 | 默认 | 作用 |
| --- | --- | --- | --- |
| `thinking` | 顶层 | `false` | 控制模型是否思考。`false` 时后端显式下发「关闭思考」参数 |
| `ui.showAgentSteps` | `ui` 下 | `false` | 是否渲染 Agent 过程卡片；关闭时只保留对话正文 |

`thinking` 的约定：

- 该值随**每次** `message_send` 下发，因此同一个 Agent 的不同请求可以各自决定是否思考。
- **默认关闭是显式行为**：DeepSeek 等厂商的上游默认是「开启思考」，SDK 会显式下发关闭参数，而不是靠省略字段。
- 后端按模型厂商翻译：DeepSeek 下发顶层 `thinking.type`；其他厂商关闭时使用 `reasoning_effort: "none"`。
- 若厂商既不吃 `thinking` 也不吃 `reasoning_effort`，可由后端在 Agent 版本的 `model_options` 中显式指定映射，形如 `{"thinking": {"on": {...}, "off": {...}}}`；无法识别厂商时开关会静默失效（请求仍成功，只是思考未被关闭）。

`ui.showAgentSteps` 的约定：

- 只影响渲染，不改变后端是否产生过程事件；关掉后正文仍照常流式输出。
- 关闭时正文为空且消息处于流式中的占位气泡仍会显示打字指示器，不会出现「空白气泡」。

> **升级注意（0.1.x → 0.2.0）**：两个开关默认值均为关闭。从旧版本升级后，思考内容与过程卡片会**默认不再显示**；如需保留原有可见性，请显式传入 `thinking: true` 与 `ui.showAgentSteps: true`。

删除会话是**软删除**：服务端只把会话标记为已删除，**不会删除消息、附件与 token 用量记录**，磁盘上的附件文件也保留；删除后该会话不再出现在列表中，也不能再继续对话。被删除会话占用的存储由后续的数据保留策略处理，如需彻底清除请联系 AI Base 运维。

## 8. 注册工具

工具函数在浏览器执行，后端只负责转发调用。服务端 Embed Client 仍必须配置工具白名单：

```typescript
agent.registerTool({
  name: 'get_weather',
  description: '获取天气信息',
  inputSchema: {
    type: 'object',
    properties: { city: { type: 'string' } },
    required: ['city'],
    additionalProperties: false,
  },
  sideEffect: 'none',
  async execute(params) {
    const { city } = params as { city: string }
    const response = await fetch(`/api/weather?city=${encodeURIComponent(city)}`)
    return response.json()
  },
})
```

跳转、写入、删除、支付或外部调用等副作用操作必须增加确认逻辑，并在服务端配置允许范围。不要把密钥、用户密码或其他敏感数据作为工具参数暴露给 Agent。

自定义确认流程：

```typescript
const agent = createAgentClient({
  // endpoint、platformId、agentId、getToken 同上
  callbacks: {
    onConfirmationRequired(confirmation) {
      showConfirmationDialog({
        title: confirmation.name,
        summary: confirmation.summary,
        onConfirm: () => agent.resolveToolCall(confirmation.callId, true),
        onCancel: () => agent.resolveToolCall(confirmation.callId, false),
      })
    },
  },
})
```

未提供自定义 `onConfirmationRequired` 时，悬浮 UI 会使用内置确认界面。

### 页面自动发现工具

页面工具默认关闭。显式开启后，SDK 只使用当前顶层页面可见元素的临时 `snapshotId/ref`，不执行任意 JavaScript，也不接受 CSS/XPath：

```typescript
const agent = createAgentClient({
  // ...
  pageTools: {
    enabled: true,
    confirmationKeywords: ['提交', '删除', '支付'],
    maxCalls: 20,
    maxDurationMs: 120000,
  },
})
```

密码框、文件框和跨域 iframe 不可操作。预算上限为 `maxCalls: 100`、`maxDurationMs: 600000`。

### 临时内存工具

如果后台 Embed Client 开启“允许临时页面工具”，工具只保存在当前 SDK 实例内存中，首次连接和重连会自动注册：

```typescript
agent.registerTools([
  {
    name: 'read_current_page',
    description: '读取当前页面标题',
    inputSchema: { type: 'object' },
    sideEffect: 'none',
    async execute() {
      return { title: document.title }
    },
  },
])
```

## 9. 自定义组件（Generative UI）

让智能体在对话中直接展示宿主网页的自定义组件（例如用户信息卡片），而不是只能输出文本。链路为：

```text
模型调用业务工具（如 show_user_card）
  -> 后端把工具结果转成 custom 内容块（component_name + props + fallback）
  -> SDK 按组件名查注册表渲染
  -> 未注册组件时展示 fallback 文本
```

### 9.1 注册组件

```typescript
import { createChatUI, registerCustomComponent } from 'xxai-agent'
import UserInfoCard from './UserInfoCard.vue'

registerCustomComponent('UserInfoCard', UserInfoCard)

const chat = createChatUI({ ... })
```

- 组件名必须与后端工具返回的 `component_name` 完全一致。
- 组件按普通 props 接收 `block.props` 中的字段（`name`、`email` 等）。
- `custom` 块协议字段统一为下划线格式 `component_name`；SDK 同时兼容读取存量 `componentName` 数据。

### 9.2 新增一个自定义组件的标准流程

1. 前端：编写 Vue 组件文件，并通过 `registerCustomComponent('<组件名>', Component)` 注册。
2. 后端：在 `apps/backend/app/modules/tools/business/` 新增一个业务工具文件（可复制 `custom_component.py` 模板），返回 `{ "kind": "custom", "component_name": "<组件名>", "props": {...}, "fallback": "..." }`；店铺运营项目（hua8）的分层示例见 `apps/backend/app/modules/tools/shop/`（`data/` 查数据、`ui/` 渲染组件）。
3. 注册页：在 `apps/backend/app/modules/tools/business/registry.py` 中 import 新模块（导入即注册；shop 分层工具由 `tools/shop/registry.py` 汇总后挂到统一注册页）。
4. 启用：在管理后台为对应 Agent 启用该内置工具。
5. 验证：对话触发工具后，已注册组件正常渲染；未注册时展示 `fallback`。

### 9.3 示例：用户信息卡片

后端 `show_user_card` 工具返回：

```json
{
  "kind": "custom",
  "component_name": "UserInfoCard",
  "props": { "name": "张三", "email": "zhangsan@example.com", "title": "前端工程师" },
  "fallback": "张三 · zhangsan@example.com"
}
```

前端组件 `UserInfoCard.vue`：

```vue
<script setup lang="ts">
defineProps<{
  name?: string
  email?: string
  avatar?: string
  title?: string
  department?: string
  summary?: string
}>()
</script>

<template>
  <div class="user-info-card">
    <img v-if="avatar" :src="avatar" alt="avatar" />
    <div>
      <strong>{{ name }}</strong>
      <div>{{ title }} · {{ department }}</div>
      <div>{{ email }}</div>
    </div>
  </div>
</template>
```

> 注意：`fallback` 是安全底线，后端要求必须非空；模型未提供时后端会根据 `props` 自动生成，组件不可用时用户仍然能看到信息摘要。

### 9.4 示例：店铺列表

店铺列表类组件以 `ShopList` 为例：展示工具返回 `kind=custom` 的渲染块，`props.shops` 数组条目字段与业务平台字段保持一致（本项目店铺工具返回 hua8 原字段 `platformStoreName` / `principalUserName` / `platformStoreId` / `tagList` 等），结构形如：

```json
{
  "kind": "custom",
  "component_name": "ShopList",
  "props": {
    "shops": [
      {
        "platformStoreName": "一世感•轻奢花店",
        "principalUserName": "花笙",
        "platformStoreId": "25518721",
        "tagList": [{ "id": "t1", "name": "托管" }]
      }
    ]
  },
  "fallback": "一世感•轻奢花店"
}
```

前端注册 `ShopList` 组件后按普通 props 接收 `shops` 数组即可；数据应由后端按真实业务接口返回，不让模型编造。新增展示工具时参考 `apps/backend/app/modules/tools/shop/ui/show_shop_list.py`，改 `name` / `component_name` / `input_schema` / `props` 白名单即可。

## 10. Markdown 图表

消息正文按 Markdown 渲染。围栏代码块命中已注册的图表语言时，SDK 会在气泡内把源码渲染成图表；否则保持普通代码块展示，内容始终可读、可复制。

内置语言：

| 围栏语言 | 图表类型 | 说明 |
| --- | --- | --- |
| ` ```mermaid ` | 流程图、时序图、状态图、思维导图等 | 渲染为 SVG |
| ` ```echarts ` | 柱状图、折线图、饼图等 | 围栏内容必须是 JSON 配置对象（容忍注释与尾随逗号，但不会执行 JS） |

### 10.1 启用内置图表渲染

SDK 不把图表引擎打进产物（mermaid 单文件约 2.8M、echarts 约 1.0M），引擎按「显式注入 → 全局变量 → 动态 `import()`」的顺序解析，都拿不到时降级为代码块。三种启用方式任选其一：

```bash
# 方式一：接入项目安装引擎，打包器会自动解析动态 import
npm install mermaid echarts
```

```html
<!-- 方式二：全局脚本（适合直接用 dist/xxai-agent.umd.cjs 或浏览器直连 ESM 的场景） -->
<script src="https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
```

```ts
// 方式三：显式注入，适合需要固定引擎版本或按需加载的场景
import { configureMarkdownDiagrams } from 'xxai-agent'
import mermaid from 'mermaid'
import * as echarts from 'echarts'

configureMarkdownDiagrams({ mermaid, echarts })

// 只启用其中一个、或临时关闭图表渲染
configureMarkdownDiagrams({ mermaid, echarts: null })
configureMarkdownDiagrams({ enabled: false })
```

`configureMarkdownDiagrams` 还支持 `theme: 'light' | 'dark' | 'auto'`（默认 `auto`：先看最近的 `.dark` 容器，再跟随系统偏好）。

### 10.2 接入其它图表语言

任何语言都可以用同一接缝注册，SDK 不做语言白名单。渲染器可以同步返回清理函数，也可以异步返回：

```ts
import { registerMarkdownFenceRenderer } from 'xxai-agent'
import vegaEmbed from 'vega-embed'

registerMarkdownFenceRenderer('vega', {
  async mount(element, code, context) {
    const result = await vegaEmbed(element, JSON.parse(code), {
      actions: false,
      theme: context.theme === 'dark' ? 'dark' : undefined
    })
    return () => result.view.finalize()
  }
})
```

- `mount(element, code, context)`：把源码渲染到占位容器，`context` 提供 `theme` 与归一化后的 `language`。
- 返回值是清理函数，组件卸载或消息更新时会调用；抛错或返回空表示无法渲染，SDK 自动降级为代码块并提示「图表渲染不可用，已显示源码」。
- 语言名大小写不敏感（`Mermaid` / `mermaid` 等价）；未注册语言不做任何处理。

### 10.3 安全边界

图表源码来自模型输出，属于未受信输入，SDK 做了三层防护：

1. Mermaid 以 `securityLevel: 'strict'`、`startOnLoad: false`、`suppressErrorRendering: true` 初始化，并关闭流程图 HTML 标签。
2. 渲染前按行剔除 `%%{...}%%`（可覆盖安全配置）与 `click`（可挂 JS 回调或链接）指令；超过 20000 字符的源码直接降级。
3. Mermaid 产出的 SVG 在写入页面前会经 `DOMPurify` 以 SVG profile 再清洗一次。

ECharts 只接受 `JSON.parse` 得到的对象，不会执行围栏里的 JS 表达式。需要额外说明的是：SDK 不修复图表引擎自身的安全问题，接入方应保持引擎版本更新；高安全要求的场景建议自行实现渲染器或在沙箱中渲染。

### 10.4 降级原因排查

渲染失败时消息里会显示源码，并给出具体原因：

| 提示 | 含义 | 处理 |
| --- | --- | --- |
| 未检测到 Mermaid / ECharts 引擎 | 引擎既没有注入，也没有出现在全局变量中，动态 `import()` 也失败 | 按 10.1 引入引擎；宿主打包器无法解析动态 `import()` 时用显式注入或全局脚本 |
| 图表配置不是合法的 JSON 对象 | ECharts 围栏内容不是 JSON 对象（例如写了 `echarts.init(...)`、单引号、无引号键名） | 让模型输出纯 JSON；注释与尾随逗号已被容忍 |
| 图表定义尚未完整 | Mermaid 源码为空、超长，或还没形成图定义（流式输出中途） | 等消息输出完成；确认首行是 `graph TD` 之类的图类型声明 |

### 10.5 已知限制

- 主题在图表挂载时确定，切换 `.dark` 类或系统主题后，已渲染的图表要等消息重新渲染才会换色。
- 流式输出过程中围栏可能只有半截语法，此时保持代码块展示，等源码形成可渲染的图定义后再渲染。
- 浏览器直接 `import '../dist/xxai-agent.es.js'` 且未提供全局引擎时，动态 `import('mermaid')` 会失败并降级为代码块，这属于预期行为。

## 11. 本地开发和 Demo

本包单独开发仍可用 npm（发布链路见第 12 节，CI 走 `npm ci`）：

```bash
cd apps/ai-sdk
npm install
npm run build
npm run demo
```

在 monorepo 里更推荐用仓库根的 pnpm workspace（`apps/front`、`apps/shop`、`apps/desktop/front` 是同一 workspace 成员）：

```bash
pnpm install     # 仓库根一次装完，并触发本包 prepare 生成 dist/
pnpm build:sdk   # 只重建 dist
pnpm --dir apps/ai-sdk exec vite build   # 同上，等价写法
```

SDK 源码开发命令：

```bash
npm run dev
npm run preview
npm run test -- --run
npm run type-check
```

> ⚠️ `dist/` 不被 git 跟踪。仓库根 `pnpm install` 会执行本包的 `prepare`（= `npm run build`）生成 `dist/`。宿主 `apps/front`、`apps/shop` 通过 `workspace:*` 软链到本包目录（`node_modules/xxai-agent -> ../../ai-sdk`），改动 `apps/ai-sdk/src` 后只需重建 dist（`pnpm build:sdk` 或 `pnpm --filter xxai-agent build`），宿主 dev server / 打包会直接读到新产物，不需要重装依赖。发布到 npm 不受影响：`workspace:*` 在 pack/publish 时会被替换成实际版本号。

本地 Demo 页面通过 dev server 的同源代理 `/demo-api/agent-token` 换 token，需要先设置 `EMBED_CLIENT_ID`、`EMBED_CLIENT_SECRET`、`EMBED_AGENT_ID` 和 `EMBED_ORIGIN`（见 [2.2 本地 Demo 方式](#22-本地-demo-方式)）；AI Base 后端也要配置同样的 Embed 变量。

## 12. 发布到 npm

SDK 通过 GitHub Actions 自动发布到 npm 官方仓库，工作流见 `.github/workflows/publish-ai-sdk.yml`，触发方式是 GitHub Release 创建（`release` 事件类型 `published`）。

发布流程：

1. 修改 `apps/ai-sdk/package.json` 中的 `version`（遵循语义化版本），提交并推送到 GitHub。
2. 在 GitHub 仓库创建 Release。版本号以 `package.json` 的 `version` 为准，与 Tag 是否一致不影响发布；版本号为预发布（如 `0.2.0-beta.1`）时，npm 会自动使用预发布标识（如 `beta`）作为 dist-tag，不会覆盖 `latest`。
3. Release 发布后，Actions 依次执行类型检查、单元测试，再执行 `npm publish --provenance --access public` 发布到 npmjs.com；任一步骤失败都不会发布。

发布前需要配置：

- GitHub 仓库 Secrets 中新增 `NPM_TOKEN`，值为 npmjs.com 的 **Granular Access Token**：权限选择 `Read and write`（可限定仅 `xxai-agent` 包），并且**必须勾选 "Bypass two-factor authentication"**。npm 已于 2025-11 移除旧的 Automation/legacy token，未勾选 Bypass 2FA 的 token 在 CI 发布时会报 `ENEEDAUTH` / `EOTP`。
- `prepublishOnly` 会自动执行构建和 `verify-package` 产物校验，校验不通过会中止发布。
- npm provenance 来源证明要求 GitHub 仓库为公开仓库，且 `package.json` 的 `repository` 与发布仓库一致（当前为 `xingwenl/xxai`）。

> 推荐长期方案：npm **Trusted Publishing**（OIDC，无需 token）。在 npmjs.com 的 `xxai-agent` 包设置中添加 Trusted Publisher，GitHub 配置填 `xingwenl` / `xxai` / 工作流 `publish-ai-sdk.yml`；配置后 CI 使用 Node ≥ 22 自带的最新 npm，`npm publish` 自动完成身份认证和 provenance。注意：首次发布仍需先用 token 完成，包存在后才能配置 Trusted Publisher。

## 13. 常见问题

### token 从哪里获取？

生产环境由接入项目服务端调用 AI Base 的 `POST /api/v1/embed/tokens`，浏览器只从接入项目的 `/api/agent-session` 获取短期 token。本地 Demo 用 `npm run demo` 启动的 dev server 同源代理 `/demo-api/agent-token`（凭据留在 dev server 进程内）；AI Base 的 `GET /api/agent-token` 需要后台登录态。

### 可以把 `client_secret` 放到前端吗？

不可以。前端代码和网络请求对用户可见，`client_secret` 泄露后可以被用于签发 token。

### 可以让浏览器传 `external_user_id` 吗？

生产环境不可以。必须由接入项目服务端从登录态或服务端匿名会话取得；浏览器传入的 `user.id` 只能作为展示或上下文。

### token 过期怎么办？

交给 SDK：它按 JWT 的 `exp` 缓存 token，剩余有效期不足 30 秒就重新调用 `getToken`；REST 收到 `401`、WS 收到 `embed_token` 错误时也会作废缓存并重换一次。接入方只需要保证 `getToken` 可以随时被调用（通常就是重新走一遍自己的 token 代理），不要自己返回一枚长期 token 或把过期时间写死。

如果 `getToken` 返回的不是 JWT、或 payload 里没有 `exp`，SDK 无法判断新鲜度，会退化为不缓存——每次取用都重新调用。

## 14. 安全检查清单

- 浏览器请求中没有 `client_secret`。
- WebSocket URL 中没有 token。
- token 只通过连接建立后的 `auth` 消息传递。
- token 使用短 TTL，过期或重连时重新获取。
- `external_user_id` 来自接入项目后端登录态。
- token 代理不允许浏览器覆盖 `agent_id`、`origin` 和工具白名单。
- 不把 token、secret、完整 prompt 或工具敏感参数写入日志。
- 高风险工具有明确的用户确认和服务端授权。

## 15. 桌面客户端（Electron）接入

桌面壳应用可以复用同一套 SDK，但来源约束与网页不同，接入前需要满足下面四点。

### 15.1 渲染层必须由 http(s) origin 承载

`file://` 加载的页面无法接入：

- Embed token 的来源只接受无路径的 `http(s)` origin，`file://` 无法登记到 `allowed_origins`；
- 实测（Electron 37.10.3 / Chromium 138）：`file://` 页面建立 WebSocket 时请求头是字面值 `Origin: file://`，与网关的来源校验对不上；`fetch` 请求则完全不带 `Origin` 头，服务端无法据此判断来源。

推荐做法：由 Electron 主进程内建一个只监听 `127.0.0.1` 的静态服务承载前端产物，窗口从固定端口加载，例如 `http://127.0.0.1:5390`；开发环境端口（如 `http://127.0.0.1:5190`）也按同一规则登记。

Electron 官方安全清单同样建议不要用 `file://` 承载本地页面（[Security 第 18 条](https://www.electronjs.org/docs/latest/tutorial/security)），改用 http origin 会一并消除这条技术债。

### 15.2 桌面来源需要同时登记到两个地方

| 位置 | 作用 | 漏登记的后果 |
| --- | --- | --- |
| Embed Client 的 `allowed_origins` | 决定能否签发 token | 换取 token 时返回 `origin is not allowed` |
| 服务端 `CORS_ORIGINS` 环境变量 | 决定浏览器能否读取 HTTP 响应 | 聊天可用，但附件上传/下载、消息快照等接口被浏览器拦截 |

另需注意：桌面端配置的 AI Base 站点根必须是 **AI Base 自己的地址**，不要填业务平台的地址。业务平台（如 hua8）与 AI Base 的接口路径前缀都是 `/api/v1`，填错时会打到业务平台并拿到它自身的 404（常见形态是 HTTP 200 + `{code,msg}`），表现为「会话凭证获取失败」这类与真实原因无关的报错。

### 15.3 token 由主进程换取，登录态不下发

以店铺运营平台登录态为例，推荐链路：

```text
渲染层 getToken --> 主进程 IPC
主进程 -- 平台登录态 token --> POST /api/v1/shop-agent/session?origin=http://127.0.0.1:5390
AI Base 校验登录态 --> 签发短期 embed access_token
主进程 --> 渲染层：只把 access_token 交给 SDK
```

- 桌面端**不需要** `client_secret`，它始终留在 AI Base 服务端；把 `client_secret` 打包进客户端属于反模式（RFC 8252 §8.5），不能当作安全方案。
- 平台登录态 token 不下发到渲染层，渲染层只持有短期（默认 10 分钟）embed token。
- 需要为桌面端指定独立 Agent 或启用宿主工具时，在会话请求里带上 `agentId` 与 `hostToolNames`：

```json
{
  "shopToken": "平台登录态 token",
  "shopUserId": "1001",
  "agentId": 12,
  "hostToolNames": ["get_current_shop", "list_shops"]
}
```

需要在一个部署里接入多个 Embed Client 时（例如每个平台一个 Client），由**可信服务端**在会话请求里带上自己的 `clientId` 与 `clientSecret`：

```json
{
  "shopToken": "平台登录态 token",
  "shopUserId": "1001",
  "agentId": 12,
  "hostToolNames": ["get_current_shop", "list_shops"],
  "clientId": "client_xxx",
  "clientSecret": "xxx"
}
```

- 两者必须**成对提供**；携带时还必须显式给出 `agentId` 与 `origin`，不会回退到服务端默认 Agent 或默认来源；
- 缺省时仍沿用服务端 `EMBED_CLIENT_ID` / `EMBED_CLIENT_SECRET` / `EMBED_AGENT_ID` / `EMBED_ORIGIN`，既有调用方行为不变；
- 凭证等同于签发权限，只能由平台自己的服务端持有并转发，不要下发到浏览器或打包进客户端；
- 该 Client 自己的 `allowed_origins`、Agent 绑定、宿主工具绑定与配额仍然逐条生效。

如果希望凭证**固定留在 AI Base 后端**、任何客户端都不携带（推荐做法），直接在 `apps/backend/app/modules/shop_agent/router.py` 顶部的 `PROJECT_EMBED_*` 常量里填该项目的 Embed Client 与该项目的 Agent、来源：

```python
PROJECT_EMBED_CLIENT_ID = "client_xxx"      # 该项目专用的 Embed Client
PROJECT_EMBED_CLIENT_SECRET = "xxx"        # 只留在服务端
PROJECT_EMBED_AGENT_ID = 12                # 该项目专用的 Agent
PROJECT_EMBED_ORIGIN = "http://127.0.0.1:5390"
```

取值优先级为「请求携带的凭证 > `PROJECT_EMBED_*` 常量 > `EMBED_*` 环境变量」；常量留空时行为与不使用该机制完全一致。接入新项目时新增一组同名前缀的常量与独立接口方法，避免项目之间互相影响。

### 15.4 宿主工具生效的三个条件

桌面端注册的工具必须同时满足以下条件，缺一会被网关静默忽略：

1. 工具策略已在后台绑定到目标 Agent 与目标 Embed Client；
2. 换取 token 时 `hostToolNames` 包含该工具名，否则 token 的 `host_tools` 为空；
3. 前端 `registerTool` 的 `name` 与 `inputSchema` 与后台策略指纹完全一致。

### 15.5 已知限制

- 端口必须固定，否则来源登记会失效；
- 主进程只信任登记过的来源，窗口导航守卫需要同步更新；
- 桌面来源是本地端口，任何本机程序理论上都能占用同一端口，真正的访问控制仍然是 token 签发环节；
- 需要跨进程使用桌面能力时，建议通过 preload IPC 暴露白名单能力，而不是给渲染层注入 Node 能力。

### 15.6 后台策略与前端注册的 Schema 对齐

宿主工具策略的 `input_schema` 必须与前端 `registerTool` 提交的 JSON 在字段与取值集合上完全一致（键顺序无关）；网关按「JSON 键排序 + 无空白分隔」的 sha256 指纹比对，不一致的工具会被静默忽略，只在服务端日志里留 `Host tool registration rejected`。

以运营工作台首批只读工具为例，可直接照抄下表：

| 工具名 | `input_schema` | 指纹（sha256） |
| --- | --- | --- |
| `get_current_shop` | `{"type":"object","properties":{},"additionalProperties":false}` | `99334726611ccf58a148b0814696bfa6fe08c1b2d027e946beccf5a74331c9aa` |
| `list_shops` | `{"type":"object","properties":{"keyword":{"type":"string"},"limit":{"type":"integer"}},"additionalProperties":false}` | `b5498e7cd696fdec4c0282d60f5f3d595eaf862425fe7806d87d81cc8d5c3e39` |
| `get_session_health` | `{"type":"object","properties":{"platform":{"type":"string"}},"additionalProperties":false}` | `11da5b1dfb0962a6a936d9f01531060d5a05384f59f58f374b53ab6c28646be0` |
| `list_local_tasks` | `{"type":"object","properties":{"status":{"type":"string"},"limit":{"type":"integer"}},"additionalProperties":false}` | `c506136f7b08cd50b699c8fce14c0b920825baca6002dfdd97267860e7fc0b12` |

排障顺序建议：先看 token 的 `host_tools` claim 是否包含该工具（为空说明 `hostToolNames` 没带上或没绑定到 Embed Client），再看服务端日志里该工具是被 `policy_found=false` 跳过还是被 `host tool schema does not match policy` 拒绝。

工具"注册成功但模型从不调用"时，按以下三行日志定位（均带 `request_id`，可直接 `rg` 关键字）：

1. `Host tools active for connection` / `Temporary host tools enabled for connection`：注册是否被网关接受；
2. `Embed request host tools request_id=... registered=[...] bound=[...]`：本次请求开始时连接级已注册、已授权的工具集合；
3. `Model tools bound request_id=... runtime_tools=[...] host_tools=[...] bound=[...]`：模型实际拿到的工具表；`host_tools` 有值但 `bound` 里没有它，说明工具被同名冲突剔除。

连接建不起来（页面完全没有反应）时，看 `Replay stream missing` 与 `Replay latest sequence is not numeric` 告警：二者都已降级为"不重放"，不会再中断建连。

工具"已经被模型调用，但结果是执行失败"时，按下面两张日志表定位。服务端日志在 `apps/backend/logs/app-YYYY-MM-DD.log`，浏览器日志在宿主页面的 DevTools 控制台（Electron 应用是渲染进程 DevTools）：

| 场景 | 服务端关键字 | 浏览器控制台关键字 |
| --- | --- | --- |
| 工具调用已下发到页面 | `Host tool dispatched request_id=... call_id=... tool=... wait_timeout_seconds=...` | `[xxai-agent][host-tool] call received` |
| 页面回传成功结果 | `Host tool result received call_id=... tool=... result_bytes=...` | `[xxai-agent][host-tool] result sent` |
| 页面回传失败原因 | `Host tool error received call_id=... tool=... code=... message=...` | `[xxai-agent][host-tool] execution failed` |
| 结果超过 32KiB 被拒 | `Host tool result too large call_id=... result_bytes=...` | `[xxai-agent][host-tool] execution failed`（`message=host_tool_result_too_large`） |
| 页面一直没回结果 | `Host tool execution timed out waiting for page result call_id=...` | 无（说明页面侧没执行到发送结果） |
| 页面回传了但结果被忽略 | `Host tool result ignored reason=... pending_keys=[...]` | 无 |
| 工具步骤最终状态 | `Tool step completed request_id=... tool=... status=... error_code=...` | 工具卡片文案 |
| 工具步骤以失败收尾（真实原因） | `Tool step failed detail request_id=... tool=... outcome_status=... outcome_error=...` | 工具卡片文案 |

注意：`Tool step completed ... status=succeeded` 只代表"工具调用这一轮结束了"，页面回传的错误会作为结果回填模型，因此仍需看 `Host tool error received` / `Host tool failed` 两行里的 `code` / `message`。

`Tool step completed ... status=failed` 落库与前端文案统一是"工具执行失败"，真实原因写在紧随其后的 `Tool step failed detail`：`outcome_error` 为空说明是调用器抛出的运行时异常（此时上方会有 `Host tool invocation failed` 或 `Tool invocation raised` 的堆栈），有 `code` 说明是工具自身返回的失败结果。`wait_timeout_seconds` 是本次等待页面的服务端上限，它异常小（如 0）说明审计行已过期或时间列类型不匹配（`TIMESTAMP WITH TIME ZONE` 与 naive 时间相减会抛 `can't subtract offset-naive and offset-aware datetimes`）。

工具"下发后立刻失败、页面结果被丢弃"时按下面这段顺序读（都是单条 `rg` 即可定位）：

1. `Host tool future registered ... pending_keys=[...]`：下发时 Future 已登记，`pending_keys` 里应含本次 `call_id`；
2. `Host tool wait window already expired ... expires_at=... now_utc=...`：等待上限算成了过去 —— 审计时间列读写口径不一致（naive 值被 asyncpg 当成本地时间写进 `TIMESTAMP WITH TIME ZONE`，东八区相差 8 小时）；
3. `Host tool future released ... pending_keys=[...]`：Future 在这一刻被回收，之后到达的页面结果必然被判为迟到；
4. `Host tool result ignored reason=no_pending_future ... future_found=... future_done=... pending_keys=[...]`：`pending_keys=[]` 说明请求已经结束（结果迟到），`pending_keys` 里是别的 `callId` 说明页面回传的 `callId` 与下发的不一致。

页面工具自身的常见失败码（来自 SDK 内部校验，日志里以 `message=` 出现）：

- `page_unavailable`：页面没有可用 `document`（工具执行在非渲染上下文）。
- `page_tool_budget_exceeded`：页面工具调用预算用尽（默认 `maxCalls: 20`、`maxDurationMs: 120000`，硬上限分别为 100 / 600000；预算窗口从本次 SDK 实例的**第一次**页面工具调用开始计时，不随用户消息重置，长时间不刷新页面会一直失败，刷新页面后恢复）。
- `page_snapshot_stale` / `page_element_not_visible`：`page_click` / `page_type` 使用的 `snapshotId`/`ref` 已过期，需要先重新 `page_snapshot`。
- `page_action_not_allowed`：目标元素是密码框、文件框或不可编辑元素。
- `host_tool_result_too_large`：结果超过 32KiB，需要缩小返回内容（例如减少快照元素或文本长度）。

## 16. 会话历史组件（宿主自备数据源）

0.2.0 起，主入口额外导出两个**只负责渲染**的会话历史组件，用于「后台管理里查阅历史会话」这类不需要聊天窗口的场景：

- `ConversationList`：会话列表（含分页、空态、加载态），点击条目触发 `select` 事件。
- `ConversationHistory`：单个会话的消息时间线，复用聊天窗口里同一套消息渲染（含 Markdown、引用、以及可选的 Agent 执行过程卡片）。

两者都**不发任何请求、不认识后端路径、不持有鉴权**：数据由宿主通过 `ConversationHistorySource` 注入。宿主只需实现两个方法：

```ts
import type { ConversationHistorySource } from 'xxai-agent'

const source: ConversationHistorySource = {
  // 返回 { items, total, page, page_size }，供列表分页与展示
  async listConversations({ page, page_size }) {
    const res = await fetch(`/api/v1/platforms/${platformId}/conversations?page=${page}&page_size=${page_size}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    return (await res.json()).data
  },
  // 返回消息数组，元素形状与 embed 的会话消息接口一致（含 loop 字段）
  async listMessages(conversationId) {
    const res = await fetch(`/api/v1/platforms/${platformId}/conversations/${conversationId}/messages`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    return (await res.json()).data
  },
}
```

组件属性：

| 组件 | 属性 | 说明 |
| --- | --- | --- |
| `ConversationList` | `source`（必填） | 数据源 |
| | `params` | `{ page?, page_size?, [key: string]: unknown }`，变化时自动重新拉取并重置到 `params.page` |
| | `emptyText` / `loadingText` | 空态与加载态文案 |
| | `@select` | 选中会话时触发，参数为会话摘要对象 |
| `ConversationHistory` | `source`（必填） | 数据源 |
| | `conversationId` | 切换会话时自动重新拉取 |
| | `showAgentLoop` | 默认 `true`，是否渲染每轮的思考/工具/技能过程卡片 |
| | `emptyText` / `loadingText` | 空态与加载态文案 |
| | `@loaded` / `@error` | 加载成功（消息数组）/ 失败 |

非 Vue 宿主（如 React）可以用 `createApp` 把组件挂到一个容器上，SDK 已把 Vue 运行时打包进产物，宿主不需要自行安装 Vue：

```ts
import { createApp } from 'xxai-agent'
import { ConversationList } from 'xxai-agent'
import 'xxai-agent/style.css'

const app = createApp(ConversationList, { source })
app.mount(document.getElementById('conversation-list')!)
// 卸载时调用 app.unmount()，避免重复挂载残留
```

样式已并入既有单一样式文件，只需 `import 'xxai-agent/style.css'`；这些页面位于白色背景时组件内部会局部覆盖少量 `--agent-*` 变量，不会影响聊天窗口。

## License

MIT
