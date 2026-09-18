# 实施计划

## 变更文件

| 文件 | 职责 |
|---|---|
| `apps/backend/app/modules/agent/provider_headers.py`（新增） | 纯函数工具：精确主机名判定 OpenCode 端点、构造静态兼容头、按会话构造 session 头、安全求值会话 id provider |
| `apps/backend/app/modules/agent/services.py`（改） | `build_chat_model` 增加 `session_id_provider` 入参并把 `model_options.default_headers` 与兼容头合并；`ProviderThinkingChatOpenAI` 增加按次注入 session 头 |
| `apps/backend/app/modules/conversation/router.py`（改） | 两处 `build_chat_model` 传入 `lambda: context.conversation_id` |
| `apps/backend/app/modules/gateway/router.py`（改） | Embed WebSocket 入口传入 `lambda: context.conversation_id` |
| `apps/backend/app/modules/tools/basic/vision.py`（改） | 读图客户端补静态兼容头（该路径无会话上下文，只发 UA 与客户端标识） |
| `apps/backend/app/modules/tools/basic/image_gen.py`（改） | 生图客户端补静态兼容头 |
| `apps/backend/tests/agent/test_provider_headers.py`（新增） | 工具函数单测 + 请求头注入端到端单测（httpx.MockTransport 抓真实请求头） |
| `apps/backend/.env.example`（改） | 补 OpenCode Zen Go 的可复制配置示例 |
| `docs/CHANGELOG.md`（改） | 按仓库约定记录本次功能项 |

实施步骤如何落实 `research.md` 的最终决策（方案 D）：
工具模块只做「判定 + 造头」两件事，不含任何客户端构造逻辑，因此 `build_chat_model` 与两个工具客户端
可以共用同一份判定，避免三处各写一遍主机名匹配；会话 id 通过无参可调用对象在调用期求值，
不改 `execute_chat` / `stream_chat` / `stream_embed_chat` 的签名与调用时序（这是否决方案 C 的原因）。

## 实施步骤

1. 新增 `provider_headers.py`：`is_opencode_endpoint`、`merge_default_headers`、`session_headers`、
   `resolve_session_id`、`SessionIdProvider` 类型别名。
2. 改造 `build_chat_model(version, *, session_id_provider=None)`：
   - 从 `model_options` 中取出 `default_headers`（不再直接展开，避免与兼容头冲突）；
   - 其余 `model_options` 仍按原样展开，保持既有行为；
   - 通过 `merge_default_headers(base_url, configured)` 得到最终静态头并传给 `ChatOpenAI(default_headers=...)`。
3. 给 `ProviderThinkingChatOpenAI` 增加 `session_id_provider` 字段与 `_with_session_headers(kwargs)` 方法，
   覆写 `_generate` / `_stream` / `_agenerate` / `_astream`（`_stream` / `_astream` 保持 `*args, **kwargs`
   签名，避免破坏位置参数调用）。
4. 覆写 `_stream` / `_astream` 时用 `yield from` / `async for` 透传，保证流式内容不被缓冲或改写。
5. 三处 `build_chat_model` 调用点传入 `session_id_provider`。
6. 读图、生图两个客户端补 `default_headers`。
7. 写单测，覆盖验收标准 1–4。
8. 补 `.env.example` 示例与 `docs/CHANGELOG.md`。
9. 运行 ruff 与相关测试目录回归，把真实输出写入 `verify.md`。

## 测试步骤

| 命令 | 预期结果 |
|---|---|
| `poetry run ruff check app/modules/agent app/modules/tools/basic app/modules/conversation/router.py app/modules/gateway/router.py` | 无告警 |
| `poetry run pytest tests/agent/test_provider_headers.py -q` | 新增单测全绿 |
| `poetry run pytest tests/agent tests/conversation tests/gateway tests/tools -q` | 无回归，无新增失败 |

关键断言（对应验收标准）：

1. base_url 为 `https://opencode.ai/zen/go/v1` 且 provider 返回 `42` 时，抓到的请求头包含
   `User-Agent: ai-base/1.0`、`x-opencode-client: ai-base`、`x-opencode-session: 42`，
   且 `User-Agent` 不含 `OpenAI/Python`。
2. 同一模型连续两次调用、provider 分别返回 `42` 与 `43` 时，两次请求头各自取值，验证「按次求值」。
3. provider 返回 `None` 时只发送 `User-Agent` 与 `x-opencode-client`。
4. base_url 为 `https://api.deepseek.com` 时抓到的请求头与不使用本功能时完全一致（无三个新增头）。
5. `model_options.default_headers` 显式给出 `User-Agent` / `x-opencode-session` 时，配置值不被覆盖。
6. `ainvoke`、`bind_tools` 后再 `ainvoke`、`astream` 三条路径都带上三个头。

若当前阶段无法执行（例如沙箱限制），必须在 `verify.md` 说明原因并标注待人工验证，不得写成已执行。

## 回滚说明

- 本次改动的接缝只有一处：`provider_headers.py` 的端点判定。回滚方式为把 `build_chat_model` 的
  `default_headers` 合并逻辑还原为直接展开 `model_options`，并删除调用点的 `session_id_provider` 参数，
  行为即回到本次改动之前（非 OpenCode 端点本来就不注入任何头，因此对既有链路无残留影响）。
- 特别注意：`model_options.default_headers` 在改动前是通过 `**` 展开生效的，回滚时需保留该能力，
  不要直接把 `default_headers` 键丢弃。
- 不涉及数据库与迁移，无需数据回滚。

## 人工确认点

- spec 方案对齐确认：已由用户在对话中批准（含把首轮 session id 改为懒取值真实会话 id 的修正）。
- 真实 OpenCode Go API key 联调（验证上游不再返回 `missing x-opencode-session`）：本阶段无可用密钥，
  列为待人工验证项，不阻塞代码合入。
