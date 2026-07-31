# xxai-agent

AI Agent JavaScript SDK，支持聊天和工具调用。

完整接入流程见 [AI Agent SDK 接入手册](../../docs/runbooks/agent-sdk-usage.md)。
SDK 与后端的模块边界、对话流程和后续修改规则见 [AI Agent SDK 流程与变更指南](../../docs/design/agent-sdk-flow.md)。

## 安装

```bash
npm install xxai-agent
```

如果使用悬浮聊天 UI，请同时引入样式：

```typescript
import 'xxai-agent/style.css'
```

## 本地开发

```bash
cd apps/ai-sdk
npm install

# 开发模式（源代码）
npm run dev

# 构建项目
npm run build

# 预览构建结果
npm run preview

# 测试 demo（需要先 build）
npm run demo
```

## 快速开始

```typescript
import { createAgentClient } from 'xxai-agent'

const agent = createAgentClient({
  endpoint: 'wss://api.example.com',
  platformId: 'your-platform-id',
  agentId: 'your-agent-id',
  user: { id: 'user-123', displayName: 'Alice' },
  getToken: async ({ user }) => {
    // 该接口是接入方自己的后端接口，不是模型服务商的 API Key 接口。
    // 接入方后端应从当前登录态取得 external_user_id，不要信任 user.id。
    const res = await fetch('/api/agent-session', { credentials: 'include' })
    return (await res.json()).token
  },
  ui: {
    mode: 'floating',
    position: 'right',
    theme: 'auto'
  }
})
```

### Token 与终端用户身份

`getToken` 返回的是由 AI Base 后端签发的短期 Embed Access Token，默认有效期为 10 分钟。它不是模型 API Key，也不是 Embed Client 的 `client_secret`。`client_secret` 只能保存在接入方服务端，不能打包进网页或 SDK 配置。

`external_user_id` 是接入方业务系统中的终端用户唯一标识，来源应是接入方服务端已经验证的登录态或匿名会话。SDK 不生成该值，也不会把它放进 WebSocket 地址或 `auth` 消息。生产 token 代理应由服务端根据登录态取得该值，再调用 AI Base 的 `POST /api/v1/embed/tokens`：

```text
浏览器 -> 接入方 /api/agent-session
接入方服务端从登录态取得 external_user_id
接入方服务端 -- client_id + client_secret + external_user_id --> AI Base /api/v1/embed/tokens
AI Base -> 接入方 -> 浏览器：短期 access_token
SDK 使用 access_token 建立 WebSocket
```

SDK 每次连接和重连都会调用 `getToken(context)`。`context` 只提供当前平台、Agent 和页面用户上下文，不代表 SDK 已完成用户认证；接入方后端不应把浏览器传来的 `user.id` 当作可信身份：

```typescript
type TokenProviderContext = {
  platformId: string
  agentId: string
  user?: { id: string; displayName?: string }
}
```

本地 Demo 可以使用 `/api/agent-token?external_user_id=demo-user`，但该接口允许浏览器直接指定用户标识，只适合开发联调，不能直接作为生产身份认证。

## API

### createAgentClient(options)

创建 Agent 客户端实例。

**参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| endpoint | string | 是 | WebSocket 端点 |
| platformId | string | 是 | 平台 ID |
| agentId | string | 是 | Agent ID |
| getToken | (context: TokenProviderContext) => Promise<string> | 是 | 获取短期 Embed Access Token 的函数；每次连接/重连调用 |
| user | `{ id: string; displayName?: string }` | 否 | 传给 token provider 的业务用户上下文，不由 SDK 自动认证 |
| ui | UIOptions | 否 | UI 配置 |
| systemPrompt | string | 否 | 系统提示词 |
| messages | Message[] | 否 | 初始消息列表 |
| callbacks | AgentCallbacks | 否 | 回调函数 |
| transport | 'websocket' | 否 | 传输方式，默认 'websocket' |

**返回：** `AgentClient`

### AgentClient 方法

| 方法 | 说明 |
|------|------|
| connect() | 连接服务端 |
| disconnect() | 断开连接 |
| open() | 打开聊天窗口 |
| close() | 关闭聊天窗口 |
| toggle() | 切换聊天窗口 |
| destroy() | 销毁实例 |
| sendMessage(text) | 发送消息 |
| cancelMessage() | 停止当前生成 |
| getMessages() | 获取消息列表 |
| addMessage(message) | 添加消息 |
| clearMessages() | 清空消息 |
| registerTool(tool) | 注册工具 |
| registerTools(tools) | 批量注册工具 |
| unregisterTool(name) | 注销工具 |
| getTool(name) | 获取工具 |
| getToolNames() | 获取工具名称列表 |
| clearCustomTools() | 清空自定义工具 |
| setSystemPrompt(prompt) | 设置系统提示词 |
| getSystemPrompt() | 获取系统提示词 |
| on(event, handler) | 监听事件 |
| off(event, handler) | 取消监听事件 |

### 事件

| 事件 | 说明 | 回调参数 |
|------|------|----------|
| message | 收到新消息 | (message: Message) |
| connection_state | 连接状态变化 | (state: ConnectionState) |
| error | 错误事件 | (error: Error) |
| citation | 收到知识库引用 | (citation: object) |

## 示例

### Headless 模式

```typescript
const agent = createAgentClient({
  // ...
  ui: {
    mode: 'headless'
  }
})

agent.on('message', (msg) => {
  console.log('收到消息:', msg)
})

agent.sendMessage('Hello')
```

### 注册工具

```typescript
agent.registerTool({
  name: 'get_weather',
  description: '获取天气信息',
  inputSchema: {
    type: 'object',
    properties: {
      city: { type: 'string' }
    },
    required: ['city']
  },
  async execute(params) {
    const res = await fetch(`/api/weather?city=${params.city}`)
    return res.json()
  }
})
```

## License

MIT
