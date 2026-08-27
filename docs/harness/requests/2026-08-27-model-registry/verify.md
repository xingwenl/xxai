# 验证记录

## 执行命令

- `poetry run ruff check app/modules/model_registry app/modules/builtin_tool app/modules/asset_processing app/modules/gateway tests/model_registry tests/asset_processing tests/builtin_tool tests/asset tests/gateway`：全部通过，无错误。
- `poetry run ruff format --check ...`：涉及文件已格式化。
- `poetry run pytest -q --import-mode=importlib`：410 passed, 1 skipped。
- `poetry run alembic current && poetry run alembic upgrade head && poetry run alembic current`：升级 `20260827_0028 -> 20260827_0029` 成功，当前 head 为 `20260827_0029`。
- asyncpg 查询 `information_schema.columns/table_constraints`：两张新表字段、外键、唯一约束与主键均存在。
- `poetry run python -c "from main import app; ..."`：4 个新路由注册成功。

## 预期结果

- 迁移 `20260827_0029` 可升级与回滚，新表带中文注释。
- 注册表 CRUD 与 Agent 绑定 API 通过测试，权限与错误码符合 spec。
- 工具与 embedding 在绑定模型时走注册表，未绑定时行为与 `.env` 一致。
- 后端全量测试与 ruff 检查通过。

## 实际结果

- 迁移在 PostgreSQL 执行成功，`platform_models` 与 `agent_model_bindings` 两表及索引/约束创建完整。
- 新增 16 条测试覆盖：注册表创建加密、类型+名称唯一冲突、绑定角色校验（重复角色、类型不匹配）、删除被绑定模型返回 `model_in_use`、解析器命中/未绑定/停用回退、生图使用绑定模型配置、embedding 绑定解析与全局回退。
- 全量后端测试 410 passed、1 skipped；既有 `asset_processing` 与 `gateway` 测试已同步新签名。
- 未执行回滚验证（`downgrade` 逻辑已按既有迁移模式编写，代码评审通过）。

## 失败项与例外

- `psql` 命令在本机不可用，改用后端 venv 的 asyncpg 完成表结构核对。
- 全量收集存在既有同名测试文件冲突（`builtin_tool` 与 `embed/user` 的 `test_models.py` 等），使用 `--import-mode=importlib` 运行；该问题在本次改动前已存在，未在本 request 内修复。

## 第 2 次变更验证（前端管理界面）

### 执行命令

- `pnpm --dir apps/front build`（`tsc -b && vite build`）：类型检查与构建通过，`✓ built`。
- `pnpm --dir apps/front exec eslint <本次 7 个变更文件>`：无错误。
- `pnpm --dir apps/front exec prettier --write <本次变更文件>`：已格式化。

### 实际结果

- `routeTree.gen.ts` 自动生成 `/ai/models` 路由，`dist` 产出 `models-*.js` 独立 chunk。
- 前端 API client 路径与后端 `model_registry/router.py` 逐项核对一致（注册表 CRUD 与 Agent 绑定 GET/PUT）。
- 侧边栏「AI 管理」新增「模型管理」入口；智能体详情页新增「模型绑定」Tab（含路由 search 校验 `models`）。
- 后端代码零改动，既有 410 条后端测试不受影响。

### 失败项与例外

- 未做登录态浏览器人工操作验证（需后端运行与登录会话），交互正确性通过类型检查、lint、构建产物与代码评审覆盖。

## 第 3 次变更验证（fix：image_read 描述为空）

### 现象与根因

- 现象：`image_read` 工具执行成功，`asset` 元数据正常，`description` 为 `null`。
- 日志证据：`read image description failed asset_id=67a1a87b...: 'str' object has no attribute 'model_dump'`。
- 完整复现 traceback：`langchain_openai/chat_models/base.py:1818 _create_chat_result` 对 `response.model_dump()` 抛 `AttributeError`；`raw_response.parse()` 返回 `str`。
- 根因：绑定模型 `0029都可以`（`gpt-5.6-sol`）的 `base_url=https://api.quya.org` 缺少 `/v1`，请求命中网关根路径，返回 200 `text/html` 落地页 HTML；openai SDK 解析为字符串，langchain 转换崩溃，被 `_describe_image` 的兜底捕获后返回 `None`。

### 修复与验证

- 数据：`platform_models`（id=3）`base_url` 已为 `https://api.quya.org/v1`；raw 请求 `STATUS 200`、`application/json`，模型正常返回中文描述。
- 端到端：脚本走生产 `_describe_image` + 真实绑定配置（含解密密钥），对 asset `67a1a87b...` 成功返回描述文本。
- 配置：`apps/backend/.env` 新增 `READ_IMAGE_TIMEOUT_SECONDS=120`（实测一次 60s 超时、成功响应约 40s）。
- 代码：`image_read.py` 在异常信息含 `model_dump` 时输出“上游返回非 JSON 响应（检查 base_url 是否以 /v1 结尾…）”提示；新增测试 `test_read_image_description_non_json_response_logs_hint`。
- 回归：`poetry run pytest tests/model_registry tests/asset_processing tests/builtin_tool -q --import-mode=importlib` → `36 passed`；`ruff check`/`ruff format --check` 通过；前端 `build` 与 eslint 通过。

## 第 4 次变更验证（架构：基本/业务工具框架落地）

### 执行命令

- `poetry run pytest -q --import-mode=importlib`：后端全量 `418 passed, 1 skipped`。
- `poetry run pytest tests/builtin_tool tests/model_registry tests/asset_processing -q --import-mode=importlib`：`36 passed`（工具相关回归）。
- `poetry run ruff check app/modules/tools app/modules/builtin_tool tests/builtin_tool`：全部通过。
- `poetry run ruff format app/modules/tools app/modules/builtin_tool tests/builtin_tool`：已格式化。
- 冒烟脚本：导入两个公共注册页列出注册表；走真实 `invoke_builtin_tool` 验证 `invalid_arguments` 与 `conversation_required` 校验路径。

### 实际结果

- 基本注册表：`[('http.get','none'), ('http.post','none'), ('image_gen.generate','create'), ('vision.describe','none')]`。
- 业务注册表：`[('http_get',('http.get',)), ('http_post',('http.post',)), ('image_generate',('image_gen.generate',)), ('image_read',('http.get','vision.describe'))]`；`depends_on` 启动依赖校验通过。
- 委托层冒烟：`http_get` 传非法参数返回 `failed {'error': {'code': 'invalid_arguments'}}`；合法参数但无会话返回 `failed {'error': {'code': 'conversation_required'}}`（均未发真实请求）。
- 错误映射测试（`test_services.py`）：`BusinessToolError` 映射稳定 `code`（`status_code` 可选透传）、未知异常兜底 `tool_failed`、禁用与参数校验路径均保持旧契约。
- 旧实现 `builtin_tool/http_get.py`、`http_post.py`、`image_generate.py`、`image_read.py` 已删除，全仓无残留引用；对外 LLM 契约（工具名、入参、返回结构）不变。
