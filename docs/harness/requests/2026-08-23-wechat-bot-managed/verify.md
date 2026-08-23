# 验证记录：后台可管理的微信助手（MVP2）

## 验证范围

- 自动验证：绑定仓库/服务/管理路由/chat 客户端/认证扩展单元测试、相关模块回归、
  静态检查、迁移链、compose 解析。
- 人工联调（未执行，需真实微信账号与后台数据）：扫码绑定、微信对话经 chat 接口回复、
  后台会话可见、解绑停实例。

## 执行命令与结果

| 命令 | 预期 | 实际（2026-08-23） |
|---|---|---|
| `poetry run pytest tests/wechat_bot -q` | 新增用例全绿 | 14 passed |
| `poetry run pytest tests/agent tests/conversation tests/embed tests/platform tests/user tests/auth -q` | 无回归 | 117 passed |
| `poetry run ruff check app/modules/wechat_bot app/modules/agent/repositories.py app/core/security.py app/core/config.py app/modules/conversation/router.py tests/wechat_bot` | 无告警 | All checks passed |
| `PYTHONPYCACHEPREFIX=/tmp/pyc-cache poetry run python -m compileall -q app/modules/wechat_bot tests/wechat_bot` | 无语法错误 | STATIC_OK |
| `poetry run alembic heads` | 迁移链以 `20260823_0022` 为 head | `20260823_0022 (head)` |
| `docker compose config --services` | 解析成功且含 `wechat-bot-worker` | 输出 db/redis/api/wechat-bot-worker/worker/front |
| `pnpm --dir apps/front exec tsc -b`（前端管理台） | 无类型错误 | 通过 |
| `pnpm --dir apps/front exec eslint src/features/wechat-bots src/api/wechat-bots.ts ...`（前端管理台） | 无告警 | 通过 |
| `pnpm --dir apps/front build`（前端管理台） | 打包成功且含 `/ai/wechat-bots` 路由 | 构建成功，routeTree 已注册路由 |
| `poetry run pytest tests/wechat_bot -q`（扫码流程 fix） | 新增配对码/pending 复用用例全绿 | 18 passed |
| `poetry run alembic heads`（扫码流程 fix） | 迁移链以 `20260823_0023` 为 head | `20260823_0023 (head)` |
| `poetry run pytest tests/wechat_bot -q`（轮询卡死 fix） | 新增超时用例全绿 | 19 passed |
| `pnpm --dir apps/front exec tsc -b` / `eslint`（轮询卡死 fix） | 无类型错误/告警 | 通过 |
| `poetry run pytest tests/builtin_tool -q`（http_post） | 新增 POST 用例全绿 | 16 passed |
| `poetry run pytest tests/builtin_tool tests/conversation tests/agent tests/wechat_bot -q`（http_post） | 无回归 | 88 passed |
| `poetry run alembic heads`（http_post） | 迁移链以 `20260823_0024` 为 head | `20260823_0024 (head)` |
| `poetry run pytest tests/wechat_bot -q`（上下文复用 fix） | 新增会话映射/透传/404 用例全绿 | 24 passed |
| `poetry run pytest tests/conversation tests/agent -q`（上下文复用 fix） | 无回归 | 53 passed |
| `poetry run ruff check app/modules/wechat_bot tests/wechat_bot`（上下文复用 fix） | 无告警 | All checks passed |
| `PYTHONPYCACHEPREFIX=/tmp/pyc-cache poetry run python -m compileall -q app/modules/wechat_bot tests/wechat_bot`（上下文复用 fix） | 无语法错误 | STATIC_OK |

## 失败项与修正

- compose 依赖环（`api -> api`）：patch 误将 `api: service_started` 加到 api 服务自身
  depends_on，已修正为 wechat-bot-worker 依赖 api，`docker compose config` 通过。
- `get_default_agent` 测试初版未构造发布版本导致返回 None，补充 AgentVersion 后通过。
- 全量 pytest 存在预存收集冲突：`tests/embed|builtin_tool/test_models.py`、
  `tests/user|builtin_tool/test_routes.py`、`tests/user|skill_runner/test_services.py`
  同名模块冲突（与本次改动无关），相关模块单独跑均通过。

## 例外与待办

- 无法自动验证：真实扫码绑定、微信消息经 chat 接口端到端回复、解绑停实例（需真实微信账号）。
- 人工联调步骤见 `plan.md`；完成后在 `acceptance.md` 记录结论。
