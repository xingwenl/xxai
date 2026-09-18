# OpenCode Zen Go 接入兼容设计说明

## 目标

让本仓库可以直接把 OpenCode Zen Go（base_url `https://opencode.ai/zen/go/v1`）当作 OpenAI 兼容模型源接入，
并按上游要求补齐客户端标识与会话头，消除
`Request is missing x-opencode-session and cannot be routed efficiently` 这一路由/缓存降级问题。

受影响对象：平台管理员（在模型注册表或 `.env` 里登记 OpenCode Go 模型条目）、所有走
`build_chat_model` 的对话链路（REST `/chat`、`/chat/stream`、Embed WebSocket），以及读图/生图两个
OpenAI 兼容辅助工具。

完成后应产生的可验证结果：
1. 指向 `opencode.ai` 的模型请求带上 `x-opencode-session`、`x-opencode-client` 与自有 `User-Agent`；
2. 指向其他供应商（DeepSeek、中转站等）的请求头与现状**完全一致**，无回归；
3. 上述行为有单元测试覆盖，并在 `verify.md` 记录真实命令与结果。

关键调研结论（详见 `research.md`）：
- 官方文档要求自定义 UA + 每会话稳定的 `x-opencode-session`，且报错属于降级而非鉴权失败；
- 本机 Pi 源码给出可照搬的参考实现：精确主机名匹配 + `x-opencode-session` + `x-opencode-client`；
- OpenAI SDK 存在 UA 大小写陷阱（`user-agent` 小写会与 SDK 默认 UA 合并），必须用精确大小写 `User-Agent`；
- 注入通道已用本机原型实测（`default_headers` 与 per-call `extra_headers` 均生效），因此不引入 contextvar。
- 会话 id 可用且**从第一轮就可用**：会话在模型调用之前创建（`_resolve_conversation` /
  `_resolve_embed_conversation` 会写入 `context.conversation_id`），只是 `build_chat_model` 在 router 入口
  构造得更早，所以采用「懒取值 provider」在真正发请求时读取，而不是在构造期取值。

## 范围

### 包含

- 新增上游请求头工具模块：判定「是否 OpenCode 端点」并构造兼容请求头（`User-Agent`、`x-opencode-client`、
  可选 `x-opencode-session`）。
- `build_chat_model` 增加可选 `session_id_provider` 入参（无参可调用对象，返回会话 id 或 None），
  按端点判定注入头；非 OpenCode 端点保持零注入。
- `ProviderThinkingChatOpenAI` 增加按次注入能力，用于把会话级 session id 送到每一次模型调用
  （包括 `bind_tools` 之后与流式 `astream`）。
- 三处 `build_chat_model` 调用点传入 `session_id_provider=lambda: context.conversation_id`：
  `conversation/router.py` 的非流式与流式入口、`gateway/router.py` 的 Embed WebSocket 入口。
- 复用同一请求头工具，为 `tools/basic/vision.py`（读图）与 `tools/basic/image_gen.py`（生图）这两个
  自带 base_url 的 OpenAI 兼容客户端补上客户端标识头与 UA。
- 在 `.env.example` / 相关文档补充 OpenCode Zen Go 的配置示例（base_url、模型名、`model_options` 用法）。
- 单元测试与 Harness 六件套文档。

### 不包含

- Anthropic 格式 `/v1/messages` 路径的接入（需要 `ChatAnthropic` 类客户端）。因此 `qwen3.8-max`、
  `minimax-m3` 这类只提供 `/v1/messages` 的模型本期不可用。
- OpenAI Responses 路径 `/v1/responses` 的自动化接入与验证（可通过 `model_options.use_responses_api=true`
  手工尝试，本期不作为验收项）。
- embedding 路径（`asset_processing/runtime.py`）的上游头注入：OpenCode Go 当前不提供 embedding 模型。
- 修改 `conversation/services.py`、`gateway/runtime.py` 的调用时序以让新会话首轮就拿到真实会话 id
  （调研方案 C/D 都不需要改时序，此项仅用于说明边界）。
- 前端 UI 改动、模型注册表表结构改动。

## 数据模型

本次不涉及数据模型变化：不改表、不加列、不需要 alembic 迁移。
`agent_versions.model_options` 与 `platform_models.options` 继续作为自由 JSON 使用，本次只是明确其中
`default_headers` 键的用途。

## 设计说明

### 端点判定

照搬来源 2 的做法，用**精确主机名**匹配，而不是子串包含：
`urlparse(base_url).hostname == "opencode.ai"`。为空的 base_url 判定为非 OpenCode。

### 请求头构成

OpenCode 端点下注入以下头（非 OpenCode 端点返回空字典，调用方不改变任何现有行为）：

| 头 | 取值 | 说明 |
|---|---|---|
| `User-Agent` | `ai-base/1.0` | 必须精确大小写，否则会与 SDK 默认 UA 合并 |
| `x-opencode-client` | `ai-base` | 客户端标识，对应 Pi 的 `x-opencode-client: pi` |
| `x-opencode-session` | 会话 id（见下） | 上游用于路由与 prompt 缓存，要求每会话稳定 |

合并顺序：`model_options.default_headers` 里的同名键优先级最高，允许使用者覆盖 UA 与客户端标识。

### session id 取值

统一使用真实会话 id 的字符串形式：`build_chat_model` 接收一个无参可调用对象
`session_id_provider`，在**每次模型调用之前**求值，读取 `context.conversation_id`。

这样「开始新会话」的第一轮也能拿到真实 id（会话在该轮内、模型调用之前创建），
同一会话在整个生命周期内取值恒定，不存在首轮占位值或首轮/次轮切换。

取值格式满足来源 2 的校验正则 `^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$`。

防御性约定：若 provider 返回 `None`（理论上不应发生），仍然发送 `User-Agent` 与 `x-opencode-client`，
只是不发送 `x-opencode-session`，并用 debug 日志记录一次，便于定位异常链路而不是静默丢头。

### 注入时机

- 静态头（UA、`x-opencode-client`，以及配置里显式给出的 `x-opencode-session`）在 `build_chat_model`
  构造 OpenAI 客户端时通过 `default_headers` 注入；
- 会话头在每次模型调用时通过 `extra_headers` 注入，由 `session_id_provider` 现场求值，
  既保证首轮即可拿到真实 id，也避免客户端实例在多次调用之间复用导致的会话串号。

## 风险

- 回归风险：`build_chat_model` 被三条主链路共用。缓解方式是端点判定只认精确主机名，非 OpenCode
  分支返回空头，并用单测锁定「非 OpenCode 端点不产生任何新增头」。
- 兼容性风险：`User-Agent` 大小写写错会静默退化为「SDK UA + 自定义 UA 合并」，反而更不满足上游要求。
  缓解方式是在工具模块内固定精确大小写，并用单测断言请求头里不存在 `OpenAI/Python` 字样。
- 联调风险：懒取值依赖「runtime 先解析会话、再调用模型」这一现有前置条件。该条件已通过静态走查确认
  （三处会话解析均在模型轮次之前，且 `copy_for_turn` 无调用点、`context` 全程同一实例），
  但仍需单测锁定：会话未解析时不得发送 `x-opencode-session`，解析后同一请求内多次模型调用取值一致。
- 数据风险：无。本次不写数据库结构，不改会话内容。

## 停点判断

- 是否涉及架构边界变化：否（仅上游 HTTP 请求头构造，不改变模块职责边界与调用时序）。
- 是否涉及数据模型变化：否。
- 是否涉及 API 契约变化：否（不改本仓库对外 REST/WS 请求体与响应体；仅改变发往上游的请求头）。
- 是否涉及鉴权或权限行为变化：否（API key 的读取与解密路径不变）。
- 结论：**不触发四类强制审批条件**；但按仓库规则仍需完成「spec 后方案对齐检查点」的用户确认。

## 验收标准

1. 当模型 base_url 为 `https://opencode.ai/zen/go/v1` 时，实际发出的请求包含
   `User-Agent: ai-base/1.0`、`x-opencode-client: ai-base`、`x-opencode-session: <会话 id>`，
   且请求头中不出现 `OpenAI/Python`。
2. `x-opencode-session` 在同一会话的多轮请求中保持一致；**开始新会话的第一轮也带上真实会话 id**
   （即以该轮内新建的 `conversation_id` 取值），不存在占位值或缺省。
3. 当模型 base_url 指向非 `opencode.ai` 主机时，请求头与改动前一致（不新增上述三个头）。
4. `model_options.default_headers` 中显式给出的同名头能覆盖默认值。
5. 读图（`image_read`）与生图（`image_generate`）在 base_url 指向 `opencode.ai` 时同样带上客户端标识头与 UA。
6. 新增单测全部通过，且 `tests/agent`、`tests/conversation`、`tests/gateway`、`tests/tools` 回归通过。
7. `.env.example` 或文档给出 OpenCode Zen Go 的可复制配置示例（base_url、模型名、`model_options`）。
8. `verify.md` 记录实际执行的命令与真实输出；真实 API key 联调若无法执行，必须明确标注为待人工验证。

## 变更记录

### 初始版本

- 时间：2026-09-17
- 变更原因：首次创建 request，接入 OpenCode Zen Go 并补齐上游要求的请求头
- 变更内容：建立本次任务的初始设计说明
- 影响章节：全部
- 是否触发人工确认：否（不涉及架构/数据模型/API 契约/鉴权四类审批条件），但需完成 spec 后方案对齐确认
