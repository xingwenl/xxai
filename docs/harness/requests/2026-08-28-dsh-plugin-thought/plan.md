# 实施计划

## 变更文件

| 文件 | 职责 | 对应 spec 增量点 |
|---|---|---|
| `docs/harness/specs/plugin-boundaries.md`（新增） | 固化平台原则：原语收敛、组合可扩展、不热替换；映射现有分层 | 1 |
| `apps/backend/app/modules/tools/business/framework.py`（修改） | `depends_on` 支持业务工具键；新增环检测；元数据字段 | 2、3 |
| `apps/backend/app/modules/tools/basic/framework.py`（修改） | `BasicTool` 元数据字段与默认值 | 3 |
| `apps/backend/app/modules/tools/business/registry.py` 或等价入口（修改） | 启动校验接入环检测与缺失校验 | 2 |
| `apps/backend/app/modules/gateway/dispatcher.py`（修改） | 工具执行前/后发布异步可观测事件 | 4 |
| `apps/backend/tests/tools/test_dependency_graph.py`（新增） | 缺失依赖、环检测、合法依赖图用例 | 2、3 |
| `apps/backend/tests/gateway/test_tool_events.py`（新增） | 事件顺序与字段断言 | 4 |
| `docs/harness/requests/2026-08-28-dsh-plugin-thought/{verify,acceptance}.md`（更新） | 实施后的真实验证与验收记录 | 全部 |

## 实施步骤

1. 先写平台原则文档 `docs/harness/specs/plugin-boundaries.md`，明确边界，作为后续代码实现的依据。
2. 扩展 `BusinessTool` 元数据与依赖语义：`depends_on` 允许业务工具键（命名空间区分）；`BasicTool`/`BusinessTool` 增加 `version`、`author`、`permissions`、`side_effect` 默认值字段。
3. 在启动校验中实现依赖图校验：缺失检测（已有）+ 环检测（DFS 染色或拓扑排序），环时报错输出完整路径。
4. dispatcher 工具执行前发布 `tool_pre_execute`、执行后发布 `tool_post_execute` 异步事件（含耗时、状态、结果摘要），消费方先接入审计日志，不做拦截。
5. 补单元测试，跑通 `pytest` 与 `ruff`，更新 `verify.md`、`acceptance.md`。

## 测试步骤

- `poetry run pytest -q apps/backend/tests/tools/test_dependency_graph.py apps/backend/tests/gateway/test_tool_events.py --import-mode=importlib`：预期新增用例全部通过。
- `poetry run pytest -q --import-mode=importlib`：预期全量后端测试通过，无回归。
- `poetry run ruff check app/modules/tools app/modules/gateway tests/tools tests/gateway`：预期无错误。
- 启动校验冒烟：构造临时 A→B→A 依赖环用例，预期启动报错并打印环路径。

## 回滚说明

- 代码回滚：`git revert` 本次提交即可；增量点相互独立，可分别回滚（先回滚事件钩子，再回滚依赖校验，最后回滚元数据）。
- 行为关注点：事件钩子为新增异步发布，移除后仅丢失可观测性，不影响工具执行；依赖校验收紧后启动失败属预期保护行为，回滚即恢复旧校验。
- 文档回滚：删除 `docs/harness/specs/plugin-boundaries.md` 并还原本 request 的 verify/acceptance 初始态。

## 人工确认点

- 进入实现前需人工确认：spec 范围（4 个增量点 + 1 条原则）、依赖语义扩展（业务工具可依赖业务工具）、事件钩子只做可观测不拦截。
- 若后续要将工具元数据（如 `permissions`）对外部（前端/MCP）暴露或执行 enforcement，需另行确认。
- 若后续要做 Agent 能力组合模板，属新 request，需重新走确认流程。
