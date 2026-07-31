# 前端 Agent 页面导航设计说明

## 目标

在 `apps/front` 接入已发布的 `xxai-agent@0.1.0`，用户登录后台后可以通过浮动助手说“打开智能体管理”“打开模型用量”等指令，导航到后台已有页面。

## 范围

- 新增受当前登录用户保护的短期 Agent token 代理接口。
- 在认证布局全局挂载 SDK floating UI。
- 注册单一宿主工具 `navigate_to_page`，只允许跳转内部路由白名单。
- 使用 TanStack Router 执行导航，不允许外部 URL、任意路径或脚本执行。
- 增加路由白名单的纯函数测试或等价静态验证，并完成前后端定向构建/测试。

## 非目标

- 不支持外部 URL。
- 不新增页面管理、数据库表、模型或新的权限角色。
- 不改动现有公开 Demo `/api/agent-token` 的行为。
- 不在浏览器保存或提交 `client_secret`。

## 方案

前端通过现有登录 JWT 请求 `/api/v1/embed/agent-token`。后端依赖 `require_current_active_user`，将当前用户 ID 和名称作为 Embed end user 身份，复用 `issue_embed_token` 完成 Client、Agent、Origin 和 host tool 白名单校验。前端用返回的短期 token 连接 SDK WebSocket。

`navigate_to_page` 的输入为 `{ route: string }`。前端维护中文页面名称到 TanStack Router 内部路径的映射，并只允许映射结果执行。工具执行成功返回目标路径；未知页面返回错误，SDK 将错误回传给 Agent，页面保持不变。

由于后端将 `navigation` 标记为有副作用工具，bridge 收到 `confirmation_required` 时使用浏览器原生确认框征求当前用户同意；拒绝时回传拒绝状态，不执行导航。

## 授权与审批

- 架构边界：沿用现有 Embed token、Agent gateway 和 React 路由边界，不新增服务。
- 数据模型：无变化。
- API 契约：新增 `/api/v1/embed/agent-token`。
- 鉴权行为：新增当前后台登录态到 Embed token 代理的保护。
- 人工确认：已于 2026-07-31 确认方案，授权范围为仅内部后台页面导航，不支持外部 URL。

## 验收标准

- 未登录用户不能调用新的 token 代理接口。
- 登录用户在配置完整且绑定有效时，能初始化 SDK floating UI 并连接 WebSocket。
- 说出白名单页面名称时，Agent 能请求 `navigate_to_page`，前端通过 TanStack Router 打开目标页面。
- 未知页面、外部 URL 和非白名单路径不会触发导航。
- SDK bridge 卸载后不残留浮动 UI、WebSocket、定时器或事件监听。
- 后端定向测试和前端 `build`、`lint` 通过；失败项和环境限制记录在 `verify.md`。

## 变更记录

### 2026-07-31 第 1 次变更（fix）

- 变更原因：前端已注册 `navigate_to_page`，但当前 seed 未创建对应的后台策略，且模型 system prompt 未说明当前连接可用宿主工具，导致模型无法正确回答工具列表或发起页面导航。
- 变更内容：seed 增加 `navigate_to_page` 策略及 Agent/Embed Client 绑定；运行时将已授权页面工具注入 system prompt，并要求模型按实际工具列表回答和调用。
- 影响章节：范围、方案、验收标准。
- 是否触发人工确认：否，复用已确认的宿主工具三重白名单和内部页面导航边界。

### 2026-07-31 第 2 次变更（fix）

- 变更原因：日志显示 token、Agent 和页面注册名称均通过，但 runtime 收到的 `tools` 为空；进一步确认前端和 seed 的 `page_name` 描述不同，Schema 指纹校验后静默丢弃注册。
- 变更内容：统一 `navigate_to_page` 的完整 JSON Schema；注册拒绝时记录原因和两侧 Schema 指纹，记录最终 active tools 与 `stream_graph` 输入工具名。
- 影响章节：方案、风险、验收标准。
- 是否触发人工确认：否，不改变工具授权边界。

### 2026-07-31 初始版本

- 变更原因：接入已发布 `xxai-agent`，增加后台内部页面自然语言导航。
- 变更内容：新增受保护 token 代理、全局 SDK bridge、内部路由白名单宿主工具。
- 影响章节：全部。
- 是否触发人工确认：是，用户已确认仅允许打开后台已有页面。
