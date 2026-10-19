---
id: 2026-10-19-tool-approval-wiring
tier: A
risk: high
approval:
  required: true
  granted: true
  grantedAt: 2026-10-19
  grantedBy: 用户
  grantedNote: "停点确认：按 ③a 范围实现；SSE/REST 待确认的恢复与续跑拆为 ③b 另立 A 档 request；无确认通道的过渡行为取「拒绝并告知」。"
  why: ["鉴权或权限行为变化：内置写工具（create_task/delegate_tasks/image_generate）在无人值守运行中从「一律执行」改为「按策略裁决，可被拒绝」；在无确认通道的交互式通路上从「静默执行」改为「拒绝执行」", "API 契约变化：内置工具读模型的 side_effect 由 Literal[\"none\"] 放宽为规范五值；BuiltinToolOutcome.status 新增 rejected", "数据模型与模块边界变化：新增通用工具确认表 tool_confirmations 及其迁移，新建 tool_approval 模块"]
---

## 目标与范围

- 目标：让 `side_effect` 成为唯一权威的副作用声明，并把它从工具定义一路接到**所有运行形态**的执行闸口——无人值守按策略裁决、交互式弹确认卡、无确认通道则拒绝执行。

- 现状（逐条可核对）：
  - 声明链在暴露层断裂：`apps/backend/app/modules/tools/basic/framework.py:16` 的 `_ALLOWED_SIDE_EFFECTS = {"none","create"}` 是第三套词汇（`create` 不在规范五值内）→ `apps/backend/app/modules/tools/business/framework.py:43-49` 的 `BusinessTool` 没有 `side_effect` 字段、`:55-77` 装饰器不收 → `apps/backend/app/modules/builtin_tool/registry.py:31-38` 的 `_from_business` 不传 → `BuiltinToolDefinition.side_effect` 恒为默认 `"none"` → `apps/backend/app/modules/builtin_tool/schemas.py:12,19` 把读模型写死成 `Literal["none"]`。
  - 真值被丢弃：`apps/backend/app/modules/tools/basic/image_gen.py:47` 已声明 `side_effect="create"`，`apps/backend/app/modules/tools/business/image_generate.py:70` 用 `depends_on=("image_gen.generate",)` 包装它，该值止步于此。
  - 闸口只覆盖两条通路：宿主工具 `apps/backend/app/modules/gateway/dispatcher.py:396-398`；MCP `apps/backend/app/modules/mcp/services.py:168-187`。分派层只有 MCP 分支拿到裁决器：`apps/backend/app/modules/conversation/tool_dispatch.py:90-105`（builtin）与 `:107-116`（skill_script）调用时不传 `confirmation_decider`，只有 `:132-142`（MCP）传。
  - 于是裁决器永远拿不到真值：`apps/backend/app/modules/tasks/unattended.py:89-110 build_confirmation_decider` 读到 `"none"` → `auto_approved`；`apps/backend/app/modules/workflows/services.py:99-126` 的保存期守卫对内置工具永不触发。
  - WS 的确认等待机制已存在且与工具来源解耦：`apps/backend/app/modules/gateway/dispatcher.py:282-348`（`pending_mcp_confirmations[call_id]` + `asyncio.wait_for`）与 `apps/backend/app/modules/gateway/router.py:247-295`（按 `callId` `set_result`）；SDK 已能渲染并回传（`apps/ai-sdk/src/ui/components/ChatWidget.vue:103-107`、`apps/ai-sdk/src/core/client.ts:1016-1026`），无需改动。
  - 无确认通道的通路今天会**静默执行**：`apps/backend/app/modules/conversation/services.py:780-795` 的 REST 流式路径不注入 decider。

- 范围：
  1. 新增唯一词汇与派生规则，`create` 归一为 `write`。
  2. 内置工具按真实副作用标注，并由 `depends_on` 派生下界以防包装层低报。
  3. 无人值守（任务/工作流/委派子运行）对内置工具按策略裁决，未批准不执行 handler。
  4. 交互式 WS/embed：内置工具弹确认卡、落确认行、等待批准；同会话内记住已批准（`financial` 除外）。
  5. 无确认通道（REST 流式、微信助手非流式、交互式委派子运行）：拒绝执行并明确告知模型。
  6. 新增通用确认表与迁移；契约放宽；测试与 verify 脚本。
- 不做：不迁移 MCP 既有 `mcp_tool_confirmations` 数据；不给技能脚本接线；不改 `http_post` 现有的 `none` 声明；不引入参数级/路径级规则；不做 SSE/REST 待确认的恢复与续跑（见停点判断）。

## 来源与方案比较

- 本机 Pi `/Users/lixingwen/xw/git/pi`（调研日期 2026-10-19，第一手源码）：**没有工具级副作用分类，也没有统一审批层** —— `grep -rln "sideEffect|side_effect" packages/*/src` 无命中；`packages/agent/src/harness/types.ts:135` 的 `"permission_denied"` 属 `FileErrorCode`（`packages/agent/src/harness/env/nodejs.ts:111`），不是审批。它的审批只有两件粗粒度机制：项目信任门 `packages/coding-agent/src/cli/args.ts:219-221`（usage 原文 `Trust project-local files for this run`）与把弹窗交给扩展 `packages/coding-agent/src/core/extensions/types.ts:137-138 confirm(title, message, opts?): Promise<boolean>`。故本仓库的 `side_effect` + `confirmation_policy` 分类已比 Pi 细，缺的不是分类法而是**分类到闸口的接线**，因此本方案只接线、不重造。
- 内部先例（同构已跑通）：宿主工具 `apps/backend/app/modules/host_tool/schemas.py:6-7` 定义规范五值与 `confirmation_policy`，`apps/backend/app/modules/gateway/dispatcher.py:396-398` 据此判定并等待；MCP 侧同构；前端已按五值渲染（`apps/front/src/api/mcp-servers.ts:44`）。多态引用采用判别列 + 可空 FK 的既有写法（`apps/backend/app/modules/tasks/models.py:130-145`、`apps/backend/app/modules/workflows/models.py:71-79`）。
- 迁移约定：`apps/backend/migrations/versions/` 单头链，下一号 `20261019_0040`，建表参照 `20261013_0036_workflows.py:29-196`，字段 `comment` 必须中文（`AGENTS.md` 与 `apps/backend/app/shared/base_model.py:32`）。

## 被否决的选项

拷问第一轮（4/4 采纳推荐）：入口范围为「WS embed + 控制台 SSE」，不做独立收件箱；弹窗策略为「`write`/`external`/`financial` 弹，`none`/`navigation` 直通」；技能脚本本轮不纳入；控制台不做独立收件箱。
拷问第二轮（末轮）：确认落库；无通道通路给出明确处置；交互式委派子运行不冒泡；TTL 与记忆策略确定；维持两项不做。

- **把 MCP 的 `mcp_tool_confirmations` 就地泛化成通用表**：它的 `tool_id` 是 `mcp_tools` 的 NOT NULL 外键、`audit_id` 是 `mcp_tool_call_audits` 的 unique NOT NULL 外键（`apps/backend/app/modules/mcp/models.py:143-203`），而内置工具既无工具表也无审计表（`grep -rn audit apps/backend/app/modules/builtin_tool apps/backend/app/modules/conversation` 零命中）。同批泛化必然连带改掉 MCP 的审计语义与 `POST /mcp-confirmations/{id}/resolve`（`apps/backend/app/modules/mcp/router.py:249-270`，`_require_admin`），风险与收益不对等；改为新表并存，统一列为后续项。
- **只做内存等待、不落库**：能实现弹窗，但得不到审计留痕，也无法承载「同会话记住批准」这一已确认的语义；且断连后待确认行无迹可查。
- **给内置工具新增 `confirmation_policy` 字段**：会与 `side_effect` 形成第二套开关，同一件事两个字段；本轮由 `side_effect` 直接派生弹窗与否。
- **参数级/路径级审批规则**：本轮的分类粒度是工具级，参数级规则需要规则表达式语言与前端编辑器，是独立能力。
- **把技能脚本一并纳入**：技能包 manifest 没有副作用声明字段，纳管需先给技能包加声明，属独立变更。
- **`http_post` 改判为 `external`**：它当前声明 `none`（`apps/backend/app/modules/tools/basic/http_post.py:45`），改判会让所有已绑定它的 Agent 立刻开始弹确认，属未经验证的行为变更。
- **无确认通道时保持今天的静默执行**：与本次「写工具必须经批准」的目标直接冲突；静默执行写工具正是要被消除的行为。
- **`financial` 也纳入「同会话记住批准」**：`financial` 是 `apps/backend/app/modules/tasks/unattended.py:25 NEVER_AUTO_APPROVE_SIDE_EFFECTS` 里唯一的硬线（不可逆、支付类），记住它等于让一次批准永久生效。
- **本轮一并做 SSE/REST 待确认的恢复与续跑**：全仓不存在续跑机制——`continue_run` 仅在 `apps/backend/app/modules/agent_runtime/loop.py:427` 与 `runtime.py:136` 有定义、**零调用点**，`resume_token` 无生产者无消费者；这需要持久化等待前的消息快照与已执行工具结果、新增会话级 resolve 端点、修正硬编码的 loop 终态（`apps/backend/app/modules/agent_runtime/events.py:276-286`），与本任务的声明链接线是两件正交的难题，合并会同时撑爆本 spec 的 150 行上限与单次评审边界。
- **交互式委派子运行的确认冒泡到父会话**：需要为子运行建立事件路由与 `callId` 命名空间隔离，改动面从 dispatcher 扩到 `delegate_tasks` 与事件流；本轮子运行一律拒绝并告知。

## 停点判断

- 架构边界变化=是（新建 `tool_approval` 模块）；数据模型变化=是（新表 `tool_confirmations`）；API 契约变化=是；鉴权/权限行为变化=是 → `approval.required: true`，**实现前必须经用户确认**。
- 拆分结论：本 request 只承担「声明链接线 + 确认表 + 交互式 WS 确认 + 无人值守接线 + 无通道拒绝」。SSE/REST 待确认的恢复与续跑单独立 A 档 request（暂记 ③b），本轮结束时 SSE/REST 通路的行为是**拒绝并告知**，直到 ③b 落地。

## 变更点

1. 新增 `apps/backend/app/modules/tools/side_effects.py`：`SideEffect = Literal["none","navigation","write","financial","external"]`、`SIDE_EFFECT_ALIASES = {"create": "write"}`、`normalize_side_effect()`（非法值抛错）、`SIDE_EFFECT_ORDER = ("none","navigation","write","external","financial")`、`max_side_effect(*values)`。
2. `apps/backend/app/modules/tools/basic/framework.py:16` 的 `_ALLOWED_SIDE_EFFECTS` 换为规范五值并归一别名；`apps/backend/app/modules/tools/basic/image_gen.py:47` 的 `"create"` 落成 `write`。
3. `apps/backend/app/modules/tools/business/framework.py:43-49` 增 `side_effect: str = "none"`、`:55-77` 装饰器增参；新增 `effective_side_effect(tool) = max_side_effect(声明值, 各 depends_on 的 basic 工具声明值)`；`:80-88 validate_business_tool_dependencies` 扩展为启动期校验未知值与「声明值低于依赖最大值」。
4. 标注：`create_task.py:24`、`delegate_tasks.py:146` 标 `write`；`image_generate.py:70` 由 `depends_on` 派生 `write`；只读工具保持 `none`。
5. `apps/backend/app/modules/builtin_tool/registry.py:31-38 _from_business` 传 `side_effect=effective_side_effect(tool)`。
6. 契约：`apps/backend/app/modules/builtin_tool/schemas.py:12,19` 的 `Literal["none"]` 改为 `SideEffect`；`:27-35 BuiltinToolOutcome.status` 增 `"rejected"`。
7. `apps/backend/app/modules/conversation/tool_dispatch.py:90-105`：builtin 分支在 `getattr(tool,"side_effect","none") != "none"` 时先咨询裁决器；未批准不执行 handler，返回 `BuiltinToolOutcome(status="rejected", result={"status":"rejected","auto_approved":False,"reason":...,"message":...})`；`:36-46 ConfirmationDecision` 增可选 `reason`；`confirmation_decider is None` 时拒绝并给 `reason="no_confirmation_channel"`。本模块不 import `tasks.unattended`（避免 tasks→conversation→tasks 循环）。
8. `apps/backend/app/modules/tasks/unattended.py:89-110 build_confirmation_decider` 回填 `decide()` 的原因码。
9. 委派继承：`apps/backend/app/modules/builtin_tool/services.py:93` 构造 `BusinessToolContext` 时补 `confirmation_decider`，`apps/backend/app/modules/tools/business/delegate_tasks.py:259` 传入子运行；交互式父运行的子运行拿到 `None` 即走 7 的拒绝分支。
10. 新增 `apps/backend/app/modules/tool_approval/`：`models.py` 定义 `ToolConfirmation`（表 `tool_confirmations`，判别列 `tool_kind` + 可空 `tool_id`/`tool_ref` + `tool_name`，`platform_id`/`agent_id`/`conversation_id`/`loop_run_id`，`user_id`/`platform_end_user_id` 恰一非空的 CheckConstraint，`side_effect`、`arguments_encrypted`、`status` 默认 `pending`、`expires_at`、`resolved_at`，字段全部中文 `comment`）；`repositories.py` 提供 `create`/`claim(status)`（CAS：`update().where(id, status=="pending")`，照 `apps/backend/app/modules/mcp/repositories.py:290-301`）/`find_approved`（记忆查询）；`services.py` 提供 `request_confirmation`、`resolve_confirmation`、`expire_pending_for_connection`；迁移 `apps/backend/migrations/versions/20261019_0040_tool_confirmations.py`（`down_revision="20261016_0039"`，downgrade 对称 drop_table）。
11. `apps/backend/app/modules/gateway/dispatcher.py:149-163` builtin 分支：`side_effect != "none"` 且无记忆批准时发 `confirmation_required(tool_type=classify_tool_type(tool), side_effect=..., arguments=..., expires_at=...)`、落确认行、以 `call_id` 为键注册 Future（写法照 `:299-300`）、`asyncio.wait_for` 等待；批准后执行 handler，拒绝/超时返回 rejected 结果且不执行。`apps/backend/app/modules/gateway/router.py:247-295` 的 `_handle_confirmation_resolve` 增 builtin 分支；`:1293` 连接清理时把该连接 pending 的确认行标 `expired`。
12. 记忆：`tool_kind`+`tool_name`+`conversation_id`+主体 命中的已批准行抑制重复弹窗；`financial` 恒不记忆。
13. `apps/backend/app/modules/agent_runtime/events.py` 的确认载荷补齐 `toolType`/`sideEffect`/`expiresAt`/`confirmationId`（WS 与 SSE 同一构造器），使确认卡文案与倒计时可用。
14. `CONTEXT.md` 增术语「工具确认」「确认记忆」；`docs/adr/0009-*.md` 记录本决策；`docs/CHANGELOG.md` 同步。

## 验收标准

1. 无人值守默认配置行为不变：`auto_approve=true`（默认）、`strict_approval=false` 时任务调用 `create_task` 成功执行，`task_runs.auto_approved_count` 加 1。
2. 无人值守拒绝：`strict_approval=true` 时任务调用 `create_task` 未执行（无新任务行），工具结果为 `{"status":"rejected","auto_approved":false,"reason":"strict_approval_allows_navigation_only",...}`，对应步骤状态为 `failed`。
3. 额度拒绝：`auto_approve=false` 时调用 `image_generate` 被拒（`reason="auto_approve_disabled"`），`apps/backend/storage/` 无新增资产文件。
4. `financial` 硬线：`side_effect="financial"` 的工具在任何策略下都不自动批准（`reason="financial_side_effect_not_auto_approved"`）。
5. 委派继承（无人值守）：`strict_approval=true` 的父任务经 `delegate_tasks` 派出的子运行调用 `create_task` 同样被拒，拒绝原因回填父运行的工具结果。
6. 交互式 WS 批准：WS 会话中调用 `create_task` 收到 `confirmation_required`（`callId` 非空、`sideEffect="write"`、`expiresAt` 有值），回 `confirmation_resolve{approved:true}` 后工具执行、任务行落库，无需重发消息。
7. 交互式 WS 拒绝：回 `approved:false` 后不执行、任务行不落库，模型收到的工具结果 `status="rejected"`。
8. 确认记忆：同一会话内第二次调用同一工具不再弹卡直接执行；`financial` 工具第二次仍弹卡。
9. 无通道拒绝：REST 流式对话（`POST /api/v1/agents/{agent_id}/chat`）与微信非流式通路调用 `create_task` 未执行，工具结果 `status="rejected"` 且 `reason="no_confirmation_channel"`。
10. 断连清理：WS 在等待确认期间断开，该确认行状态变为 `expired` 且不残留 `pending`。
11. 契约：`GET` 内置工具目录接口返回的 `side_effect` 为规范五值（`image_generate` 为 `write`）；`apps/backend/.venv/bin/python -m pytest tests/conversation tests/builtin_tool tests/tasks tests/workflows tests/agent_runtime tests/gateway tests/mcp -q` 全绿；`python3 tools/harness/audit.py` 输出 `ERROR: 0 WARN: 0`。
12. `bash tools/harness/verify.sh 2026-10-19-tool-approval-wiring` 按既有退出码语义收尾（0=全部执行通过，3=有未执行项，1=有失败），`verify.md` 落真实输出与未执行项。
