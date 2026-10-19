# 工具审批接线：把已有的副作用分类接到执行闸口，并新建通用确认表

## Status

accepted

关联 Harness request：`2026-10-19-tool-approval-wiring`（tier A，spec 与验证证据见 `docs/harness/requests/2026-10-19-tool-approval-wiring/`）。术语（工具确认、确认记忆、无人值守运行、自动批准）见 `CONTEXT.md`。本 ADR 与 `docs/adr/0007-run-event-model-unification.md:40` 的关系见 Decision 第 8 条。

## Decision

**副作用只保留一套词汇，落在 `app/modules/tools/side_effects.py`。** `SideEffect = Literal["none","navigation","write","financial","external"]`，`create` 只作为历史别名归一到 `write`；声明期走 `normalize_side_effect()`（未知值直接抛错、启动即失败），运行期走 `coerce_side_effect()`（未知值保守回落 `external`，永不抛），`max_side_effect()` 用保守度全序 `none < navigation < write < external < financial` 取上界。此前有三套互不兼容的词汇：规范集写在 `mcp/schemas.py:6` 与 `host_tool/schemas.py:6`，而能力层自造了 `{"none","create"}`（`tools/basic/framework.py:16`），`financial` 排在最保守端是因为 `tasks/unattended.py:25` 把它硬编码为永不自动批准。

**真正的缺陷不是「没有分类」而是「分类没接到闸口」，所以修的是透传而不是分类法。** 真值早在 `tools/basic/image_gen.py:47` 声明了 `side_effect="create"`，但包装层 `BusinessTool`（`tools/business/framework.py:43-49`）没有这个字段，暴露层 `builtin_tool/registry.py:31-38 _from_business` 也就没传，最后被 `builtin_tool/schemas.py:12,19` 写死成 `Literal["none"]` —— 于是裁决器永远拿到 `"none"`、永远 `auto_approved`。因此本轮给 `BusinessTool` 补字段与装饰器参数，并用 `effective_side_effect(tool) = max(自身声明, 各 depends_on 的 basic 工具声明)` 防止包装层低报副作用（`image_generate` 就是靠这条从 `image_gen.generate` 继承到 `write`）。

**审批闸口放在 `builtin_tool/services.py::invoke_builtin_tool`，不放在 `conversation/tool_dispatch.py`。** 三个理由：它是所有内置工具调用的必经 public seam（REST 分派、无人值守任务、网关 WS 都经此，放这里最不易被绕过）；契约校验（`invalid_arguments`）先在、弹卡在后，不为一次注定失败的调用打扰用户；网关 `dispatcher.py` 直调它，因此 WS 路径不必自己搭 Future 等待。判据取**注册表定义** `definition.side_effect` 而非传入的 `tool` 对象，避免旁路。`tool_dispatch.py` 只把 decider 透传下去。

**新建通用确认表 `tool_confirmations`（迁移 `20261019_0040`），不复用 `mcp_tool_confirmations`。** `McpToolConfirmation`（`mcp/models.py:143-203`）的 `tool_id` 是 `mcp_tools` 的 NOT NULL 外键、`audit_id` 是 `mcp_tool_call_audits` 的 unique NOT NULL 外键，而内置工具既无工具表也无审计表（`builtin_tool/`、`conversation/` 里 grep `audit` 零命中），泛化会同时破坏 MCP 的语义与唯一约束。多态沿用仓库先例（`tasks/models.py:130-145` 的「类型判别列 + 可空外键」）：用 `tool_name`/`tool_type` 字符串 + 「会话主体恰有一个非空」约束 + 五个外键列各自可空。

**交互式确认复用网关既有的连接级等待通道，`gateway/router.py` 零改动。** `pending_mcp_confirmations` 这个字典在连接层只做「按 `callId` `set_result(bool)`」（`gateway/router.py:262-266`），与工具来源完全解耦；MCP 的落库与执行发生在 await 的另一侧。于是内置工具的 Future 直接注册进同一个字典即可复用整条链路，不必给 `stream_embed_chat` 沿途 8 处形参再加一份状态。代价是字典名与实际含义不再一致，记为命名债。

**无人值守侧复用已有的 `UnattendedPolicy`，不新增第二套策略。** `build_confirmation_decider()` 现在对内置工具也生效，`auto_approve`/`strict_approval` 的既有语义与默认值（`True`/`False`）不变，`financial` 仍然永不自动批准。**没有确认通道时取「拒绝并告知」**：decider 为 `None`、或返回 `None`（表示不由本层处理）时，闸口直接返回 `rejected` 结果而不是放行——写操作宁可拒绝也不静默执行。

**交互式运行里 `navigation` 直通、不弹卡。** 闸口本身只判断 `side_effect != "none"`（保持 fail-closed，这样 `auto_approve=False` 仍能拦住一切），「navigation 直通」落在交互式裁决器 `RuntimeToolDispatcher._decide_builtin_confirmation` 里：`navigation` 只改宿主页面的路由、不写数据，直接返回批准，不落库也不发事件。内置工具目前没有任何一个声明 `navigation`，这条是为将来可能出现该声明的工具预留与已确认策略一致的语义。

**委派子运行 fail-closed，确认不向父会话冒泡。** 只有无人值守策略构造的裁决器带 `INHERITABLE_DECIDER_ATTR` 才下传给 `execute_unattended_chat`；交互式裁决器绑在父连接的等待通道上，下传等于让确认弹窗冒泡到父会话（需要父侧事件路由与去重），本轮明确不做。因此交互式会话里派生的子运行遇到需确认工具一律拒绝。

**确认 TTL 600 秒，并在会话内记住同类工具的批准。** `remember_check` 只认同平台、同会话、同工具名、TTL 内的 `approved` 记录；`financial` 列入 `MEMORY_EXEMPT_SIDE_EFFECTS`，每次都要问。过期与拒绝分别回 `confirmation_expired` 与 `user_rejected` 两个稳定原因码给模型——拒绝是明确表态，超时可能只是人不在，两者的可重试语义不同。

**SSE/REST 的待确认本轮仍不可解决，ADR 0007 第 3 条继续成立。** 本轮只接通 WS（控制台浮窗与 embed 都走它）；REST 流式与微信助手取「拒绝并告知」。把 SSE 接上需要一整套新对外能力（REST 解决端点、鉴权、幂等）加上从零建续跑机制（`continue_run` 全仓零调用、`resume_token` 无生产者无消费者），拆为 ③b 另立 A 档 request，不在本 ADR 覆盖范围。

## Considered Options

- **保留三套词汇，只把 basic 的 `side_effect` 原样透传到 builtin**：`"create"` 会漏进对外契约，且包装层的低报（`BusinessTool` 自己声明 `none` 而依赖是 `write`）依然无法发现。
- **复用 `mcp_tool_confirmations`，把 `tool_id`/`audit_id` 放宽为可空**：破坏 MCP 侧的 NOT NULL 与唯一约束语义，且表名会让后续所有读者误判适用范围。
- **把闸口放在 `conversation/tool_dispatch.py`**：只覆盖 REST/无人值守分派路径，网关 `dispatcher.py` 直调 `invoke_builtin_tool` 的那条路会绕过去。
- **不动模型层，在 `builtin_tool/services.py` 里用 `getattr` 猜副作用**：真值在包装层就丢了，等于把判据建在恒为 `none` 的字段上。
- **给内置工具新增 `confirmation_policy` 字段（照宿主工具的形态）**：与 `side_effect != "none"` 的判定重复，两处策略迟早漂移；宿主工具需要它是因为页面注册信息里没有副作用概念，内置工具不需要。
- **让交互式裁决器随委派下传（确认冒泡到父会话）**：需要父连接的事件路由、去重与 UI 归属处理，成本远超本轮收益。
- **无确认通道时保持现状（静默执行）**：与「写操作需要在场批准」的目标直接冲突，且会让 REST 流式路径成为绕过审批的后门。
- **一次性把 SSE 的 REST 解决端点与续跑一起做**：那是新的对外契约（鉴权、幂等、审计、配额）加上一个从零开始的运行恢复机制，与本轮「把已有分类接到闸口」不是一件事。

## Consequences

- **无人值守运行的行为变化是实质性的**：`create_task`/`delegate_tasks`/`image_generate` 从「一律执行」变成「按 `UnattendedPolicy` 裁决，可被拒绝」。默认 `auto_approve=True` 下仍然批准，只有 `strict_approval=True` 时非 `navigation` 的工具会被拒。
- **交互式 WS 会出现确认卡**：控制台浮窗与 embed 侧本来就能渲染（`apps/ai-sdk` 与 `apps/front` 无需改动），前提是事件里的 `callId` 非空。REST 流式与微信助手在 ③b 之前取「拒绝并告知」。
- **对外读模型放宽是契约变化**：`BuiltinToolCatalogRead.side_effect` 与 `AgentBuiltinToolRead.side_effect` 由 `Literal["none"]` 改为五值，`BuiltinToolOutcome.status` 新增 `rejected`（`agent_runtime/tool_events.py:99` 已经把 `rejected` 映射为 `failed`）。前端目前不消费内置工具的该字段，故无回归。
- **`pending_mcp_confirmations` 的名字不再准确**：它现在承载所有需确认工具的等待通道（MCP 与内置工具共用）。改名要动连接层的 8 处形参与断连清理，本轮只加注释，债务记在这里。
- **确认表约束名被约定二次前缀并截断**：模型里写 `ck_tool_confirmations_exactly_one_principal`，经仓库 `ck: "ck_%(table_name)s_%(constraint_name)s"` 约定后超 PG 63 字符上限，实际落地为 `ck_tool_confirmations_ck_tool_confirmations_exactly_one_7668`。这是仓库既有行为（`conversations` 的同名约束同样双前缀），ORM DDL 与迁移建出的名字一致，不改。
- **迁移必须与镜像同版本发布**：容器启动命令是 `alembic upgrade head && uvicorn ...`，镜像里的 `versions/` 落后于 DB 会让启动直接失败（本次实测 `Can't locate revision identified by '20261019_0040'`）。新增迁移后必须重建后端镜像。
- **SSE 出站载荷本轮仍缺字段**：`agent_runtime/events.py` 的 `confirmation_required` 构造器已支持 `confirmation_id` 并输出 `confirmationId`，但 SSE 映射路径（`events.py:571-688`）没有接线，客户端拿到的仍只有 `callId`/`name`/`toolType`/`summary.arguments`；`message_completed` 的 loop 终态也仍硬编码为 completed，与 DB 的 `waiting_confirmation` 不一致。两者一并留给 ③b。
- **断开连接可能留下 `pending` 记录**：连接层取消等待中的 Future 时，确认行不会被就地标记，由 TTL 过期兜底（与 MCP 既有行为一致）。
