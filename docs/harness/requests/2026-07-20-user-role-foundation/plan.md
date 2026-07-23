# 实施计划

## 变更文件

- `docs/harness/requests/2026-07-20-user-role-foundation/*`
  - 记录本次 user-role 设计闭环。
- `apps/backend/app/modules/role/*`
  - 新增角色模块代码。
- `apps/backend/app/modules/user/*`
  - 扩展用户角色关联、详情返回与按角色过滤。
- `apps/backend/app/shared/base_repository.py`
  - 如有必要，补充关联查询的共享抽象，但仅在通用性明确时处理。
- `apps/backend/migrations/versions/*`
  - 新增 `sys_roles` 与 `sys_user_roles` migration。
- `apps/backend/tests/role/*`
  - 角色模块最小测试。
- `apps/backend/tests/user/*`
  - 用户角色关联与按角色过滤测试。

## 实施步骤

1. 新建本次 request，完成业界调研与设计收敛。
2. 获得人工确认后，新增 `sys_roles`、`sys_user_roles` 模型与 migration。
3. 实现 `role` 模块的 schema、repository、service、router。
4. 扩展 `user` 模块的 schema、repository、service、router，支持角色集合维护。
5. 扩展用户列表查询参数，支持 `role_id` / `role_code` 过滤。
6. 补充最小自动化测试，覆盖：
   - 角色创建与唯一约束
   - 用户绑定角色
   - 用户按角色过滤
   - 已绑定角色删除保护
7. 运行验证命令并记录真实结果。

## 测试步骤

- `apps/backend/.venv/bin/pytest apps/backend/tests -q`
  - 预期结果：新增角色模块与用户角色测试通过。
- `apps/backend/.venv/bin/ruff check apps/backend`
  - 预期结果：代码无 lint 报错。
- `apps/backend/.venv/bin/python -m compileall apps/backend/app apps/backend/tests apps/backend/main.py apps/backend/migrations`
  - 预期结果：代码和迁移文件可正常编译。
- `apps/backend/.venv/bin/python -c "import json,sys; sys.path.insert(0, 'apps/backend'); from main import app; print(sorted(path for path in app.openapi()['paths'].keys() if 'users' in path or 'roles' in path))"`
  - 预期结果：OpenAPI 中可见 `/api/v1/roles` 与扩展后的 `/api/v1/users` 路由。

## 回滚说明

- 若回滚本次改动，删除 `role` 模块文件、`user` 模块相关扩展和对应测试。
- 若 migration 已经执行，还需要在真实数据库中回滚新增的角色相关版本。

## 人工确认点

- 待确认：是否接受“用户与角色采用多对多建模”，而不是给用户增加单个 `role_id`。
- 待确认：是否接受本次同时新增最小 `role` 模块 CRUD，而不是只在用户接口里内嵌角色关系。
- 待确认：是否接受“角色已被绑定时禁止删除”的第一阶段策略。
