---
source: script
request: 2026-10-13-workflow-orchestration
ranAt: "2026-10-13 18:21:46 CST"
exitCode: 3
---

## 已执行的命令与结果

### 迁移：在一次性临时库上从零 upgrade head，断言三张表与 tasks.workflow_id 可空

```bash
WF_TMP_DB=ai_base_wf_verify_<pid> python <pg_create_db.py> && cd apps/backend && DATABASE_URL=<临时库> alembic upgrade head && python <pg_schema.py>
```

临时库已创建： ai_base_wf_verify_14758
INFO  [alembic.runtime.migration] Running upgrade 20260903_0033 -> 20260919_0034, 新增任务定义与任务运行两张表
INFO  [alembic.runtime.migration] Running upgrade 20260919_0034 -> 20260919_0035, tasks 新增终端用户执行身份列
INFO  [alembic.runtime.migration] Running upgrade 20260919_0035 -> 20261013_0036, 新增工作流定义、工作流运行、步骤运行三张表，并给任务表加工作流外键
工作流表： ['workflow_runs', 'workflow_step_runs', 'workflows']
tasks.workflow_id 可空：YES
结果：通过

### 迁移可回退：downgrade -1 后三张表消失，再 upgrade head 回到 20261013_0036 (head)

```bash
cd apps/backend && DATABASE_URL=<临时库> alembic downgrade -1 && python <pg_schema_after_downgrade.py> && alembic upgrade head && alembic current
```

INFO  [alembic.runtime.migration] Running downgrade 20261013_0036 -> 20260919_0035, 新增工作流定义、工作流运行、步骤运行三张表，并给任务表加工作流外键
降级后：工作流表 0 张，tasks.workflow_id 已移除
INFO  [alembic.runtime.migration] Running upgrade 20260919_0035 -> 20261013_0036, 新增工作流定义、工作流运行、步骤运行三张表，并给任务表加工作流外键
重新升级后：20261013_0036 (head)
结果：通过

### 验收 1：PostgreSQL 上同一工作流只允许一条 running，skipped 不受影响

```bash
cd apps/backend && DATABASE_URL=<临时库> python <pg_partial_index.py>
```

第一条 running：插入成功
第二条 running 被拒绝： IntegrityError
running 之后插入 skipped：成功（where 子句未退化成全表唯一）
结果：通过

### 验收 1：SQLite 上同一语义（证明 sqlite_where 也写了，索引没退化成全表唯一）

```bash
cd apps/backend && python <sqlite_partial_index.py>
```

SQLite 第一条 running：插入成功
SQLite 第二条 running 被拒绝： IntegrityError
SQLite running 之后插入 skipped：成功
结果：通过

### 验收 2/3/4/6/8：工作流模块单测（静态校验、保存拒收、失败语义、调度 skip 与看门狗）

```bash
bash -c set -o pipefail; cd apps/backend && .venv/bin/python -m pytest tests/workflows -q 2>&1 | tail -8
```

........................................................................ [ 80%]
.................                                                        [100%]
89 passed in 6.30s
结果：通过

### 验收 9：现有任务零回归

```bash
bash -c set -o pipefail; cd apps/backend && .venv/bin/python -m pytest tests/tasks -q 2>&1 | tail -5
```

.....................................................................    [100%]
69 passed in 6.96s
结果：通过

### 静态检查：ruff check（工作流模块、被改动的任务模块与 conversation.services、迁移、测试）

```bash
bash -c set -o pipefail; cd apps/backend && .venv/bin/ruff check app/modules/workflows app/modules/tasks app/modules/conversation/services.py migrations/versions/20261013_0036_workflows.py tests/workflows 2>&1 | tail -10
```

All checks passed!
结果：通过

### 验收 5/7 端到端：两步骤工作流手动运行 → 两步 succeeded、第二步提示词已替换、旧快照仍可解释

```bash
cd apps/backend && python <e2e_two_steps.py>
```

Workflow step attempt failed run_id=2 step_id=only attempt=1/2 error=RuntimeError: 第 3 次调用被测试注入失败
保存后：version=1，节点 2 个，边 1 条
手动触发：已入队，started_at 为空
运行状态：completed，完成步骤 2/2
步骤状态： [('first', 'succeeded'), ('second', 'succeeded')]
第一步提示词： 产出素材
第二步提示词： 基于 OUTPUT-FOR: 产出素材 写摘要
改定义后：version=2
旧运行仍保留 version=1 的两步骤快照：可解释
重试：首次注入失败后第二次尝试成功，retry_count=2，两次输入一致
保存期拒绝 模板引用 {{first.other}}：step 'second' template path must be 'output', got 'other'
保存期拒绝 绑定路径 [first, other]：step 'second' input binding 'q' path must be 'output', got 'other'
运行详情字段：raw_output_size=24，output_truncated=False
端到端结论：通过
结果：通过

### 前端：类型检查（tsc -b）

```bash
bash -c set -o pipefail; cd apps/front && pnpm exec tsc -b && echo 'tsc：0 error'
```

tsc：0 error
结果：通过

### 前端：eslint（断言工作流相关文件 0 问题；仓库整体有 11 条既有问题）

```bash
bash -c set -o pipefail; cd apps/front && pnpm lint >/tmp/wf-verify-lint.txt 2>&1; tail -2 /tmp/wf-verify-lint.txt;     if grep -qi 'workflow' /tmp/wf-verify-lint.txt; then echo '工作流文件出现 lint 问题'; exit 1; fi;     echo '工作流相关 lint 问题：0'
```


 ELIFECYCLE  Command failed with exit code 1.
工作流相关 lint 问题：0
结果：通过

### 前端：生产构建（含路由树生成）

```bash
bash -c set -o pipefail; cd apps/front && pnpm exec vite build 2>&1 | tail -4
```

(!) Some chunks are larger than 500 kB after minification. Consider:
- Using dynamic import() to code-split the application
- Use build.rolldownOptions.output.codeSplitting to improve chunking: https://rolldown.rs/reference/OutputOptions.codeSplitting
- Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.
结果：通过

## 未执行项与原因

- 真实模型网关的端到端运行：未执行。需要可用的模型网关与已发布 Agent，且会在共享开发库写入真实会话、消息与用量记录；改用替换模型推理层的端到端探针覆盖同一条代码路径（保存 → 入队 → 逐步执行 → 传值 → 落库 → 快照）。
- 浏览器端到端点击流（脚本内未包含）：本脚本只做类型检查、lint 与生产构建，不起前端 dev server 与后端 API。本轮由人工另跑了一次 Playwright 验证（真实后端 8010 + 真实前端 5180），结果见「验收结论」末尾；其中表单提交（新建 / 编辑保存）与「立即运行」按钮的点击流未覆盖。
- 多副本调度抢占：未执行。需要同时运行两个调度进程竞争同一批到期任务；当前只覆盖了仓储层的 for update skip locked 语义与单进程 tick。
- 步骤级人工审批：未执行。v1 明确不做，waiting 状态只在枚举里预留，没有实现可验。

## 验收结论

逐条对照 spec.md 的 9 条验收标准（命令与真实输出见上）：

1. 三张表与部分唯一索引：通过。一次性临时库上 alembic upgrade head 从零建表，downgrade -1 后三表与 tasks.workflow_id 消失、再 upgrade 回到 20261013_0036；同一工作流的第二条 running 记录在 PostgreSQL 与 SQLite 上都报唯一约束冲突，running 之后插 skipped 正常。
2. 保存期静态校验：通过。引用后面的步骤、step_id 重复、超 max_steps、边指向不存在的 step_id 逐条被拒且不写库（test_validators.py / test_services.py）。
3. 工具步骤声明 financial 之类不可自动批准的 side_effect：通过，保存时直接拒绝（test_services.py）。
4. 步骤覆盖其它平台的 agent_id：通过，保存时被拒（test_services.py）。
5. 两步骤手动运行：通过。端到端探针断言 run completed、两条 step 都 succeeded、第二步收到的提示词里 {{first.output}} 已被第一步的真实输出替换；超 50KB 的输出在 model_visible_output 上被截断并带标记、raw_output 保留全量（test_runner.py），运行详情里 raw_output_size 与 output_truncated 由 schema 计算返回（端到端探针第 7 步 + test_routes.py）。
6. 失败语义：通过。on_error=abort 时后续步骤不执行、workflow_step_runs 里没有该步记录、run 为 failed；continue_with_default 时后续步骤照跑且该步的 on_error_applied 为真；max_retries 的重试拿同一份输入，兜底值只在全部尝试用尽之后才生效（test_runner.py 三例 + 端到端探针第 5 步）。
7. 定义快照：通过。改定义后 version 递增到 2，旧 run 仍带 version=1 的两节点快照，能解释那一次运行（端到端探针）。
8. 调度语义：部分通过。三种 skip_reason、看门狗收敛、只有入队态才被认领由 test_scheduler.py / test_repository.py 覆盖；真实进程被强杀与多副本抢占未实测（见未执行项）。
9. 现有任务零回归：通过。pytest tests/tasks -q 69 passed。

剩余风险：
- 选择器的 path 已在保存期收紧为只允许 output：{{first.other}} 与 [first, other] 都在保存时被拒且不写库（端到端探针第 6 步）。运行期仍会再查一次作为边界检查，两处共用 validators.OUTPUT_PATH。
- _require_platform_member 查的是 platform_admins 成员表，经 HTTP 进来的调用者恒被判为平台管理员，所以「同一平台内只看自己名下」这一层目前只有服务层直接调用覆盖到；跨平台隔离（404）有效。该行为与 tasks 模块一致，本次未改动，若要收紧属于鉴权行为变化、需另行审批。
- 前端已暴露每步的失败重试次数；步骤级 agent_id 覆盖仍只有 API 支持、界面不暴露（v1 决定），列表页「最近运行」按行查询（N+1）。
- 真实模型网关端到端、脚本内浏览器点击流、多副本调度抢占未执行，原因见上一节。

补充：人工浏览器验证（非本脚本，Playwright + 真实后端 8010 + 真实前端 5180，平台 1 / 管理员 user 7）——14/14 断言通过，problems 为空，覆盖列表页、定义页、运行记录页、运行明细四屏：列表显示「2 / 50」步骤数与最近运行时间；定义页显示两个步骤与「失败重试次数」下拉；运行记录显示「已完成 2 / 2」；运行明细显示「尝试 2 次」、「模型可见输出（超过 50KB 已截断，完整输出 108000 字节）」与截断后的输出文本。该验证同时暴露并修掉了 4 处前端手写类型与真实 payload 不一致的缺陷（后端 WorkflowRead 不返回 steps；运行详情缺 raw_output_size / output_truncated；RetryBadge 语义过时；运行记录不返回 created_at）。

是否可归档：可以归档。9 条验收标准中 8 条用真实命令验证，第 8 条为部分验证且缺口已显式列出；测试与静态检查全绿。
- 脚本退出码由 tools/harness/verify.sh 写入 verify.md 的 frontmatter。
