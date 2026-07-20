# 业界调研记录

## 调研问题

- 在本仓库的 FastAPI 后端中，应该采用什么基础技术栈与目录边界，才能支持后续业务模块持续扩展。
- 在你已倾向 `PostgreSQL + FastAPI` 的前提下，还需要明确 ORM、迁移、连接方式、应用生命周期、目录组织与测试边界。

## 功能复杂度

- 级别：核心功能
- 选择理由：本次不是单点接口设计，而是后续所有后端 request 的基础工程决策，会直接影响架构边界、数据访问方式、模块拆分和实现成本。
- 最低调研要求：官方文档 + 成熟开源项目 + 方案比较 + 明确最终决策与未采纳原因。

## 参考依据

### 来源 1

- 类型：官方文档
- 名称：FastAPI - Bigger Applications - Multiple Files
- 链接：https://fastapi.tiangolo.com/tutorial/bigger-applications/
- 版本或发布日期：在线文档，页面未标注单独发布日期
- 调研日期：2026-07-19
- 核心做法：官方明确建议大型应用使用多文件结构，通过 `APIRouter`、依赖注入和分目录组织路由，避免所有内容堆在单文件中。
- 对本项目的启发：后端应从一开始就采用可拆分目录，不继续把业务逻辑放在 `main.py`。

### 来源 2

- 类型：官方文档
- 名称：FastAPI - Lifespan Events
- 链接：https://fastapi.tiangolo.com/advanced/events/
- 版本或发布日期：在线文档，页面未标注单独发布日期
- 调研日期：2026-07-19
- 核心做法：推荐使用 `FastAPI(lifespan=...)` 管理启动与关闭资源，而不是继续依赖旧式 `startup` / `shutdown` 事件。
- 对本项目的启发：数据库连接初始化、缓存、后台资源注册应统一挂到 `lifespan`，避免全局副作用分散。

### 来源 3

- 类型：官方文档
- 名称：SQLAlchemy 2.0 Documentation - Asynchronous I/O
- 链接：https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
- 版本或发布日期：SQLAlchemy 2.0 在线文档
- 调研日期：2026-07-19
- 核心做法：`create_async_engine`、`async_sessionmaker` 和 `AsyncSession` 构成标准异步 ORM 访问方式，可建立统一可复用的 Session 工厂。
- 对本项目的启发：若后端以 FastAPI 异步路由为主，数据库层也应统一走 SQLAlchemy 2.0 async API，而不是同步/异步混搭。

### 来源 4

- 类型：官方文档
- 名称：Alembic Tutorial
- 链接：https://alembic.sqlalchemy.org/en/latest/tutorial.html
- 版本或发布日期：Alembic 1.18.5 文档
- 调研日期：2026-07-19
- 核心做法：迁移环境应作为应用源码树的一部分长期维护，`env.py` 负责接入项目的数据库 URL、模型元数据和迁移配置。
- 对本项目的启发：不能用“手写 SQL”或“删除重建”替代正式迁移；数据库模式演进必须进入版本化管理。

### 来源 5

- 类型：成熟开源项目
- 名称：fastapi/full-stack-fastapi-template
- 链接：https://github.com/fastapi/full-stack-fastapi-template
- 版本或发布日期：GitHub 仓库页面，2026-07-19 访问
- 调研日期：2026-07-19
- 核心做法：成熟模板采用 FastAPI + PostgreSQL，并将后端基础设施、模型、API 组织为可扩展工程结构，同时配套迁移、容器化和环境配置。
- 对本项目的启发：`FastAPI + PostgreSQL` 是成熟生产组合；但该模板以 `SQLModel` 为中心，更适合追求一体化建模的项目，不一定最适合本仓库强调的模块职责分层。

## 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| 方案 A：按层分目录 `api/services/repositories/models` | 结构简单，容易快速起步；与不少教程一致 | 模块增多后跨目录跳转频繁，同一业务逻辑分散，后期边界容易松动 | 中 |
| 方案 B：按领域模块分目录 `modules/<domain>/router/service/repository/model/schema`，配合 `core/shared` | 与业务边界一致，单模块内聚，高扩展性；适合多业务模块长期演进 | 初期模板和约束要写清楚，否则团队容易写出风格漂移 | 高 |
| 方案 C：基于 SQLModel 的一体化模板 | 上手快，请求模型与 ORM 模型整合度高，社区模板多 | 模型职责更容易耦合；复杂业务下读写模型、领域对象、数据库对象容易混在一起 | 中低 |

## 最终决策

- 选择方案：方案 B，采用 `FastAPI + PostgreSQL + SQLAlchemy 2.0 async + Alembic`，目录按领域模块划分，并保留 `core/shared` 作为跨模块基础设施层。
- 选择原因：
  - 与 FastAPI 官方“多文件 + APIRouter”方向一致。
  - 比纯分层目录更适合后续用户、订单、知识库、对话等多个业务模块并行增长。
  - SQLAlchemy 2.0 async 和 Alembic 都是当前成熟、可控、可迁移的主流组合。
  - 能满足“请求模型、数据库模型、业务规则”分离，避免单模型承担过多职责。
- 不选择其他方案的原因：
  - 不选方案 A：短期更省事，但规模一上来会出现横切目录膨胀，模块边界不如领域化清晰。
  - 不选方案 C：虽然 `full-stack-fastapi-template` 很成熟，但 `SQLModel` 更强调建模一体化，不完全符合本次希望保留清晰 repository/service 边界的目标。
- 对后续 spec、plan 或人工确认的影响：
  - 本次会形成后端基础架构规范，属于架构边界决策。
  - 进入实际实现前应由你确认：是否接受“全异步数据库访问 + Alembic 迁移 + 领域模块化目录”这组三项核心决定。

## 剩余风险

- 资料时效性：本次使用的是 2026-07-19 可访问的官方文档与成熟模板页面；若后续依赖版本升级，具体 API 细节可能需要二次核对。
- 与本项目上下文的差异：成熟模板通常已经内置鉴权、容器编排和前后端联动，本仓库当前仍是后端基础阶段，需适度收敛复杂度。
- 尚未验证的假设：
  - 尚未验证团队是否希望所有模块统一走全异步数据库访问。
  - 尚未验证是否接受在实现阶段新增 `asyncpg`、`alembic` 等依赖。
