# 实施计划

## 变更文件

- `docs/harness/requests/2026-07-19-backend-foundation-bootstrap/*`
  - 记录本次基础设施实现的完整闭环。
- `apps/backend/main.py`
  - 应用入口，暴露 ASGI app。
- `apps/backend/app/__init__.py`
  - 应用工厂与生命周期装配。
- `apps/backend/app/core/config.py`
  - 统一读取环境变量和基础配置。
- `apps/backend/app/core/logging.py`
  - 统一日志初始化。
- `apps/backend/app/core/database.py`
  - 统一异步引擎、session factory 和依赖注入入口。
- `apps/backend/app/shared/base_model.py`
  - SQLAlchemy 公共基类与命名约定。
- `apps/backend/app/shared/exceptions.py`
  - 统一业务异常和异常处理器注册。
- `apps/backend/app/shared/responses.py`
  - 固定返回格式与响应辅助函数。
- `apps/backend/app/shared/pagination.py`
  - 分页参数、分页元信息和辅助方法。
- `apps/backend/app/modules/system/*`
  - 最小系统模块，用健康检查接口验证基础设施装配。
- `apps/backend/tests/*`
  - 最小测试用例。
- `apps/backend/pyproject.toml`
  - 补齐基础依赖声明。

## 实施步骤

1. 创建本次 request 文档，明确第一阶段基础设施范围和顺序。
2. 建立应用工厂、日志初始化和配置入口。
3. 建立数据库基础层与 SQLAlchemy 公共基类。
4. 建立统一异常、固定返回格式和分页共享能力。
5. 增加最小 `system` 模块，用健康检查接口验证装配路径。
6. 补最小测试，优先覆盖共享响应和分页能力。
7. 执行可运行的最小验证命令，并把受环境限制的项写入 `verify.md`。

## 测试步骤

- `apps/backend/.venv/bin/pytest apps/backend/tests -q`
  - 预期结果：共享能力测试通过。
- `apps/backend/.venv/bin/ruff check apps/backend`
  - 预期结果：基础代码无 lint 报错。
- `python -m compileall apps/backend/app apps/backend/main.py`
  - 预期结果：代码可被解释器编译，无语法错误。

## 回滚说明

- 若要回滚本次改动，删除新增的 request 工作区和 `apps/backend/` 下新增基础设施文件即可。
- 本次不涉及业务表结构迁移，无需数据库回滚。

## 人工确认点

- 无，本次在已确认的后端技术规范范围内推进。
