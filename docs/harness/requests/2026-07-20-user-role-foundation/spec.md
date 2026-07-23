# 设计说明

## 目标

- 在现有 `sys_users` 基础上，引入系统模块角色能力，让用户可以拥有自己的角色。
- 支持在用户列表中按角色过滤用户，为后台用户管理提供基础检索能力。
- 为未来的权限体系保留稳定扩展位，但本次只落到“角色资料 + 用户角色关联”层。
- 方案基于 `research.md` 中的结论：采用多对多用户-角色建模，而非给用户表增加单一 `role_id`。

## 范围

- 新增系统角色数据模型：
  - `sys_roles`
  - `sys_user_roles`
- 角色采用系统模块命名规范：
  - 角色表：`sys_roles`
  - 用户角色关联表：`sys_user_roles`
- 扩展 `user` 模块能力：
  - 用户创建时可传角色集合
  - 用户更新时可调整角色集合
  - 用户详情返回角色摘要
  - 用户列表支持按 `role_id` 或 `role_code` 过滤
- 新增最小 `role` 模块基础资料管理能力：
  - `POST /api/v1/roles`
  - `GET /api/v1/roles/{role_id}`
  - `GET /api/v1/roles`
  - `PATCH /api/v1/roles/{role_id}`
  - `DELETE /api/v1/roles/{role_id}`
- 角色字段建议范围：
  - `id`
  - `code`
  - `name`
  - `description`
  - `is_active`
  - `created_at`
  - `updated_at`
- 用户角色关联字段建议范围：
  - `id`
  - `user_id`
  - `role_id`
  - `created_at`

## 非目标

- 本次不实现权限表、菜单表、资源表或接口级权限控制。
- 本次不实现角色继承、复合角色、职责分离策略。
- 本次不实现组织维度、租户维度或项目维度的 scoped role。
- 本次不实现登录态中基于角色的鉴权拦截。

## 风险

- 会新增两张真实业务表，后续若从“多角色”退回“单角色”会产生迁移成本。
- 用户接口返回结构会扩展角色信息，现有调用方若已依赖旧结构需要同步确认。
- 角色删除若不加保护，可能出现删除后用户角色关联残留或业务语义丢失。
- 当前 `user` 模块里 `account/password` 扩展尚未形成完整账号体系，角色设计需避免与未来 auth request 冲突。

## 停点判断

- 是否涉及架构边界变化：否，仍沿用现有 backend 分层与模块化规范。
- 是否涉及数据模型变化：是，会新增 `sys_roles` 与 `sys_user_roles`。
- 是否涉及 API 契约变化：是，会新增角色接口，并扩展现有用户接口。
- 是否涉及鉴权或权限行为变化：否，本次只做角色数据与查询能力，不直接做访问控制。
- 结论：进入实现前需人工确认。

## 验收标准

- 存在可审阅的 `sys_roles` 与 `sys_user_roles` ORM 模型及 Alembic migration。
- `role` 模块代码结构完整，符合仓库既定分层规范。
- 角色资料支持创建、详情、分页列表、更新、删除的最小闭环。
- 用户创建/更新支持维护角色集合，并对不存在的角色给出稳定错误语义。
- 用户详情中可返回角色摘要，至少包含 `id`、`code`、`name`。
- 用户列表支持按 `role_id` 或 `role_code` 过滤，并在列表项中返回 `roles` 角色摘要字段。
- 角色已被用户绑定时，删除操作会被拒绝并返回稳定冲突语义。
- 至少有最小自动化测试覆盖角色关联与按角色过滤用户的 service 逻辑。

## 建议接口与数据设计

### 表结构建议

- `sys_roles`
  - `id`：主键
  - `code`：角色编码，唯一，例如 `super_admin`、`operator`
  - `name`：角色名称，例如“超级管理员”“运营”
  - `description`：角色说明
  - `is_active`：是否启用
  - `created_at`、`updated_at`
- `sys_user_roles`
  - `id`：主键
  - `user_id`：外键指向 `sys_users.id`
  - `role_id`：外键指向 `sys_roles.id`
  - `created_at`
  - 唯一约束：`(user_id, role_id)`

### 查询建议

- 用户列表优先支持两种角色过滤：
  - `role_id`
  - `role_code`
- 不建议第一阶段就支持 `role_name like`、多角色并集/交集 DSL、角色层级展开查询。
- 默认排序仍保持 `created_at desc`。

### 用户接口建议

- `POST /api/v1/users`
  - 建议新增 `role_ids: list[int] = []`
- `PATCH /api/v1/users/{user_id}`
  - 建议支持 `role_ids` 整体替换
- `GET /api/v1/users/{user_id}`
  - 建议返回 `roles: [{id, code, name}]`
- `GET /api/v1/users`
  - 建议新增可选查询参数：
    - `role_id`
    - `role_code`

### 角色接口建议

- `POST /api/v1/roles`
- `GET /api/v1/roles/{role_id}`
- `GET /api/v1/roles`
- `PATCH /api/v1/roles/{role_id}`
- `DELETE /api/v1/roles/{role_id}`

删除策略建议：

- 若角色已被用户绑定，第一阶段优先禁止删除并返回稳定错误，而不是自动级联删关联。

## 变更记录

### 初始版本

- 时间：2026-07-20
- 变更原因：新增 user-role 基础设计闭环
- 变更内容：定义角色表、用户角色关联表、用户角色查询与最小角色模块范围
- 影响章节：全部
- 是否触发人工确认：是，进入实现前需人工确认

### 2026-07-20 第 1 次变更

- 变更原因：用户已确认采用多对多 user-role 建模，并要求继续实现
- 变更内容：落地 `sys_roles`、`sys_user_roles`、最小 `role` 模块 CRUD、用户角色关联与按角色过滤用户；同时补齐 `sys_users` 与现有模型差异的迁移衔接
- 影响章节：范围、风险、验收标准
- 是否触发人工确认：是，已在当前对话中获得确认

### 2026-07-20 第 2 次变更

- 变更原因：用户要求 `user list` 列表项也返回 `roles` 字段
- 变更内容：将 `roles` 纳入用户列表默认字段与可选字段集合，并在列表项中返回角色摘要
- 影响章节：验收标准
- 是否触发人工确认：是，已在当前对话中获得确认

### 2026-07-21 第 3 次变更

- 变更原因：用户希望简化多表联查实现，避免在 service 中逐个用户手动补角色
- 变更内容：为 `User` / `Role` 增加 ORM `relationship`，并将用户详情与列表角色加载改为 `selectinload` 驱动的关系查询
- 影响章节：风险、验收标准
- 是否触发人工确认：否
