# 验证记录

## 执行命令

以下命令均在 `apps/backend/` 目录下执行。

1. `poetry run ruff check app/modules/agent app/modules/tools/basic app/modules/conversation/router.py app/modules/gateway/router.py tests/agent tests/conversation`
2. `poetry run ruff format --check app/modules/agent/provider_headers.py app/modules/agent/services.py tests/agent/test_provider_headers.py`
3. `poetry run pytest tests/agent/test_provider_headers.py -q`
4. `poetry run pytest tests/conversation/test_rest_parity.py -q`
5. `poetry run pytest tests/agent tests/conversation tests/gateway tests/tools -q`
6. `poetry run pytest -q --import-mode=importlib`
7. `poetry run pytest -q`

调研阶段另外跑过两组一次性原型（httpx.MockTransport 抓真实请求头，脚本位于 `/tmp`、未入库）：

8. 直接使用 OpenAI SDK，对比 `default_headers={"user-agent": ...}` 与 `{"User-Agent": ...}` 的实际请求头。
9. 用 `ProviderThinkingChatOpenAI` 子类覆写 `_agenerate` / `_astream`，验证 `ainvoke`、`bind_tools` 后再 `ainvoke`、`astream` 三条路径的请求头。

## 预期结果

1. 无 lint 告警。
2. 三个文件格式合规（这三个文件在改动前是 ruff format 干净的，改动后需保持干净）。
3. 新增的 10 个单测全部通过。
4. 该文件原有 13 个行为一致性测试加新增 1 个顺序护栏测试全部通过。
5. 四个相关测试目录无回归。
6. 全量测试通过。
7. 复现仓库既有的 pytest 收集问题，确认与本次改动无关。
8. 小写 `user-agent` 会退化为与 SDK 默认 UA 合并的值；精确大小写才会完整替换。
9. 三条调用路径都带上 `User-Agent: ai-base/1.0`、`x-opencode-client: ai-base`、`x-opencode-session: <会话 id>`。

## 实际结果

1. 通过：`All checks passed!`
2. 通过：`3 files already formatted`
3. 通过：`10 passed in 2.49s`
4. 通过：`14 passed in 1.75s`
5. 通过：`213 passed, 1 skipped, 1 warning in 4.02s`（warning 为既有 `StarletteDeprecationWarning`）
6. 通过：`633 passed, 1 skipped, 3 warnings in 11.24s`
7. 复现 5 个收集错误：`tests/embed/test_models.py`、`tests/model_registry/test_models.py`、
   `tests/skill_runner/test_services.py`、`tests/user/test_routes.py`、`tests/user/test_services.py`，
   全部是 `import file mismatch`（与 `tests/builtin_tool/` 下的同名模块冲突）。这是仓库既有的
   pytest 模块命名/导入模式问题，报错文件名中不含本次新增或修改的任何文件。
8. 实测：`{"user-agent": "ai-base/1.0"}` 得到 `User-Agent: OpenAI/Python 2.48.0, ai-base/1.0`（未替换）；
   `{"User-Agent": "ai-base/1.0"}` 得到 `User-Agent: ai-base/1.0`（完整替换）。
9. 实测三条路径请求头均为 `ua=ai-base/1.0 session=<会话 id> client=ai-base`；
   `base_url` 不含 `opencode.ai` 时不注入任何头。

关键断言与验收标准的对应关系：

| 验收标准 | 覆盖测试 |
|---|---|
| 1. OpenCode 端点带三个头且 UA 不含 `OpenAI/Python` | `test_opencode_request_carries_session_and_client_headers` |
| 2. 会话 id 稳定 / 首轮即真实值 | `test_session_id_is_evaluated_per_call`、`test_execute_chat_resolves_conversation_before_first_model_call` |
| 3. 非 OpenCode 端点零新增头 | `test_non_opencode_endpoint_gains_no_new_headers`、`test_merge_default_headers_adds_client_identity_only_for_opencode` |
| 4. `default_headers` 可覆盖 | `test_configured_session_header_is_not_overridden`、`test_merge_default_headers_lets_configured_values_win` |
| 5. 读图 / 生图同样补头 | 代码复用同一 helper（`vision.py`、`image_gen.py`）；无独立网络级测试，见剩余风险 |
| 6. 单测 + 回归通过 | 命令 3、4、5、6 |
| 7. 配置示例 | `apps/backend/readme.md`「接入 OpenCode Zen Go」小节 + `.env.example` |

## 失败项与例外

- 命令 7 的 5 个收集错误：仓库既有问题，与本次改动无关，本次未修复（按仓库约定不顺手修无关问题）。
  `--import-mode=importlib` 下全量 633 项通过，可作为「本次改动未引入回归」的证据。
- `poetry run ruff check app tests`（全目录）报出 1 个既有错误：`app/modules/embed/repositories.py`
  的 `BaseRepository` 未使用导入。与本次改动无关，未修复。
- `apps/backend/readme.md` 与 `apps/backend/README.md` 是同一个文件（macOS 大小写不敏感文件系统），
  git 中记录的路径为小写 `readme.md`。
- 格式检查范围说明：`apps/backend/app/modules/gateway/router.py` 与
  `apps/backend/tests/conversation/test_rest_parity.py` 在改动前就不满足 `ruff format --check`
  （已用 `git show HEAD:<path>` 导出原文件比对确认），因此本次不对这两个文件执行格式化，
  避免产生无关的大范围 diff。

## 待人工验证（真实上游联调）

以下三项需要 OpenCode Go 的真实 API Key 才能确认，本次环境无可用密钥，**未执行**，不得视为已验证：

1. 配置 `MODEL_DEFAULT_BASE_URL=https://opencode.ai/zen/go/v1` +
   `MODEL_DEFAULT_NAME=glm-5.2` + `OPENAI_API_KEY=<真实 Key>` 后发起一轮真实对话，
   确认上游不再返回 `Request is missing x-opencode-session`。
2. 确认同一会话连续两轮请求使用同一个 `x-opencode-session` 值。
3. 确认上游是否对 `x-opencode-client: ai-base` 的取值有额外要求（文档只要求 UA 使用自有名称，
   Pi 使用 `x-opencode-client: pi`，本仓库按同样形式使用 `ai-base`）。

建议的人工验证方式：在服务端开启 debug 日志后发起真实对话，或用抓包/代理查看出站请求头。
