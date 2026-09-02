# Agent 运行时自感知规格（模型 / 配置 / 用量 / 版本）

## 目标

让 AI 能准确回答自身运行时信息：当前模型、非敏感配置、用量、版本。
采用方案一（调研结论）：系统提示词注入静态运行时元数据块 + 新增统一业务工具 `get_runtime_info`
实时查询用量与身份信息。后台 REST 会话与 embed WebSocket 会话两条链路行为一致。

## 范围

### 包含

- `build_system_prompt()` 新增「运行时信息」段，注入白名单静态元数据：
  模型名、Agent 版本号、服务版本、SDK 最低版本、温度、能力摘要。
- 新增业务工具 `get_runtime_info`（`apps/backend/app/modules/tools/business/runtime_info.py`）：
  实时返回当前会话用量、今日/累计用量、Agent/client 身份与模型信息。
- `ModelUsageRepository` 新增按 `conversation_id` 的会话用量汇总方法。
- 两条链路（`conversation/services.py` 后台 REST、`gateway/runtime.py` embed WebSocket）
  通过既有 `build_system_prompt` 与 builtin 工具链路自动生效，无需各链路单独改动。
- 单测：元数据块拼装（字段白名单、敏感字段不出现）、`get_runtime_info` 工具契约与降级、
  会话用量汇总 SQL 正确性。
- Harness 六件套文档（本 request）。

### 不包含

- 修改 `agent_versions` 表结构或主对话模型语义。
- 新增数据库表；用量继续复用 `ModelUsageRecord`。
- 向 SDK 协议新增事件或字段（`get_runtime_info` 是模型侧工具，非客户端事件；
  `session_ready` 已有 client/agent/quota 信息，本次不扩展）。
- 实时成本金额计算（`ModelUsageRecord` 无金额字段，仅披露 token 用量）。
- 用量实时推送（工具为查询式，不做会话内主动推送）。

## 设计

### 1. 运行时元数据块（系统提示词注入）

在 `build_system_prompt()` 中，`version.system_prompt` 之后新增段落：

```text
【运行时信息】
- 模型：<model_name>
- Agent 版本：v<version>
- 服务版本：<app_version>
- SDK 最低版本：<sdk_minimum_version>
- 温度：<temperature>
- 能力：<capabilities 摘要，如 image/native_file/text_retrieval>
说明：以上为当前会话实际运行配置；涉及用量、连接、配额等信息请调用 get_runtime_info 工具获取。
```

实现：

- 新增纯函数 `build_runtime_metadata_block(version, settings)`（放 `conversation/runtime.py`），
  返回文本块或 `None`（字段缺失时跳过对应行），便于单测。
- 白名单字段：`model_name`、`version`、`temperature`、`capabilities`（仅取
  image/native_file/text_retrieval 三项布尔值）；系统层：`app_version`、`sdk_minimum_version`。
- 禁止字段：`api_key_encrypted`、`model_base_url`（如需连接信息走工具返回脱敏域名）。
- `build_system_prompt()` 三个调用点自动生效，无额外传参（`version` 已传入）。

### 2. 业务工具 `get_runtime_info`

- 文件：`apps/backend/app/modules/tools/business/runtime_info.py`，在
  `tools/business/registry.py` 注册导入。
- 名称：`get_runtime_info`；描述：说明「返回当前会话与 Agent 的运行时信息：模型名、
  版本、当前会话/今日 token 用量、连接身份」，仅在用户询问自身配置/版本/用量时调用。
- 输入契约：空对象 `{}`（无参数），避免模型传错参数。
- 返回结构（降级字段为 `null`，不报错）：

```json
{
  "model": { "name": "gpt-5.2", "temperature": 0.2, "capabilities": { "image": true } },
  "agent": { "agentId": 11, "name": "客服助手", "slug": "support-bot" },
  "version": { "agentVersion": 3, "serviceVersion": "0.1.0", "sdkMinimumVersion": "0.1.0" },
  "usage": {
    "conversation": { "promptTokens": 1200, "completionTokens": 300, "totalTokens": 1500, "messageCount": 8 },
    "today": { "totalTokens": 25000, "messageCount": 120 },
    "total": { "totalTokens": 120000, "messageCount": 600 }
  },
  "client": { "clientId": "client_live", "name": "线上站点" }
}
```

- handler 用 `BusinessToolContext`（platform_id/agent_id/conversation_id/session）查
  `ModelUsageRepository`；client 身份从当前会话最近一条用量记录的 `client_id` 反查
  `PlatformEmbedClient`（后台会话无 client_id 时返回 null，避免扩展框架字段）：
  - `conversation`：新增 `session_summary(conversation_id, platform_id, agent_id)`，按
    `conversation_id` 过滤汇总 prompt/completion/total_tokens 与记录数。
  - `today`：`summary()` 用 `date.today()` 起止；`total`：不传 start_date（或传最小日期），
    按 platform/agent 汇总。
  - 身份：`Agent`/`PlatformEmbedClient` 查询失败返回 `null`（沿用 session-info 降级策略）。
- 安全：仅返回白名单字段，不返回密钥、base_url；工具依赖 DB 会话只读查询。

### 3. 工具可见性

- 通过 `builtin_tool/registry.py` 的 `_from_business` 自动包装进入既有 builtin 工具链路；
  Agent 需在管理端绑定启用该工具后模型才可见（与 `knowledge_search` 一致）。
- REST 后台会话与 embed 会话均通过 `invoke_builtin_tool` 执行，无链路差异。

## 测试

- `apps/backend/tests/` 新增：
  - `build_runtime_metadata_block` 单测：字段齐全、缺失字段跳过、敏感字段（api_key/base_url）
    不出现、capabilities 仅白名单三项。
  - `get_runtime_info` handler 单测：会话用量正确、今日/累计降级为 null、Agent 查询失败不抛错。
  - `ModelUsageRepository.session_summary` 单测：按 conversation_id 汇总正确、跨会话不串数据。
- 回归：现有系统提示词拼装测试、工具注册完整性校验（`validate_business_tool_dependencies`）。

## 非目标

- 不新增 SDK 事件或 `session_ready` 字段（客户端侧信息在 `2026-08-24-ai-sdk-session-info` 已覆盖）。
- 不做金额/成本统计。
- 不自动为存量 Agent 启用新工具（保持「绑定才可见」语义，避免行为突变）。

## 风险

- 提示词长度：元数据块固定小体积（<500 字符），不随会话增长。
- 隐私：字段白名单 + 单测断言，密钥/base_url 不进入提示词与工具返回。
- 兼容性：旧 Agent 未绑定新工具时模型不可见该工具，行为与现状一致；
  系统提示词新增段落对既有会话无破坏性影响。
- 性能：工具查询为索引列过滤（conversation_id/platform_id/agent_id），量级可控；
  today/total 汇总如超时则返回 null 降级。

## 停点判断

- 是否涉及架构边界变化：否，改动在既有提示词组装与工具框架内。
- 是否涉及数据模型变化：否，无新表新字段。
- 是否涉及 API 契约变化：是，模型可见工具列表新增 `get_runtime_info`，
  系统提示词内容（模型行为输入）变化。
- 是否涉及鉴权或权限行为变化：否，沿用 Agent 绑定工具的既有权限语义，查询只读。
- 结论：**进入实现前需人工确认**（API 契约/行为变化）。

## 验收标准

- 系统提示词包含运行时信息段，含模型名、Agent 版本、服务版本、温度、能力摘要；
  不含 api_key、base_url 等敏感字段。
- Agent 绑定并启用 `get_runtime_info` 后，模型可调用该工具；返回含当前会话用量、
  今日/累计用量、Agent/client 身份与模型信息。
- 查询失败（如 DB 异常）时工具返回各字段 `null`，不抛错、不泄漏堆栈。
- 后台 REST 会话与 embed WebSocket 会话均能看到运行时信息段并能调用该工具。
- 未绑定该工具的存量 Agent 行为不回归（工具不可见，提示词其余段落不变）。
- 相关单测通过，Harness 六件套文档齐备。

## 变更记录

### 2026-09-01 第 1 次变更（实现期澄清）

- 变更原因：实现 `get_runtime_info` 时明确 client 身份的获取路径。
- 变更内容：返回结构新增 `client`（clientId/name），来自当前会话最近用量记录反查
  `PlatformEmbedClient`；后台会话或查询失败时为 `null`。`BusinessToolContext` 不新增字段。
- 影响章节：设计（业务工具返回结构、handler 说明）。
- 是否触发人工确认：否（未改变已批准的范围与契约方向，仅补全返回示例）。
