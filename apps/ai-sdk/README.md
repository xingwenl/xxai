# xxai-agent

AI Agent JavaScript SDK，支持聊天和工具调用。

## 安装

```bash
npm install xxai-agent
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
  getToken: async () => {
    const res = await fetch('/api/agent-token')
    return (await res.json()).token
  },
  ui: {
    mode: 'floating',
    position: 'right',
    theme: 'auto'
  }
})
```

## API

### createAgentClient(options)

创建 Agent 客户端实例。

**参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| endpoint | string | 是 | WebSocket 端点 |
| platformId | string | 是 | 平台 ID |
| agentId | string | 是 | Agent ID |
| getToken | () => Promise<string> | 是 | 获取令牌的函数 |
| ui | UIOptions | 否 | UI 配置 |
| systemPrompt | string | 否 | 系统提示词 |
| messages | Message[] | 否 | 初始消息列表 |
| callbacks | AgentCallbacks | 否 | 回调函数 |
| transport | 'websocket' \| 'sse' | 否 | 传输方式，默认 'websocket' |

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
