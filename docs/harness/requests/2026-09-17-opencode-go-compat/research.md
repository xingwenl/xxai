# 业界调研记录

## 调研问题

- 问题：本仓库要把 OpenCode Zen Go（base_url `https://opencode.ai/zen/go/v1`）作为模型源接入，上游返回
  `Request is missing x-opencode-session and cannot be routed efficiently`，需要按上游要求补齐请求头。
- 影响范围：`build_chat_model` 的上游请求头构造方式、`model_options` 的兼容约定、辅助模型（读图/生图）OpenAI 兼容客户端的请求头。
- 影响决策：会话级 session id 从哪里取、注入点放在构造期还是调用期、是否需要在模型配置层暴露开关。

## 功能复杂度

- 级别：普通业务功能（模型供应商接入兼容），非核心 Agent Loop 改造。
- 选择理由：不改数据模型、不改对外 API 契约、不改鉴权，属于「上游客户端请求头」这一局部接缝。
- 最低调研要求：一个官方来源 + 一个成熟开源项目实际实现；已满足，并额外用本机原型验证了注入机制。

## 参考依据

### 来源 1

- 类型：官方文档
- 名称：OpenCode Docs — Go（"Where can I use it?"）
- 链接：https://opencode.ai/docs/go/
- 版本或发布日期：页面无版本号，抓取日期 2026-09-17
- 调研日期：2026-09-17
- 核心做法：文档对客户端提出三点要求——① 发送典型的 coding agent 流量；② 用自有 User-Agent
  （例如 `my-coding-agent/1.0`）标识自己，不要使用通用 SDK 或 HTTP 库名称；③ **每个会话**在
  `x-opencode-session` 中发送稳定的 session ID，用于优化路由和 prompt 缓存。文档同时列出成品端点表：
  `/v1/chat/completions`（`@ai-sdk/openai-compatible`）、`/v1/messages`（`@ai-sdk/anthropic`）、
  `/v1/responses`（`@ai-sdk/openai`）。
- 对本项目的启发：报错文案是 “cannot be routed efficiently”，属于**路由/缓存降级**而非硬鉴权失败，
  因此必须补齐请求头，但不能把它当作鉴权错误来排查。session id 是「每会话稳定」语义，静态写死在
  模型配置里会让所有会话共用一个值，等于没做。

### 来源 2

- 类型：成熟开源项目（本机源码，按仓库 AGENTS.md 要求优先读本机）
- 名称：Pi — `packages/coding-agent/src/core/provider-attribution.ts`
- 链接：本机 `/Users/lixingwen/xw/git/pi`（OpenCode Go 官方文档 "Validated Clients" 表中列为已验证客户端）
- 版本或发布日期：本机当前检出
- 调研日期：2026-09-17
- 核心做法：`getSessionHeaders()` 仅在 `model.provider` 为 `opencode`/`opencode-go` 或
  `new URL(baseUrl).hostname === "opencode.ai"`（精确主机名匹配）时注入
  `{ "x-opencode-session": sessionId, "x-opencode-client": "pi" }`；session id 由会话管理器生成
  （`createSessionId()` 使用 UUIDv7），并有格式校验正则
  `^[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?$`。注入时机是**每次 provider 请求前**（`transformHeaders`
  钩子），不是客户端构造期。
- 对本项目的启发：可直接照搬两个结论——① 用**精确主机名**匹配判定是否注入，避免污染其他供应商；
  ② 除 `x-opencode-session` 外还要带一个客户端标识头 `x-opencode-client`，值用本仓库自己的名字。

### 来源 3

- 类型：成熟开源项目（同上仓库的模型目录生成脚本）
- 名称：Pi — `packages/ai/scripts/generate-models.ts`（OpenCode 变体映射）
- 链接：`/Users/lixingwen/xw/git/pi/packages/ai/scripts/generate-models.ts`
- 版本或发布日期：本机当前检出
- 调研日期：2026-09-17
- 核心做法：`opencode-go` 的 basePath 为 `https://opencode.ai/zen/go`；`@ai-sdk/openai-compatible`
  走 `openai-completions`，base_url 取 `${basePath}/v1`；脚本还修正了 models.dev 的已知错配，把
  `minimax-m2.7`、`qwen3.5-plus`、`qwen3.6-plus` 从 Anthropic 路径改回 OpenAI 兼容路径
  （Anthropic 路径不接受 Bearer 鉴权）。另对 `opencode-go` 的 `reasoning` 字段做了与
  `reasoning_content` 的等价处理。
- 对本项目的启发：本次只需覆盖 OpenAI 兼容 `/v1/chat/completions` 路径，base_url 直接填
  `https://opencode.ai/zen/go/v1` 即可被 langchain-openai 拼接为 `/v1/chat/completions`；
  Anthropic `/v1/messages` 路径需要另一个客户端，明确列为非目标。此外本项目
  `_THINKING_FIELDS` 已包含 `reasoning`，思考字段无需额外改造。

### 来源 4

- 类型：官方 SDK 源码（依赖包内）
- 名称：openai-python — `_base_client.py` 头部合并顺序
- 链接：`apps/backend/.venv/lib/python3.12/site-packages/openai/_base_client.py:717`、`:466`、`:401`
- 版本或发布日期：本机 `OpenAI/Python 2.48.0`
- 调研日期：2026-09-17
- 核心做法：`default_headers` 以 `custom_headers` 存入客户端，并在 `default_headers` 属性中于
  `"User-Agent": self.user_agent` 之后展开；`_build_headers()` 再把 per-request 的
  `options.headers`（即 SDK 的 `extra_headers`）合并到最后。因此 `default_headers` 能覆盖 SDK 自带 UA，
  per-request `extra_headers` 优先级最高。
- 对本项目的启发：**存在一个大小写陷阱**——字典键 `"User-Agent"` 与 `"user-agent"` 在 Python 里是两个
  不同的键，写成小写时 httpx 会把两个值合并，得到
  `User-Agent: OpenAI/Python 2.48.0, ai-base/1.0`，反而仍然带着通用 SDK 名，不满足文档第 ② 条。
  必须使用精确大小写 `User-Agent`。

### 来源 5

- 类型：官方 SDK 源码（依赖包内）
- 名称：langchain-openai — `ChatOpenAI.default_headers` 字段与客户端构造
- 链接：`apps/backend/.venv/lib/python3.12/site-packages/langchain_openai/chat_models/base.py:835`、`:1262`
- 版本或发布日期：本机已安装版本
- 调研日期：2026-09-17
- 核心做法：`ChatOpenAI` 提供 `default_headers: Mapping[str, str] | None`，在构造 OpenAI/AsyncOpenAI
  客户端时作为 `default_headers` 传入；`_get_request_payload()` 会把调用期 kwargs 并入 payload，
  因此 `extra_headers` 也能按次传入。
- 对本项目的启发：`build_chat_model` 已经把 `version.model_options` 原样展开进 `ChatOpenAI(...)`，
  所以静态头**现在就能配**（`model_options.default_headers`），无需改代码；真正缺的只是「按会话变化」
  的那一个头。

## 方案比较

目标：把 `x-opencode-session` / `x-opencode-client` / 非通用 UA 三个头稳定送达上游，且不影响其他供应商。

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| A. 只用 `model_options.default_headers` 静态配置 | 零代码改动，立即可用 | session id 全平台共用一个值，违背「每会话稳定」语义，路由/缓存收益基本为零；UA 大小写写错还会静默失效 | 低（可作为逃生口保留，但不能作为主方案） |
| B. 在 `build_chat_model(version, *, session_id=...)` 构造期注入 `default_headers`，会话 id 由调用方传入 | 改动小、易测；非 opencode 端点行为完全不变 | 调用点是 router 层，此时会话尚未创建，「开始新会话」的请求拿不到 id，只能传 `None` 或占位值 | 低（已否决，见下） |
| C. 用 contextvar 在 runtime 内按调用注入 | 可以拿到 `_resolve_conversation` 之后的真实会话 id | 需要 runtime 在多个模型调用点设置/清理，覆盖面大、隐蔽失败风险高 | 中 |
| D. 传「懒取值」的 `session_id_provider` 可调用对象，在真正发请求时读 `context.conversation_id`（推荐） | 与 C 一样能拿到首轮真实 id，但不需要 contextvar：不改调用时序、不改运行时分发、只在两处构造点与一处客户端子类落地；`context` 是同一个对象且 `_resolve_conversation` 会在模型轮次前赋值 | provider 的求值时机依赖「runtime 先解析会话再调用模型」这一现有前置条件，需用测试锁定 | 高（推荐） |

修正一处早前判断：`_resolve_conversation` / `_resolve_embed_conversation` 会在**第一轮**请求内创建会话并写入
`context.conversation_id`（`apps/backend/app/modules/conversation/services.py:198`、
`apps/backend/app/modules/gateway/runtime.py:410`），且两条链路都在调用模型之前完成。因此「新会话首轮拿不到
真实会话 id」并不成立——准确说法是**模型对象在 router 入口就构造好了，构造时机早于会话创建**，方案 B 因此被否决。
（已核对 `stream_chat` 同样在模型轮次前内联解析会话；`copy_for_turn` 全仓库无调用点，`context` 全程是同一实例。）

注入通道本身也做了比较（原型实测，非推测）：

| 注入通道 | 实测结论 |
|---|---|
| `ChatOpenAI(default_headers={"User-Agent": "ai-base/1.0"})` | 生效，UA 被完整替换为 `ai-base/1.0` |
| `ChatOpenAI(default_headers={"user-agent": "ai-base/1.0"})` | **不生效**：变为 `OpenAI/Python 2.48.0, ai-base/1.0` |
| `model.ainvoke(..., extra_headers={...})` | 生效，per-call 覆盖 |
| 子类覆写 `_agenerate`/`_astream` 注入 kwargs | 生效，`ainvoke`、`bind_tools` 后再 `ainvoke`、`astream` 三条路径均带上三头 |

## 最终决策

- 选择方案：**D**（懒取值 provider），并保留 A 作为逃生口。
- 选择原因：改动集中在「上游请求头」这一个接缝，命中面小、可单测；非 OpenCode 端点分支直接返回空头，
  对既有 DeepSeek/中转站链路为零回归；同时按来源 2 的做法用**精确主机名**判定，避免误伤其他供应商。
- 不选择其他方案的原因：A 无法满足「每会话稳定」语义；B 在 router 层拿不到会话 id；C 与 D 能达到同等效果，
  但 C 需要在 runtime 的多个调用点设置与清理 contextvar，隐蔽失败风险更高，D 只在两处构造点与一处客户端子类落地。
- 对后续 spec、plan 或人工确认的影响：不再需要为「首轮 session id 兜底取值」做取舍；
  不触发架构/数据模型/API 契约/鉴权四类审批条件。

## 剩余风险

- 资料时效性：OpenCode Go 文档无版本号，端点表与模型清单可能随上游调整；本次只依赖「注入两个头 +
  自定义 UA」这一稳定要求，不依赖具体模型清单。
- 与本项目上下文的差异：来源 2/3 是 TypeScript 客户端，注入时机是每次请求前；本项目走
  langchain-openai，注入时机在客户端构造期与调用期，已用原型验证等价。
- 尚未验证的假设：
  1. 上游是否对 `x-opencode-client` 的取值有白名单要求（文档只提到 UA 要自有名称，Pi 用 `pi`）；
  2. `context.conversation_id` 在模型调用前必然已赋值的结论来自静态代码走查（三处会话解析 + 无 `copy_for_turn`
     调用点），尚未用运行期断言验证，需在实现阶段用单测锁定；
  3. Anthropic `/v1/messages` 与 `/v1/responses` 两个路径本次不覆盖，相关模型（如 `qwen3.8-max`）暂不可用。
     以上第 1、3 项都需要真实 API key 才能确认，将在 `verify.md` 记录实际结论或标注为待人工验证。
