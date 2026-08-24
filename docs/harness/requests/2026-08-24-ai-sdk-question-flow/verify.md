# 验证记录

## 验证范围

- 后端：`ask_user` 内置工具定义、dispatcher 挂起/恢复/超时/次数上限、网关 `question_required`/`question_answer` 协议、能力协商、loop step `waiting_question` 状态、系统提示词。
- SDK：协议解析、客户端事件分发与 `answerQuestion`、WebSocket 发送、`QuestionCard.vue` 组件类型。

## 验证命令与结果

### 后端单测（新增 + 相关回归）

```bash
cd apps/backend
poetry run pytest tests/gateway/test_question_flow.py tests/conversation/test_runtime.py -q
# 结果：45 passed
```

覆盖：提问事件发送与用户答案恢复、超时返回 expired、单请求 3 次上限、非法参数拒绝、`_handle_question_answer` 只唤醒匹配 Future、`_event_to_protocol_payload` 转换、`validate_incoming_message` 对 `question_answer` 的 payload 校验、`ProtocolEnvelope` 支持 `question_required`、`tool_step_values` 的 `waiting_question` 映射、系统提示词仅在 ask_user 可见时追加。

增量调整：移除无条件注入与客户端能力门控（`_runtime_tools_with_ask_user`/`supports_questions` 删除），ask_user 仅在后台启用绑定后进入工具列表；REST 路径 `_rest_runtime_tools` 过滤 ask_user（REST 无实时问答通道的功能缺口兜底）。回归测试：`test_rest_tool_lists_exclude_ask_user_even_when_db_bound`。

### 后端全量（跳过既有收集冲突）

```bash
poetry run pytest tests/gateway tests/conversation tests/builtin_tool -q
# 结果：101 passed, 1 skipped

poetry run pytest tests -q \
  --ignore=tests/embed/test_models.py \
  --ignore=tests/user/test_routes.py \
  --ignore=tests/user/test_services.py
# 结果：287 passed, 1 skipped
```

说明：`tests/embed/test_models.py`、`tests/user/test_routes.py`、`tests/user/test_services.py` 在整包收集时因同名模块冲突报 `import file mismatch`，属仓库既有问题（2026-08-20 的 request 验证记录同样跳过）；这三个文件单独运行均通过（18 passed）。

### 后端静态检查

```bash
poetry run ruff check app/modules/builtin_tool/registry.py app/modules/gateway/ \
  app/modules/conversation/runtime.py app/modules/conversation/services.py \
  tests/gateway/test_question_flow.py tests/conversation/test_runtime.py
# 结果：All checks passed
```

### SDK 测试、类型检查与构建

```bash
cd apps/ai-sdk
pnpm test -- --run
# 结果：12 个测试文件 76 passed（含新增 question_required 解析、answerQuestion、sendQuestionAnswer 用例）

pnpm type-check
# 结果：通过（vue-tsc --noEmit）

pnpm build
# 结果：构建成功，dist 产物正常生成
```

## 未解决问题

- 手工端到端验证（真实模型调用 `ask_user`、前端卡片交互、超时与旧客户端降级）未在本次自动验证中覆盖；验收阶段建议本地起后端 + SDK 示例观察一次完整"提问 → 选择 → 继续执行"链路。
- SDK 版本号（`package.json` 0.1.5 与 `protocol.ts` SDK_VERSION 0.1.0 不一致）为既有状态，本次未调整。
- 全量收集冲突（3 个文件同名模块）为既有问题，未在本次修复。
