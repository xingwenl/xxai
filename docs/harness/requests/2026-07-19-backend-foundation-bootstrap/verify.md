# 验证记录

## 执行命令

- `apps/backend/.venv/bin/pytest apps/backend/tests -q`
- `apps/backend/.venv/bin/ruff check apps/backend`
- `apps/backend/.venv/bin/python -m compileall apps/backend/app apps/backend/main.py`
- `apps/backend/.venv/bin/python -c "import asyncpg"`
- `apps/backend/.venv/bin/python -c "import alembic"`
- `apps/backend/.venv/bin/python -c "from main import app; print(app.title)"`
- `apps/backend/.venv/bin/python -c "from app.core.database import init_database; init_database(); print('database-engine-ready')"`
- `poetry lock`
- `bash -n apps/backend/scripts/create_tables.sh`
- `bash apps/backend/scripts/create_tables.sh`
- `docker exec my_fastapi_db psql -U root -d ai_db -c '\dt'`
- `docker exec my_fastapi_db psql -U root -d ai_db -c 'select * from alembic_version;'`

## 预期结果

- 共享能力测试通过。
- 基础代码无 lint 报错、无语法错误。
- 新增依赖可在虚拟环境中导入。
- 应用对象可正常导入。
- 数据库引擎对象可初始化。
- `poetry.lock` 与 `pyproject.toml` 中的新依赖保持一致。
- 自动建表脚本语法正确，并能统一执行 Alembic migration。
- 真实数据库中可见迁移后的业务表与正确的 Alembic 版本号。

## 实际结果

- `apps/backend/.venv/bin/pytest apps/backend/tests -q`
  - 第一次从仓库根目录运行时失败，原因是测试环境未自动包含 `apps/backend` 到导入路径。
  - 补充 `apps/backend/tests/conftest.py` 后重新执行 `.venv/bin/pytest tests -q`，结果为 `5 passed`。
- `apps/backend/.venv/bin/ruff check apps/backend`
  - 结果：`All checks passed!`
- `apps/backend/.venv/bin/python -m compileall apps/backend/app apps/backend/main.py`
  - 结果：基础代码可正常编译。
- `apps/backend/.venv/bin/python -c "import asyncpg"`
  - 初次结果：失败，提示 `ModuleNotFoundError: No module named 'asyncpg'`。
  - 处理动作：安装缺失依赖后复验通过。
- `apps/backend/.venv/bin/python -c "import alembic"`
  - 初次结果：失败，提示 `ModuleNotFoundError: No module named 'alembic'`。
  - 处理动作：安装缺失依赖后复验通过。
- `./.venv/bin/pip install asyncpg alembic`
  - 结果：成功安装 `asyncpg 0.31.0`、`alembic 1.18.5` 及其依赖。
- `apps/backend/.venv/bin/python -c "from main import app; print(app.title)"`
  - 结果：输出 `AI Base Backend`，应用可正常导入。
- `apps/backend/.venv/bin/python -c "from app.core.database import init_database; init_database(); print('database-engine-ready')"`
  - 结果：输出 `database-engine-ready`，数据库引擎对象可正常初始化。
- `poetry lock`
  - 首次结果：因沙箱网络限制无法连接 `pypi.org`。
  - 处理动作：在允许联网解析后重跑成功，结果为 `Writing lock file`。
- `bash -n apps/backend/scripts/create_tables.sh`
  - 结果：脚本语法检查通过。
- `bash apps/backend/scripts/create_tables.sh`
  - 首次结果：脚本成功触发 Alembic，但暴露出 `20260720_0002` migration 对本地库既有 `sys_users` 状态不兼容。
  - 处理动作：将 migration 调整为兼容 `users` 与 `sys_users` 两种前置状态，并补齐索引/字段的条件化处理。
  - 最终结果：脚本执行成功，输出 `Database tables are up to date.`。
- `docker exec my_fastapi_db psql -U root -d ai_db -c '\dt'`
  - 结果：数据库内存在 `alembic_version`、`sys_users`、`sys_roles`、`sys_user_roles` 四张表。
- `docker exec my_fastapi_db psql -U root -d ai_db -c 'select * from alembic_version;'`
  - 结果：返回版本号 `20260720_0002`。

## 失败项与例外

- 本次为了让建表脚本可用，顺带完成了真实数据库上的 migration 执行与版本核验。
