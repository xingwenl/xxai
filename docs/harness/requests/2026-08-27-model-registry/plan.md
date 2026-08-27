# 平台级模型注册表与 Agent 能力路由实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增平台级模型注册表与 Agent 绑定，内置工具与 embedding 按 Agent 能力路由解析模型，未绑定回退全局配置。

**Architecture:** 新增 `model_registry` 模块承载表模型、Schema、仓储、服务与路由；`BuiltinToolContext` 已携带 `platform_id`/`agent_id`，在 `_handle_image_generate`/`_handle_image_read` 内解析注册表模型并透传；`asset_processing/runtime.py` 的 embedding 构建按会话归属 Agent 解析模型。全部密钥加密复用 `agent/services.py` 的 Fernet 工具。

**Tech Stack:** FastAPI、SQLAlchemy async、Alembic、Pytest、OpenAI SDK、LlamaIndex。

---

### Task 1: 数据模型与迁移

**Files:**
- Create: `apps/backend/app/modules/model_registry/models.py`
- Modify: `apps/backend/migrations/versions/20260827_0029_platform_model_registry.py`
- Test: `apps/backend/tests/model_registry/test_models.py`

- [ ] 定义 `PlatformModel` 与 `AgentModelBinding`，字段全部带中文 `comment`，唯一约束按 spec。
- [ ] 编写迁移 `20260827_0029`，`upgrade` 创建两张表与索引，`downgrade` 可回滚。
- [ ] 迁移冒烟：`alembic upgrade head` 后 `alembic current` 为最新版本。

### Task 2: 注册表 CRUD 与绑定 API

**Files:**
- Create: `apps/backend/app/modules/model_registry/schemas.py`
- Create: `apps/backend/app/modules/model_registry/repositories.py`
- Create: `apps/backend/app/modules/model_registry/services.py`
- Create: `apps/backend/app/modules/model_registry/router.py`
- Modify: `apps/backend/app/main.py`（挂载路由）
- Test: `apps/backend/tests/model_registry/test_api.py`

- [ ] 平台模型 CRUD：创建、分页列表（按类型过滤）、更新、删除（被绑定返回 `model_in_use`）。
- [ ] Agent 绑定 GET/PUT/DELETE：角色唯一、类型匹配校验，整体替换在事务内完成。
- [ ] API Key 加密落库、响应只返回 `has_api_key`。
- [ ] 所有接口复用 `_require_platform_admin` 权限校验。

### Task 3: 模型解析服务

**Files:**
- Create: `apps/backend/app/modules/model_registry/resolver.py`
- Test: `apps/backend/tests/model_registry/test_resolver.py`

- [ ] `resolve_agent_model(session, platform_id, agent_id, role)` 返回启用且类型匹配的绑定模型。
- [ ] 未命中返回 `None`；模型停用或能力不匹配时记录告警并返回 `None`。
- [ ] 密钥解密失败返回 `None` 并记录错误，不抛出明文。

### Task 4: 工具与 embedding 接入

**Files:**
- Modify: `apps/backend/app/modules/builtin_tool/services.py`
- Modify: `apps/backend/app/modules/builtin_tool/image_generate.py`
- Modify: `apps/backend/app/modules/builtin_tool/image_read.py`
- Modify: `apps/backend/app/modules/asset_processing/runtime.py`
- Test: `apps/backend/tests/builtin_tool/test_image_tools.py`
- Test: `apps/backend/tests/asset_processing/test_embedding_resolution.py`

- [ ] `image_generate`/`image_read` 处理函数先解析注册表模型，未命中时保持现有 `.env` 路径。
- [ ] embedding 构建按会话 Agent 解析 `embedding` 角色模型，未命中回退全局配置。
- [ ] 解析器依赖会话上下文获取 `agent_id`，不改变消息与资源契约。

### Task 5: 验证与文档

**Files:**
- Modify: `docs/harness/requests/2026-08-27-model-registry/verify.md`
- Modify: `docs/harness/requests/2026-08-27-model-registry/acceptance.md`
- Modify: `docs/harness/requests/2026-08-27-model-registry/meta.json`

- [ ] 运行 `poetry run pytest` 全量后端测试，修复失败项。
- [ ] 运行 `poetry run ruff check` 与 `poetry run ruff format --check`。
- [ ] 补 verify.md 实际输出证据，验收通过后更新 acceptance.md 与 meta.json。

### Task 6: 前端管理界面（第 2 次变更增量）

**Files:**
- Create: `apps/front/src/api/model-registry.ts`
- Create: `apps/front/src/features/model-registry/index.tsx`
- Create: `apps/front/src/routes/_authenticated/ai/models.tsx`
- Modify: `apps/front/src/components/layout/data/sidebar-data.ts`
- Create: `apps/front/src/features/agents/agent-model-bindings-tab.tsx`
- Modify: `apps/front/src/features/agents/agent-detail-page.tsx`

- [x] API client 封装注册表 CRUD 与 Agent 绑定 4 组接口，类型与后端 schema 对齐。
- [x] 「模型管理」页：平台选择器、类型过滤、分页表格、新建/编辑对话框（API Key 仅写不读）、启停开关、删除确认（`model_in_use` 中文提示）。
- [x] 智能体详情页新增「模型绑定」Tab：三个能力角色下拉选择（仅启用且类型匹配的模型），保存走 `PUT` 整体替换，未绑定提示回退全局配置。
- [x] 侧边栏「AI 管理」新增「模型管理」入口。
- [x] `pnpm --dir apps/front build` 与 lint 通过，routeTree 自动生成。

### Task 7: 修复 image_read 描述为空（第 3 次变更，bugfix）

**Files:**
- Modify: `apps/backend/app/modules/builtin_tool/image_read.py`
- Modify: `apps/backend/tests/builtin_tool/test_image_tools.py`
- Modify: `apps/backend/.env`（本地配置，不入库）
- Modify: `apps/front/src/features/model-registry/index.tsx`

- [x] 定位根因：绑定模型 `base_url` 缺 `/v1`，网关根路径返回 HTML，openai SDK 解析为 `str` 导致 langchain `model_dump()` 崩溃，描述静默为 `None`。
- [x] 数据修复：`platform_models`（id=3）`base_url` 补 `/v1`。
- [x] 配置加固：`READ_IMAGE_TIMEOUT_SECONDS=120`。
- [x] 代码加固：非 JSON 上游响应输出可操作告警；新增回归测试。
- [x] 端到端验证：生产 `_describe_image` 路径对真实 asset 返回描述；相关回归 36 passed。

### Task 8: 基本/业务工具分层框架落地（第 4 次变更，架构）

**Files:**
- Create: `apps/backend/app/modules/tools/__init__.py`
- Create: `apps/backend/app/modules/tools/invoke.py`
- Create: `apps/backend/app/modules/tools/basic/__init__.py`
- Create: `apps/backend/app/modules/tools/basic/framework.py`
- Create: `apps/backend/app/modules/tools/basic/http_get.py`
- Create: `apps/backend/app/modules/tools/basic/registry.py`
- Create: `apps/backend/app/modules/tools/business/__init__.py`
- Create: `apps/backend/app/modules/tools/business/framework.py`
- Create: `apps/backend/app/modules/tools/business/http_get.py`
- Create: `apps/backend/app/modules/tools/business/registry.py`

- [x] 基本工具框架：`@basic_tool` 装饰器、注册表、稳定错误码、单一职责约束（一个文件一个能力）。
- [x] 业务工具框架：`@business_tool`、`BusinessToolContext`、`depends_on` 启动依赖校验。
- [x] 4 个内置工具迁入 basic/business（定义 + handler 同页）：`http.get`、`http.post`、`image_gen.generate`、`vision.describe`。
- [x] 公共注册页 import 收集 + `list/get`；统一入口兜底错误码。
- [x] 生产接线：`builtin_tool/services.py` 收敛为薄委托层（保留旧签名），经 `BusinessToolContext` 映射委托业务注册表；`BusinessToolError` 映射稳定错误码，未捕获异常兜底 `tool_failed`。
- [x] 测试更新：`tests/builtin_tool/test_http_get.py`/`test_http_post.py` 改测基本工具，`test_image_tools.py` 改测业务工具，新增 `test_services.py` 锁定委托层错误映射。

## 测试步骤

- `poetry run pytest apps/backend/tests/model_registry apps/backend/tests/builtin_tool apps/backend/tests/asset_processing -q`：新增与回归用例通过。
- `poetry run pytest`：后端全量通过。
- `poetry run ruff check apps/backend/app apps/backend/tests`：无错误。
- `alembic upgrade head && alembic current`：迁移可执行且为最新。
- `pnpm --dir apps/front build`：前端类型检查与构建通过。
- `pnpm --dir apps/front lint`：前端 lint 通过（仅本次变更文件）。

## 回滚说明

- 代码：还原 `model_registry` 模块与三处解析调用点即可。
- 数据：`alembic downgrade -1` 删除两张新表；`.env` 兜底保证未绑定 Agent 行为不依赖新表。
- 密钥：加密字段依赖 `AGENT_MASTER_KEY`，回滚前确保该配置存在，否则无法解密既有条目。

## 人工确认点

- 数据模型：`platform_models` 与 `agent_model_bindings` 的表设计、字段与唯一约束。
- API 契约：注册表 CRUD 与 Agent 绑定接口路径、请求/响应语义、删除被绑定模型的错误策略。
- 路由语义：按能力角色单模型绑定，未绑定回退全局配置；主对话模型不走注册表。
- 以上确认通过后才进入 Task 1 实现。
