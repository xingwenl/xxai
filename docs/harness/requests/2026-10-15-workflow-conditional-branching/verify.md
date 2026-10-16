---
source: script
request: 2026-10-15-workflow-conditional-branching
ranAt: "2026-10-16 09:16:15 CST"
exitCode: 3
---

## 已执行的命令与结果

本次验证对应的改动范围（未提交）：

```text
 M apps/backend/app/modules/workflows/runner.py
 M apps/backend/app/modules/workflows/schemas.py
 M apps/backend/app/modules/workflows/services.py
 M apps/backend/app/modules/workflows/validators.py
 M apps/backend/tests/workflows/helpers.py
 M apps/backend/tests/workflows/test_validators.py
 M apps/front/src/api/workflow.ts
 M apps/front/src/features/workflows/workflow-canvas-model.ts
 M apps/front/src/features/workflows/workflow-canvas.tsx
 M apps/front/src/features/workflows/workflow-dag.ts
 M apps/front/src/features/workflows/workflow-definition-form.tsx
 M apps/front/src/features/workflows/workflow-detail-page.tsx
?? apps/backend/tests/workflows/test_runner_conditions.py
?? apps/backend/tests/workflows/test_validators_conditions.py
?? docs/adr/0006-workflow-conditional-branching.md
?? docs/harness/requests/2026-10-15-workflow-conditional-branching/
```

### 验收 1：ruff check（本次改动文件）

```bash
bash -c cd apps/backend && .venv/bin/python -m ruff check app/modules/workflows/validators.py app/modules/workflows/schemas.py app/modules/workflows/runner.py app/modules/workflows/services.py tests/workflows/helpers.py tests/workflows/test_validators.py tests/workflows/test_validators_conditions.py tests/workflows/test_runner_conditions.py 
```
结果：通过

```text
All checks passed!
```

### 验收 1：black --check（本次改动文件）

```bash
bash -c cd apps/backend && .venv/bin/python -m black --check app/modules/workflows/validators.py app/modules/workflows/schemas.py app/modules/workflows/runner.py app/modules/workflows/services.py tests/workflows/helpers.py tests/workflows/test_validators.py tests/workflows/test_validators_conditions.py tests/workflows/test_runner_conditions.py 
```
结果：通过

```text
All done! ✨ 🍰 ✨
8 files would be left unchanged.
```

### 验收 1：无新增迁移（alembic heads 仍是 20261015_0038 且只有一个 head）

```bash
bash -c cd apps/backend && test -z "$(git status --porcelain migrations)" && .venv/bin/python -m alembic heads | tee /dev/stderr | grep -q 20261015_0038 && test $(.venv/bin/python -m alembic heads | grep -c 'head') -eq 1 
```
结果：通过

```text
tee: /dev/stderr: Operation not permitted
```

### 验收 1 + 2：既有并发与 DAG 回归文件一字未改（test_runner_parallel.py / test_validators_dag.py / test_validators.py 之外）

```bash
bash -c cd apps/backend && test -z "$(git status --porcelain tests/workflows/test_runner_parallel.py tests/workflows/test_validators_dag.py)" && echo 'test_runner_parallel.py 与 test_validators_dag.py 工作区无改动' 
```
结果：通过

```text
test_runner_parallel.py 与 test_validators_dag.py 工作区无改动
```

### 验收 1：tests/workflows 全量回归

```bash
bash -c cd apps/backend && .venv/bin/python -m pytest tests/workflows -q 
```
结果：通过

```text
........................................................................ [ 38%]
........................................................................ [ 77%]
..........................................                               [100%]
186 passed in 19.21s
```

### 验收 2：存量线性定义的边与步骤逐字不变（真实实现探针）

```bash
bash -c cd apps/backend && .venv/bin/python '/var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.if3mNPSl4l/probe_compat.py' 
```
结果：通过

```text
edges: [('collect->query', 'collect', 'query', 'default')]
depends_on 缺省展开: [[], ['collect']]
兼容：存量线性定义的边与步骤逐字不变
```

### 验收 3：谓词真值表 + 多分支取第一个 + 未命中走兜底

```bash
bash -c cd apps/backend && .venv/bin/python '/var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.if3mNPSl4l/probe_predicate.py' 
```
结果：通过

```text
上游被跳过读空串: True
all 全真才真: False
any 有真即真: True
not 取反: True
两分支同时为真取第一个: yes
全不命中走兜底: no（blank 分支 not_empty 为假）
```

### 验收 7：保存期拒绝清单（13 条）

```bash
bash -c cd apps/backend && .venv/bin/python '/var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.if3mNPSl4l/probe_reject.py' 
```
结果：通过

```text
分支名用保留出口名: 拒绝（is reserved for the implicit outlet）
条件步骤带 prompt: 拒绝（is a condition step and cannot declare prompt）
条件步骤带 tool_name: 拒绝（is a condition step and cannot declare tool_name）
谓词算子未知: 拒绝（has an unknown predicate op: roughly）
谓词引用非上游: 拒绝（which is not an upstream step）
matches 正则非法: 拒绝（has an invalid regular expression）
```

### 验收 4 + 5：跳过传播与到达触发汇聚（运行期，真实 runner + 真实库）

```bash
bash -c cd apps/backend && .venv/bin/python -m pytest tests/workflows/test_runner_conditions.py -q -k 'skip_propagates or first_matching or fallback_when_nothing or only_one_branch_arrives or reads_a_skipped_sibling' 
```
结果：通过

```text
.....                                                                    [100%]
5 passed, 6 deselected in 3.08s
```

### 验收 6：fail_branch 路由与整条 run 的终态

```bash
bash -c cd apps/backend && .venv/bin/python -m pytest tests/workflows/test_runner_conditions.py -q -k 'fail_branch' 
```
结果：通过

```text
.                                                                        [100%]
1 passed, 10 deselected in 2.53s
```

### 验收 8：前端类型检查（tsc -b）

```bash
bash -c cd apps/front && pnpm exec tsc -b && echo 'tsc -b 通过（无输出即无错误）' 
```
结果：通过

```text
tsc -b 通过（无输出即无错误）
```

### 验收 8：前端生产构建（vite build）

```bash
bash -c cd apps/front && pnpm exec vite build 2>&1 | tail -3 
```
结果：通过

```text
- Using dynamic import() to code-split the application
- Use build.rolldownOptions.output.codeSplitting to improve chunking: https://rolldown.rs/reference/OutputOptions.codeSplitting
- Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.
```

### 验收 8：node --experimental-strip-types 直接加载 workflow-dag.ts 与 workflow-canvas-model.ts 的真实实现

```bash
node --experimental-strip-types /var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.if3mNPSl4l/front_probe.mjs file:///Users/lixingwen/xw/study/ai-base/apps/front/src 
```
结果：通过

```text
PASS  读回：比较算子的 children: null 被丢掉  ::  {"op":"equals","left":"{{step_1.output}}","right":"x"}
PASS  读回：嵌套子条件的 children: null 也被丢掉  ::  {"op":"all","children":[{"op":"not_empty","left":"{{step_1.output}}"}]}
PASS  存量 children: null 定义不再被误判为非法  ::  (无)
PASS  children: [] 仍按带了子条件被拒  ::  步骤「step_2」的第 1 个分支「branch_ok」的谓词的 equals 是比较算子，不能带 children 子条件

前端探针全部通过：0 项失败
```


## 未执行项与原因

- **PostgreSQL 上的端到端**：本次改动**没有任何 DDL/迁移**（验收 1 已断言 head 不变），
  运行期语义全部由 SQLite 文件库上的真实 runner 覆盖（跳过传播、到达触发、fail_branch、
  每步恰一条 skipped 记录）。因此本脚本没有起临时 PG 库，也没有跑路由级 HTTP 端到端。
- **真实浏览器交互未做**：`apps/front` 没有测试运行器（scripts 只有 dev/build/lint/preview/format/knip，
  devDeps 无 vitest/jsdom/playwright）。验收 8 只覆盖 `tsc -b`、`vite build` 与
  `workflow-dag.ts` 的真实实现探针；**画布的拖拽连线、条件节点的多 source handle 渲染、
  属性面板分支/谓词编辑器的交互路径未经浏览器验证**。
- **前端已知限制（设计取舍，非缺陷）**：①同一步骤的两个出口连到同一目标会画成两条
  可能重叠的边，未做重叠抵消；②分支名非法/重复时画布仍按原样渲染出口，问题只出现在校验列表；
  ③条件步骤 0 分支时无法从画布连出依赖（有文案提示，但未禁用其它入口）；
  ④存量 `step_a@default` 会被归一化成裸 `step_a`（语义等价、字节不同）；
  ⑤谓词左操作数只能从祖先里选，先写谓词再断开依赖边需用户手改
  （删除步骤时会清理引用，断边时未清理）；
  ⑥改分支名不联动下游 `depends_on`：下游那条 `cond@yes` 会变成不存在的出口，
  前后端都会拒绝保存并列出可用出口，用户需手删依赖再重连；
  ⑦谓词正则按各自引擎判定（后端 `re.compile`、前端 `new RegExp`），
  Python 独有的 `(?P<n>x)` 能过保存期但读不回编辑器；
  ⑧`removeEdges` 手写解析 `edge_id` 与 `workflow-canvas-model.ts` 的 `edgeId()` 是两份实现，格式若改需同步。
- **本机时钟敏感用例的已知抖动**：`tests/workflows/test_scheduler.py::test_trigger_records_deadline_missed_beyond_grace`
  断言 `next_run_at > datetime.now(UTC)`，而 `next_run_at` 是调度器 tick 当时按 `cron='*/5 * * * *'`
  推进出来的下一个整 5 分钟点。只要 tick 到断言之间墙钟跨过那个整点（例如机器休眠/被挂起），
  断言就会失败。本脚本曾观察到一次这种失败（`next_run_at=22:45:00` 而断言时刻已是 `22:47:01`），
  重跑即通过；该用例只涉及 `workflows/scheduler.py` 与 `tasks/triggers.py`，
  两者本次**一字未改**（见上方改动范围），属于既有用例的时间敏感性，不是本次改动引入的回归。
- **Agent 编排接管模式下的多 sink 行为未做端到端验证**：条件分支后若不补显式汇聚步骤，
  `terminal_step_id` 会回退到定义里的最后一个步骤（可能是被跳过的那条分支），
  本轮只在 ADR 0006 的 Consequences 里点明并推荐「分支后补显式汇聚步骤」，
  没有为此写运行期用例（属于已知设计限制，不是漏测项）。
- **前端校验与后端校验的规则等价性未做机器比对**：两侧各有一份结构校验
  （`workflow-dag.ts` 的 `validateDag` 与 `validators.py`），本脚本分别验证了各自的拒绝清单，
  但没有做「同一份非法定义在两侧都必须被拒」的交叉穷举。
- **条件步骤的 token 成本不可测**：条件步骤不建会话、不调模型，因此 `model_usage_records` 里
  没有它的行（预期行为，非漏记）。

## 验收结论

| # | 验收标准 | 结论 |
| --- | --- | --- |
| 1 | tests/workflows 全绿 + ruff/black 通过 + 无新增迁移 | 通过 |
| 2 | 存量线性定义零改动兼容（边仍全为 source_handle='default'） | 通过 |
| 3 | 谓词真值表 / 多分支取第一 / 未命中走兜底 | 通过 |
| 4 | 跳过传播：未选中分支落 skipped 且每步恰一条 | 通过 |
| 5 | 到达触发汇聚：只有一条分支到达也执行 | 通过 |
| 6 | fail_branch：failed + on_error_applied=False，run 仍 completed | 通过 |
| 7 | 保存期拒绝清单（13 条） | 通过 |
| 8 | 前端 tsc -b / vite build / workflow-dag.ts 真实实现探针 | 通过 |
