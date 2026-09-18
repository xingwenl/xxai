<!-- 启动worker -->
# docker compose up --build --force-recreate worker -d

## 关键配置项

- `AGENT_MAX_ITERATIONS`：单次对话任务中 Agent 工具循环的最大迭代轮数（每轮 = 一次 LLM 调用，含其工具执行），默认 `20`；达到上限后停止调用工具并追加一次不带工具的收尾回复。设置为 `0` 或负值表示不设限。

## 接入 OpenCode Zen Go

OpenCode Go 提供 OpenAI 兼容的 `/v1/chat/completions` 端点，可直接作为主对话模型使用。

全局默认模型（未绑定模型注册表时生效）：

```dotenv
MODEL_DEFAULT_BASE_URL=https://opencode.ai/zen/go/v1
MODEL_DEFAULT_NAME=glm-5.2
OPENAI_API_KEY=<OpenCode Zen 的 API Key>
```

该路径上的 API Key 取自 `OPENAI_API_KEY`（`build_chat_model` 在 Agent 版本未配置密钥时
不显式传 key，由 OpenAI SDK 回落到该环境变量）。

也可以在「模型注册表」里登记条目，`base_url` 填 `https://opencode.ai/zen/go/v1`，
`model_name` 填上游模型 ID（如 `glm-5.2`、`kimi-k2.6`、`deepseek-v4-pro`、`mimo-v2.5`）。

注意事项：

- 只有走 `/v1/chat/completions` 的模型可用。上游用 `@ai-sdk/anthropic`（`/v1/messages`）
  提供的模型（如 `qwen3.8-max`、`minimax-m3`）本仓库当前不支持。
- 当 `base_url` 主机名为 `opencode.ai` 时，本服务会自动带上自有 `User-Agent`、
  `x-opencode-client: ai-base`，以及每个会话稳定不变的 `x-opencode-session`
  （取自当前会话 ID），用于满足上游的路由与 prompt 缓存要求。其他供应商不会收到这些头。
- 需要覆盖默认请求头时，可在模型配置的 `model_options` 里写 `default_headers`，同名键优先：

  ```json
  {
    "default_headers": {
      "User-Agent": "my-agent/1.0",
      "x-opencode-session": "pinned-session"
    }
  }
  ```

  注意 `User-Agent` 必须使用该大小写：写成小写 `user-agent` 时，OpenAI SDK 会把它与自带的
  `OpenAI/Python x.y.z` 合并成一个值，导致上游仍能识别出通用 SDK 名。
