# Phase 2D 管理后台调研记录

## 调研问题

- Phase 2D 管理后台如何在不继续堆散页面的前提下，补齐 Embed Client、Origin、宿主工具策略、绑定关系和审计能力？
- 管理端如何呈现长期密钥、短期 token、Origin 白名单、Agent 绑定和宿主工具授权，才能兼顾可用性与安全边界？
- 本次实现应优先复用现有页面与 API，还是新增独立工作台？

## 功能复杂度

- 级别：核心功能
- 选择理由：本次涉及嵌入式鉴权治理、宿主工具授权和审计查看，虽然主要是管理后台前端，但会暴露平台级配置能力；当前代码还缺少部分绑定读取 API，属于 API 契约补充。
- 最低调研要求：参考官方文档、成熟 SaaS 管理后台做法和现有仓库实现，记录来源、方案比较与最终决策。

## 参考依据

### 来源 1

- 类型：官方文档
- 名称：Stripe API keys
- 链接：https://docs.stripe.com/keys
- 版本或发布日期：官方在线文档，调研日期为 2026-07-30
- 核心做法：Stripe 将 publishable key 与 secret key 分开；secret key 用于服务端敏感操作，新密钥值只在创建时展示，之后需要通过轮换获得新密钥。
- 对本项目的启发：Embed Client 的 `client_secret` 必须只在创建或轮换成功后短暂展示；列表页只显示 `client_id`、启用状态、Origin、TTL、限额和绑定概况，不显示密钥明文。

### 来源 2

- 类型：官方文档
- 名称：Auth0 Application Settings
- 链接：https://auth0.com/docs/get-started/applications/application-settings
- 版本或发布日期：官方在线文档，调研日期为 2026-07-30
- 核心做法：Auth0 在应用设置中集中维护 Allowed Callback URLs、Allowed Logout URLs、Allowed Web Origins 等嵌入/浏览器相关白名单。
- 对本项目的启发：Origin 白名单应作为 Embed Client 的核心配置字段内嵌在 Client 表单中，不应单独拆一个页面；表单需要明确提示必须填写精确 Origin。

### 来源 3

- 类型：官方文档
- 名称：MDN Web Docs - Origin
- 链接：https://developer.mozilla.org/en-US/docs/Glossary/Origin
- 版本或发布日期：官方在线文档，调研日期为 2026-07-30
- 核心做法：Web Origin 由 scheme、hostname 和 port 共同定义，同源判断不包含路径。
- 对本项目的启发：前端 Origin 输入需要提示 `https://example.com` 这类精确 Origin；后端已有 `normalize_origins` 校验，前端应提前做同等提示和基础校验。

### 来源 4

- 类型：官方文档 / 成熟产品实践
- 名称：LaunchDarkly Projects
- 链接：https://launchdarkly.com/docs/home/account/projects
- 版本或发布日期：官方在线文档，调研日期为 2026-07-30
- 核心做法：LaunchDarkly 使用项目作为顶层隔离单元，在项目内组织环境、SDK key、feature flags 和访问控制。
- 对本项目的启发：后台应围绕平台和 Agent 组织资源关系。平台级资源池负责创建资源，Agent 详情或配置入口负责绑定关系，避免每个关系都做独立页面。

### 来源 5

- 类型：官方文档
- 名称：TanStack Query - Invalidations from Mutations
- 链接：https://github.com/tanstack/query/blob/main/docs/framework/react/guides/invalidations-from-mutations.md
- 版本或发布日期：TanStack Query v5 文档，调研日期为 2026-07-30
- 核心做法：mutation 成功后通过 `queryClient.invalidateQueries` 使相关 query 失效并重新获取服务端状态。
- 对本项目的启发：管理端创建、更新、绑定、解绑和轮换密钥后，应按平台、Agent、Client、Tool 维度刷新缓存，避免显示过期授权状态。

### 来源 6

- 类型：安全实践
- 名称：OWASP Logging Cheat Sheet
- 链接：https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html
- 版本或发布日期：官方在线文档，调研日期为 2026-07-30
- 核心做法：安全相关事件需要保留可调查的上下文，但日志应避免记录敏感凭据和高风险数据。
- 对本项目的启发：审计页应展示调用状态、工具名称、主体、错误和时间；密钥、token、敏感参数仍需依赖后端脱敏，不在前端主动扩大展示面。

## 当前仓库依据

- 已有后台页面：
  - `apps/front/src/features/agents/index.tsx`
  - `apps/front/src/features/knowledge/index.tsx`
  - `apps/front/src/features/skills/index.tsx`
  - `apps/front/src/features/system/mcp-servers.tsx`
- 已有后端能力：
  - `apps/backend/app/modules/embed/router.py` 已提供 Embed Client 创建、列表、更新、轮换密钥、绑定/解绑 Agent、签发 token、消息快照。
  - `apps/backend/app/modules/host_tool/router.py` 已提供宿主工具策略创建、列表、更新、绑定/解绑 Agent、绑定/解绑 Embed Client、审计列表。
- 当前缺口：
  - 前端没有 Embed Client 管理入口。
  - 前端没有宿主工具策略管理入口。
  - 后端缺少读取 Embed Client 当前 Agent 绑定的管理接口。
  - 后端缺少读取宿主工具当前 Agent / Embed Client 绑定的管理接口。
  - 宿主工具策略创建冲突当前抛出 `ValueError`，管理端更适合稳定返回业务冲突错误。

## 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| 方案 A：继续为每种资源新增独立页面 | 实现直观；与现有页面开发方式一致 | 页面数量继续增加，绑定关系分散，用户需要在多个页面来回跳转 | 中等，只适合短期补页面 |
| 方案 B：少页面、Agent 为中心，平台级资源池 + 绑定配置 | 页面较少；资源创建和 Agent 配置边界清楚；符合 Phase 2D 管理目标 | 需要补少量绑定读取 API；需要整理前端组件以避免页面过大 | 高，推荐采用 |
| 方案 C：完整统一 AI 管理工作台重构 | 长期体验最好，可统一平台上下文、审计和 Agent 详情 | 范围大，会牵动现有多个页面和导航，不适合当前只补 2D 管理后台 | 低，本次不采用 |

## 最终决策

- 选择方案：方案 B，少页面、Agent 为中心，平台级资源池 + 绑定配置。
- 选择原因：
  - 用户明确希望页面越少越好。
  - 已有 Agent、知识库、Skill、MCP 页面可以作为基础，不需要重做。
  - Phase 2D 剩余关键缺口集中在 Embed Client、Origin、宿主工具策略和绑定治理。
  - 后端已有大部分管理能力，只需补最小读取接口和前端接入。
- 不选择其他方案的原因：
  - 不选择方案 A：会继续堆页面，无法改善资源绑定关系分散的问题。
  - 不选择方案 C：当前后台仍处早期，不值得先做大范围信息架构重构。
- 对后续 spec、plan 或人工确认的影响：
  - 需要在实现前确认最小 API 契约补充：新增绑定读取接口，修正宿主工具重复创建错误语义。
  - 确认后再进入实现。

## 剩余风险

- 资料时效性：调研来源为 2026-07-30 在线文档；后续产品文档可能更新，但不影响本次“密钥只展示一次、Origin 精确配置、资源池 + 绑定”的基本决策。
- 与本项目上下文的差异：成熟 SaaS 往往已有完整组织/项目/环境模型，本项目当前只有平台与 Agent 两级主要上下文，因此本次不引入环境层。
- 尚未验证的假设：
  - 现有前端全量构建基线问题可能仍会阻塞完整验收。
  - 真实后端数据库和浏览器联调需要在实现后补充验证。
