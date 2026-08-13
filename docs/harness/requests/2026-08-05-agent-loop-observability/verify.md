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
cd apps/backend && poetry run pytest tests/conversation tests/gateway -q
cd apps/backend && poetry run ruff check app/modules/conversation/runtime.py app/modules/conversation/services.py app/modules/conversation/router.py tests/conversation/test_runtime.py
cd apps/backend && poetry run black --check app/modules/conversation/runtime.py tests/conversation/test_runtime.py
cd apps/ai-sdk && npm run test -- --run && npm run type-check && npm run build
git diff --check
```

## 结果

### 2026-08-06 增量验证：生成中消息与过程面板展示

- `cd apps/ai-sdk && npm run test -- --run`：`31 passed`，新增展示纯函数测试覆盖空白 Markdown、非文本内容块、运行中工具/知识库摘要和空步骤摘要。
- `cd apps/ai-sdk && npm run type-check`：通过。
- `cd apps/ai-sdk && npm run build`：通过，Vite 完成 69 个模块转换并生成 ESM、UMD、CSS 和类型声明产物。
- 本地浏览器静态状态验证：pending assistant 仅含空白 Markdown 且 Loop 运行中时，`.xxai-message-content-blocks` 数量为 `0`，过程摘要为“思考中 · 调用工具 · 检索知识库”，按钮 `disabled=false`、初始 `aria-expanded=false`。
- 运行中点击过程摘要后，`aria-expanded=true`，立即显示模型生成、MCP 工具和知识库检索 3 个过程卡片；验证未依赖最终 `message_completed`。
- 390×844 视口验证：内容区域仍为 `0`、过程卡片为 `3`，过程组件最右边界为 `378px`，未超过 `390px` 视口；截图确认摘要、工具名和知识库状态未重叠。
- 临时静态验证页已删除，本地 Vite 开发服务器已停止，不进入最终变更。
- 补充实现：`ChatWidget` 在首个消息更新时创建临时 running Loop；`AgentLoopPanel` 在首个真实步骤到达时自动展开，后续步骤不会覆盖用户主动收起状态。
- pending Message 响应式回归：浏览器中先以 `message.loop.steps=[]` 渲染 `ChatMessageList`，初始摘要为“思考中”、卡片数 `0`、`aria-expanded=false`；500ms 后整体替换父级 pending message，使其 Loop 包含一个 running MCP 工具步骤，`AgentLoopPanel` 直接从最新 `props.message.loop` 同步读取后变为“思考中 · 调用工具”、卡片数 `1`、`aria-expanded=true`，详情显示 `get_weather 正在执行...`。
- 完整 Message 传递回归使用的临时 `reactivity-test.html` 已在验证后删除，不进入最终变更。

### 2026-08-06 增量验证：Agent 上游错误终止

- `cd apps/backend && poetry run pytest tests/conversation/test_runtime.py tests/gateway/test_chat_flow.py -q`：`25 passed`。
- `cd apps/backend && poetry run pytest tests/conversation tests/gateway -q`：`50 passed, 1 skipped`；仅有 Starlette/httpx 未来版本弃用警告。
- `cd apps/backend && poetry run ruff check ...`：通过。
- `cd apps/backend && poetry run black --check app/modules/conversation/runtime.py`：通过。其余本次涉及文件沿用仓库现有未完全 Black 格式化状态，组合检查会提示 6 个文件可重排，本次未做无关整文件格式化。
- `cd apps/ai-sdk && npm run test -- --run`：补充传输层错误测试后为 `29 passed`。
- `cd apps/ai-sdk && npm run type-check`：通过。
- `cd apps/ai-sdk && npm run build`：通过。
- `git diff --check`：通过。

## 2026-08-13 增量验证：清除聊天记录按钮

用户需求：聊天窗口提供“清除聊天记录”按钮。

实现（`ChatWidget.vue` + `styles/index.css`）：

- 头部新增垃圾桶按钮：首次点击变为“确认？”（红色，3 秒未再点自动恢复），再次点击调用已有的 `agent.clearLocalHistory()`（清空内存消息、移除 localStorage 消息、重置会话与待确认状态，并触发 `history_cleared` 事件）。
- `ChatWidget` 监听 `history_cleared` 事件同步清空消息列表与 pending 状态；组件卸载时清理确认定时器与事件监听。
- 按钮 hover 红色提示，避免误触删除。

验证：

- `cd apps/ai-sdk && npx vitest run`：`73 passed`。
- `cd apps/ai-sdk && npm run type-check`、`npm run build`：通过。
- `git diff --check`：通过。
- 新增回归证据：502 被映射为 `agent_upstream_unavailable`；标准 SSE/Embed 流只发终止 `error`，不发 `message_completed`；Embed Loop 和生成步骤为 `failed`；SDK 生成失败助手消息并清理 pending request。
- 错误路径复审后补充 SDK 传输层收口：请求已发送但尚未收到 `message_started` 时若 WebSocket/token/协议连接失败，也会生成失败助手消息并清理 active request。SDK 定向测试为 `8 passed`，全量复测为 `29 passed`。

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
- 工具场景已改为模型原生 `astream()`：流式累计工具调用参数，工具完成后继续逐块发送最终正文，不再等待完整回答后一次性发送。
- 标准后台 SSE 与 Embed WebSocket 现在复用相同的流式工具循环；标准 SSE 继续发送兼容的 `tool_call`、`tool_result` / `confirmation_required` 事件，并实时发送 AgentLoop 事件。
- 新增取消边界测试：工具开始事件发出后关闭生成器，不会执行尚未开始的工具。
- 后端增量验证通过：`47 passed, 1 skipped`；Ruff 与 Black 定向检查通过。唯一警告是 Starlette TestClient 关于未来 `httpx2` 的弃用提示。
- SDK 增量验证通过：`27 passed`，类型检查和生产构建通过。
- SDK 流式滚动增加 48px 底部阈值：用户停留在底部附近时继续跟随，主动向上阅读后不再被每个 delta 强制拉回；边界纯函数测试通过。

## 未执行项

- 用户已执行 `poetry run alembic upgrade head`；本环境于 2026-08-05 重跑 `poetry run alembic current`，因沙箱禁止连接 PostgreSQL，仍无法复核服务端版本。
- npm 安装依赖后的审计报告显示依赖树存在 `17` 个安全告警（10 moderate、6 high、1 critical）；未执行 `npm audit fix --force`，避免无关破坏性升级。
- 历史消息接口已接入 `content_blocks` 和 Loop 摘要/步骤返回；尚未提供后台独立审计接口。
- 尚未进行浏览器端真实 WebSocket 联调和多内容块视觉回归，由用户负责联调。
- 尚未补充独立 Vue UI 测试；当前以 SDK 核心测试、类型检查和生产构建作为前端自动验证。

## 阻塞或例外

- 本需求涉及数据模型变化和 API 契约变化，人工确认已于 2026-08-05 获得。
- 当前未进入 acceptance 完成态：真实数据库版本复核和浏览器端联调仍缺少可执行证据。
- Vue UI 仍未引入组件挂载测试依赖；本次滚动判断已通过纯函数单测、类型检查和生产构建验证。
- 本次未进行真实 502 网关联调；验证使用抛出 `HTTP 502 Bad Gateway` 的模型桩覆盖协议和状态收敛。
- 模型客户端超时补丁验证：`cd apps/backend && poetry run pytest tests/system/test_agent_settings.py tests/agent/test_agent_services.py -q`：`5 passed`；默认 `request_timeout=60`、`stream_chunk_timeout=60`、`max_retries=0` 已由测试断言覆盖。

## 2026-08-13 增量验证：时间线内联展示、引用/工具明细与思考内容落库

实际执行命令与结果：

- `cd apps/backend && .venv/bin/pytest tests/conversation/test_runtime.py tests/knowledge/test_knowledge_services.py -q`：`50 passed`。
- `cd apps/backend && .venv/bin/pytest tests/conversation tests/gateway tests/embed tests/knowledge -q`：`106 passed, 1 skipped`。
- `cd apps/backend && .venv/bin/pytest -q --import-mode=importlib`：`247 passed, 1 skipped`（默认收集模式的同名测试文件冲突为既有问题，与本次变更无关）。
- `cd apps/ai-sdk && npx vitest run`：`51 passed`（含新增 4 个 client 时间线/思考增量测试与 3 个展示纯函数测试）。
- `cd apps/ai-sdk && npm run type-check`：通过。
- `cd apps/ai-sdk && npm run build`：通过，生成 ESM/UMD/CSS/类型声明产物。
- `git diff --check`：通过。

## 2026-08-13 增量验证：技能组展开宽度修复

用户实测反馈“调用技能点开后，内部宽度变得很宽”。根因：`AgentLoopSkillGroup` 的 `<details>` 展开后，技能详情文本使用 `white-space: nowrap`，且容器链（`.xxai-timeline-entry` / `.xxai-loop-skill-group` / `.xxai-loop-skill-item`）缺少 `min-width: 0`，长文本（技能输出摘要 JSON）把卡片按 min-content 撑宽，超出消息容器。

修复（仅样式）：

- `AgentLoopSkillGroup.vue`：组卡片加 `min-width: 0` / `width: 100%` / `max-width: 100%` / `box-sizing: border-box`；列表与行加 `min-width: 0`；详情文本去掉 `nowrap` 与 `ellipsis`，改为 `overflow-wrap: anywhere` + `word-break: break-word`，长文本在卡片内换行。
- `ChatMessage.vue`（`.xxai-timeline-entry`）、`AgentLoopPanel.vue`（`.xxai-loop-details`）、`AgentLoopStepCard.vue`（`.xxai-loop-card`）同步补 `min-width: 0` / `max-width: 100%`，防止其他步骤卡片被长内容撑宽。

验证：

- `cd apps/ai-sdk && npx vitest run`：`60 passed`。
- `cd apps/ai-sdk && npm run type-check`：通过。
- `cd apps/ai-sdk && npm run build`：通过。
- `git diff --check`：通过。
- 截图验证曾尝试通过 headless Chrome 渲染 SSR 预览页，但沙箱环境中 Chrome 持续 SIGABRT 崩溃且自动审核服务不可用，无法产出截图；改用标准 CSS 规则（min-width: 0 + 允许换行）与 SSR 结构断言验证，待用户在真实浏览器确认视觉效果。

## 2026-08-13 增量验证：悬浮窗拖拽与缩放

用户需求：ai-sdk 聊天窗支持上下左右拖拽与放大缩小（带最大最小范围）。纯 UI 交互，无协议/数据模型变化；`UIOptions` 仅新增可选字段，向后兼容，无需重新审批。

实现：

- `types.ts` 新增 `UIWindowBounds`（width/height/minWidth/minHeight/maxWidth/maxHeight），挂到 `UIOptions.window` 可选配置；默认 430×680，最小 320×480，最大不超过视口四周 8px 留白。
- 新增 `ui/window-layout.ts` 布局纯函数：`resolveWindowBounds`（尺寸归一、min/max 与视口封顶）、`defaultWindowRect`（按 position 定位右下/左下）、`dragWindowRect`（位置平移并 clamp 在视口内）、`resizeWindowRect`（锚定左上角向右下扩展，受用户 min/max 与视口右/下边界约束）、`clampWindowRect`。
- `ChatWidget.vue`：标题栏作为拖拽手柄（Pointer Events 统一鼠标/触摸，按钮区不触发拖拽），右下角新增缩放手柄；窗口打开时按视口计算初始位置，视口 resize 时重新 clamp；`onUnmounted` 完整清理拖拽/缩放监听。
- `styles/index.css`：拖拽区 `cursor: grab` + `touch-action: none` + `user-select: none`；缩放手柄右下角 `nwse-resize`，hover 高亮；`.xxai-chat-window` 改为内联 left/top/width/height 定位。
- 配置透传链：`src/index.ts` → `ui/index.ts` → `ChatWidget`；`UIWindowBounds` 从包入口导出；`docs/runbooks/agent-sdk-usage.md` 补充 `window` 配置示例。

验证：

- `cd apps/ai-sdk && npx vitest run`：`70 passed`（新增 10 个 window-layout 边界测试：默认尺寸/位置、左右定位、拖拽视口 clamp、缩放 min/max 与视口约束、小视口兼容）。
- `cd apps/ai-sdk && npm run type-check`：通过。
- `cd apps/ai-sdk && npm run build`：通过。
- `git diff --check`：通过。
- 拖拽/缩放手感需用户在真实浏览器验证（本环境 headless Chrome 持续崩溃，无法截图）。

## 2026-08-13 增量修复：缩放手柄被输入条遮挡导致缩放不可用

用户实测：拖拽正常，但找不到/无法使用放大缩小。根因：`.xxai-chat-input-wrapper` 为 `position: absolute; bottom: 0; z-index: 2` 铺满窗口底部，右下角缩放手柄未设置 z-index（默认 auto），被输入条完全盖住，既不可见也不可点击。

修复（`styles/index.css`）：

- `.xxai-window-resize-handle` 提升 `z-index: 10`（高于输入条 2），并加浅色背景、放大点击区到 28×28、默认透明度 0.6、hover 高亮，保证可见且可点。
- 发送按钮右下角与手柄有约 14×18px 的重叠（按钮中心区域不受影响），符合常见聊天浮窗右下角缩放手柄的交互。

验证：

- `cd apps/ai-sdk && npx vitest run`：`70 passed`。
- `cd apps/ai-sdk && npm run type-check`、`npm run build`：通过，产物已包含 `z-index:10` 手柄样式。
- `git diff --check`：通过。
- 用户需重新加载使用本地构建的页面（`npm run build` 后刷新，或重新 `npm link`）；若 `apps/front` 依赖 npm 包则需发布新版本后升级依赖。

## 2026-08-13 增量验证：拖拽位置与缩放大小本地持久化

用户反馈：缩放大小与拖拽位置需要保存到本地，刷新后恢复，否则窗口位置/尺寸丢失。

实现：

- `core/client.ts`：`AgentClient.storageKey` 由私有改为公开只读，供 UI 复用同一实例的持久化命名空间（消息存储与窗口布局共用前缀、不同 key，互不冲突；`AgentClientOptions.storageKey` 可自定义前缀）。
- 新增 `ui/window-storage.ts`：`serializeWindowRect` / `parseWindowRect` 纯函数，解析时校验 JSON 结构、有限数值与正尺寸，损坏数据回退默认布局。
- `ChatWidget.vue`：窗口 key 为 `` `${agent.storageKey}:window` ``；`onMounted` 时先读取本地布局并 clamp 到当前视口再应用；拖拽/缩放结束（`pointerup`）与视口 resize 重新 clamp 后写入 `localStorage`；读取/写入均 try/catch，隐私模式等受限环境静默降级。

验证：

- `cd apps/ai-sdk && npx vitest run`：`73 passed`（新增 3 个 window-storage 序列化/解析测试）。
- `cd apps/ai-sdk && npm run type-check`、`npm run build`：通过，产物已包含 localStorage 持久化逻辑。
- `git diff --check`：通过。
- 迁移：新增 `20260813_0021_agent_loop_step_thinking`（`agent_loop_steps.thinking_text`），语法解析通过；数据库实例迁移由用户在有库环境执行 `poetry run alembic upgrade head`。

新增覆盖：

- 工具步骤 `input_summary` 输出脱敏截断参数 JSON（≤300 字符），`output_summary` 输出脱敏截断结果摘要（≤500 字符），确认与失败/等待确认状态文案保持兼容。
- 知识库引用携带 `knowledgeBase`（id/name/slug）与命中片段 `text`，`retrieve_citations` 按知识库归属回填。
- `_thinking_text` 兼容 `reasoning_content` 与 thinking 内容块；`stream_graph`/`run_graph` 把思考文本累计到 `GraphResult.thinking_text` 并落库。
- `agent_step_delta`（field=thinking）在标准 SSE 与 Embed WebSocket 两条路径实时下发；SDK 时间线按事件到达顺序维护“正文片段 + 步骤卡片”，完成消息保留时间线。
- SDK `AgentLoopStepCard` 展示思考文本（流式/折叠/超长截断）、知识库名+段落、工具参数与结果；无时间线历史消息降级为“过程在上、正文在下”折叠面板。

## 2026-08-13 增量验证：思考内容真实链路修复（用户反馈“看不到思考内容”）

用户使用思考模型（DeepSeek reasoner 等）实测反馈思考内容未展示。定位根因：

- `langchain-openai 1.4.1` 的 `ChatOpenAI` 模块文档明确声明“非官方 OpenAI 规范字段（如 `reasoning_content`）不会被提取或保留”，流式 `_convert_delta_to_message_chunk` 与非流式 `_convert_dict_to_message` 都会丢弃 DeepSeek/GLM/Kimi 在 `delta`/`message` 中返回的 `reasoning_content`。
- 后端 `_thinking_text` 依赖 `additional_kwargs["reasoning_content"]`，但真实链路中该字段在 LangChain 解析阶段就已丢失，因此思考内容既不实时下发也不落库；单测直接构造 `additional_kwargs` 无法暴露该问题。

修复：

- `app/modules/agent/services.py` 新增 `ProviderThinkingChatOpenAI` 子类：在 `_convert_chunk_to_generation_chunk`（流式）与 `_create_chat_result`（非流式）两个解析入口，把 `reasoning_content`/`reasoning`/`reasoning_details` 归一化补回 `additional_kwargs`；`build_chat_model` 默认返回该子类，覆盖所有 Agent 模型配置。
- `app/modules/conversation/runtime.py` 的 `_thinking_text` 同步兼容 `reasoning` 别名与列表形式（如 `reasoning_details` 内容块），保持与正文严格分离。
- 新增回归测试 `tests/agent/test_thinking_model.py`（厂商字段归一化、流式 delta 保留、非流式 response 保留、正文不受影响）与 `tests/conversation/test_runtime.py` 的 `stream_graph` 全链路测试（逐块 `thinking_delta` + `GraphResult.thinking_text` 累计）。

实际执行命令与结果：

- `cd apps/backend && .venv/bin/pytest tests/agent/test_thinking_model.py tests/conversation/test_runtime.py -q`：`31 passed`。
- `cd apps/backend && .venv/bin/pytest tests/conversation tests/gateway tests/embed tests/knowledge tests/agent -q`：`119 passed, 1 skipped`。
- `cd apps/backend && .venv/bin/pytest -q --import-mode=importlib`：`252 passed, 1 skipped`（较上轮新增 5 个思考链路测试）。
- `cd apps/backend && .venv/bin/ruff check app/modules/agent/services.py app/modules/conversation/runtime.py tests/agent/test_thinking_model.py tests/conversation/test_runtime.py`：通过；`black --check` 同组文件：通过。
- `cd apps/ai-sdk && npx vitest run`：`51 passed`（SDK 本轮无改动，回归确认）。
- `git diff --check`：通过。

验证边界说明：

- 本地模拟 DeepSeek SSE 流式服务验证曾尝试启动（`HTTPServer` 绑定 127.0.0.1），因沙箱网络策略被拒且提升权限被自动审核拒绝；改为用与真实 DeepSeek reasoner 完全一致的 delta 结构（`delta.reasoning_content`）驱动假流式模型，走通 `stream_graph` 全链路验证提取与累计逻辑。
- 真实浏览器 + DeepSeek reasoner 端到端联调与 `poetry run alembic upgrade head` 仍由用户在有库环境执行；确认可见后即可进入 acceptance。

## 2026-08-13 增量验证：技能步骤合并折叠与思考内容折叠

用户反馈“一开始调用的多个技能合并在一起可折叠，思考内容也可折叠”。实现（仅 SDK 展示层，无协议/数据模型变化，无需重新审批）：

- `apps/ai-sdk/src/ui/message-presentation.ts` 新增 `isSkillStep` / `leadingSkillSteps`：只合并首个 `model_generation` 之前的连续技能步骤（`skill_instruction` / `skill_tool`）；回答中途再调用的技能保持独立卡片，按时间顺序内联展示。
- 新增 `AgentLoopSkillGroup.vue` 技能组折叠卡片：summary 显示“调用技能 · N 个”与汇总状态（执行中/完成/失败/待确认），展开后逐行展示技能名、版本、状态与输出摘要；默认展开、用户可折叠。
- `AgentLoopStepCard.vue` 思考内容改为 `<details>` 折叠：生成进行中默认展开实时可见，完成后默认收起；用户手动切换状态通过 `@toggle` 保持，不被后续步骤事件覆盖。
- `ChatMessage.vue` 时间线与 `AgentLoopPanel.vue` 历史降级路径均把组内技能步骤按原时间顺序合并渲染，不产生重复卡片或空占位。
- `vitest.config.ts` 接入 `@vitejs/plugin-vue`，新增 SSR 组件渲染测试 `chat-message.ssr.test.ts`，覆盖技能组合并、思考折叠/展开、生成后技能不合并、历史面板路径。

实际执行命令与结果：

- `cd apps/ai-sdk && npx vitest run`：`60 passed`（新增 4 个 `leadingSkillSteps` 纯函数测试与 5 个 SSR 组件渲染测试）。
- `cd apps/ai-sdk && npm run type-check`：通过。
- `cd apps/ai-sdk && npm run build`：通过，生成 ESM/UMD/CSS/类型声明产物。
- `git diff --check`：通过。
