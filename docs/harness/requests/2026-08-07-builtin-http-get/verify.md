# 验证记录

## 验证环境

- 日期：2026-08-07。
- 目录：`apps/backend`。
- Python：项目 `.venv`，仓库要求 Python 3.12。
- 数据库迁移：使用 Alembic PostgreSQL 离线 SQL 模式验证，未修改本地或远程真实数据库。

## 实际执行记录

### 新功能与相关运行时测试

- 命令：`.venv/bin/pytest tests/builtin_tool tests/asset tests/conversation tests/gateway -q`
- 预期：HTTP GET、资源服务、后台对话和 Embed Gateway 回归通过。
- 实际：`60 passed, 1 skipped`。随后增加模型真实工具循环测试并纳入全量测试。
- 结论：通过。

### 全量测试

- 首次命令：`.venv/bin/pytest -q`
- 实际：收集阶段因仓库既有的 `tests/skill_runner/test_services.py` 与 `tests/user/test_services.py` 同名模块冲突而失败；新增 asset 测试已改为唯一文件名，剩余冲突与本 request 无关。
- 处理：不修改无关测试结构，改用 Pytest 官方 importlib 导入模式。
- 最终命令：`.venv/bin/pytest -q --import-mode=importlib`
- 最终实际：`225 passed, 1 skipped, 1 warning`，耗时 5.94 秒。
- 警告：Starlette `TestClient` 提示未来应从 `httpx` 迁移到 `httpx2`，属于既有依赖警告。
- 结论：通过。

### 静态检查

- 命令：`.venv/bin/ruff check .`
- 实际：`All checks passed!`
- 结论：通过。

### 格式检查

- 命令：`.venv/bin/black --check app/modules/builtin_tool app/modules/asset tests/builtin_tool tests/asset migrations/versions/20260807_0019_builtin_http_get.py`
- 实际：18 个本次新增文件无需重新格式化。
- 说明：项目级 `.venv/bin/black --check app ...` 会报告约 40 个既有文件未采用当前 Black 版本格式；本次没有批量格式化无关文件。早期对 6 个已修改运行时文件执行 Black 后产生等价排版变化，因安全策略拒绝丢弃未提交内容而保留，相关全量测试与 Ruff 均通过。
- 结论：本次新增文件通过。

### OpenAPI 契约

- 命令：`.venv/bin/python -c "from app import create_app; ..."`
- 实际：`OpenAPI routes verified`。
- 核对路径：`/api/v1/platforms/{platform_id}/builtin-tools`、Agent 工具绑定路径和 `/api/v1/assets/{asset_id}` 均注册；定向测试确认 Bearer 安全声明。
- 结论：通过。

### Alembic 迁移

- 命令：`.venv/bin/alembic history`
- 实际：`20260807_0019` 为唯一 head，down revision 为 `20260806_0018`。
- 命令：`.venv/bin/alembic upgrade 20260806_0018:20260807_0019 --sql`
- 实际：成功生成 PostgreSQL DDL、字段中文 `COMMENT`、索引、外键、唯一约束和唯一会话主体检查约束。
- 结论：离线迁移验证通过；未对真实数据库执行 `upgrade head`。

### 文档与差异

- 命令：`python3 -m json.tool docs/harness/requests/2026-08-07-builtin-http-get/meta.json`
- 实际：JSON 有效。
- 命令：`git diff --check`
- 实际：通过，无空白错误。

## 覆盖结果

- URL 协议、凭证、DNS 多地址、私网地址和逐跳重定向校验已覆盖。
- JSON 解析、文本返回、图片与普通文件流式落盘、未知类型降级、无界响应大小限制和失败清理已覆盖。
- ORM 中文备注、唯一主体约束、文件名安全化、存储路径逃逸和数据库失败补偿已覆盖。
- 内置工具在模型工具循环中的本地分发、`builtin_tool` step 类型和结构化结果回填已覆盖。
- 后台非流式/SSE 与 Embed Gateway 相关回归集合及全量后端集合已通过。

## 未完成与例外

- 未访问真实公网 URL；HTTP 行为通过 HTTPX MockTransport 验证，避免测试依赖外部网络。
- 未在真实 PostgreSQL 执行迁移，部署前仍需备份并执行 `alembic upgrade head`。
- 未验证生产网络出口防火墙。应用层 SSRF 校验存在 DNS 校验与真实连接之间的时间窗口，生产必须阻止私网、链路本地和云元数据网段。
- 资源恶意文件扫描和生命周期清理属于 spec 明确非目标。

## 2026-08-07 管理端与 SDK 增量验证

### 管理端生产构建

- 命令：`pnpm build`（目录：`apps/front`）。
- 首次实际：失败，暴露同一智能体页面既有的 `z.coerce.number()` 与 React Hook Form 泛型不匹配。
- 处理：按仓库知识库表单的既有模式区分 Zod 输入/输出类型，仅修正类型声明和数值输入值类型，不改变表单运行行为。
- 最终实际：TypeScript 编译和 Vite 生产构建通过，转换 4067 个模块。
- 例外：Vite 报告既有的 `react-swc esbuild` 弃用警告与大 chunk 警告，不影响构建结果。
- 结论：通过。

### 管理端静态检查

- 命令：`pnpm exec eslint src/api/builtin-tools.ts src/features/agents/index.tsx src/features/agents/builtin-tools-dialog.tsx`（目录：`apps/front`）。
- 实际：退出码 0，无错误或警告。
- 全量命令：`pnpm lint`。
- 全量实际：5 个既有错误、4 个既有警告；错误位于 `sign-out-dialog.tsx`、`lib/auth.ts`、`lib/http.ts`，本次文件未出现问题。
- 结论：本次变更通过；全量 ESLint 仍受无关既有问题阻塞。

### SDK 类型、测试与产物

- 命令：`pnpm type-check`（目录：`apps/ai-sdk`）。
- 实际：`vue-tsc --noEmit` 通过。
- 命令：`pnpm test -- --run`。
- 实际：8 个测试文件、34 个测试全部通过；连接失败用例按预期输出模拟错误日志。
- 命令：`pnpm build`。
- 实际：ESM、UMD、类型声明和 CSS 构建通过。
- 命令：`pnpm verify-package`。
- 实际：包入口 `xxai-agent.es.js`、`xxai-agent.umd.cjs`、`index.d.ts`、`style.css` 全部有效。
- 结论：通过。

### 本地页面检查

- 地址：`http://localhost:8080/ai/bots`，现有前端与后端服务均在运行。
- 实际：未登录会话按预期跳转到 `/sign-in?redirect=%2Fai%2Fbots`；浏览器控制台无 warning/error。
- 例外：当前没有可用测试账号，未执行真实登录后的弹窗点击和启停写操作，避免擅自创建账号或修改现有 Agent 绑定。

### 差异检查

- 命令：`git diff --check`。
- 实际：通过，无空白错误。
