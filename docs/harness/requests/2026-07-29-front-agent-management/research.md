# 智能体管理前端接入调研

## 调研问题

评估前端是否可以直接接入智能体管理，以及第一阶段所需的真实接口、平台边界和版本管理能力。

## 功能复杂度

- 级别：核心业务功能，当前阻塞
- 选择理由：智能体属于平台级资源，涉及平台归属、版本发布、模型配置和 API 密钥；前端管理需要完整 CRUD 和平台选择能力。
- 最低调研要求：核对后端路由、schema、模型和服务测试，并比较当前可用接口与完整管理闭环的差异。

## 参考依据

### 来源 1

- 类型：本项目后端接口
- 名称：智能体路由与 schema
- 链接：`apps/backend/app/modules/agent/router.py`、`apps/backend/app/modules/agent/schemas.py`
- 版本或发布日期：当前仓库 HEAD，2026-07-29 调研
- 调研日期：2026-07-29
- 核心做法：仅提供 `POST /platforms/{platform_id}/agents` 创建智能体，以及版本创建、发布、回滚接口。
- 对本项目的启发：当前不能构建列表、编辑、停用或删除页面。

### 来源 2

- 类型：本项目后端接口
- 名称：平台路由与 schema
- 链接：`apps/backend/app/modules/platform/router.py`、`apps/backend/app/modules/platform/schemas.py`
- 版本或发布日期：当前仓库 HEAD，2026-07-29 调研
- 调研日期：2026-07-29
- 核心做法：仅提供创建平台和按 id 获取平台；没有当前用户的平台列表接口。
- 对本项目的启发：前端无法在管理入口选择合法的 `platform_id`。

### 来源 3

- 类型：成熟实践参考
- 名称：TanStack Query Mutations
- 链接：https://tanstack.com/query/latest/docs/framework/react/guides/mutations
- 版本或发布日期：官方文档，2026-07-29 调研
- 调研日期：2026-07-29
- 核心做法：管理页面应将列表查询与创建/编辑/删除 mutation 分离，并在成功后失效列表 query。
- 对本项目的启发：待后端补齐资源列表和变更契约后，前端可沿用现有用户/角色管理模式实现。

## 现有接口与管理需求差异

| 管理能力 | 后端现状 | 是否足够 |
|---|---|---|
| 平台选择 | 只有 `GET /platforms/{platform_id}` | 否，缺少平台列表 |
| 智能体列表 | 无 | 否 |
| 创建智能体 | `POST /platforms/{platform_id}/agents` | 单独可用，但无法形成管理闭环 |
| 编辑智能体 | 无 | 否 |
| 启用/停用 | 无 `is_active` 字段和接口 | 否 |
| 删除智能体 | 无 | 否 |
| 版本创建 | `POST /platforms/{platform_id}/agents/{agent_id}/versions` | 可用 |
| 版本发布/回滚 | 已提供 | 可用，但缺少版本列表接口 |

## 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| 只做创建和版本操作页面 | 不改后端 | 没有列表和平台选择，不能称为管理页面 | 低 |
| 前端写死 `platform_id` 并调用已有接口 | 可快速演示创建 | 依赖隐藏配置，无法支持多平台，也无法编辑/删除 | 低，不建议 |
| 先补齐后端管理契约，再实现前端 | 能形成真实 CRUD 闭环，平台权限由后端校验 | 需要新增后端 API 和模型字段/行为设计 | 高，推荐 |

## 最终决策

- 当前决策：补齐后端管理契约后实现前端智能体管理。
- 推荐的后端契约：`GET /platforms`、`GET /platforms/{platform_id}/agents`、`PATCH /platforms/{platform_id}/agents/{agent_id}`、`DELETE /platforms/{platform_id}/agents/{agent_id}`、`GET /platforms/{platform_id}/agents/{agent_id}/versions`，并增加 `is_active` 字段；保留已有创建、版本创建、发布和回滚接口。
- 删除决策：硬删除。`agent_versions.agent_id` 已设置 `ON DELETE CASCADE`，删除智能体会一并删除版本，数据库不会留下孤立配置。
- 人工确认记录：用户于 2026-07-29 确认允许新增 API，要求支持停用和删除，并确认删除采用硬删除。

## 剩余风险

- 尚未确定平台列表是否只返回当前用户拥有的平台，还是包含其管理员平台。
- 尚未确定智能体删除是硬删除、软删除还是仅禁止后续使用。
- 尚未确定版本列表和发布版本在页面中的展示与编辑范围。
- API Key 只允许写入，不允许在列表和版本详情响应中回显明文。
