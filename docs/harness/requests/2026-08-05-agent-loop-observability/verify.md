# 验证记录

## 当前阶段

- 阶段：verify
- 已完成后端模型、迁移脚本、标准会话与 Embed 网关 AgentLoop 事件、SDK 类型/协议/状态聚合和聊天内容块渲染。

## 已执行命令

```bash
sed -n '1,260p' docs/harness/policies/global.md
find docs/harness/templates -maxdepth 1 -type f | sort
find docs/harness/requests -maxdepth 2 -type f | sort | tail -80
git status --short
rg -n "agent_step_delta|asset_id|后台详细|第 1 次设计确认" docs/harness/requests/2026-08-05-agent-loop-observability/{spec.md,plan.md}
git diff --check -- docs/harness/requests/2026-08-05-agent-loop-observability/spec.md docs/harness/requests/2026-08-05-agent-loop-observability/plan.md docs/harness/requests/2026-08-05-agent-loop-observability/meta.json
cd apps/backend && poetry run pytest tests/conversation tests/gateway tests/embed -q
cd apps/ai-sdk && npm run test -- --run && npm run type-check && npm run build
python -m compileall -q apps/backend/app apps/backend/migrations/versions/20260805_0017_agent_loop_observability.py
git diff --check
cd apps/backend && poetry run alembic current
```

## 结果

- 已读取全局 Harness 策略，确认本需求属于复杂 / 架构级变更。
- 已确认模板文件存在。
- 已确认当前新增 request 不复用旧 request。
- 发现工作区已有与本任务无关的未提交改动：`.env.example`、`.gitignore`、`apps/backend/run.sh`、`apps/backend/readme.md`，以及已有 `apps/ai-sdk/design/` 未跟踪目录。本次不处理这些改动。
- 已完成设计自检：第一版不发送 `agent_step_delta`，图片和文件使用 `asset_id`，后台详细审计页面和接口延期，文档之间保持一致。
- `git diff --check` 通过，未发现新增文档空白错误。
- 后端会话、网关与 Embed 测试通过：首次验证为 `60 passed, 1 skipped`；补齐标准会话 Loop 步骤投影后复测为 `61 passed, 1 skipped`。
- SDK 测试通过：`22 passed`；类型检查和生产构建均通过。
- Python 后端应用与迁移脚本编译检查通过。
- 本轮补充技能可观测性：技能加载会生成 `skill_instruction` 步骤，脚本工具步骤会记录技能名称和版本；验证测试覆盖技能步骤先于模型生成。
- 本轮补充内容块边界校验：限制数量、文本长度、资源标识和自定义组件名称/回退文案，非法内容降级为安全错误块。
- 本轮前端样式已按 `apps/ai-sdk/design/chat-glass.html` 对齐玻璃面板、语义色和运行中脉冲状态。
- 针对实时 UI 回归补充 SDK 测试：`agent_step_started` 到达后，pending assistant 的 `message_updating` 会立即携带 running Loop 步骤；SDK 测试现为 `23 passed`。
- 按设计稿重新校正 SDK 聊天窗口比例：窗口宽度、字号、卡片内边距、输入栏和长引用省略均采用正常聊天 UI 尺度；demo 宿主页同步移除旧紫色背景。
- 消息渲染已组件化，Markdown 使用 `markdown-it + dompurify`，并补充图片、文件、表格、操作、自定义组件和错误 fallback 渲染入口。
- SDK UI 新增品牌色配置，可分别设置用户消息背景/文字色和发送按钮背景/文字色；默认值仍为设计稿 sky/cyan 主色。
- SDK 最新验证：类型检查通过、`23 passed`、生产构建通过。
- 已补工具步骤回归断言：MCP 工具识别为 `mcp_tool`，技能脚本识别为 `skill_tool`，并保留工具调用 ID。
- 已补实时性回归断言：工具阻塞未完成时，`tool_started` 已先于 `tool_completed` 和最终回答产出。
- 已补数据库串行化回归断言：`tool_started` 未被消费确认前，技能工具不会开始使用共享 `AsyncSession`。
- 已补标准会话非流式响应回归测试：`loop.steps` 从已落库步骤读取，不再固定为空数组。
- 已按 `apps/ai-sdk/design/chat-glass.html` 重写 SDK 聊天 UI 组件树，旧 `ChatBubble` 已移除。
- 已补 Markdown 渲染测试：确认 `markdown-it` 语法输出和 `dompurify` HTML 过滤均生效。

## 未执行项

- 用户已执行 `poetry run alembic upgrade head`；本环境于 2026-08-05 重跑 `poetry run alembic current`，因沙箱禁止连接 PostgreSQL，仍无法复核服务端版本。
- npm 安装依赖后的审计报告显示依赖树存在 `17` 个安全告警（10 moderate、6 high、1 critical）；未执行 `npm audit fix --force`，避免无关破坏性升级。
- 历史消息接口已接入 `content_blocks` 和 Loop 摘要/步骤返回；尚未提供后台独立审计接口。
- 尚未进行浏览器端真实 WebSocket 联调和多内容块视觉回归，由用户负责联调。
- 尚未补充独立 Vue UI 测试；当前以 SDK 核心测试、类型检查和生产构建作为前端自动验证。
- 标准后台 SSE 在启用 MCP/技能工具时仍复用非流式 `execute_chat` 执行，工具步骤尚未做到与 Embed 网关一致的执行期间实时推送。

## 阻塞或例外

- 本需求涉及数据模型变化和 API 契约变化，人工确认已于 2026-08-05 获得。
- 当前未进入 acceptance 完成态：真实数据库版本复核和浏览器端联调仍缺少可执行证据。
- 另有两项实现收尾：标准后台 SSE 工具分支实时化、Vue UI 组件测试补齐。
