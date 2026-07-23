# 验证记录

## 执行命令

- `apps/backend/.venv/bin/pytest apps/backend/tests -q`
- `apps/backend/.venv/bin/ruff check apps/backend`
- `apps/backend/.venv/bin/python -m compileall apps/backend/app apps/backend/tests apps/backend/main.py apps/backend/migrations`
- `apps/backend/.venv/bin/python -c "import json,sys; sys.path.insert(0, 'apps/backend'); from main import app; print(sorted(path for path in app.openapi()['paths'].keys() if 'users' in path or 'roles' in path)); print(json.dumps(app.openapi()['paths']['/api/v1/users']['get']['parameters'], ensure_ascii=False))"`
- `apps/backend/.venv/bin/pytest apps/backend/tests/user -q`（在补充 user list 的 `roles` 字段后复验）
- `apps/backend/.venv/bin/ruff check apps/backend`（在补充 user list 的 `roles` 字段后复验）
- `apps/backend/.venv/bin/python -m compileall apps/backend/app apps/backend/tests apps/backend/main.py`（在补充 user list 的 `roles` 字段后复验）
- `apps/backend/.venv/bin/pytest apps/backend/tests/user apps/backend/tests/role -q`（在改为 ORM relationship + selectinload 后复验）
- `apps/backend/.venv/bin/ruff check apps/backend`（在改为 ORM relationship + selectinload 后复验）
- `apps/backend/.venv/bin/python -m compileall apps/backend/app apps/backend/tests apps/backend/main.py`（在改为 ORM relationship + selectinload 后复验）

## 预期结果

- 角色模块与用户角色相关测试通过。
- 代码无 lint 报错、无语法错误。
- OpenAPI 中可见 `/api/v1/roles` 与扩展后的 `/api/v1/users` 路由。
- `GET /api/v1/users` OpenAPI 中声明 `role_id`、`role_code` 查询参数。
- 用户列表默认返回项中包含 `roles` 角色摘要字段。
- user-role 多表查询改为 ORM relationship 加载后，现有接口返回结构保持不变。

## 实际结果

- `apps/backend/.venv/bin/pytest apps/backend/tests -q`
  - 结果：`30 passed`
- `apps/backend/.venv/bin/ruff check apps/backend`
  - 结果：`All checks passed!`
- `apps/backend/.venv/bin/python -m compileall apps/backend/app apps/backend/tests apps/backend/main.py apps/backend/migrations`
  - 结果：应用代码、测试与 migration 文件均可正常编译。
- `apps/backend/.venv/bin/python -c "import json,sys; sys.path.insert(0, 'apps/backend'); from main import app; print(sorted(path for path in app.openapi()['paths'].keys() if 'users' in path or 'roles' in path)); print(json.dumps(app.openapi()['paths']['/api/v1/users']['get']['parameters'], ensure_ascii=False))"`
  - 结果：OpenAPI 中可见 `['/api/v1/roles', '/api/v1/roles/{role_id}', '/api/v1/users', '/api/v1/users/{user_id}']`，且用户列表参数包含 `role_id`、`role_code`。
- `apps/backend/.venv/bin/pytest apps/backend/tests/user -q`（在补充 user list 的 `roles` 字段后复验）
  - 结果：`18 passed`
- `apps/backend/.venv/bin/ruff check apps/backend`（在补充 user list 的 `roles` 字段后复验）
  - 结果：`All checks passed!`
- `apps/backend/.venv/bin/python -m compileall apps/backend/app apps/backend/tests apps/backend/main.py`（在补充 user list 的 `roles` 字段后复验）
  - 结果：应用代码与测试可正常编译。
- `apps/backend/.venv/bin/pytest apps/backend/tests/user apps/backend/tests/role -q`（在改为 ORM relationship + selectinload 后复验）
  - 结果：`24 passed`
- `apps/backend/.venv/bin/ruff check apps/backend`（在改为 ORM relationship + selectinload 后复验）
  - 结果：`All checks passed!`
- `apps/backend/.venv/bin/python -m compileall apps/backend/app apps/backend/tests apps/backend/main.py`（在改为 ORM relationship + selectinload 后复验）
  - 结果：应用代码与测试可正常编译。

## 失败项与例外

- 本次为衔接当前工作区已存在的 `sys_users + account/password` 模型状态，新增 migration 同时包含：
  - `users -> sys_users` 重命名
  - `account/password` 列补齐
  - `sys_roles` / `sys_user_roles` 建表
- 尚未执行真实数据库上的 `alembic upgrade head` 复验，因此 migration 目前以静态审阅、编译和应用 metadata 接通验证为主。
- 本次 `user list` 增加 `roles` 字段仅涉及响应组装与测试，不涉及新的 migration。
- 本次 ORM 查询优化仅涉及模型关系与仓储查询实现，不涉及新的 migration 或 API 契约变化。
