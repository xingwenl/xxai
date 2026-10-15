---
source: script
request: 2026-10-15-delegated-subagent-runtime
ranAt: "2026-10-15 17:08:49 CST"
exitCode: 3
---

## 已执行的命令与结果

### 临时 PostgreSQL 库 + alembic upgrade head
```bash
python /tmp/pg_admin.py create $ADMIN_DSN $TMP_DB && DATABASE_URL=$TMP_DSN alembic upgrade head
```

结果：通过
    INFO  [alembic.runtime.migration] Running upgrade 20260919_0035 -> 20261013_0036, 新增工作流定义、工作流运行、步骤运行三张表，并给任务表加工作流外键
    INFO  [alembic.runtime.migration] Running upgrade 20261013_0036 -> 20261014_0037, Agent 绑定编排工作流：新增绑定列，并把「同一工作流串行」的约束让开会话内触发
    INFO  [alembic.runtime.migration] Running upgrade 20261014_0037 -> 20261015_0038, 运行期委派子 Agent：给运行记录加父运行列，让子运行可回溯到父运行

### 验收 2：PG 侧外键动作 = SET NULL
```bash
MA_PG_DSN=$TMP_DSN python /tmp/pg_fk_probe.py
```

结果：通过
    PG 侧：列 integer/NULL、外键 SET NULL、索引齐备

### 验收 2：迁移可逆（downgrade -1 后 upgrade head 回到 head）
```bash
DATABASE_URL=$TMP_DSN alembic downgrade -1 && alembic upgrade head && alembic current
```

结果：通过
    INFO  [alembic.runtime.migration] Running upgrade 20261014_0037 -> 20261015_0038, 运行期委派子 Agent：给运行记录加父运行列，让子运行可回溯到父运行
    INFO  [alembic.runtime.migration] Will assume transactional DDL.
    20261015_0038 (head)

### 验收 2：SQLite 方言外键动作 = SET NULL
```bash
MA_SQLITE_DB=/tmp/ma_verify_sqlite.db python /tmp/sqlite_fk_probe.py
```

结果：通过
    SQLite 侧：自引用外键 on_delete=SET NULL

### 验收 5、6：父运行有委派工具与 MCP，子运行两者都没有
```bash
MA_SCOPE_DB=/tmp/ma_verify_scope.db python /tmp/tool_scope_probe.py
```

结果：通过
    父运行工具=['delegate_tasks', 'get_runtime_info', 'mcp_probe_echo']
    子运行工具=['get_runtime_info']

### 验收 3、4、5、9：真链路委派 3 个子任务（真库 + 只替换模型）
```bash
MA_PG_DSN=$TMP_DSN python /tmp/delegation_e2e.py
```

结果：通过
    父子落库：父 loop=1，子 loop=[2, 3, 4]，峰值并发=3，耗时=1.37s

### 验收 7、8：参数级拒绝 / 单子失败 / 超时 / 取消级联
```bash
MA_PARAM_DB=/tmp/ma_verify_param.db python /tmp/param_probe.py
```

结果：通过
    参数级拒绝零子运行；单子失败=2 且不中止其余；超时/取消后无 running 子运行（共 7 条）

### 验收 1：新增测试（委派端到端 + loop 串行执行）
```bash
cd apps/backend && python -m pytest tests/conversation/test_delegated_runs.py tests/agent_runtime/test_loop.py tests/tasks/test_task_services.py -q
```

结果：通过
    ........................................................                 [100%]
    56 passed in 4.33s

### 验收 1：回归 conversation + agent_runtime
```bash
cd apps/backend && python -m pytest tests/conversation tests/agent_runtime -q
```

结果：通过
    ........................................................................ [ 93%]
    ..............                                                           [100%]
    230 passed in 5.47s

### 验收 1：回归 workflows + tasks
```bash
cd apps/backend && python -m pytest tests/workflows tests/tasks -q
```

结果：通过
    ........................................................................ [ 73%]
    .....................................................                    [100%]
    197 passed in 20.55s

### 验收 1：回归 gateway（事件流与 embed 链路）
```bash
cd apps/backend && python -m pytest tests/gateway -q
```

结果：通过
    
    -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
    112 passed, 1 skipped, 1 warning in 2.89s

### 验收 1：ruff check（本次改动文件）
```bash
cd apps/backend && ruff check ${BACKEND_FILES[@]}
```

结果：通过
    All checks passed!

### 验收 1：black --check（新增文件 + HEAD 上本已合格的文件）
```bash
cd apps/backend && black --check ${BLACK_FILES[@]}
```

结果：通过
    All done! ✨ 🍰 ✨
    14 files would be left unchanged.

### 验收 9：apps/ai-sdk 类型检查（type-check）
```bash
bash -c set -eo pipefail; cd apps/ai-sdk; pnpm run type-check 2>&1 | tail -4
```

结果：通过
    > xxai-agent@0.2.0 type-check /Users/lixingwen/xw/study/ai-base/apps/ai-sdk
    > vue-tsc --noEmit
    

### 验收 9：apps/ai-sdk 构建（build）
```bash
bash -c set -eo pipefail; cd apps/ai-sdk; pnpm run build 2>&1 | tail -4
```

结果：通过
    dist/style.css            44.38 kB │ gzip:   7.97 kB
    dist/xxai-agent.umd.cjs  301.02 kB │ gzip: 111.84 kB
    ✓ built in 2.73s

### 验收 9：apps/front 重链本地 SDK 依赖（file:../ai-sdk）
```bash
bash -c set -eo pipefail; cd apps/front; pnpm install --frozen-lockfile --prefer-offline 2>&1 | tail -3
```

结果：通过
    Progress: resolved 1, reused 1, downloaded 0, added 1, done
    
    Done in 681ms using pnpm v9.15.9

### 验收 9：apps/front 类型检查与构建，产物含委派 UI
```bash
bash -c set -eo pipefail; cd apps/front; pnpm exec tsc -b; pnpm exec vite build 2>&1 | tail -3; grep -rl '子运行' dist/assets | head -3 | sed 's/^/  产物命中：/'; test -n "$(grep -rl '子运行' dist/assets | head -1)"
```

结果：通过
    - Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.
      产物命中：dist/assets/_taskId-_F9M9weA.js
      产物命中：dist/assets/xxai-agent.es-p4l2emib.js

## 未执行项与原因

- **真模型调用**：委派端到端探针把 `app.modules.agent.services.build_chat_model` 换成替身模型，
  因此「真实模型是否会自主选择 `delegate_tasks`」「真实 token 成本」未验证。
  理由：验证脚本不应依赖外部模型额度与随机输出；工具契约、并发、落库、读侧均已在生产代码路径上验证。
  影响面：委派能力本身的正确性不依赖模型输出，但「模型何时用它」属提示词工程，只能人工试用验证。
- **验收标准 3 的原判据 `model_usage_records.agent_id` 未执行**：`record_model_usage` 全仓唯一定义在
  `app/modules/conversation/repositories.py:325`，**唯一调用方是 `app/modules/gateway/runtime.py:509`（Embed WS 链路）**；
  无人值守 / 委派链路本就不写用量行，原判据不可能满足。已按 spec 回写改用 `conversations.agent_id` 承担，
  并在本脚本的端到端探针中断言三条子会话的 `agent_id` 分别是三个子 Agent。
- **SSE 事件序列逐字快照比对未做**：委派在父运行内只是一个普通工具调用，没有新增事件类型；
  本次只验证了「未绑定委派工具的运行读侧投影键集合不变」与 gateway 回归测试，未做事件序列逐字 diff。
- **black 只在部分改动文件上断言**：仓库范围的 black 本就不干净，app/core/config.py app/modules/conversation/models.py app/modules/conversation/repositories.py app/modules/conversation/runtime.py app/modules/gateway/dispatcher.py app/modules/tasks/schemas.py app/modules/tasks/services.py tests/agent_runtime/test_loop.py tests/tasks/test_task_services.py
  这 9 个文件在 HEAD 上就会被 black 判为需重排（本次也改到了它们），把它们纳入断言等于把既存格式债
  记到本次改动头上，也会引入与本次无关的重排 diff。因此 black 断言只覆盖「本次新建的文件」与
  「HEAD 上本已合格的文件」，即只把「因本次改动而变脏」判为失败。
- **浏览器交互（真实渲染 / 拖拽 / 点击）未做**：`apps/front` 没有测试运行器
  （scripts 只有 dev/build/lint/preview/format/format:check/knip，devDeps 无 vitest/jsdom/playwright）；
  本脚本只做类型检查、生产构建与产物字符串检查。
- **真实 HTTP / WebSocket 端到端（embed token → WS → 委派）未做**：需要 embed 客户端与真实模型；
  探针直接在服务层调用 `execute_unattended_chat`。
- **并发上限只在 PG 上以 3（默认闸 4）验证**：未做生产压力测试，也未验证 `DELEGATION_MAX_CONCURRENCY=1` 时的串行退化
  （该场景由 `apps/backend/tests/conversation/test_delegated_runs.py::test_concurrency_cap_is_enforced` 覆盖）。

## 验收结论

| # | 验收标准 | 结论 |
| --- | --- | --- |
| 1 | 回归测试全绿 + ruff / black 通过 | 通过 |
| 2 | 迁移可逆且外键动作 = SET NULL | 通过 |
| 3 | 一次派 3 个子任务：同父、独立会话、归属正确 | 通过（会话 `agent_id` 判据） |
| 4 | 真并发（3 个子运行时间窗重叠） | 通过 |
| 5 | 子运行工具清单无 `delegate_tasks` | 通过 |
| 6 | 子运行 MCP 不可用、平台内置工具可用 | 通过 |
| 7 | 参数级整体拒绝零子运行；单子失败不中止其余 | 通过 |
| 8 | 超时只影响该子任务；取消后子运行落终态 | 通过 |
| 9 | 未绑定形状不变、绑定后可读回、前端构建通过 | 通过 |

剩余风险：
1. 委派的触发依赖模型自主判断，脚本无法覆盖「真实模型是否会在合适时机发起委派」；
   工具描述已写明适用场景与自包含 task 要求，但提示词效果需人工试用评估。
2. 子运行的会话隔离由「每个子运行一个独立 Session + 独立会话记录」保证；
   若日后有人把 `ctx.session` 复用进子运行，会同时踩并发写与事务复用两个坑——
   `apps/backend/app/modules/tools/business/delegate_tasks.py` 的模块 docstring 已把这条写成硬边界。
3. 前端委派展示只做了类型检查、构建与产物字符串检查，没有浏览器交互验证（无测试运行器）。
4. 子运行不写 `model_usage_records`（既存事实：该表只由 Embed WS 链路写），
   因此委派的 token 成本目前无法按子运行归集；如后续要计费需另开 request。

是否可归档：**可以**（未执行项均为上述「主动不执行」范围，不影响本次决策的成立）。
