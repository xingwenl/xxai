# 业界调研记录

## 调研问题

- 在当前 FastAPI + SQLAlchemy 后端中，如何增加最小可落地的登录注册能力。
- 登录后如何保护 `user` 与 `role` 相关接口，同时尽量少改现有模块边界。
- 当前阶段应该选择 cookie session、Bearer JWT，还是直接引入完整认证框架。
- 密码存储、token 生命周期和公开接口边界应遵循哪些成熟安全实践。

## 功能复杂度

- 级别：核心功能
- 选择理由：
  - 本次会新增登录、注册、鉴权依赖和受保护路由，直接改变 API 契约与鉴权行为。
  - 现有 `sys_users.password` 仍未进入正式安全策略，需要一并明确密码哈希方案。
  - 方案将影响后续前端接入、Swagger 调试方式和用户生命周期。
- 最低调研要求：
  - FastAPI 官方安全文档
  - 至少一个成熟认证框架或成熟实践案例
  - 至少一个权威安全指南

## 参考依据

### 来源 1

- 类型：官方文档
- 名称：FastAPI - OAuth2 with Password (and hashing), Bearer with JWT tokens
- 链接：https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/
- 版本或发布日期：在线文档，2026-07-23 访问
- 调研日期：2026-07-23
- 核心做法：
  - 使用 `OAuth2PasswordBearer` 提取 Bearer token。
  - 登录接口发放 JWT access token。
  - 使用密码哈希而不是明文密码比对。
  - 通过依赖注入获取当前登录用户，并在受保护路由统一复用。
- 对本项目的启发：
  - 本项目适合把“登录态校验”做成公共依赖，并挂到 `user` / `role` 路由。
  - 登录接口可以优先采用 Bearer JWT，便于现有 API 风格与 Swagger 调试。

### 来源 2

- 类型：权威安全指南
- 名称：OWASP Authentication Cheat Sheet
- 链接：https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html
- 版本或发布日期：在线文档，2026-07-23 访问
- 调研日期：2026-07-23
- 核心做法：
  - 密码必须安全哈希存储，避免明文或可逆加密。
  - 登录失败响应不应泄露过多账户状态细节。
  - 会话或 token 应有明确生命周期，并在服务端做好校验。
- 对本项目的启发：
  - 本次不能继续沿用明文密码存储语义，应切换到安全哈希。
  - 登录失败建议统一返回稳定错误，例如“账号或密码错误”。
  - token 需要设置过期时间，并校验用户启用状态。

### 来源 3

- 类型：成熟框架官方文档
- 名称：FastAPI Users - Authentication backends / JWT strategy
- 链接：https://fastapi-users.github.io/fastapi-users/latest/configuration/authentication/
- 版本或发布日期：在线文档，2026-07-23 访问
- 调研日期：2026-07-23
- 核心做法：
  - 认证链路通常拆为 transport（Bearer/Cookie）与 strategy（JWT/DB/Redis）。
  - Bearer + JWT 适合前后端分离和纯 API 服务。
  - Cookie/Database 策略更适合服务端会话与失效控制要求更强的场景。
- 对本项目的启发：
  - 当前仓库还没有完整认证基础设施，引入整套框架会显著扩大范围。
  - 但它验证了“Bearer transport + JWT strategy”是成熟且常见的最小 API 方案。

### 来源 4

- 类型：官方文档
- 名称：Django authentication system
- 链接：https://docs.djangoproject.com/en/5.2/topics/auth/default/
- 版本或发布日期：在线文档，2026-07-23 访问
- 调研日期：2026-07-23
- 核心做法：
  - 公开注册、登录与受保护后台能力应分开建模。
  - 认证与授权分层处理，先确认“用户是谁”，再判断“用户能做什么”。
- 对本项目的启发：
  - 本次可以只做到 authentication：注册、登录、识别当前用户、保护路由。
  - `role` 暂时只承载用户属性与后续授权扩展位，不在本 request 内新增角色授权规则。

## 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| 方案 A：Cookie + 服务端 session | 服务端可控失效，浏览器使用方便 | 需要额外 session 存储、CSRF 策略与更多基础设施 | 中 |
| 方案 B：Bearer JWT access token + 密码哈希 + 路由依赖保护 | 实现路径最短；符合 FastAPI 官方教程；适合纯 API；Swagger 友好 | 第一阶段不支持服务端主动注销所有 token；刷新 token 需后续补充 | 高 |
| 方案 C：直接引入完整认证框架（如 FastAPI Users） | 功能齐全，支持多种认证后端 | 会引入较多抽象和依赖，当前仓库规模下容易超出最小闭环 | 中低 |

## 最终决策

- 选择方案：方案 B。
- 选择原因：
  - 与当前项目的模块规模最匹配，可以在现有 `user` 数据模型上补齐注册、登录和受保护依赖。
  - 与 FastAPI 官方安全教程一致，后端实现和 Swagger 联调路径都比较直接。
  - 能在不引入额外 session 存储的前提下满足“登录注册”和“只有登录后才能访问 user/roles”。
- 不选择其他方案的原因：
  - 不选方案 A：当前仓库没有 Redis、session 表或 CSRF 基础设施，首次落地成本偏高。
  - 不选方案 C：会把 request 范围扩大到框架接入、适配和额外抽象，不利于先完成最小 auth 闭环。
- 对后续 spec、plan 或人工确认的影响：
  - 会新增公开 auth 接口，属于 API 契约变化。
  - 会调整密码存储与登录校验流程，属于鉴权行为变化。
  - 可能新增配置项，如 JWT secret、过期时间和算法，进入实现前需人工确认。

## 剩余风险

- 资料时效性：本次基于 2026-07-23 可访问的 FastAPI、OWASP、FastAPI Users 和 Django 官方资料整理。
- 与本项目上下文的差异：
  - 成熟框架通常还包含邮件验证、密码重置、刷新 token 和多端会话管理；本次不会一次做满。
  - 部分官方示例默认使用表单登录；本项目是否保留表单登录或改为 JSON 登录，需要在 spec 中明确。
- 尚未验证的假设：
  - 当前前端或调用方是否更偏好 `account` 登录还是 `email` 登录；本次先按 `account` 登录收敛。
  - 当前是否需要默认角色自动分配；本次先不在注册流程自动绑定角色。
