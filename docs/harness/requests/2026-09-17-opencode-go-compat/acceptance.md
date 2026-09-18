# 验收记录

## 验收结论

`spec.md` 的验收标准 1–7 已全部达成，且有真实命令输出为证（见 `verify.md`）：

- 指向 `opencode.ai` 的模型请求会带上自有 `User-Agent: ai-base/1.0`、`x-opencode-client: ai-base`
  与按会话稳定求值的 `x-opencode-session`，三个头在 `ainvoke`、`bind_tools` 后再 `ainvoke`、
  `astream` 三条路径上都由测试断言过；
- 非 OpenCode 端点不新增任何请求头，`model_options.default_headers` 的显式配置可以覆盖默认值；
- 新增单测 10 项全绿，相关四个目录回归 `213 passed, 1 skipped`，
  `--import-mode=importlib` 下全量 `633 passed, 1 skipped`；
- 配置示例已写入 `apps/backend/readme.md` 与 `.env.example`。

验收标准 8（真实上游联调）**未完成**：本环境没有 OpenCode Go 的真实 API Key，
三项联调项已在 `verify.md` 的「待人工验证」小节逐条列出。因此本 request 暂不标记为 `done`，
保持 `active`，待人工完成真实联调后回收。

## 剩余风险

1. **真实上游未联调**：`x-opencode-client` 的取值是否被上游接受、`cannot be routed efficiently`
   是否彻底消失，均需真实 Key 验证。当前实现对上游是「多发两个头 + 替换 UA」的保守改动，
   即使上游忽略这些头，也不会比改动前更差。
2. **读图 / 生图链路缺少网络级测试**：这两个工具复用同一 helper，但只做了代码层复用，
   没有像主对话链路那样用 `httpx.MockTransport` 断言真实请求头。风险低（同一函数、同一判定），
   后续如需可在 `tests/tools` 补断言。
3. **Anthropic 路径不支持**：`/v1/messages` 提供的模型（如 `qwen3.8-max`、`minimax-m3`）
   在本仓库不可用，已在 `readme.md` 中明确写出，避免使用者误配。
4. **仓库既有问题未修**：`poetry run pytest -q` 的 5 个收集错误与
   `app/modules/embed/repositories.py` 的未使用导入，均为改动前既有，按约定本次不顺手修复。

## 人工验收记录

- spec 方案对齐：已确认。用户先质疑「新会话首轮为何没有 `conversation_id`」，复核代码后方案由
  「首轮兜底占位值」修正为「懒取值真实会话 id」，随后用户回复「可以」批准实现。
- 真实上游联调：尚未进行，需 OpenCode Go API Key。这是本 request 保持 `active` 的唯一原因。
