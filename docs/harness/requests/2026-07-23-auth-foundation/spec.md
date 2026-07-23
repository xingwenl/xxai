# 设计说明

## 目标

- 为当前后端增加最小认证闭环：注册、登录、识别当前登录用户。
- 让 `user` 与 `role` 模块接口默认只允许已登录用户访问。
- 在不引入完整权限系统的前提下，补齐密码哈希、JWT access token 和统一鉴权依赖。
- 方案基于 `research.md` 结论：采用 `Bearer JWT + 密码哈希 + 依赖注入保护路由`，不在第一阶段引入 session 存储或完整认证框架。

## 范围

- 新增 `auth` 模块最小接口：
  - `POST /api/v1/auth/register`
  - `POST /api/v1/auth/login`
  - `GET /api/v1/auth/me`
- 新增认证基础能力：
  - 密码哈希与校验
  - JWT access token 生成与解析
  - 当前登录用户依赖
  - 当前启用用户依赖
- 调整受保护路由：
  - `user` 模块所有现有接口需要登录后访问
  - `role` 模块所有现有接口需要登录后访问
- 配置层扩展：
  - JWT secret
  - JWT algorithm
  - access token 过期时间
- 测试范围：
  - 注册成功与冲突校验
  - 登录成功与失败
  - 未登录访问 `user` / `role` 返回未认证错误
  - 已登录访问 `auth/me`、`user`、`role` 成功

## 非目标

- 本次不实现 refresh token。
- 本次不实现登出黑名单或服务端 token 撤销表。
- 本次不实现邮箱验证、短信验证码、找回密码、修改密码。
- 本次不实现基于角色的细粒度授权；登录后即可访问 `user` 与 `role`，不再区分不同角色权限。
- 本次不改造前端页面或浏览器登录态存储方式。

## 风险

- `sys_users.password` 的存储语义会从当前实现切换到哈希值，属于真实认证逻辑变更。
- 新增公开注册接口后，用户创建会出现两条路径：`/auth/register` 和受保护的 `/users` 管理接口，需要保持语义区分。
- 若沿用 Bearer JWT access token-only 方案，第一阶段无法做到服务端逐 token 主动吊销。
- 当前实现采用 JSON 登录请求体而不是 `OAuth2PasswordRequestForm`，调用方需要按 `account/password` JSON 传参。

## 停点判断

- 是否涉及架构边界变化：否，仍沿用现有 FastAPI 模块、service、repository 分层。
- 是否涉及数据模型变化：否，预期复用现有 `sys_users` 字段，不新增 auth 专属表。
- 是否涉及 API 契约变化：是，会新增 `auth` 接口，并改变 `user` / `role` 的访问前提。
- 是否涉及鉴权或权限行为变化：是，会新增登录态与未认证拦截。
- 结论：进入实现前需人工确认。

## 验收标准

- 存在独立 `auth` 模块代码结构，包含 router、schemas、services。
- `POST /api/v1/auth/register` 可创建普通用户，且不允许调用方在注册时直接写入 `role_ids`。
- `POST /api/v1/auth/login` 可基于 `account + password` 返回 access token 和 token 类型。
- `GET /api/v1/auth/me` 在携带有效 token 时返回当前用户摘要与角色摘要。
- `user` 与 `role` 路由在未携带有效登录态时返回稳定未认证语义。
- 密码不会以明文形式写入数据库。
- 停用用户或不存在用户的 token 访问会被拒绝。
- 至少有最小自动化测试覆盖注册、登录、未登录拦截和已登录访问。

## 建议接口与行为设计

### 公开接口

- `POST /api/v1/auth/register`
  - 请求体建议字段：
    - `name`
    - `email`
    - `account`
    - `password`
  - 约束：
    - `email` 唯一
    - `account` 唯一
    - 不接受 `role_ids`
  - 返回：
    - 新创建用户摘要，不返回密码

- `POST /api/v1/auth/login`
  - 请求体字段：
    - `account`
    - `password`
  - 返回：
    - `access_token`
    - `token_type`
    - `expires_in`

- `GET /api/v1/auth/me`
  - 返回当前登录用户：
    - `id`
    - `name`
    - `email`
    - `account`
    - `is_active`
    - `roles`

### 受保护接口

- `GET /POST /PATCH /DELETE /api/v1/users...`
- `GET /POST /PATCH /DELETE /api/v1/roles...`
- 统一通过公共依赖校验 Bearer token 与用户状态。

### 密码与 token 策略

- 密码存储：
  - 当前实现采用标准库 `scrypt` 安全哈希，避免明文存储。
- 登录失败错误语义：
  - 统一返回“账号或密码错误”，避免泄露账户存在性。
- token 策略：
  - 第一阶段只发 access token。
  - token 携带用户标识和过期时间。
  - 默认短时有效，例如 30 分钟，可通过配置调整。

### 与现有 `user` 模块的关系

- `/auth/register` 负责公开注册。
- `/users` 保持为登录后的后台管理接口。
- 现有 `UserCreate` 若仍保留 `role_ids`，应仅用于后台管理接口，不复用为注册请求体。

## 变更记录

### 初始版本

- 时间：2026-07-23
- 变更原因：首次创建 auth 功能 request
- 变更内容：定义登录注册、JWT 鉴权依赖、受保护路由与最小测试范围
- 影响章节：全部
- 是否触发人工确认：是，进入实现前需人工确认

### 2026-07-23 第 1 次变更

- 变更原因：用户已确认 auth 方案并允许进入实现
- 变更内容：新增人工审批记录，允许实现公开 auth 接口、Bearer JWT 登录态和 `user`/`role` 受保护路由
- 影响章节：停点判断、验收标准
- 是否触发人工确认：是，已在当前对话中获得确认

### 2026-07-23 第 2 次变更

- 变更原因：结合当前依赖约束收敛最终实现细节
- 变更内容：登录接口最终采用 JSON `account/password` 请求体；密码哈希最终采用标准库 `scrypt`；路由保护基于 `HTTPBearer`
- 影响章节：风险、建议接口与行为设计
- 是否触发人工确认：否
