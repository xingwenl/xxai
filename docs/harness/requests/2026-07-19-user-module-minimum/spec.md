# 设计说明

## 目标

- 建立仓库中的第一个真实业务模块 `user`，作为后续模块开发模板。
- 在已完成的后端基础设施之上，验证真实数据模型、Alembic 迁移、分页列表和固定返回格式的配合方式。
- 保持第一版范围收敛，只实现最小用户资料管理能力。

## 范围

- 新建 `user` 模块：
  - `models.py`
  - `schemas.py`
  - `repositories.py`
  - `services.py`
  - `router.py`
- 新增用户数据模型：
  - `id`
  - `name`
  - `email`
  - `is_active`
  - `created_at`
  - `updated_at`
- 新增接口：
  - `POST /api/v1/users`
  - `GET /api/v1/users/{user_id}`
  - `GET /api/v1/users`
  - `PATCH /api/v1/users/{user_id}`
  - `DELETE /api/v1/users/{user_id}`
- 接通 Alembic 基础配置，并提供首个用户表 migration。
- 增加最小测试。

## 非目标

- 本次不实现登录。
- 本次不存储密码。
- 本次不实现角色、权限或组织关系。
- 本次不实现登录相关状态更新。

## 风险

- 本次新增真实数据模型与 API 契约，后续修改会影响迁移与接口兼容性。
- 用户邮箱唯一约束若只在服务层检查，仍存在并发条件下的数据库唯一冲突可能，后续需要结合数据库错误处理进一步强化。
- 由于当前未启动真实 PostgreSQL，本次迁移文件主要做静态正确性验证。

## 停点判断

- 是否涉及架构边界变化：否，沿用已确认的后端规范。
- 是否涉及数据模型变化：是，会新增 `users` 表。
- 是否涉及 API 契约变化：是，会新增 3 个 `user` 接口。
- 是否涉及鉴权或权限行为变化：否。
- 结论：本次原本需要人工确认，但用户已于 2026-07-19 明确批准“可以 写一个user模块”，可继续推进实现。

## 验收标准

- `user` 模块代码结构完整，符合仓库既定分层规范。
- 存在可审阅的 `users` 表模型与 Alembic migration。
- `POST /api/v1/users` 支持创建用户，并对重复邮箱给出稳定错误语义。
- `GET /api/v1/users/{user_id}` 支持按 ID 查询用户详情。
- `GET /api/v1/users` 支持分页列表，并将 `page_no`、`page_size`、`items`、`total`、`pages` 直接放入 `data`。
- `PATCH /api/v1/users/{user_id}` 支持局部更新 `name`、`email`、`is_active`。
- `DELETE /api/v1/users/{user_id}` 支持删除用户，并返回稳定成功响应。
- 至少有最小自动化测试覆盖 schema 或 service 逻辑。

## 变更记录

### 初始版本

- 时间：2026-07-19
- 变更原因：在后端基础设施完成后，开始实现第一个真实业务模块
- 变更内容：定义 `user` 模块最小闭环范围、数据模型和接口基线
- 影响章节：全部
- 是否触发人工确认：是，已在当前对话中获得确认

### 2026-07-19 第 1 次变更

- 变更原因：用户要求将 migration 从静态验证推进到本地 PostgreSQL 真实落库
- 变更内容：补充数据库容器启动、`alembic upgrade head` 执行和库内结果核验
- 影响章节：风险、验收标准
- 是否触发人工确认：否

### 2026-07-19 第 2 次变更

- 变更原因：用户要求为 `user` 模块补齐更新与删除能力
- 变更内容：新增 `PATCH /api/v1/users/{user_id}` 与 `DELETE /api/v1/users/{user_id}`，复用现有 `users` 表，不引入新字段
- 影响章节：范围、非目标、验收标准
- 是否触发人工确认：是，已在当前对话中获得确认

### 2026-07-19 第 3 次变更

- 变更原因：用户希望将基础 CRUD 封装为通用仓储能力，降低后续模块重复代码
- 变更内容：新增共享 `BaseRepository`，并让 `UserRepository` 继承复用通用增删改查
- 影响章节：范围、验收标准
- 是否触发人工确认：否

### 2026-07-19 第 4 次变更

- 变更原因：继续增强共享仓储，补齐更接近 TypeORM repository 手感的通用条件查询
- 变更内容：为 `BaseRepository` 新增 `get_one_by()`、`exists()`、`list_by()`，并进一步瘦身 `UserRepository`
- 影响章节：验收标准
- 是否触发人工确认：否

### 2026-07-20 第 5 次变更

- 变更原因：用户要求调整分页返回结构，取消 `meta.pagination` 嵌套
- 变更内容：将分页基础改为在 `data` 中直接返回 `page_no`、`page_size`、`items`、`total`、`pages`
- 影响章节：验收标准
- 是否触发人工确认：是，已在当前对话中获得确认
