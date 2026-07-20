# 业界调研记录

## 调研问题

- 在本仓库当前技术基线上，`user` 模块的第一版最小闭环应该包含哪些数据字段与接口。
- 如何在不提前引入鉴权复杂度的前提下，先把第一个真实业务模块做成后续模块的参考模板。

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

## 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| 方案 A：第一版就做完整用户鉴权体系（密码、JWT、登录） | 功能看起来更完整 | 会立刻把鉴权、密码安全、权限语义都拉进来，范围过大 | 低 |
| 方案 B：先做最小用户资料模块（创建、详情、分页列表），把密码与鉴权留到下一 request | 范围清晰，能验证 ORM、迁移、分页和响应基线 | 还不是完整账号系统 | 高 |
| 方案 C：只做用户表，不暴露 API | 数据层先行 | 无法验证 API 契约和共享返回格式是否顺手 | 中低 |

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

## 剩余风险

- 资料时效性：来源来自 2026-07-19 可访问的官方文档与成熟模板。
- 与本项目上下文的差异：成熟模板通常含密码和登录体系，本次刻意收敛为资料型用户模块。
- 尚未验证的假设：
  - 当前未引入真实数据库联通验证，迁移脚本仍以静态审阅为主。
