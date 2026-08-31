# 验收记录

## 2026-08-31 本地验收结论（按 spec 验收标准逐条）

| 验收标准 | 状态 | 依据 |
| --- | --- | --- |
| `knowledge_search` 已注册，描述与输入契约符合规格 | 通过 | 注册测试 + 契约测试；描述与 `attachment_search` 双向区分 |
| 权限隔离：未绑定/跨库/跨平台不可检索 | 通过 | `no_knowledge_base`、`knowledge_base_not_available` 测试 |
| 检索正确性：余弦排序、阈值过滤、去重、截断、limit 限制 | 通过 | 单元测试覆盖（mock embedding，未打真实 API） |
| `attachment_search` 描述更新、handler 与契约不变 | 通过 | 描述断言 + 既有 30 个附件工具测试全部通过 |
| 迁移 `20260831_0032` 在链上、可升级可回滚 | 通过 | `alembic heads` 确认 head；downgrade 为删除绑定语句 |
| 后端定向/全量测试、Ruff 通过 | 通过 | 451 passed + ruff 0 错误 |

## 待人工验收（服务器环境）

- `alembic upgrade head` 应用迁移并确认存量 Agent 自动获得 `knowledge_search` 绑定。
- 真实知识库检索（真实 embedding 端点、真实 Agent 绑定）结果正确。
- 真实会话中模型可自主调用 `knowledge_search` 且不再误用 `attachment_search`。

## 剩余风险

- 检索质量依赖知识库索引状态（`active_index_version`）与 embedding 端点可用性；
  异常按 `tool_failed` 冒泡，无降级路径（与既有注入链路一致）。
- 模型仍可能偶发误选工具；通过双工具描述互指降低概率，不承诺 100% 消除。
- 服务器真实验证未执行前，本 request 保持 `active`，不标记 `done`。
