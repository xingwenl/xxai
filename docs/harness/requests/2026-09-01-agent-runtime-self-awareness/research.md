# Agent 运行时自感知（模型 / 配置 / 用量 / 版本）调研

调研日期：2026-09-01

## 调研问题

让 AI 能准确回答「你现在用的是哪个模型、什么配置、用量多少、什么版本」，而不是编造或含糊回答。需要披露的信息：

- 模型：当前对话模型名（`AgentVersion.model_name`）
- 配置：温度、模型选项、能力等非敏感配置
- 用量：token 用量（已有 `ModelUsageRecord`）
- 版本：Agent 版本号（`AgentVersion.version`）、服务版本（`settings.app_version`）、SDK 最低版本（`settings.sdk_minimum_version`）

## 功能复杂度

- 级别：核心功能（新增模型可见工具 + 系统提示词内容变化）
- 选择理由：涉及 API 契约（模型可见工具列表）、行为变化（系统提示词新增运行时元数据段）、
  跨后台 REST 与 embed WebSocket 两条链路，属于策略 B（复杂/架构级变更），需人工确认后实现。

## 本地现状（代码事实）

- 系统提示词组装：`apps/backend/app/modules/conversation/runtime.py` 的 `build_system_prompt()`
  按 `version.system_prompt -> caller_system_prompt -> skill_instructions -> citations -> host_tools`
  顺序拼接；`load_runtime_context()` 组装 `RuntimeContext`（含 `agent`/`version`/`conversation_id` 等）。
  调用点共三处：`conversation/services.py:397`（后台非流式）、`:551`（后台流式）、
  `gateway/runtime.py:636`（embed 流式）。
- 模型配置：`AgentVersion`（`apps/backend/app/modules/agent/models.py:63`）含
  `model_name`/`model_base_url`/`api_key_encrypted`/`temperature`/`model_options`/`capabilities`/`version`；
  `AgentVersionRead` 只对外暴露 `has_api_key`，不暴露密钥本体。
- 用量：`ModelUsageRecord`（`conversation/models.py:123`）含
  `platform_id`/`agent_id`/`agent_version_id`/`client_id`/`user_id`/`platform_end_user_id`/
  `conversation_id`/`message_id`/`model_name`/`prompt_tokens`/`completion_tokens`/`total_tokens`；
  `ModelUsageRepository`（`model_usage/repositories.py`）有按日期范围 + agent/client 的
  `summary()` 与分页 `list_records()`，暂无「按 conversation 汇总」方法（可新增）。
- 业务工具框架：`tools/business/framework.py` 的 `business_tool` 装饰器 + `BUSINESS_TOOL_REGISTRY`；
  `business/registry.py` 统一导入注册；`builtin_tool/registry.py` 用 `_from_business` 包装成
  `BuiltinToolDefinition`，使业务工具进入既有内置工具链路（管理端目录、Agent 绑定、运行时委托）；
  执行统一走 `invoke_builtin_tool`（`conversation/router.py:72`、`gateway/dispatcher.py:106`），
  构建 `BusinessToolContext`（platform_id/agent_id/conversation_id/user_id/session）。因此新增业务工具
  只需在 `business/registry.py` 注册，两条链路绑定后即自动可用。
- 版本：`settings.app_version`（`core/config.py:135`，默认 `0.1.0`）、`settings.sdk_minimum_version`
  （`:254`，默认 `0.1.0`）；`system/services.py` 已有服务版本查询接口先例。
- 先例：`2026-08-24-ai-sdk-session-info` 的 `session_ready` 下发 client/agent/quota 采用
  「查询失败→null、不阻塞连接」降级策略，本次沿用。
- 约束：`2026-08-27-model-registry` 明确「不修改 `agent_versions` 主对话模型语义」；本期不触碰。

## 参考方案（业界）

### 方案一：系统提示词注入运行时元数据块 + 业务工具实时查用量（业界主流，推荐）

- **Langflow PR #12855**（2026-05，github.com/langflow-ai/langflow/pull/12855）：
  结构化默认系统提示词 + 运行时环境注入（`{current_date}`、`{model_name}` 等）；
  不修改用户配置，渲染后写入 `_effective_system_prompt`；对缓存友好（静态前缀 + 运行时渲染尾部）；
  附 18 个单测。配套 PR #12864 把 `{current_date}`/`{model_name}` 注入默认系统提示词。
- **LobeHub PR #16593**（2026-06，lobehub/lobehub）：
  将身份注入从各 Agent 提示词模板下沉到共享 context-engine provider（`ModelInfoProvider`），
  为每个 Agent 注入 `Current model: {displayName} ({id})`，builtin 与自定义 Agent 全覆盖。
- **ironclad-agent `runtime_metadata_block(version, primary_model, active_model)`**
  （docs.rs，已打开核实）：构建紧凑运行时元数据块注入系统提示词，使 agent 能准确报告
  版本与模型配置；纯函数、零副作用，可单测。

共同点：静态元数据（模型、版本、配置）随系统提示词注入，让模型开箱即知自身身份；
用量等动态数据另行获取（工具或事件），不掺入静态提示词。

### 方案二：会话开始注入用量快照（Claude Code /status 模式）

- **Claude Code statusline**（code.claude.com/docs/en/statusline，已打开核实）：
  status line 从会话 JSON 读取 `model.id`/`model.display_name`、`version`、
  `context_window.total_input_tokens`/`total_output_tokens`/`used_percentage`、
  `cost.total_cost_usd`、`rate_limits` 等字段；事件驱动刷新（新消息到达时更新）。
- 该模式把「当前状态快照」交给会话层维护，模型本身不主动查询。

### 方案三：纯工具查询，不注入提示词

- 不注入任何元数据，模型在用户询问时调用工具获取。
- 业界无成熟先例；Langflow/LobeHub/ironclad-agent 均选择注入而非纯工具，因为
  模型对「自身身份」类问题常直接编造，不一定会调用工具。

### 用量与成本的 API 侧事实（佐证字段语义）

- Anthropic Messages API：`usage: {input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens}`。
- OpenAI Responses/Chat Completions：`usage.input_tokens/output_tokens`（含 prompt cache 明细）。
- Vercel AI SDK：`onFinish({ usage })` / `event.usage.totalTokens` 在流结束后记录 token 用量
  （ai-sdk.dev cookbook: record token usage after streaming object）。
- 本仓库 `ModelUsageRecord` 已按上述语义落库（prompt/completion/total_tokens），无需新增字段。

## 方案比较

| 维度 | 提示词注入 + 业务工具（方案一） | 会话快照注入（方案二） | 纯工具查询（方案三） |
| --- | --- | --- | --- |
| 模型自答可靠性 | 高，身份信息开箱可见 | 高，但用量为快照 | 低，模型可能编造 |
| 用量实时性 | 高，工具实时查库 | 低，会话内滞后 | 高 |
| 实现面 | 中：元数据块 + 新工具 + 双链路 | 小：仅提示词拼接 | 小：仅新工具 |
| 业界依据 | Langflow/LobeHub/ironclad-agent 一致 | Claude Code statusline | 无 |
| 兼容性 | 提示词内容变化，旧 SDK 不受影响 | 同左 | 无提示词变化 |
| 隐私风险 | 需白名单字段，敏感字段不注入 | 同左 | 由工具契约控制 |

## 最终决策

采用方案一：**系统提示词注入运行时元数据块 + 新增统一业务工具 `get_runtime_info`**。

- 元数据块（静态、随每次会话组装）：
  - 模型名（`AgentVersion.model_name`）、Agent 版本号（`AgentVersion.version`）
  - 服务版本（`settings.app_version`）、SDK 最低版本（`settings.sdk_minimum_version`）
  - 非敏感配置白名单：`temperature`、`capabilities` 摘要（如 image/native_file/text_retrieval）
  - 敏感字段绝不注入：`api_key_encrypted`；`model_base_url` 默认不注入（避免泄露内网服务地址），
    如需披露走工具返回脱敏域名。
- 业务工具 `get_runtime_info`（动态、实时）：
  - 当前会话用量（`ModelUsageRecord` 按 `conversation_id` 汇总，需在 `ModelUsageRepository`
    新增会话汇总方法）
  - 今日/累计用量（按 platform/agent 汇总，复用现有 `summary` 思路）
  - 连接与身份信息（agent 名称/slug、client 名称、模型名）
  - 降级：任一查询失败返回对应字段为 `null`，不阻塞工具调用
- 注入位置：`build_system_prompt()` 内新增一个段落（在 `version.system_prompt` 之后追加
  「运行时信息」段），三个调用点自动生效，两条链路（后台 REST + embed WebSocket）一致。
- 兼容性：系统提示词内容变化不影响 SDK 协议；新增业务工具走既有 builtin 工具链路，
  Agent 未绑定时不暴露给模型，行为向后兼容。

## 关键决策与边界

- 不改 `agent_versions` 表结构与主对话模型语义（遵守 model-registry 约束）。
- 不新增数据库表；用量复用 `ModelUsageRecord`。
- 不向系统提示词注入任何密钥、完整 base_url、用户隐私数据。
- 元数据块为纯文本静态拼装（不含工具执行副作用），可单测。
