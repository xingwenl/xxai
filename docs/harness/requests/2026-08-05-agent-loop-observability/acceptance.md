# 验收记录

## 当前结论

- 已完成 research、spec、plan 和 implement；verify 已完成可执行的本地代码验证。
- 状态：代码验收通过，request 仍为 `active/verify`，待真实浏览器联调和数据库版本复核后再完成 acceptance。

### 2026-08-06 增量验收：生成中消息与过程面板展示

- 已满足：助手正文为空或仅为空白字符时不渲染内容区域，有 AgentLoop 时只保留思考区。
- 已满足：首个消息更新早于 AgentLoop 事件时，仍立即显示“思考中”面板，不再出现生成期间只有空白或普通输入指示器的窗口。
- 已满足：`ChatMessageList`、`ChatMessage` 与 `AgentLoopPanel` 全程传递完整 Message；浏览器动态验证证明 `message.loop.steps` 从 `0` 更新为 `1` 后，工具卡片和展开状态同步刷新。
- 已满足：工具、技能或知识库步骤在生成期间到达后，过程摘要立即可点击展开和收起，不再等待最终答案完成。
- 已满足：展开状态不再由 Loop 的 `running` 状态强制改写，用户主动收起后可保持选择。
- 已满足：运行中摘要区分“调用工具”和“检索知识库”，空步骤时稳定显示“思考中”，不再出现尾随分隔符或重复“已思考”。
- 验证结论：SDK `31 passed`，类型检查与生产构建通过；桌面与 390px 视口的本地浏览器交互验证通过。
- 剩余风险：本轮使用静态运行中 Loop 状态完成组件验收，真实 WebSocket 端到端联调仍沿用本 request 的既有待办，不影响本次局部交互结论。

### 2026-08-06 增量验收：Agent 上游错误提示

- 已满足：502/连接类 Agent 错误统一通过现有 `error` 事件发送到 C 端，提示包含 HTTP 状态码和“本轮对话已结束”。
- 已满足：错误事件终止当前 request，不发送 `message_completed`；SDK pending assistant 和 Loop 状态收敛为失败并触发 `onError`。
- 已满足：运行中 Loop/模型生成步骤保存为 `failed`，失败半成品不创建完整助手消息。
- 已满足：C 端本地 WebSocket/token/协议传输错误与服务端 `error` 共用终止逻辑；活跃 request 即使尚未收到 `message_started` 也会结束并展示失败消息。
- 验证结论：定向后端 25 项通过，conversation/gateway 回归 50 项通过（1 skipped）；SDK 29 项、类型检查和构建通过。
- 剩余风险：尚未在真实 502 网关和浏览器环境联调，保留既有 request 的外部联调风险。
- 已补充：模型客户端默认不自动重试 502，并在 60 秒请求/流分块超时后进入统一 `error`；可通过环境变量和 `model_options` 调整。

## 已满足项

- 已创建独立 request 工作区。
- 已记录业界调研来源、方案比较和最终决策。
- 已定义多内容块消息、AgentLoop run/step、协议事件和隐私边界。
- 已列出实施文件、步骤、测试命令和回滚说明。
- 已实现消息内容块、AgentLoop Run/Step 模型、Embed WebSocket 生命周期事件、SDK 聚合和前端折叠面板。
- 已实现 Markdown、图片/文件资源引用结构和 custom fallback 的前端降级渲染。
- 已修复工具调用未进入 AgentLoop 的问题；天气类工具会作为 `host_tool` 或 `mcp_tool` 步骤展示。
- 已修复 Embed 网关长耗时工具静默问题：工具开始和完成状态会在实际执行期间实时推送，前端不再等待最终回答后才显示。
- 已补充技能可观测性：技能指令加载、技能名称、技能版本和技能脚本工具均进入 AgentLoop 步骤及实时事件。
- 已补充多内容块安全边界：Markdown、图片/文件资源引用、表格/图表/操作、自定义组件均有统一类型入口，非法块安全降级。
- 已按 `apps/ai-sdk/design/chat-glass.html` 调整聊天窗口和 AgentLoop 面板视觉样式。
- 已修复前端实时刷新缺口：AgentLoop 事件会绑定到 pending assistant 消息，步骤开始、完成和 Loop 完成均可在回答生成期间刷新界面。
- 已重新校正聊天页面比例，避免大字号、长引用和输入栏互相挤压；过程卡片与设计稿保持四种语义颜色和折叠层级。
- 已将消息内容改为组件化渲染，Markdown 使用 `markdown-it + dompurify`，自定义组件支持注册后渲染，未注册组件显示安全 fallback。
- 已支持 SDK UI 品牌色配置，可自定义用户消息和发送按钮的背景色、文字色。
- 已修复标准会话非流式接口丢失 Loop 步骤的问题，最终响应会返回已落库的安全步骤摘要。
- 已废弃旧 `ChatBubble` 结构，按设计稿重写为 `ChatMessage`、独立内容组件和 `TypingIndicator` 组件树。
- 已直接采用 `chat-glass.html` 的尺寸与视觉 token：Header 60px、聊天区 `18px 16px`、正文 15px、过程卡片 14px/12px radius/10px gap、输入控件 42px。
- 已实现带工具 Agent 的模型原生流式输出：工具参数按模型 chunk 累计，工具执行状态实时展示，工具后的最终正文按 `message_delta` 逐块到达。
- 已统一标准 SSE 与 Embed WebSocket 的流式工具语义，并保留标准 SSE 原有工具兼容事件。
- 已验证流关闭后的取消边界，尚未开始的工具不会继续执行。
- 已优化流式消息自动滚动：仅在用户位于底部附近时跟随，用户主动上滚阅读时不会被强制拉回。

## 未满足项

- 数据库迁移已由用户执行 `poetry run alembic upgrade head`；本环境无法再次连接数据库核验 current 状态。
- 尚未进行真实浏览器 WebSocket 联调，由用户负责。
- 尚未补充基于 Vue Test Utils 的独立组件挂载测试；已补 Markdown 解析安全测试，并通过类型检查和生产构建。

## 剩余风险

- 内容块中的图片和文件需要后续资源服务提供临时 URL 解析。
- 当前 AgentLoop 详情仍是公开安全摘要，后台审计页面按约定延期。
- 标准 SSE 与 WebSocket 流式工具循环已补齐；剩余主要是浏览器联调和资源 URL 解析接入。
- 自定义组件 props 的安全边界、文件 URL 授权和历史消息兼容细节需在实现阶段细化。
- 当前未实现资源服务将 `asset_id` 解析为临时 URL；前端联调图片/文件时需使用已授权的 URL 或后续接入资源服务。
- npm 依赖树仍有安全审计告警，需单独安排依赖升级任务处理。

## 下一步

- 在可连接已迁移数据库的运行环境执行 `poetry run alembic current`，确认版本为 `20260805_0017`。
- 启动后端和 SDK demo，使用真实 token 完成 WebSocket AgentLoop 事件、历史消息恢复和 Markdown/图片/文件/custom fallback 的浏览器联调。
- 保存联调结果后，再执行 `/accept 2026-08-05-agent-loop-observability`。
