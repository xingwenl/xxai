请继续处理我的项目 Agent Runtime 架构优化，不要从头开始，也不要只处理单个 bug。

# 一、项目位置

项目根目录：

/Users/lixingwen/xw/study/ai-base

主要后端代码：

- apps/backend/app/modules/agent_runtime/
- apps/backend/app/modules/gateway/
- apps/backend/app/modules/conversation/

参考项目：

/Users/lixingwen/xw/git/pi

Harness request：

docs/harness/requests/2026-09-03-agent-runtime-architecture/

正式文档包括：

- research.md
- spec.md
- plan.md
- verify.md
- acceptance.md
- meta.json

# 二、项目总目标

将当前项目改造成一套高质量、逻辑清晰、可复用、可测试的 Python Agent Runtime。

最终目标是：

1. Agent 主循环只有一套核心实现。
2. REST、REST SSE、WebSocket 不再各自维护 Agent 循环。
3. REST、SSE、WebSocket 只负责协议转换、连接管理和鉴权。
4. Agent Runtime 负责：
   - 模型调用
   - 多轮工具调用
   - 工具结果回填
   - 流式事件
   - 工具确认
   - ask_user
   - continuation
   - 取消
   - 最大轮数
   - 错误处理
   - 运行状态
5. 工具调用使用统一的类型化契约。
6. 工具异常、取消、确认等待、用户问题等待具有清晰且互不混淆的语义。
7. Agent Runtime 不依赖 FastAPI、WebSocket、SQLAlchemy 等协议或基础设施。
8. 数据库持久化通过 Adapter 或 Persistence 接口注入。
9. REST、SSE、WS 的公开协议保持兼容。
10. 不改变已有鉴权、权限、工具确认和审计行为。
11. 所有核心行为都有自动化测试。
12. 代码中的关键中文注释要解释业务意图、关键约束和非直观原因。

# 三、架构目标

目标架构：

```text
REST Router
    |
REST Service / SSE Adapter
    |
    v
AgentRuntime
    |
    v
AgentLoop
    |
    +-- Model Adapter
    +-- Tool Executor
    +-- Event Sink
    +-- Persistence Adapter
    +-- Cancellation
    +-- Continuation
    |
    v
Conversation / Gateway Adapter
    |
    +-- REST Response
    +-- SSE Events
    +-- WebSocket Events
```

职责边界：

- `agent_runtime`
  - 供应商无关
  - 协议无关
  - 不直接操作数据库
  - 不直接操作 FastAPI/WebSocket
  - 负责 Agent 执行语义

- `conversation`
  - 会话、消息、loop、loop step 持久化
  - LangChain/模型上下文组装
  - REST 结果适配
  - SSE 事件适配

- `gateway`
  - WebSocket 连接
  - requestId、sequence、replay
  - 鉴权
  - host tool、确认和 ask_user 的现有接入
  - WebSocket 事件适配

# 四、已经完成的工作

## 1. agent_runtime 模块

已经建立：

- `contracts.py`
- `loop.py`
- `runtime.py`
- `tools.py`
- `hooks.py`
- `persistence.py`
- `lifecycle.py`
- `composition.py`
- `adapters.py`
- `langchain_adapter.py`
- `graph_bridge.py`
- `conversation_adapter.py`
- `event_adapters.py`
- `tool_loop.py`

已经具备：

- `AgentRequest`
- `AgentEvent`
- `AgentResult`
- `ToolCall`
- `ToolOutcome`
- `AgentLoop`
- `AgentRuntime`
- `ToolExecutor`
- `ToolDispatcher`
- continuation
- cancel_event
- persistence factory
- stream 事件
- 模型流式调用
- 工具确认
- ask_user
- 统一错误事件

## 2. REST/SSE/WS 灰度接入

已经完成：

- REST 非流式 AgentRuntime 灰度分支
- REST SSE AgentRuntime 灰度分支
- WebSocket AgentRuntime 灰度接入
- legacy Graph fallback 保留
- `AGENT_RUNTIME_ENABLED` 配置开关
- 统一 AgentResult 到旧 GraphResult 的转换
- 统一内部 AgentEvent 到 REST/SSE/WS 事件的转换

要求继续保持：

- 公开 REST 路径不变
- REST 请求体和响应体不变
- SSE 事件类型不变
- WebSocket 事件类型不变
- `requestId` 不变
- `sequence` 行为不变
- 鉴权和工具权限不变

## 3. 已修复的问题

已经修复过：

- usage 缺少 `prompt_tokens`
- `GraphResult.knowledge_grounded` 缺失
- 工具参数 dict 写入数据库字符串字段
- SQLAlchemy `AsyncSession` 并发使用
- frozen dataclass 赋值错误
- WS host tool 卡住
- 工具结果重复执行
- replay/sequence 兼容
- 首事件前流式异常导致永久等待
- task 与 queue 同时完成时丢尾事件
- 流式路径遗漏 `on_event`
- runtime 并发请求 persistence 串流
- continuation 重复追加工具结果
- continuation ��失 `pending_confirmation_id`
- continuation usage/tool_events 不累积
- legacy callback 丢失 `error`
- legacy callback 丢失 `resume_token`
- legacy callback 丢失 `call_id`
- 工具异常没有标准 `tool_completed(status=failed)`
- 工具异常与取消语义混淆
- AsyncSession 在工具调用中被错误共享
- `GraphResult` 与 `AgentResult` 字段不一致
- runtime 工具失败事件重复发布

# 五、最近已经完成的增量

最近完成的是“多工具调用失败策略”。

参考了 Pi：

- `/Users/lixingwen/xw/git/pi/packages/agent/src/agent-loop.ts`
- `/Users/lixingwen/xw/git/pi/packages/agent/src/types.ts`

当前策略：

1. 同一个模型响应包含多个工具调用时，按顺序执行。
2. 某个工具抛出普通异常时：
   - 转换成 `ToolOutcome(status="failed")`
   - 发布 `tool_completed(status=failed)`
   - 继续执行后续工具
3. 工具主动返回 `status="failed"` 时：
   - 不立即终止整轮
   - 继续执行同批次后续工具
4. 成功和失败结果一起回填下一轮模型。
5. 模型可以根据失败结果决定：
   - 直接回答
   - 重试
   - 更换工具
   - 明确告知用户失败
6. `CancelledError` 不转换为普通工具失败。
7. confirmation、ask_user、waiting_user 保持暂停语义。
8. 当前不引入工具并行执行，以避免：
   - AsyncSession 并发问题
   - 工具���作用并发
   - 审计顺序不稳定
   - 结果顺序和协议 sequence 复杂化

已验证：

```text
agent_runtime/test_loop.py
13 passed

agent_runtime
72 passed

agent_runtime + conversation + gateway
241 passed, 1 skipped, 1 warning

ruff
All checks passed

compileall
passed

git diff --check
passed
```

# 六、当前正在处理的问题

当前下一步是：

## AgentLoop 最大轮数收尾

目前发现：

- `AgentLoop` 达到 `max_turns` 后直接跳出循环。
- 如果上一轮仍然包含工具调用，可能直接返回上一轮结果。
- 这可能导致：
  - 没有明确的最终回答
  - 没有明确的预算终态
  - 可能把工具调用结果误当作最终回复
  - 与旧 Graph 的最大迭代收尾逻辑不一致
- 旧代码中已经有：

```python
_MAX_ITERATIONS_WRAPUP_PROMPT
```

配置项：

```text
AGENT_MAX_ITERATIONS
```

默认值：

```text
20
```

需要先阅读旧 Graph 的完整实现，再设计 runtime 收尾行为。

# 七、剩余总计划

严格按照以下阶段继续执行：

## 阶段 1：最大轮数收尾

目标：

- 达到最大工具轮数后有明确行为。
- 不再无限循环。
- 不执行收尾阶段的副作用工具。
- 最终返回明确回答或明确预算终态。
- REST、SSE、WS 协议保持兼容。

执行步骤：

1. 读取：
   - `agent_runtime/loop.py`
   - `agent_runtime/runtime.py`
   - `conversation/runtime.py`
   - `conversation/services.py`
   - 相关测试
2. 对照 Pi 的停止和终态事件。
3. 找到旧 Graph 最大迭代的真实收尾逻辑。
4. 更新：
   - `research.md`
   - `spec.md`
   - `plan.md`
   - `meta.json`
5. 如果改变 Agent Loop 公开行为，先向我说明方案并等待确认。
6. 实现最大轮数收尾。
7. 增加测试：
   - `max_turns` 触发
   - 收尾提示注入
   - 收尾轮不执行工具
   - 收尾轮仍返回工具调用时不无限循环
   - 收尾事件顺序
   - 最终结果字段
   - confirmation 不受影响
   - ask_user 不受影响
   - cancel 不受影响
8. 更新 `verify.md` 和 `acceptance.md`。

建议的实现方向：

- 达到最大工具轮数后，只允许进行一次收尾模型调用。
- 收尾调用加入明确提示：
  “已达到本次任务最大执行轮数，请停止调用工具，基于已有信息直接回答。”
- 收尾轮禁止工具执行。
- 如果收尾模型仍返回工具调用：
  - 不执行工具
  - 转成稳定的“达到最大轮数，无法继续调用工具”的结果
  - 不能再次请求模型
- 发布明确的完成或预算终态。
- 不把预算终止伪装成供应商错误。
- 不把预算终止伪装成用户取消。

## 阶段 2：工具状态和终态统一

检查：

- `completed`
- `failed`
- `confirmation_required`
- `waiting_user`
- `expired`
- `rejected`
- `cancelled`
- `budget_exceeded`

目标：

- 各种状态只有一套内部含义。
- 协议层映射稳定。
- 数据库 loop/step 状态映射稳定。
- 不重复发布终态事件。
- 不因为失败工具导致错误地把整个 Agent 标记为失败。
- 不因为取消生成工具失败事件。

需要增加：

- 状态映射测试
- 终态幂等测试
- continuation 状态测试
- persistence 状态测试

## 阶段 3：模型调用错误收敛

重点检查：

- 模型首事件前失败
- 模型流中途失败
- 模型返回空内容
- 模型返回不完整 tool call
- provider timeout
- rate limit
- context overflow
- usage 缺失
- usage 字段为 `None`
- usage 字段名称不一致

目标：

- 所有模型错误都转换为统一内部错误。
- REST、SSE、WS 获得稳定错误事件。
- 错误中不泄露内部堆栈、SQL 或密钥。
- retryable 字段正确。
- 不重复发布 error。

## 阶段 4：上下文和消息构建

检查：

- system prompt
- history
- user message
- assistant message
- tool result
- attachment
- citation
- skill instruction
- context window guardrail
- context compression

目标：

- 所有入口使用统一消息构建器。
- 工具结果始终保留 call_id。
- assistant tool call 与 tool result 始终正确关联。
- 上下文截断不会产生非法消息序列。
- continuation 不会重复追加消息。
- 不把 UI-only 状态写入模型上下文。

需要参考 Pi：

- context transform
- message role validation
- truncated tool call protection
- compaction/overflow 处理

## 阶段 5：工具执行边界

检查：

- builtin tool
- MCP tool
- host tool
- skill tool
- ask_user
- confirmation
- resume token
- audit id
- call id
- 工具超时
- 工具异常
- 工具取消
- 工具重复调用

目标：

- 工具执行器只负责工具执行。
- 权限判断仍由现有 Dispatcher/Adapter 负责。
- `agent_runtime` 不绕过权限。
- 工具异常统一结果化。
- 取消不伪装成失败。
- confirmation 不重复触发。
- continuation 不重复执行已完成工具。
- 有副作用工具仍然按现有确认规则执行。

## 阶段 6：Persistence 和并发

检查：

- 一个 runtime 多个请求
- 一个 WebSocket 多个 request
- REST 与 WS 并发
- persistence factory
- AsyncSession 生命周期
- loop step 顺序
- event buffer
- replay
- sequence
- terminal event 幂等

目标：

- 请求之间不共享可变事件缓冲。
- 不共享正在执行的 AsyncSession。
- 不出现 “concurrent operations are not permitted”。
- 事件顺序稳定。
- 终态只写入一次。
- replay 不重复消息。
- continuation 恢复不重复工具结果。

## 阶段 7：REST/SSE/WS 兼容验证

自动化验证：

```bash
apps/backend/.venv/bin/pytest \
  apps/backend/tests/agent_runtime \
  apps/backend/tests/conversation \
  apps/backend/tests/gateway -q
```

静态检查：

```bash
apps/backend/.venv/bin/ruff check apps/backend
```

编译检查：

```bash
apps/backend/.venv/bin/python -m compileall \
  apps/backend/app \
  apps/backend/tests \
  apps/backend/main.py
```

格式检查：

```bash
git diff --check
```

真实测试顺序：

1. WS 普通对话
2. WS 工具调用
3. WS confirmation
4. WS ask_user
5. WS cancel
6. WS 断线恢复
7. REST 非流式
8. REST SSE
9. REST 工具调用
10. REST 错误场景
11. REST 最大轮数场景

用户已确认过的场景：

- WS 普通对话正常
- WS 工具调用正常
- WS confirmation 正常
- WS ask_user 正常
- WS cancel 正常
- REST 非流式正常
- REST SSE 正常
- AgentRuntime 灰度工具调用正常

REST 人工测试当前按照约定延期到最后统一执行。

# 八、明确暂不处理的问题

以下问题已经延期，不要在当前最大轮数任务中处理：

## WS 断线重连后前端消息列表不渲染

已知现象：

- WebSocket 可以重连。
- transport 能收到：
  `message_started`
- 但消息没有正确进入前端 message list。
- 有过：
  - `event dropped by sequence`
  - `request_in_progress`
  - `4401`
  - 只保存部分消息
- 用户要求后续再处理。

当前暂不修改：

- `apps/ai-sdk/src/core/client.ts`
- `apps/ai-sdk/src/core/websocket.ts`
- 前端 message list
- replay state
- sequence state
- 断线恢复 UI

除非完成后端 Agent Runtime 主体优化并进入独立的 WS replay 专项。

# 九、仓库规则

必须先读取：

- `AGENTS.md`
- `docs/harness/README.md`
- `docs/harness/policies/global.md`
- `docs/harness/backend.md`

必须遵循：

```text
research -> spec -> plan -> implement -> verify -> acceptance
```

涉及 Agent Loop、工具执行、上下文压缩、事件回放、会话持久化和权限边界时：

- 优先阅读本地 Pi 源码。
- 调研结果写入 request 的 `research.md`。
- 方案变化写入 `spec.md` 的“变更记录”。
- 每一步写入 `plan.md`。
- 实际命令和结果写入 `verify.md`。
- 最终结论写入 `acceptance.md`。

不要：

- 回滚用户已有修改。
- 修改无关 request。
- 修改数据库模型。
- 修改公开 API。
- 修改鉴权和权限语义。
- 把敏感 token 写入文件。
- 凭上下文猜测代码。
- 只说“下一步”，却不更新计划表。

# 十、建议调用的技能

新会话建议调用：

- `superpowers:using-superpowers`
- `research`
- `codebase-design`
- `superpowers:verification-before-completion`

如果出现难以定位的异常：

- `diagnosing-bugs`
- `superpowers:systematic-debugging`

如果采用测试先行：

- `tdd`

# 十一、执行要求

请现在开始：

1. 读取当前工作区和 request 文档。
2. 读取旧 Graph 最大轮数实现。
3. 阅读 Pi Agent Loop 的相关实现。
4. 更新 research/spec/plan。
5. 如果需要人工确认，把方案明确发给我。
6. 确认后继续实现，不要停在计划阶段。
7. 每完成一个阶段自动进入下一个阶段。
8. 只有以下情况才暂停：
   - 必须人工确认架构/API/数据模型/权限变化
   - 需要我进行真实 WS/REST 测试
   - 外部环境阻塞，无法继续
9. 每次暂停时必须告诉我：
   - 当前完成了什么
   - 具体阻塞点
   - 我需要执行什么操作
   - 完成后下一步是什么
10. 不要把整个项目目标缩小成单个 bug 修复。
```
