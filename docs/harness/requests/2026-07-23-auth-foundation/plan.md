# 实施计划

## 变更文件

- `docs/harness/requests/2026-07-23-auth-foundation/research.md`
  - 记录 auth 方案调研、方案比较和最终决策。
- `docs/harness/requests/2026-07-23-auth-foundation/spec.md`
  - 固化 auth 范围、接口边界、风险和验收标准。
- `docs/harness/requests/2026-07-23-auth-foundation/plan.md`
  - 记录实现顺序、测试步骤和回滚策略。
- `docs/harness/requests/2026-07-23-auth-foundation/verify.md`
  - 实现后补充真实验证证据。
- `docs/harness/requests/2026-07-23-auth-foundation/acceptance.md`
  - 实现后补充验收结论和剩余风险。
- `docs/harness/requests/2026-07-23-auth-foundation/meta.json`
  - 维护 request 当前阶段与阻塞状态。
- `apps/backend/app/core/config.py`
  - 扩展 JWT 相关配置项。
- `apps/backend/app/core/security.py`
  - 落地密码哈希、token 生成解析和当前用户依赖。
- `apps/backend/app/modules/auth/*`
  - 新增 auth router、schemas、services。
- `apps/backend/app/__init__.py`
  - 注册 auth 路由，并为 `user` / `role` 路由接入统一鉴权依赖。
- `apps/backend/app/modules/user/*`
  - 复用现有用户仓储与 schema，必要时拆分注册请求体与后台管理请求体。
- `apps/backend/tests/auth/*`
  - 新增 auth 相关测试。
- `apps/backend/tests/user/test_routes.py`
  - 更新受保护路由后的 OpenAPI 或未登录访问断言。

## 实施步骤

1. 先补齐文档与状态。
   - 完成 `research.md`、`spec.md`、`plan.md`。
   - 将 `meta.json` 标记为 `phase=plan`、`status=blocked`，等待人工确认。
2. 确认实现方案后，补安全基础设施。
   - 在 `config.py` 增加 JWT secret、algorithm、过期时间配置。
   - 在 `security.py` 增加密码哈希、密码校验、token 编解码、当前用户依赖。
3. 新增 `auth` 模块。
   - 定义注册、登录、当前用户请求/响应 schema。
   - 复用现有 `UserRepository` 完成注册与登录业务编排。
   - 保持注册和后台用户创建的请求体边界分离。
4. 接入受保护路由。
   - 注册 `auth` 路由。
   - 为 `user` 与 `role` 路由挂上登录依赖。
   - 确保未登录请求返回统一未认证错误。
5. 补充测试与验证。
   - 增加注册、登录、`auth/me`、未登录访问 `user` / `role` 的测试。
   - 更新或新增 OpenAPI 路由测试。
6. 完成 verify 与 acceptance。
   - 记录真实测试命令与结果。
   - 对照 spec 验收标准写结论和剩余风险。

## 测试步骤

- `cd apps/backend && poetry run pytest tests/auth -q`
  - 预期结果：auth 模块核心测试通过。
- `cd apps/backend && poetry run pytest tests/user tests/role -q`
  - 预期结果：受保护路由与既有 user/role 回归通过。
- `cd apps/backend && poetry run pytest -q`
  - 预期结果：全量后端测试通过。
- `cd apps/backend && poetry run ruff check .`
  - 预期结果：无新增 lint 错误。

## 回滚说明

- 若实现后需要撤回，可整体回退本 request 涉及的 auth 模块、配置扩展和路由鉴权依赖。
- 由于本次预期不新增 auth 专属表，回滚重点在代码与配置，不涉及数据库结构回退。
- 若中途发现调用方无法接受登录协议或访问前提变化，应先撤回对 `user` / `role` 的鉴权依赖，再评估替代接入方式。

## 人工确认点

- 确认新增公开接口：`POST /api/v1/auth/register`、`POST /api/v1/auth/login`、`GET /api/v1/auth/me`。
- 确认 `user` 与 `role` 现有接口改为“必须携带有效登录态”后再访问。
- 确认当前阶段采用 `account` 作为登录凭证，且注册接口不允许直接分配角色。
- 确认当前阶段采用 Bearer JWT access token-only 方案，不实现 refresh token 与服务端 token 撤销。

## 实际执行说明

- 2026-07-23 已获得用户确认并进入实现。
- 由于当前环境中的项目解释器在沙箱内不可直接执行，验证阶段改为使用 Codex bundled Python + 项目 `.venv/lib/python3.12/site-packages` 组合运行 `pytest` 与 `ruff`。
- 为避免新增 `python-multipart` 依赖，登录接口最终采用 JSON 请求体而非表单提交。
