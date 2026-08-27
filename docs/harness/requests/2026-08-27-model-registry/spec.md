# 平台级模型注册表与 Agent 能力路由规格

## 目标

将辅助模型从全局 `.env` 配置改为后台可维护：平台管理员在模型注册表登记模型（名称、服务地址、密钥、能力、类型），Agent 绑定所需角色模型；主对话模型仍由发布版本 `agent_versions` 决定。内置工具（生图、读图）和附件 embedding 改为按 Agent 绑定解析模型，未绑定时回退全局配置，保证既有行为不回归。

## 范围

### 包含

- 新增 `platform_models` 平台模型注册表与 `agent_model_bindings` Agent 绑定表（含中文 comment）。
- 平台管理员对注册表条目的增删改查与启停。
- Agent 绑定/解绑辅助模型，每个能力角色（`image_generate`、`image_read`、`embedding`）至多绑定一个模型。
- 内置工具 `image_generate`、`image_read` 改为按 Agent 绑定解析模型，未绑定回退全局配置。
- 附件 embedding 改为按 Agent 绑定解析模型，未绑定回退全局配置。
- 工具执行上下文（`BuiltinToolContext`）携带 `platform_id`/`agent_id`，新增模型解析服务在工具处理函数内调用。
- 前端管理界面：新增「模型管理」页面（注册表 CRUD、类型过滤、启停），智能体详情页新增「模型绑定」Tab（按角色绑定/解绑）。
- 基本工具 / 业务工具分层框架：新增 `app/modules/tools`，基本工具为能力原子（输入即数据、单一职责），业务工具为 LLM 暴露层（来源解析、鉴权、持久化、模型绑定）；本期先落地框架与 `http_get` 示例，生产接线在后续变更完成。
- 相关单元测试与 Harness 六件套文档。

### 不包含

- 修改 `agent_versions` 主对话模型语义，发布版本模型保持现状。
- 模型负载均衡、失败回退、自动切换多个同能力模型（本期每角色单模型）。
- 模型计费、用量统计。

## 数据模型

### `platform_models`（平台模型注册表）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int PK | 主键 |
| `platform_id` | FK platforms.id | 所属平台，级联删除 |
| `name` | String(120) | 模型显示名称（后台维护用） |
| `model_type` | String(40) | 模型类型：`chat`、`image_generate`、`image_read`、`embedding` |
| `model_name` | String(200) | 上游模型名（如 `gpt-image-1`、`text-embedding-3-small`） |
| `base_url` | String(500) | 模型服务地址，可为空（用默认官方地址） |
| `api_key_encrypted` | Text | 加密后的 API Key，复用 `AGENT_MASTER_KEY` 加密 |
| `capabilities` | JSON | 能力矩阵：`image`、`native_file`、`text_retrieval`；生图模型额外 `output: image` |
| `options` | JSON | 模型额外参数（超时、尺寸默认值等） |
| `is_active` | Boolean | 是否启用 |
| 时间字段 | - | 复用 `BaseModel`/`TimeModel` 约定 |

约束：`UniqueConstraint(platform_id, model_type, model_name)`，同一平台同一类型同一模型名唯一。

### `agent_model_bindings`（Agent 模型绑定）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int PK | 主键 |
| `agent_id` | FK agents.id | 所属 Agent，级联删除 |
| `model_id` | FK platform_models.id | 绑定的注册表模型，级联删除 |
| `role` | String(40) | 能力角色：`image_generate`、`image_read`、`embedding`（绑定模型 `model_type` 必须与 `role` 一致） |
| `created_at` | DateTime | 绑定时间 |

约束：`UniqueConstraint(agent_id, role)`，每个 Agent 每个角色至多一个绑定。

## API 契约

沿用 `/api/v1/platforms/{platform_id}` 平台管理前缀，全部接口要求平台管理员权限（复用 `_require_platform_admin`）。

### 模型注册表 CRUD

- `GET /platforms/{platform_id}/models`：分页列出模型，支持按 `model_type` 过滤。
- `POST /platforms/{platform_id}/models`：创建模型条目；`api_key` 入参仅写不读，响应返回 `has_api_key`。
- `PATCH /platforms/{platform_id}/models/{model_id}`：更新名称、地址、密钥、能力、启停。
- `DELETE /platforms/{platform_id}/models/{model_id}`：删除；存在 Agent 绑定时返回 `model_in_use` 错误（需先解绑）。

### Agent 模型绑定

- `GET /platforms/{platform_id}/agents/{agent_id}/models`：列出该 Agent 已绑定的模型（含角色与模型摘要）。
- `PUT /platforms/{platform_id}/agents/{agent_id}/models`：整体更新绑定列表，入参为角色列表 `[{role, model_id}]`；同一角色重复绑定报错，角色与模型类型不匹配报错。
- `DELETE /platforms/{platform_id}/agents/{agent_id}/models/{role}`：解绑单个角色。

### 模型解析服务（内部，不暴露路由）

`resolve_agent_model(session, platform_id, agent_id, role) -> ResolvedModel | None`：

1. 查询 `agent_model_bindings` 找到启用且类型匹配的注册表模型；
2. 命中则返回 `model_name`/`base_url`/解密后的 `api_key`/`capabilities`/`options`；
3. 未命中返回 `None`，调用方回退全局 `.env` 配置（现有行为）。

## 能力路由语义

- `image_generate` 工具：解析角色 `image_generate` 模型；回退 `OPENAI_IMAGE_MODEL`/`OPENAI_API_KEY`。
- `image_read` 工具：解析角色 `image_read` 模型；回退 `READ_IMAGE_MODEL`/`READ_IMAGE_API_KEY`。
- 附件 embedding：解析角色 `embedding` 模型；回退 `ATTACHMENT_EMBEDDING_*`。
- 绑定模型的 `capabilities` 不匹配角色时视为配置错误，拒绝绑定或运行时回退全局配置并记录告警。
- 主对话模型不参与注册表路由，继续使用发布版本 `agent_versions` 的模型配置。

## 风险

- 兼容风险：工具与 embedding 的解析路径改变，需保证未绑定 Agent 行为与现有一致；通过回退逻辑与回归测试覆盖。
- 数据风险：密钥加密复用现有 Fernet 机制；迁移需为存量数据保留 `.env` 兜底，不强制迁移既有配置。
- 并发风险：绑定更新采用整体替换（PUT），事务内完成，避免半更新状态。

## 停点判断

- 是否涉及架构边界变化：是（新增平台级模型注册表模块与解析链路）。
- 是否涉及数据模型变化：是（新增两张表）。
- 是否涉及 API 契约变化：是（新增两组平台管理 API）。
- 是否涉及鉴权或权限行为变化：否（沿用平台管理员校验）。
- 结论：**进入实现前需人工确认**数据模型与 API 契约。

## 验收标准

- 迁移后可创建/更新/启停/删除注册表模型；删除被绑定模型返回稳定错误码。
- Agent 可按角色绑定/解绑模型，角色重复或类型不匹配被拒绝。
- 绑定 `image_generate` 后生图工具使用注册表模型；未绑定时仍走 `.env` 配置。
- 绑定 `image_read` 后读图描述使用注册表模型；未绑定时回退 `READ_IMAGE_*`。
- 绑定 `embedding` 后附件向量化使用注册表模型；未绑定时回退 `ATTACHMENT_EMBEDDING_*`。
- API Key 落库前加密，任何响应不返回明文密钥。
- 后端测试全量通过；Harness 六件套完成 verify 与 acceptance。
- 前端「模型管理」页面可完成注册表创建、编辑、启停、删除，删除被绑定模型给出明确提示。
- 前端智能体「模型绑定」Tab 可按三个能力角色绑定/解绑模型，未绑定提示回退全局配置。
- 前端构建（`tsc -b && vite build`）与 lint 通过，侧边栏入口可见。
- 基本/业务工具分层框架可导入可用：装饰器注册、依赖校验、统一入口兜底；生产工具行为不变。

## 变更记录

### 2026-08-27 初始版本

- 变更原因：首次创建 request，落实方案 B（平台级模型注册表）。
- 变更内容：数据模型、API 契约、能力路由语义与兜底策略。
- 影响章节：全部。
- 是否触发人工确认：是，数据模型与 API 契约变化，等待确认后进入实现。

### 2026-08-27 第 2 次变更

- 变更原因：验收后补充前端管理界面（原「不包含」中预留的后续增量）。
- 变更内容：新增「模型管理」页（注册表 CRUD、类型过滤、启停、删除提示）与智能体「模型绑定」Tab；全部复用既有后端 API，无后端改动。
- 影响章节：范围、验收标准。
- 是否触发人工确认：否（仅前端页面，未改变数据模型、API 契约、鉴权与架构边界；方案已与用户确认）。
- 关联计划更新：已同步更新 `plan.md`（新增 Task 6）。

### 2026-08-27 第 3 次变更（fix）

- 变更原因：`image_read` 工具执行成功但 `description` 为空（asset `67a1a87b...`）。
- 变更内容：根因为绑定模型 `base_url` 缺少 `/v1`（`https://api.quya.org`），网关根路径返回 HTML（200 `text/html`），openai SDK 解析为字符串，langchain 调用 `model_dump()` 抛 `AttributeError` 后被子描述逻辑吞掉返回 `None`。修复：数据层补 `/v1`；`apps/backend/.env` 增加 `READ_IMAGE_TIMEOUT_SECONDS=120`（实测响应约 40s、60s 超时过一次）；`image_read.py` 对非 JSON 上游响应输出可操作告警；新增回归测试与前端 `/v1` 占位提示。
- 影响章节：能力路由语义（补充诊断与超时说明）、验收标准。
- 是否触发人工确认：否（未改变数据模型、API 契约、鉴权与架构边界）。
- 关联计划更新：已同步更新 `plan.md`（新增 Task 7）。

### 2026-08-27 第 4 次变更（架构）

- 变更原因：用户提出内置工具按「基本工具 / 业务工具」分层，避免 `image_read` 这类工具混入来源解析、持久化与模型调用等多重职责后越来越乱。
- 变更内容：
  - 新增 `app/modules/tools/basic`：能力原子层，输入即数据（url/base64/file/bytes/prompt），不感知平台/Agent/会话/用户，不落库、不鉴权、不碰模型注册表；坚持基本工具单一职责（一个文件 = 一个能力）。
  - 新增 `app/modules/tools/business`：LLM 暴露层，持有 `BusinessToolContext`，负责来源解析、鉴权、持久化、Agent 模型绑定解析、结果包装。
  - 注册方式：装饰器 `@basic_tool` / `@business_tool`，定义与 handler 同页、导入即注册；公共注册页只做 import 收集与 `list/get`；业务工具用 `depends_on` 声明依赖，启动时校验依赖完整性。
  - 统一入口 `invoke_business_tool` 兜底错误码，不向 LLM 泄漏未捕获异常。
  - 本期完成 4 个内置工具的完整搬移与接线：`http_get`/`http_post`/`image_generate`/`image_read` 迁入 basic（能力原子）与 business（LLM 暴露层）双文件实现；`builtin_tool/services.py` 收敛为薄委托层（保留旧 `invoke_builtin_tool` 签名），经 `BusinessToolContext` 映射后委托业务注册表；对外 LLM 契约（工具名、入参、返回结构与稳定错误码）不变。
  - 基本工具单一职责落地：`http.get`、`http.post`、`image_gen.generate`、`vision.describe` 四个能力原子各占一个文件；业务层 `assets.py` 为唯一落库点。
  - 错误码收敛：`BusinessToolError` 统一携带 `code`（+ 可选 `status_code` 透传），未捕获异常统一兜底为 `tool_failed`。
- 影响章节：范围、能力路由语义、验收标准。
- 是否触发人工确认：是（架构边界变化），用户已确认装饰器注册方式与基本工具单一职责原则。
- 关联计划更新：已同步更新 `plan.md`（新增 Task 8）。
