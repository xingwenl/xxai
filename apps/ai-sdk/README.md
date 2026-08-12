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

SDK 的 `getToken` 返回的是 AI Base 签发的短期 Embed Access Token，不是模型 API Key，也不是 `client_secret`。默认有效期为 10 分钟，首次连接和每次重连都会重新调用 `getToken`。

| 场景 | 方式 | 是否适合生产 |
| --- | --- | --- |
| 已有业务后端和登录态 | 接入项目后端代理 `POST /api/v1/embed/tokens` | 推荐 |
| 本地 Demo | AI Base `/api/agent-token?external_user_id=...` | 仅开发联调 |
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

本地联调可以调用：

```text
GET /api/agent-token?external_user_id=demo-user
```

该接口从 AI Base 服务端环境变量读取 `EMBED_CLIENT_ID`、`EMBED_CLIENT_SECRET`、`EMBED_AGENT_ID` 和 `EMBED_ORIGIN`。由于浏览器可以任意修改 `external_user_id`，它只能用于本地 Demo，不能直接用于生产身份认证。

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
| `platformId` | `string` | 是 | 平台 ID |
| `agentId` | `string` | 是 | Agent ID |
| `getToken` | `(context) => Promise<string>` | 是 | 获取短期 Embed Access Token；连接和重连都会调用 |
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
```

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

## 9. 本地开发和 Demo

```bash
cd apps/ai-sdk
npm install
npm run build
npm run demo
```

SDK 源码开发命令：

```bash
npm run dev
npm run preview
npm run test -- --run
npm run type-check
```

本地 Demo 使用 `/api/agent-token?external_user_id=demo-user` 时，确认 AI Base 后端已配置 `EMBED_CLIENT_ID`、`EMBED_CLIENT_SECRET`、`EMBED_AGENT_ID` 和 `EMBED_ORIGIN`。

## 10. 发布到 npm

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

## 11. 常见问题

### token 从哪里获取？

生产环境由接入项目服务端调用 AI Base 的 `POST /api/v1/embed/tokens`，浏览器只从接入项目的 `/api/agent-session` 获取短期 token。本地 Demo 可使用 `/api/agent-token`。

### 可以把 `client_secret` 放到前端吗？

不可以。前端代码和网络请求对用户可见，`client_secret` 泄露后可以被用于签发 token。

### 可以让浏览器传 `external_user_id` 吗？

生产环境不可以。必须由接入项目服务端从登录态或服务端匿名会话取得；浏览器传入的 `user.id` 只能作为展示或上下文。

### token 过期怎么办？

SDK 在重连时会再次调用 `getToken`。如果主动断开后重新连接，也应重新获取短期 token，不要缓存长期 token。

## 12. 安全检查清单

- 浏览器请求中没有 `client_secret`。
- WebSocket URL 中没有 token。
- token 只通过连接建立后的 `auth` 消息传递。
- token 使用短 TTL，过期或重连时重新获取。
- `external_user_id` 来自接入项目后端登录态。
- token 代理不允许浏览器覆盖 `agent_id`、`origin` 和工具白名单。
- 不把 token、secret、完整 prompt 或工具敏感参数写入日志。
- 高风险工具有明确的用户确认和服务端授权。

## License

MIT
