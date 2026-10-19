---
source: script
request: 2026-10-19-tool-approval-wiring
ranAt: "2026-10-19 12:10:16 CST"
exitCode: 3
---

## 已执行的命令与结果

### 单元测试：agent_runtime

```bash
step_unit_agent_runtime
```

........................................................................ [ 63%]
..........................................                               [100%]
114 passed in 2.02s
结果：通过

### 单元测试：builtin_tool（含审批闸口 test_approval_gate.py）

```bash
step_unit_builtin_tool
```

.........................................................                [100%]
57 passed in 2.28s
结果：通过

### 单元测试：conversation

```bash
step_unit_conversation
```

........................................................................ [ 62%]
............................................                             [100%]
116 passed in 4.90s
结果：通过

### 单元测试：gateway（含与 SDK 共享 golden 的事件一致性）

```bash
step_unit_gateway
```

........................................................................ [ 62%]
............................s...............                             [100%]
=============================== warnings summary ===============================
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
  /Users/lixingwen/xw/study/ai-base/apps/backend/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
115 passed, 1 skipped, 1 warning in 2.25s
结果：通过

### 单元测试：host_tool

```bash
step_unit_host_tool
```

............                                                             [100%]
12 passed in 1.61s
结果：通过

### 单元测试：mcp

```bash
step_unit_mcp
```

.............................                                            [100%]
29 passed in 1.88s
结果：通过

### 单元测试：tasks

```bash
step_unit_tasks
```

......................................................................   [100%]
70 passed in 5.24s
结果：通过

### 单元测试：tool_approval（确认状态回读回归）

```bash
step_unit_tool_approval
```

.......                                                                  [100%]
7 passed in 1.56s
结果：通过

### 单元测试：tools（含 test_side_effects.py）

```bash
step_unit_tools
```

........................................                                 [100%]
40 passed in 2.09s
结果：通过

### 单元测试：workflows

```bash
step_unit_workflows
```

........................................................................ [ 38%]
........................................................................ [ 77%]
..........................................                               [100%]
186 passed in 16.84s
结果：通过

### 结构断言：副作用词汇唯一

```bash
step_single_vocabulary
```

SideEffect 定义处数 = 1（期望 1，位于 tools/side_effects.py）
独立的 _ALLOWED_SIDE_EFFECTS 定义 = 0（期望 0；tasks/unattended.py 的 STRICT_MODE_ALLOWED_SIDE_EFFECTS 不算）
apps/backend/app/modules/tools/side_effects.py:19:SideEffect = Literal["none", "navigation", "write", "financial", "external"]
结果：通过

### 注册表真值：内置工具的真实 side_effect

```bash
step_registry_truth
```

  create_task = write（期望 write）
  delegate_tasks = write（期望 write）
  image_generate = write（期望 write）
  http_post = none（期望 none）
  knowledge_search = none（期望 none）
  三处 SideEffect 收敛为同一类型 = True
结果：通过

### 契约：内置工具目录接口返回规范五值

```bash
step_contract_catalog
```

  目录条目数 = 14
  create_task = write
  delegate_tasks = write
  image_generate = write
  http_post = none
  非法取值 = {}
结果：通过

### 无人值守拒绝原因码的单测覆盖

```bash
step_policy_unit_coverage
```

覆盖无人值守拒绝原因码的单测文件：apps/backend/tests/builtin_tool/test_approval_gate.py apps/backend/tests/tasks/test_unattended.py 
结果：通过

### 端到端：WS 确认 / 拒绝 / 记忆 / 过期 / 无通道 / 无人值守任务 / 委派继承

```bash
step_e2e_probe_guarded
```

替身模型端口 = 57945
========================================================================
内置工具审批闸口 —— 端到端验证探针
BASE=http://localhost:8080/api/v1  WS=ws://localhost:8080/api/v1/ws/agents/1  STUB_PORT=57945
========================================================================

--- 准备：登录、记录原状态、启用工具、准备嵌入客户端与替身模型 ---
  已登录 admin@平台1
  原 chat 绑定 model_id=1
  探针开始前 tasks 表行数 = 0（干净）
  已启用 create_task / delegate_tasks（收尾恢复）
  嵌入客户端 client_id=client_xEq-9OI23D9ISL1xoCOaq0n4（复用/轮换密钥，已绑定 agent 1）
  替身模型 model_id=45 已绑定到 agent 1 的 chat 角色

--- AC7 交互式 WS 拒绝：弹卡 → 拒绝 → 工具不执行 ---
  通过：收到 1 张 confirmation_required —— 1 张
  通过：callId 非空（否则 SDK 无法回传） —— call_stub_19663
  通过：name == create_task —— create_task
  通过：toolType == builtin_tool —— builtin_tool
  通过：sideEffect == write —— write
  通过：expiresAt 有值 —— 2026-10-19T04:18:39.671853+00:00
  通过：confirmationId 非空（落库锚点） —— 58
  通过：summary.arguments 存在
  通过：工具结果含 rejected
  通过：拒绝结果经 agent_step 事件可观测 —— 1
  通过：tasks 表未新增（工具未执行） —— 0 -> 0
  通过：该轮消息正常收尾

--- AC6 交互式 WS 批准：弹卡 → 批准 → 工具执行 ---
  通过：收到 confirmation_required —— 1 张
  通过：tasks 表 +1（工具已执行） —— 0 -> 1
  通过：该轮消息正常收尾

--- AC8 确认记忆：同一会话内第二次调用同一写工具不再弹卡 ---
  通过：两次调用只弹 1 张确认卡 —— 1 张
  通过：两条消息都完成（记忆命中后直接执行） —— 2
  通过：tasks 表 +2 —— 1 -> 3
  通过：第二条消息复用了同一会话 —— 142

--- AC5(expiry) 确认过期：强制过期后批准 → 工具不执行 ---
  通过：收到确认卡 —— 1 张
  通过：过期的确认行被标为 expired —— status=expired id=61
  通过：工具结果体现过期（confirmation_expired） —— True
  通过：tasks 表未新增（工具未执行） —— 3 -> 3

--- AC9 无确认通道：REST 流式通路拒绝并告知 ---
  通过：SSE 不出现 confirmation_required —— 0
  通过：工具结果含 no_confirmation_channel
  通过：工具结果含 rejected
  通过：tasks 表未新增（工具未执行） —— 3 -> 3

--- AC-T1 无人值守默认策略：任务调用 create_task 成功执行 ---
  通过：任务运行结束（非 running） —— completed
  通过：create_task 执行成功 → tasks +1 —— 4 -> 5
  通过：auto_approved_count == 1 —— 1
  通过：create_task 步骤为 succeeded —— create_task|succeeded

--- AC-T2 无人值守严格模式：任务调用 create_task 被拒 ---
  通过：任务运行结束（非 running） —— completed
  通过：tasks 表未新增 —— 6 -> 6
  通过：auto_approved_count == 0 —— 0
  通过：create_task 步骤为 failed —— create_task|failed

--- AC-T3 委派继承：默认策略父任务派子运行，子运行的 create_task 仍被执行 ---
  通过：任务运行结束（非 running） —— completed
  通过：确实派出了子运行 —— 1
  通过：子运行的 create_task 执行成功 → tasks +1 —— 7 -> 8
  通过：父运行里 delegate_tasks 步骤为 succeeded —— delegate_tasks|succeeded

--- AC10 断连行为（仅观测） ---
  观测：等待确认期间断开连接后，确认行 status = pending
  说明：本实现未在断连时把 pending 确认行标为 expired（由 600s TTL 兜底），故 spec 验收标准 10 未满足，已记入 verify.md 的已知差距。

--- 收尾：恢复原状态、清理探针数据 ---
  已删除任务：3 个显式创建 + 5 个本次运行新增
  基线外任务 id：[87, 88, 89, 91, 94]；基线内（未动）：[]
  已恢复 create_task / delegate_tasks 的启用状态
  已恢复 chat 绑定 model_id=1
  已解绑并停用临时嵌入客户端
  已删除替身模型 model_id=45
  已清理遗留 pending 确认行 1 条；剩余 pending = 0
  说明：approved/rejected/expired 的确认行保留作审计留痕。

========================================================================
全部断言通过
========================================================================

替身模型收到的请求（n / last_role / 决策）：
  n=1 last_role=user decision=create_task
  n=2 last_role=tool decision=text
  n=3 last_role=user decision=create_task
  n=4 last_role=tool decision=text
  n=5 last_role=user decision=create_task
  n=6 last_role=tool decision=text
  n=7 last_role=user decision=create_task
  n=8 last_role=tool decision=text
  n=9 last_role=user decision=create_task
  n=10 last_role=tool decision=text
  n=11 last_role=user decision=create_task
  n=12 last_role=tool decision=text
  n=13 last_role=user decision=create_task
  n=14 last_role=tool decision=text
  n=15 last_role=user decision=create_task
  n=16 last_role=tool decision=text
  n=17 last_role=user decision=delegate_tasks
  n=18 last_role=user decision=create_task
  n=19 last_role=tool decision=text
  n=20 last_role=tool decision=text
  n=21 last_role=user decision=create_task
结果：通过

### Harness audit 自检

```bash
step_audit
```


v2 requests: 13  存量跳过: 59  ERROR: 0  WARN: 0
（唯一被放行的 ERROR 是「v2 request 缺少 verify.md」，该文件由 tools/harness/verify.sh 在本脚本收尾时产出；本次实得 ERROR 数见上一行）
结果：通过

## 未执行项与原因

- **spec 验收标准 10（断连清理）未满足**：等待确认期间断开 WS 连接后，确认行仍是 `pending`（探针 AC10 已实测观测），由 `tool_confirmations.expires_at` 的 600s TTL 兜底。实现未在连接清理时把该连接的待确认行标为 `expired`；已记入 `docs/adr/0009-tool-approval-wiring.md` 的 Consequences。
- **spec 验收标准 3（`auto_approve=false` 时 `image_generate` 被拒且 `storage/` 无新资产）未端到端执行**：替身模型只产出 `create_task` / `delegate_tasks` 两种 tool_call，未覆盖 `image_generate`。该拒绝走的是与验收标准 2 完全相同的 `UnattendedPolicy.decide()` 分支（`not auto_approve` → `auto_approve_disabled`），已由 `tests/tasks` 的策略单测覆盖。
- **spec 验收标准 4（`financial` 硬线）未端到端执行**：平台内置工具里没有 `side_effect="financial"` 的工具，无法用真实工具触发；由 `tests/tools/test_side_effects.py`（`financial ∈ MEMORY_EXEMPT_SIDE_EFFECTS`）与 `tests/tasks` 的策略单测覆盖。
- **spec 验收标准 8 的后半句（`financial` 第二次仍弹卡）未端到端执行**：同上，无 financial 工具可触发，由 `MEMORY_EXEMPT_SIDE_EFFECTS` 单测覆盖。
- **`POST /api/v1/agents/{id}/chat` 非流式通路（微信助手）未单独执行**：它与流式通路共用同一个 `confirmation_decider=None` 注入点，流式通路已在端到端里验证；微信侧需要微信回调桩，不在本轮范围内。
- **进程内单元断言未覆盖的**：SDK 确认卡组件的人工点击路径（`apps/ai-sdk` 的 `ToolConfirmation.vue`）需要浏览器，本脚本只验证后端出站事件字段（`callId`/`toolType`/`sideEffect`/`expiresAt`/`confirmationId`/`summary.arguments`）齐全。

## 验收结论

见 `docs/harness/requests/2026-10-19-tool-approval-wiring/spec.md` 的「验收标准」逐条对照：1/2/5(改为默认策略版)/6/7/8(记忆部分)/9(REST 流式)/11/12 通过；3、4、8(后半句)、10 见上「未执行项与原因」。
