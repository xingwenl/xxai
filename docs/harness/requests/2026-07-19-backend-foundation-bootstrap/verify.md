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

## 预期结果

- 共享能力测试通过。
- 基础代码无 lint 报错、无语法错误。
- 新增依赖可在虚拟环境中导入。
- 应用对象可正常导入。
- 数据库引擎对象可初始化。
- `poetry.lock` 与 `pyproject.toml` 中的新依赖保持一致。

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

## 失败项与例外

- 未执行真实 PostgreSQL 连通验证，因为本次未启动数据库容器，也未建立业务表结构。
- 未执行 Alembic 初始化或生成迁移版本，因为本次只完成迁移目录占位，不引入具体数据模型。
