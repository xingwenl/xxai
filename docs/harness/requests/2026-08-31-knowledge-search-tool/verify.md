# 验证记录

## 2026-08-31 实现后本地验证（全部在 `apps/backend` 下执行）

| 命令 | 结果 |
| --- | --- |
| `poetry run pytest tests/builtin_tool/test_knowledge_search.py tests/builtin_tool/test_attachment_search.py -q` | 16 passed |
| `poetry run pytest tests/builtin_tool -q` | 46 passed |
| `poetry run pytest -q --import-mode=importlib` | 451 passed, 1 skipped（`--import-mode=importlib` 为规避既有同名测试模块收集冲突，与历史全量验证一致） |
| `poetry run ruff check .` | All checks passed |
| `poetry run alembic heads` | `20260831_0032 (head)`，位于迁移链上 |
| `poetry run black --check`（新增 3 个文件） | 3 files would be left unchanged（新文件 black-clean；`attachment_search.py` 等既有文件在 HEAD 即非 black-clean，black 非本仓库门槛） |

验证内容覆盖：注册契约（`knowledge_search` 已注册、描述与 `attachment_search` 双向区分）、
错误语义（`invalid_arguments` / `no_knowledge_base` / `knowledge_base_not_available`）、
权限隔离（只检索 `list_enabled_for_agent` 启用列表）、向量检索与阈值过滤、
跨库汇总排序去重、embedding 维度校验（mock 模型，未调用真实 embedding API）。

## 待服务器环境验证（需人工）

- 真实知识库检索：在服务器数据库上确认 `alembic upgrade head` 应用迁移 `20260831_0032`、
  存量 Agent 获得 `knowledge_search` 绑定、真实 embedding 端点下检索结果正确。
- 真实会话回归：模型可自主调用 `knowledge_search` 检索知识库，且不再误用 `attachment_search`。
