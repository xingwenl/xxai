# 实施计划

## 变更文件

- 新增 `apps/backend/app/modules/tools/business/knowledge_search.py`：
  `knowledge_search` 业务工具（描述、输入契约、handler、错误码）。
- 修改 `apps/backend/app/modules/tools/business/registry.py`：
  增加 `knowledge_search` 收集页导入。
- 修改 `apps/backend/app/modules/tools/business/attachment_search.py`：
  仅更新 LLM 可见描述，明确"仅会话附件，知识库请用 knowledge_search"。
- 新增 `apps/backend/migrations/versions/20260831_0032_enable_knowledge_search.py`：
  为已启用 `attachment_search` 的 Agent 插入 `knowledge_search` 绑定。
- 新增 `apps/backend/tests/builtin_tool/test_knowledge_search.py`：
  权限隔离、错误语义、向量检索与返回契约测试（mock embedding）。
- 完成本 request 的 `verify.md`、`acceptance.md` 和 `meta.json`。

## 实施步骤

1. 实现 `knowledge_search` handler：
   参数校验 → `KnowledgeRepository(ctx.session).list_enabled_for_agent` →
   可选 `knowledge_base_id` 限定与校验 → 逐库 `build_embedding_model` + `knowledge_repo.search`
   + `retrieval_threshold` 过滤 + 维度校验 → 汇总、去重、截断、排序、限条数。
2. 在 `registry.py` 注册，确认内置工具目录自动派生（`builtin_tool/registry.py::_from_business`）。
3. 更新 `attachment_search` 描述，不改 handler 与契约。
4. 新增迁移 `20260831_0032`，确认迁移链 head 为 `20260831_0032`，可升级/回滚。
5. 编写 `test_knowledge_search.py`：
   未绑定知识库、跨库限定、限定启用库、embedding 检索路径、阈值过滤、契约字段、
   描述/契约不与附件工具冲突。所有测试 mock embedding，不调用真实 API。
6. 执行后端定向测试、全量测试、Ruff 与 Alembic 检查，修复问题。
7. 更新 `verify.md`、`acceptance.md`、`meta.json`。

## 测试步骤

- `poetry run pytest tests/builtin_tool/test_knowledge_search.py tests/builtin_tool/test_attachment_search.py -q`
- `poetry run pytest tests/builtin_tool -q`
- `poetry run pytest -q`（全量回归）
- `poetry run ruff check .`
- `poetry run alembic heads` 确认 `20260831_0032` 为 head；必要时执行一次升级/回滚往返

服务器数据库上的真实知识库检索（真实 embedding 端点、真实绑定）由人工在服务端执行后记录。

## 回滚方案

- 代码回滚：移除 `registry.py` 导入与 `knowledge_search.py` 即可让工具从目录消失；
  恢复 `attachment_search` 描述原文。
- 数据库：迁移 `downgrade` 删除 `knowledge_search` 绑定，不影响 `attachment_search` 绑定。
- 若运行时异常，可在分发层停用 `knowledge_search` 绑定，不影响其他内置工具与注入链路。

## 人工确认

- 用户批准本 `spec.md`（API 契约 + 权限行为变化）后进入实现。
- 实现不得扩展到：公开检索 API、跨 Agent/跨平台知识库访问、知识库绑定管理界面改造、
  词法检索兜底或数据模型变更。
