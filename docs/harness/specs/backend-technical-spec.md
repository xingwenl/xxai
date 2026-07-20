# 后端技术规范

## 1. 文档目标

本文档定义本仓库 `apps/backend/` 的第一版后端基础技术规范，用于统一后续 FastAPI 后端开发方式。

本文档关注：

- 核心技术栈
- 目录与模块边界
- 数据访问和迁移策略
- 配置、日志、异常和测试基线
- 已定方案与待讨论项

本文档不直接定义：

- 具体业务表结构
- 具体接口清单
- 具体鉴权实现细节

## 2. 核心技术栈

### 2.1 已定技术

- Python：`3.12+`
- Web 框架：`FastAPI`
- ASGI Server：`Uvicorn`
- 数据库：`PostgreSQL`
- ORM：`SQLAlchemy 2.0`
- 数据迁移：`Alembic`
- 请求/响应校验：`Pydantic v2`
- 项目依赖管理：`Poetry`
- 代码质量：`pytest`、`ruff`、`black`

### 2.2 推荐补充依赖

以下依赖建议在进入后端基础设施实现时补齐：

- `asyncpg`
  - 用途：PostgreSQL 异步驱动。
- `alembic`
  - 用途：数据库迁移管理。

### 2.3 当前技术结论

- 后端应采用异步请求处理链路。
- 数据库访问应统一采用 SQLAlchemy 2.0 的 async API。
- 数据库模式变更必须统一通过 Alembic 管理。
- 请求模型与数据库模型分离，不采用单一模型同时承担 API 与 ORM 两类职责。

## 3. 目录结构规范

推荐目录如下：

```text
apps/backend/
├── main.py
├── app/
│   ├── core/
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── security.py
│   │   └── logging.py
│   ├── modules/
│   │   ├── user/
│   │   │   ├── router.py
│   │   │   ├── schemas.py
│   │   │   ├── models.py
│   │   │   ├── repositories.py
│   │   │   └── services.py
│   │   └── order/
│   │       ├── router.py
│   │       ├── schemas.py
│   │       ├── models.py
│   │       ├── repositories.py
│   │       └── services.py
│   └── shared/
│       ├── base_model.py
│       └── exceptions.py
├── migrations/
│   ├── env.py
│   └── versions/
└── tests/
    ├── user/
    └── order/
```

### 3.1 结构原则

- `main.py` 只做应用装配，不承载具体业务逻辑。
- `core/` 放跨模块基础设施。
- `modules/` 按领域划分，是业务代码的主组织方式。
- `shared/` 放跨模块可复用抽象，但要克制，避免再次长成“杂物箱”。
- `migrations/` 独立维护数据库演进历史。
- `tests/` 尽量与模块边界对齐。

### 3.2 为什么选模块化，而不是纯分层

- 业务代码就近收敛，查看一个模块时不需要在多个顶层目录来回跳转。
- 模块增长时更容易维持边界，便于多人并行开发。
- 纯分层目录更适合体量小、模块少的后端；本项目预期会持续增长，更适合领域组织方式。

## 4. 分层职责

### 4.1 `main.py`

负责：

- 创建 `FastAPI` 实例
- 注册 `lifespan`
- 挂载全局中间件
- 注册各模块路由

不负责：

- 编写业务逻辑
- 直接读写数据库
- 定义模块内私有规则

### 4.2 `router.py`

负责：

- 定义路径、方法、状态码和标签
- 接收请求并完成参数校验
- 调用 service
- 返回稳定响应模型

不负责：

- 写复杂业务规则
- 拼接数据库查询
- 直接处理事务

### 4.3 `schemas.py`

负责：

- 定义请求体
- 定义响应体
- 定义输入输出 DTO

不负责：

- 直接映射数据库连接行为
- 承担业务服务逻辑

### 4.4 `models.py`

负责：

- 定义 SQLAlchemy ORM 模型
- 定义表名、字段、约束、索引和关系

不负责：

- 承担 API 请求/响应模型
- 承担复杂业务逻辑

### 4.5 `repositories.py`

负责：

- 封装数据库读写
- 提供明确的数据访问接口
- 隔离查询细节

不负责：

- 编排完整业务流程
- 暴露 HTTP 语义

### 4.6 `services.py`

负责：

- 编排业务用例
- 组合 repository
- 承载业务规则
- 定义业务错误语义

不负责：

- 耦合 FastAPI 的 `Request` 或 `Response`
- 直接返回框架级响应对象

## 5. 数据库访问规范

### 5.1 访问方式

- 默认采用 SQLAlchemy 2.0 async API。
- 推荐连接串格式：`postgresql+asyncpg://...`
- `app/core/database.py` 统一提供：
  - `engine`
  - `async_sessionmaker`
  - `get_db_session` 依赖

### 5.2 Session 原则

- 每个请求使用独立 `AsyncSession`。
- repository 通过显式注入 session 工作，不在模块内部偷偷创建全局 session。
- 事务边界优先收敛在 service 层决定，避免 repository 各自提交导致不可控行为。

### 5.3 模型原则

- ORM 模型只表达持久化结构。
- API schema 只表达对外输入输出。
- 后续若出现读写模型差异，可进一步拆分 create/update/read schema。

## 6. 数据迁移规范

- 所有数据库结构变更必须走 Alembic。
- `migrations/` 目录进入源码管理。
- 不允许把“手动执行 SQL”当作正式迁移方案。
- 每次迁移都应能说明：
  - 为什么改
  - 改了什么
  - 如何回滚

## 7. 生命周期与启动规范

- 应用启动与关闭资源统一使用 FastAPI `lifespan`。
- 启动阶段适合处理：
  - 数据库连接准备
  - 日志初始化
  - 缓存或外部客户端初始化
- 不再继续扩散旧式 `startup` / `shutdown` 事件用法。

## 8. 配置规范

- 环境变量读取统一收口到 `app/core/config.py`。
- 业务代码不能散落 `os.getenv(...)`。
- 本地开发可以继续使用 `.env`，但配置对象必须通过统一入口暴露。
- 秘钥、数据库密码等敏感值不进入仓库。

## 9. 日志与异常规范

### 9.1 日志

- 日志初始化统一在 `app/core/logging.py`。
- 先以标准库 logging 为基线，避免第一阶段引入过多日志框架复杂度。
- 日志至少区分：
  - 应用启动日志
  - 请求处理异常
  - 数据库错误

### 9.2 异常

- 预期内业务错误应转成明确 HTTP 状态码。
- 全局通用异常可在 `app/shared/exceptions.py` 统一定义。
- 不直接把内部异常栈暴露给调用方。

## 10. 测试规范

- 测试目录与模块边界尽量对齐。
- 最低建议覆盖：
  - schema 校验
  - service 业务逻辑
  - router 接口行为
- 若模块涉及复杂查询，再增加 repository 测试。
- 初始验证基线建议包含：
  - `poetry run pytest`
  - `poetry run ruff check .`
  - `poetry run black --check .`

## 11. 已确认项

- 采用 `PostgreSQL` 作为主数据库。
- 采用 `FastAPI` 作为后端框架。
- 采用按领域模块化的目录结构。
- 采用 `SQLAlchemy 2.0` 作为 ORM，而不是把 API schema 与 ORM 完全合并。
- 数据库访问统一采用异步模式，即 `SQLAlchemy 2.0 async + asyncpg`。
- 采用 `Alembic` 管理数据库迁移。
- 启动资源统一走 `lifespan`。
- 鉴权方案本阶段只预留 `app/core/security.py` 边界，不在当前 request 内定死实现。

## 12. 本次讨论结论

以下事项已在 2026-07-19 与需求方确认：

### 12.1 是否全量采用异步数据库访问

- 结论：是。

原因：

- FastAPI 路由天然适合 async。
- SQLAlchemy 2.0 async 已成熟。
- 统一异步链路比同步/异步混搭更容易维护。

### 12.2 是否立即引入 `asyncpg` 与 `alembic`

- 结论：是。

原因：

- 这两项是落地 PostgreSQL 与迁移管理的必要依赖。
- 越晚补，越容易出现“先写表结构、后补迁移”的坏习惯。

### 12.3 `shared/` 是否保留

- 结论：保留，但严格限制。

原因：

- 真实项目里一定会出现跨模块公共异常、基类和工具。
- 但必须防止所有公共代码都往里堆，导致再次退化成大杂烩。

### 12.4 鉴权方案是否现在就定

- 结论：先只预留 `core/security.py` 边界，不在本阶段拍死实现。

原因：

- 当前先做后端地基更重要。
- 鉴权会连带接口契约、用户模型和权限语义，适合单独开 request 调研。

## 13. 后续实现顺序建议

如果你确认本规范，建议下一步这样推进：

1. 建立 `core/config.py`、`core/database.py`、`core/logging.py`。
2. 引入 `asyncpg` 与 `alembic`，完成数据库基础设施。
3. 建立 `shared/base_model.py` 与全局异常基线。
4. 按模块先实现一个最小样例模块，例如 `user` 或 `health`。
5. 补齐测试基线与开发命令。

## 14. 参考来源

- FastAPI Bigger Applications: https://fastapi.tiangolo.com/tutorial/bigger-applications/
- FastAPI Lifespan Events: https://fastapi.tiangolo.com/advanced/events/
- SQLAlchemy asyncio: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
- Alembic Tutorial: https://alembic.sqlalchemy.org/en/latest/tutorial.html
- Full Stack FastAPI Template: https://github.com/fastapi/full-stack-fastapi-template
