---
source: script
request: 2026-10-14-multi-agent-orchestration
ranAt: "2026-10-14 22:09:35 CST"
exitCode: 3
---

## 已执行的命令与结果

### 建立临时 PostgreSQL 验证库

```bash
/Users/lixingwen/xw/study/ai-base/apps/backend/.venv/bin/python /var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.mOryvLm4ik/pg_admin.py create ai_base_ma_verify_74112
```
结果：通过

### 迁移上行：alembic upgrade head

```bash
DATABASE_URL='postgresql+asyncpg://root:Dd123456@127.0.0.1:5432/ai_base_ma_verify_74112' apps/backend/.venv/bin/python -m alembic upgrade head
```
结果：通过

### 迁移后库结构断言

```bash
apps/backend/.venv/bin/python <migration_probe.py> 'postgresql+asyncpg://root:Dd123456@127.0.0.1:5432/ai_base_ma_verify_74112'
```
结果：通过

### 迁移可下行（downgrade -1）

```bash
DATABASE_URL='postgresql+asyncpg://root:Dd123456@127.0.0.1:5432/ai_base_ma_verify_74112' apps/backend/.venv/bin/python -m alembic downgrade -1
```
结果：通过

### 迁移可重新上行（upgrade head）

```bash
DATABASE_URL='postgresql+asyncpg://root:Dd123456@127.0.0.1:5432/ai_base_ma_verify_74112' apps/backend/.venv/bin/python -m alembic upgrade head
```
结果：通过

### 下行再上行后结构仍然正确

```bash
apps/backend/.venv/bin/python <migration_probe.py> 'postgresql+asyncpg://root:Dd123456@127.0.0.1:5432/ai_base_ma_verify_74112'
```
结果：通过

### 部分唯一索引谓词：PostgreSQL（迁移后的真实库）

```bash
apps/backend/.venv/bin/python <index_probe.py> 'postgresql+asyncpg://root:Dd123456@127.0.0.1:5432/ai_base_ma_verify_74112' 'postgresql'
```
结果：通过

### 部分唯一索引谓词：SQLite

```bash
apps/backend/.venv/bin/python <index_probe.py> 'sqlite+aiosqlite:///<tmp>/index.db' 'sqlite'
```
结果：通过

### 保存期校验拒绝：环 / 悬空 / 非祖先 / 扇出超限 / 自引用

```bash
apps/backend/.venv/bin/python <reject_probe.py>
```
结果：通过

### 保存期校验在 HTTP 路由面返回 400 并指出 step_id

```bash
apps/backend/.venv/bin/python <http400_probe.py>
```
结果：通过

### 运行期 DAG 语义用例（并发时间窗 / 分支异构 / fail-fast / 并发闸 / 单步超时 / 审批收紧）

```bash
cd apps/backend && poetry run pytest tests/workflows/test_runner_parallel.py -v
```
结果：通过

### 保存期 DAG 校验与存量定义兼容用例

```bash
cd apps/backend && poetry run pytest tests/workflows/test_validators_dag.py tests/workflows/test_validators.py -v
```
结果：通过

### 编排绑定：接管 / 未绑定回归 / 审批一律拒绝 / 会话并发（验收 8 前半）

```bash
cd apps/backend && poetry run pytest tests/conversation/test_orchestration_binding.py -v
```
结果：通过

### 验收 6 端到端：embed 装配点 → 编排接管 → 汇聚输出落 assistant 消息并可读回

```bash
apps/backend/.venv/bin/python <embed_e2e_probe.py> <tmp>/embed.db
```
结果：通过

### 后端全量回归（workflows / conversation / agent / gateway / tasks / mcp / host_tool）

```bash
cd apps/backend && poetry run pytest tests/workflows tests/conversation tests/agent tests/gateway tests/tasks tests/mcp tests/host_tool -q
```
结果：通过

### ruff（本次 diff 涉及的后端文件）

```bash
cd apps/backend && poetry run ruff check <本次 diff 涉及文件>
```
结果：通过

### black --check（本次 diff 涉及的后端文件）

```bash
cd apps/backend && poetry run black --check <本次 diff 涉及文件>
```
结果：通过

### 验收 7：前端画布 depends_on 往返（跑 workflow-dag.ts 真实实现）

```bash
cd apps/front && node --experimental-strip-types <probe.mjs>
```
结果：通过

### 前端类型检查（tsc -b）

```bash
bash -c cd '/Users/lixingwen/xw/study/ai-base/apps/front' && pnpm exec tsc -b
```
结果：通过

### 前端构建（vite build）

```bash
bash -c cd '/Users/lixingwen/xw/study/ai-base/apps/front' && pnpm exec vite build
```
结果：通过

### 前端 lint（本次 diff 涉及的前端文件）

```bash
cd apps/front && pnpm exec eslint src/features/workflows/workflow-canvas.tsx src/features/workflows/workflow-dag.ts src/features/workflows/workflow-canvas-model.ts src/features/workflows/workflow-definition-form.tsx src/features/agents/agent-config-tab.tsx src/features/agents/agent-form-schema.ts src/api/agent.ts src/api/workflow.ts
```
结果：通过

## 未执行项与原因

- **真实 WebSocket + 真实模型网关的 embed 全链路**：本机没有可用的模型供应商凭据，无法从
  `ws://.../ws/agents/{agent_id}` 真发一条消息。验收第 6 条的做法是直接驱动 WS 所调用的同一个
  装配点 `gateway/runtime.py` 的 `stream_embed_chat`（真实会话落库、真实 assistant 落库、真实
  运行记录），只把「分支 Agent → 模型」这一跳替换成替身；WebSocket 层（token 鉴权、
  `produce_embed_request` 的组装）本次未改动，未被执行覆盖。
- **`model_usage_records.agent_id` 的逐分支断言**：验收第 4 条要求三个分支各用不同 agent_id 落
  用量记录。本次证明的是运行期真的把不同的 `agent_id` 传给了分支的会话执行
  （`tests/workflows/test_runner_parallel.py::test_parallel_branches_can_use_different_agents`）；
  用量记录本身由 `ConversationRepository.record_model_usage` 在真实模型返回 usage 后写入，
  需要真实模型网关才能产生，未执行。
- **全仓 `ruff check .` / `black --check .`**：两者在本仓库当前状态下本来就不干净，且与本次改动
  无关（`black` 有 20 个未改动文件希望被 reformat，`ruff` 有 1 条 `app/modules/embed/repositories.py:10`
  的 F401）。本次只对本 diff 涉及的后端文件断言 0 问题，不做无关文件的全仓改写。
- **`pytest`（不带目录参数）**：`apps/backend/tests/` 下 `agent`、`builtin_tool`、`embed`、
  `model_registry`、`skill_runner`、`user`、`workflows` 七个目录没有 `__init__.py`，不带参数运行会
  因同名测试文件 basename 冲突报 collection error（既有问题，非本次引入）。因此按目录分别执行。
- **迁移在已有重复脏数据上的表现**：`workflow_step_runs` 新增的 `(run_id, step_id)` 唯一索引在
  库里已有同 run 内重复 step_id 时会让迁移失败，需要在升级前清理。本次未构造脏数据复现该失败
  （临时库是空的）。
- **spec 中明确「不做」的范围**：模型自主委派（阶段二）、条件分支、循环、动态扇出、工作流级变量、
  分支级交互式人工审批、跨分支共享可变状态、工作流发布/回滚——均未实现，也无验证项。

## 验收结论

| # | 验收标准 | 结论 | 证据 |
|---|---|---|---|
| 1 | 后端测试全绿 + ruff/black 通过 | 通过（限定范围） | 全量回归 477 passed / 1 skipped；diff 涉及文件 ruff 与 black 均 0 问题。全仓 ruff/black 的既存问题见「未执行项」 |
| 2 | 保存期校验真实拒绝：环 / 悬空 / 引用非祖先 / 扇出超上限 → 400 且指出 step_id | 通过 | 服务层探针五类全拒；HTTP 路由面 400 且 message 同时指出 a/b/c |
| 3 | 三分支真并发 + 汇聚等齐 | 通过 | `test_parallel_branches_really_overlap_and_merge_waits`：`workflow_step_runs` 时间窗两两交叉、`merge.started_at >= 各分支 finished_at` |
| 4 | 分支异构 agent_id | 部分通过 | 运行期确实按步骤把不同 agent_id 传进分支执行（用例内断言）；用量记录级断言需真实模型，见「未执行项」 |
| 5 | fail-fast 先收尾再抛 / continue_with_default 继续 | 通过 | `test_fail_fast_finishes_started_branches_before_failing`（run=failed、同层兄弟仍有终态、completed_steps=3）、`test_continue_with_default_keeps_layer_running` |
| 6 | 绑定编排接管 → 汇聚输出落 assistant 消息且可读回；未绑定回归 | 通过（装配点级） | embed 端到端探针：事件 `["输出#3"]`、assistant 消息 = `输出#3`、会话历史可读回、run 落 conversation/completed；未绑定回归见 `test_unbound_agent_yields_no_orchestration_stream` 与全量 regression |
| 7 | 定义往返 + 前端构建 | 通过 | 存量线性定义解析为链且写回仍是 `null`；扇出-汇聚往返稳定；`tsc -b` 与 `vite build` 通过 |
| 8 | 会话并发不撞唯一索引 + 无递归 | 通过 | PG/SQLite 双方言索引探针；`test_same_workflow_can_run_concurrently_from_two_conversations`；`allow_orchestration is False` 在 runner 侧逐次断言 |

**剩余风险**

1. 验收 6 的 WebSocket 层与真实模型网关未被真机覆盖（本机无模型凭据），端到端只到
   `stream_embed_chat` 这一层。
2. 前端「画布连线 ↔ `depends_on`」只被半保护：后端把 `position` 当不透明坐标，从不校验它与
   依赖的语义对应，折算规则（`null` 兼容、首步折 `null`、非首步 `[]` 保留）全在 `workflow-dag.ts`
   里。本次用 Node 直接跑该模块的真实实现覆盖了「解析 / 写回 / 往返 / 非首步并行起点 / 环」，
   这条闸是有效的——它当场抓出 `toDependsOnWrite` 拿前一步的依赖当判断基准（三步以上的存量
   线性定义会被改写成显式数组）并已修正；**未覆盖的是画布拖拽产生 `position`/连线的交互路径**
   （`apps/front` 无测试运行器，也无登录态联调环境）。
3. `workflow_step_runs` 的新唯一索引对存量脏数据不宽容：升级前需要确认库里没有同一 run 内重复的
   `step_id`。
4. 编排接管轮没有逐 token 流式：汇聚必须等所有分支终态，因此只有整段 `message_delta`，
   长编排下首字延迟等于最慢分支的耗时。
5. 阶段二（模型自主委派）本次刻意不做，ADR 0004 已将 ADR 0002 中被否决的「先做多 Agent」
   记为「部分打开」。
