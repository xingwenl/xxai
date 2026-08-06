# Agent 对话 Token 优化实施计划

## 变更文件

- 后端 `knowledge/models.py`、`schemas.py`、`repositories.py`、`services.py`、检索调用和 Alembic migration。
- 后端 conversation runtime/services/schemas 与技能服务/工具。
- 前端 knowledge API、知识库表单和列表展示。
- 后端检索、runtime、技能测试，前端类型/构建验证。

## 实施步骤

1. 新增数据库字段和迁移，补齐 ORM 中文 comment、Pydantic 范围校验及前端类型。
2. 修改仓储检索返回带 similarity 的候选，完成阈值、Top K、跨库去重和全局预算。
3. 将技能 runtime 上下文改为元数据，增加绑定范围内的 `load_skill` 工具并接入工具循环。
4. 更新后台知识库创建/编辑表单和列表展示。
5. 增加单元测试和 API/schema 测试，执行后端 pytest/ruff 及前端 typecheck/build。
6. 记录真实验证结果和剩余风险，完成 acceptance。

## 回滚

代码回滚后可保留字段；需要恢复旧行为时将阈值设为 0、Top K 设为 5，并暂时关闭按需技能工具。

## 人工确认点

- 已确认第一期包含后端、数据库/API 和前端配置。
- 已确认第一阶段不包含查询改写、重排、自适应检索及按内容类型阈值。
