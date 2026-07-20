# 实施计划

## 变更文件

- `docs/harness/requests/2026-07-19-user-module-minimum/*`
  - 记录本次 `user` 模块闭环。
- `apps/backend/app/modules/user/*`
  - 新增用户模块代码。
- 扩展用户模块支持 update/delete。
- `apps/backend/app/shared/base_repository.py`
  - 抽象共享 CRUD 仓储基类。
- `apps/backend/app/__init__.py`
  - 注册用户路由。
- `apps/backend/app/core/config.py`
  - 补齐从 `DB_*` 拼接数据库连接串的能力。
- `apps/backend/app/shared/exceptions.py`
  - 增加重复资源冲突异常。
- `apps/backend/alembic.ini`
  - Alembic 配置入口。
- `apps/backend/migrations/env.py`
  - 接通应用 metadata。
- `apps/backend/migrations/script.py.mako`
  - 迁移脚本模板。
- `apps/backend/migrations/versions/*`
  - 首个用户表 migration。
- `apps/backend/tests/user/*`
  - 最小测试。

## 实施步骤

1. 创建本次 request 文档，明确用户模块第一版范围。
2. 扩展 `user` 模块的 schema、repository、service、router，加入 update/delete。
3. 抽取共享 `BaseRepository`，收敛通用 CRUD 逻辑。
4. 让 `UserRepository` 仅保留用户专属查询，如 `get_by_email()`。
5. 复用现有 `users` 表，不新增 migration。
6. 增加最小测试，覆盖 update/delete 服务逻辑与路由基线。
7. 运行最小验证命令，记录可执行项与环境限制。
8. 调整共享分页基础与 `GET /api/v1/users` 的返回结构，去掉 `meta.pagination`。

## 测试步骤

- `apps/backend/.venv/bin/pytest apps/backend/tests -q`
  - 预期结果：用户模块与现有基础测试通过。
- `apps/backend/.venv/bin/ruff check apps/backend`
  - 预期结果：代码无 lint 报错。
- `apps/backend/.venv/bin/python -m compileall apps/backend/app apps/backend/tests apps/backend/main.py`
  - 预期结果：代码可正常编译。
- `apps/backend/.venv/bin/python -c "from main import app; print([route.path for route in app.routes if 'users' in route.path])"`
  - 预期结果：能看到 `/api/v1/users` 相关路由。
- `apps/backend/.venv/bin/python -c "from main import app; import json; print(json.dumps(app.openapi()['paths']['/api/v1/users']['get'], ensure_ascii=False))"`
  - 预期结果：分页列表接口的响应模型不再包含 `meta.pagination`，而是在 `data` 中直接声明分页字段。

## 回滚说明

- 若回滚本次改动，删除 `user` 模块文件、Alembic 配置文件与对应测试即可。
- 若后续已经执行数据库迁移，还需要在真实数据库中回滚 migration。

## 人工确认点

- 已确认：用户允许继续实现 `user` 模块。
- 已确认：用户于 2026-07-20 要求调整分页返回格式，属于 API 契约变更，允许继续修改。
