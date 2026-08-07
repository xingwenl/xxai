# 实施计划

## 变更文件

- 新增 `app/modules/builtin_tool/`：代码注册表、绑定模型、Schema、仓储、服务、路由和运行时执行器。
- 新增 `app/modules/asset/`：会话资源模型、Schema、仓储、存储服务和鉴权下载路由。
- 修改 `app/modules/conversation/` 与 `app/modules/gateway/`：加载内置工具、传递会话主体和统一分发调用。
- 修改 `app/core/config.py`：增加 HTTP GET 总预算、文本上限和文件上限配置。
- 修改 `app/__init__.py`：注册工具管理与资源下载路由。
- 新增 Alembic `20260807_0019` 迁移：创建 Agent 内置工具绑定和会话资源表，所有字段添加中文备注。
- 新增 `tests/builtin_tool/`、`tests/asset/` 并补充 conversation/gateway 回归测试。
- 新增 `apps/front/src/api/builtin-tools.ts`，封装内置工具目录、Agent 绑定查询和启停请求。
- 修改 `apps/front/src/features/agents/index.tsx` 并新增 `builtin-tools-dialog.tsx`，增加内置工具管理入口和弹窗交互。
- 修改 `apps/ai-sdk/src/core/types.ts`、Agent Loop 展示逻辑及测试，将 `builtin_tool` 正式归类为工具步骤。
- 完成当前 request 的 `verify.md`、`acceptance.md` 和 `meta.json`。

## 实施步骤

1. 定义绑定与资源模型、数据库约束和迁移，先通过 SQLite 模型测试与 Alembic 静态检查。
2. 定义 `http_get` 固定工具 Schema、代码注册表和 Agent 绑定管理仓储/API，验证跨平台与停用行为。
3. 实现安全 URL 校验、DNS 全地址检查、逐跳重定向、30 秒总预算、流式大小限制和稳定错误映射。
4. 实现二进制临时文件、原子落盘、数据库补偿删除、资源归属与鉴权下载响应。
5. 将 `builtin_tools` 接入 RuntimeContext、后台 JSON/SSE 与 Embed Gateway，共用同一执行器并保持现有工具事件。
6. 增加定向测试，修复类型、格式、迁移和回归问题。
7. 执行后端定向测试、全量测试、Ruff、Black check 与 Alembic history，记录真实证据。
8. 对照规格逐项完成验收，更新 request 状态。
9. 在智能体管理列表增加工具入口，使用独立查询缓存加载 Agent 工具状态，并实现逐项启停、重试、空状态和错误反馈。
10. 补齐 SDK `builtin_tool` 类型与工具步骤展示映射，增加摘要和事件合并测试。
11. 执行管理端类型检查/构建、SDK 单元测试和差异检查，增量更新验证与验收记录。

## 测试步骤

- `poetry run pytest tests/builtin_tool tests/asset -q`
- `poetry run pytest tests/conversation tests/gateway -q`
- `poetry run pytest -q`
- `poetry run ruff check .`
- `poetry run black --check .`
- `poetry run alembic history`
- `pnpm --dir apps/front build`
- `pnpm --dir apps/ai-sdk test -- --run`

测试使用受控 HTTPX transport 或本地 ASGI/模拟流，不依赖公网。SSRF 测试覆盖 URL 语法、IPv4/IPv6、DNS 多地址和重定向；资源测试覆盖跨主体、超限和临时文件补偿。

## 回滚方案

- 代码回滚时先停用所有 `http_get` 绑定，再回滚应用版本。
- 数据库迁移 downgrade 删除资源与绑定表前，先备份或清理 `assets/` 存储目录；物理文件不由 Alembic 自动删除。
- 若运行时集成异常，可从 RuntimeContext 停止装载 `builtin_tools`，不影响 MCP、Skill 和 Host Tool 数据。

## 人工确认

- 用户于 2026-08-07 审阅并批准 `spec.md`，同意架构、数据模型、API 与权限变化，授权进入实施。
- 实现不得扩展到自定义认证、非 GET 请求、搜索、网页正文抽取或匿名资源访问。
