# 验证记录：集成微信 ClawBot（iLink）机器人服务（MVP）

## 验证范围

- 自动验证：新增单元测试、既有回归测试、语法/静态检查、compose 配置解析。
- 人工联调（未执行，需真实微信账号与模型密钥）：扫码登录、端到端收发消息。

## 执行命令与结果

| 命令 | 预期 | 实际（2026-08-23） |
|---|---|---|
| `poetry run pytest tests/wechat_bot -q` | 新增用例全绿 | 3 passed |
| `poetry run pytest tests/conversation/test_runtime.py -q` | 无回归 | 35 passed |
| `PYTHONPYCACHEPREFIX=/tmp/pyc-cache python3 -m compileall -q app/modules/wechat_bot` | 无语法错误 | COMPILE_OK |
| `poetry run ruff check app/modules/wechat_bot tests/wechat_bot app/core/config.py` | 无告警 | All checks passed |
| `docker compose config` 与 `docker compose config --services` | 包含 `wechat-bot-worker` | 输出 `wechat-bot-worker`，解析成功 |
| `poetry run ruff check app/modules/wechat_bot`（补丁后复验） | 无告警 | All checks passed |
| `poetry run pytest tests/wechat_bot -q`（补丁后复验） | 新增用例全绿 | 3 passed |
| `PYTHONPYCACHEPREFIX=/tmp/pyc-cache poetry run python -m compileall -q app/modules/wechat_bot tests/wechat_bot`（补丁后复验） | 无语法错误 | COMPILE_OK |
| `poetry run pytest tests/wechat_bot -q`（登录状态持久化变更） | 新增 session 用例全绿 | 6 passed |
| `poetry run pytest tests/conversation/test_runtime.py -q`（登录状态持久化变更） | 无回归 | 35 passed |
| `poetry run ruff check app/modules/wechat_bot tests/wechat_bot app/core/config.py`（登录状态持久化变更） | 无告警 | All checks passed |
| `docker compose config --services`（登录状态持久化变更） | 含 `wechat-bot-worker` 且解析成功 | 输出 `wechat-bot-worker` |
| `poetry run pytest tests/wechat_bot -q`（智能体绑定变更） | 新增智能体分支用例全绿 | 8 passed |
| `poetry run pytest tests/agent tests/conversation -q`（智能体绑定变更） | 无回归 | 53 passed |
| `poetry run ruff check app/modules/wechat_bot tests/wechat_bot app/modules/agent/repositories.py app/core/config.py`（智能体绑定变更） | 无告警 | All checks passed |
| `docker compose config`（智能体绑定变更） | `wechat-bot-worker` 含 `WECHAT_BOT_AGENT_ID` 与 db 依赖，解析成功 | 解析成功 |

## 失败项与修正

- 截断测试初版断言未考虑追加后缀中的换行与「长」字，改为校验前缀与后缀后通过。
- 系统 python3 编译缓存目录无写入权限，改用 `PYTHONPYCACHEPREFIX` 后通过。
- 人工联调失败项（2026-08-23）：扫码登录与收消息成功，但模型调用报 `openai.APIConnectionError`（所有连接尝试失败）。
  - 根因：容器内 `OPENAI_BASE_URL=127.0.0.1:8800/v1` 指向容器自身，宿主机模型网关不可达。
  - 修正：`wechat-bot-worker` 增加 `extra_hosts`，`OPENAI_BASE_URL` 默认改为 `host.docker.internal:8800/v1`（可覆盖），并在启动日志输出实际模型地址。
  - 复验：`docker compose config` 解析通过；端到端回复需用户重新扫码联调确认。

## 例外与待办

- 无法自动验证：`wechatbot-sdk` 真实 API 行为、扫码登录、端到端收发消息（需真实微信账号 + 模型密钥）。
- 人工联调步骤见 `plan.md`「测试步骤」；完成后在 `acceptance.md` 记录结论。
