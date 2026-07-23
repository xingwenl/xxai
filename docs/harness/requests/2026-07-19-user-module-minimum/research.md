# 业界调研记录

## 调研问题

- 在本仓库当前技术基线上，`user` 模块的第一版最小闭环应该包含哪些数据字段与接口。
- 如何在不提前引入鉴权复杂度的前提下，先把第一个真实业务模块做成后续模块的参考模板。
- 在已具备分页参数的前提下，`GET /api/v1/users` 如何补充列表过滤、排序与字段裁剪，且保持接口语义清晰、实现成本可控。

## 功能复杂度

- 级别：核心功能
- 选择理由：本次会引入首个真实业务数据模型、首组真实 API 契约、首个 Alembic 迁移配置，影响后续所有业务模块的写法。
- 最低调研要求：官方文档 + 成熟案例 + 明确范围收敛。

## 参考依据

### 来源 1

- 类型：官方文档
- 名称：FastAPI - Response Model
- 链接：https://fastapi.tiangolo.com/tutorial/response-model/
- 版本或发布日期：在线文档，2026-07-19 访问
- 调研日期：2026-07-19
- 核心做法：请求模型与响应模型应分开定义，`response_model` 应明确控制对外暴露的数据结构。
- 对本项目的启发：`user` 模块必须区分 `UserCreate` 和 `UserRead`，不能把数据库模型直接暴露为接口响应。

### 来源 2

- 类型：官方文档
- 名称：FastAPI - Handling Errors
- 链接：https://fastapi.tiangolo.com/tutorial/handling-errors/
- 版本或发布日期：在线文档，2026-07-19 访问
- 调研日期：2026-07-19
- 核心做法：业务错误应统一转换为稳定的 HTTP 错误语义。
- 对本项目的启发：用户邮箱重复、用户不存在等错误应走统一异常体系，而不是接口内各自拼装。

### 来源 3

- 类型：官方文档
- 名称：FastAPI - Query Parameters and String Validations
- 链接：https://fastapi.tiangolo.com/tutorial/query-params-str-validations/
- 版本或发布日期：在线文档，2026-07-19 访问
- 调研日期：2026-07-19
- 核心做法：查询参数应通过共享参数模型与约束统一处理。
- 对本项目的启发：用户列表接口应直接复用已建立的分页参数能力。

### 来源 4

- 类型：官方文档
- 名称：SQLAlchemy 2.0 Documentation - Declarative Table with mapped_column()
- 链接：https://docs.sqlalchemy.org/en/20/orm/declarative_tables.html
- 版本或发布日期：SQLAlchemy 2.0.51 文档，发布日期 2026-06-15
- 调研日期：2026-07-19
- 核心做法：Declarative 模型使用 `mapped_column()` 定义主键、唯一约束、索引和默认值，是 SQLAlchemy 2.0 的推荐写法。
- 对本项目的启发：`User` 模型应采用 SQLAlchemy 2.0 typed declarative 风格，清晰表达唯一邮箱与时间戳字段。

### 来源 5

- 类型：官方文档
- 名称：Alembic - Auto Generating Migrations
- 链接：https://alembic.sqlalchemy.org/en/latest/autogenerate.html
- 版本或发布日期：Alembic 1.18.5 文档
- 调研日期：2026-07-19
- 核心做法：`env.py` 需要接入应用 `target_metadata`，自动生成迁移后仍应人工复核。
- 对本项目的启发：本仓库应先把 Alembic 配置接通 `BaseModel.metadata`，并为首个用户表提供可审阅的初始化 migration。

### 来源 6

- 类型：成熟开源项目
- 名称：fastapi/full-stack-fastapi-template
- 链接：https://github.com/fastapi/full-stack-fastapi-template
- 版本或发布日期：GitHub 仓库页面，2026-07-19 访问
- 调研日期：2026-07-19
- 核心做法：成熟模板通常先给出最小可用用户模型，再叠加鉴权、权限和更复杂资料。
- 对本项目的启发：本次 `user` 模块第一版应以“用户资料管理基线”为主，不把密码、登录和权限一次性塞进来。

### 来源 7

- 类型：官方文档
- 名称：JSON:API Format - Sorting
- 链接：https://jsonapi.org/format/#fetching-sorting
- 版本或发布日期：在线规范，2026-07-20 访问
- 调研日期：2026-07-20
- 核心做法：列表接口可使用单一 `sort` 参数表达排序字段，并用前缀 `-` 表示倒序。
- 对本项目的启发：`GET /api/v1/users` 适合采用 `sort=-created_at` / `sort=created_at` 这种简单稳定的排序表达，而不是额外拆 `sort_by` 与 `sort_order` 两个参数。

### 来源 8

- 类型：官方文档
- 名称：JSON:API Format - Sparse Fieldsets
- 链接：https://jsonapi.org/format/#fetching-sparse-fieldsets
- 版本或发布日期：在线规范，2026-07-20 访问
- 调研日期：2026-07-20
- 核心做法：客户端可以通过 `fields` 参数请求返回字段子集，降低列表页不必要的数据传输。
- 对本项目的启发：`GET /api/v1/users` 可以在保留默认完整字段返回的同时，支持 `fields=id,name,email` 形式的字段裁剪。

### 来源 9

- 类型：官方文档
- 名称：PostgREST - Horizontal Filtering / Ordering
- 链接：https://docs.postgrest.org/en/stable/references/api/tables_views.html
- 版本或发布日期：在线文档，2026-07-20 访问
- 调研日期：2026-07-20
- 核心做法：精确过滤与排序能力应保持资源化和显式语义；模糊查询通常以 `like/ilike` 表达，精确匹配保持等值条件。
- 对本项目的启发：`user` 列表查询应区分“`email` 精确过滤”和“`name` 模糊匹配”两类语义，不把所有过滤都模糊化。

## 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| 方案 A：第一版就做完整用户鉴权体系（密码、JWT、登录） | 功能看起来更完整 | 会立刻把鉴权、密码安全、权限语义都拉进来，范围过大 | 低 |
| 方案 B：先做最小用户资料模块（创建、详情、分页列表），把密码与鉴权留到下一 request | 范围清晰，能验证 ORM、迁移、分页和响应基线 | 还不是完整账号系统 | 高 |
| 方案 C：只做用户表，不暴露 API | 数据层先行 | 无法验证 API 契约和共享返回格式是否顺手 | 中低 |

## 列表查询增强方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| 方案 A：继续只保留分页，不加过滤排序字段能力 | 实现最简单 | 无法满足基础后台列表真实使用场景 | 低 |
| 方案 B：增加 `name` 模糊查询、`email` 精确查询、`sort` 单参数排序、`fields` 字段裁剪 | 参数数量少、语义清晰，兼顾常见后台查询场景与实现复杂度 | 列表返回项会变为“默认全字段 + 可选子集”的动态结构 | 高 |
| 方案 C：一次性做通用 DSL，如 `filter[name][like]`、多字段复合排序、复杂运算符 | 扩展性强 | 明显超出当前 request 的“基础能力”边界，测试与文档成本更高 | 中低 |

## 最终决策

- 选择方案：方案 B。
- 选择原因：
  - 能以最小范围走通真实数据模型、repository/service/router、分页和迁移链路。
  - 不提前把鉴权问题混进来，避免当前 request 失控。
  - 能成为后续业务模块的标准模板。
- 不选择其他方案的原因：
  - 不选方案 A：需要同时定密码存储、登录流程、JWT、权限语义，范围明显过大。
  - 不选方案 C：只做表结构无法验证 API 风格和共享返回格式基线。
- 对后续 spec、plan 或人工确认的影响：
  - 本次会新增用户表和 3 个接口：创建用户、用户详情、分页列表。
  - 用户已在 2026-07-19 明确回复“可以 写一个user模块”，可作为本次数据模型与 API 契约实现确认。

## 本次列表查询增强决策

- 选择方案：列表查询增强方案 B。
- 选择原因：
  - 与用户提出的“分页 + name 模糊 + email 精确 + 创建时间排序 + 指定字段”诉求直接对应。
  - `sort=-created_at` 与 `fields=id,name,email` 都有成熟规范先例，便于后续扩到其他模块。
  - 仅扩展现有 `GET /api/v1/users`，不引入新的数据模型和复杂查询 DSL，适合当前基础阶段。
- 不选择其他方案的原因：
  - 不选方案 A：无法覆盖最基础的后台列表检索需求。
  - 不选方案 C：当前还没有多个复杂筛选场景，过早抽象会让接口和测试复杂度明显上升。
- 对后续 spec、plan 或人工确认的影响：
  - 本次会扩展 `GET /api/v1/users` 的公开查询参数与响应可选字段行为，属于 API 契约变化。
  - 用户已于 2026-07-20 在当前对话明确提出这些参数需求，可作为本次接口增强的人工确认。

## 剩余风险

- 资料时效性：来源来自 2026-07-19 可访问的官方文档与成熟模板。
- 与本项目上下文的差异：成熟模板通常含密码和登录体系，本次刻意收敛为资料型用户模块。
- 尚未验证的假设：
  - 当前未引入真实数据库联通验证，迁移脚本仍以静态审阅为主。
