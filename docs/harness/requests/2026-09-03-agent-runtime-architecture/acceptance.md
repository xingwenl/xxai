# 验收记录

## 当前结论

本次多工具调用失败策略增量已完成自动验收，当前渐进迁移阶段达到本次增量验收标准。

## 已完成

- `agent_runtime` 独立模块已建立。
- WS、REST SSE 的事件和结果适配已接入，保持公开协议兼容。
- 工具调用、工具结果、确认恢复、取消和 continuation 已建立统一内部契约。
- 后端核心测试、Python 编译检查、Ruff 和 SDK 自动化验证均通过。
- REST 非流式和 REST SSE 已完成真实验证，事件与最终结果均正常。
- 惰性工具轮次已迁移到 `agent_runtime.ToolRoundExecutor`，WS/REST SSE 工具链回归正常。
- 普通工具异常和显式 `failed` 结果均能作为工具级结果继续完成同批次调用，下一轮模型可同时读取成功与失败结果。
- 工具异常事件顺序保持 `tool_started -> tool_completed(status=failed)`；取消路径不会生成伪造的工具失败事件。
- Agent runtime、conversation、gateway 回归测试 `241 passed, 1 skipped`，Ruff 和 compileall 通过。

## 待完成

- WS 完整切换到 AgentRuntime loop 后的真实回归。
- legacy Graph 仍保留模型消息组装和最终 GraphResult 收尾实现；这是兼容层剩余风险，不影响当前协议和工具行为。后续可继续将模型轮次迁入 `AgentRuntime.AgentLoop`。
- 本次未引入工具并行执行；具有副作用的多工具调用仍按当前顺序执行，后续如需并行需单独评估 Session 并发和幂等风险。
- WS 断线重连后的前端消息列表渲染问题按用户要求延期，未纳入本次验收。

## 验收结论

当前阶段可以合并。后续模型轮次完全迁移属于独立的高风险增量任务。
# 2026-09-04 第 4 次增量验收：最大轮数收尾行为

## 结论

本轮增量达到验收标准。AgentLoop 在达到 `max_turns` 后会进行一次禁用工具的收尾调用；收尾仍返回工具调用时生成稳定失败工具结果并结束，不会执行超预算工具或无限循环。既有取消、确认等待、用户问题等待语义保持不变。

## 验收项

- [x] 最大轮数触发后停止新的工具执行
- [x] 收尾提示注入且只调用一次
- [x] 收尾轮禁止真实工具执行
- [x] 收尾再次返回工具调用时稳定结束
- [x] 完成事件与工具失败事件顺序有回归测试
- [x] REST、SSE、WebSocket 公开协议、数据库、鉴权和权限边界未修改
- [x] 收尾模型供应商内部异常不会因签名兼容回退而重复调用
- [x] `max_turns=0`/负数与 legacy Graph 一致地表示不设上限

## 剩余风险

- Ruff 和 Harness audit 的既有问题仍待独立 request 处理。
- WS 断线重连后前端消息列表渲染问题按用户要求继续延期。

## 阶段 2 增量进度

- [x] Agent runtime 已有统一工具状态枚举和运行生命周期等待/终态枚举。
- [x] 未知工具状态不再默认映射为成功。
- [x] 取消和预算耗尽具备独立内部状态表达。
- [x] conversation/gateway 重复终态映射已收敛（2026-09-07）：三个收尾站点
  统一经 lifecycle `generation_step_status_for` / `loop_status_for` /
  `loop_summary_for` 推导，不再各自维护状态口径；迟到回调处理此前已由
  RequestRegistry 终态单写与归属闸门覆盖。
- [x] conversation 工具步骤对取消、预算耗尽和未知状态使用统一安全映射。
- [x] conversation/gateway 收尾状态解析已复用统一 `resolve_result_run_status()`。
- [x] Gateway RequestRegistry 支持预算终态且迟到完成不会覆盖预算状态。
- [x] 预算终态接入未改变 WebSocket 公开 payload。
- [x] 入站确认/问题/宿主工具回调具备请求归属闸门，错配 requestId 不唤醒或变更。
- [x] 工具失败不将整个 Agent 请求错误升级为 failed，终态仍为 completed。

## 阶段 3 增量进度

- [x] runtime 错误分类与 legacy 对齐（上下文超限、5xx、连接/超时、4xx）。
- [x] 错误事件不泄露供应商原始文本，只暴露状态码与异常类型。
- [x] runtime 与 legacy usage 归一化来源一致。
- [x] 不完整工具调用不会进入执行契约，空内容响应行为已锁定。

## 阶段 4 增量进度

- [x] runtime 上下文护栏以整轮为删除单元，assistant 工具调用与结果不会拆散。
- [x] System、快照与最近一轮在裁剪中保留。
- [x] REST/WS runtime 灰度入口使用新护栏，legacy Graph 路径不变。

## 阶段 5 增量进度（2026-09-04 已确认并实现）

- [x] legacy `ToolRoundExecutor` 未知工具不再静默跳过：转为 `failed(tool_not_found)` 工具结果并回填模型，同批次后续工具继续执行。
- [x] legacy 工具异常统一失败结果化，取消（`CancelledError`）原样传播，不伪装成工具失败。
- [x] 失败工具只有 error 时，回填文本包含错误摘要，模型不会只看到 `None`。
- [x] host tool 等待按审计 `expires_at` 收敛：`awaiting_confirmation` 超时 → `expired`；`running` 超时 → `failed(host_tool_execution_timeout)`。
- [x] 取消/超时在 `finally` 清理 pending Future；超时与页面回调竞争时从审计终态恢复，不产生二次转换。
- [x] 权限、确认与审计边界未修改：runtime 仍只通过注入执行器调用，公开协议与数据库模型不变。
- [x] 全量回归 `277 passed, 1 skipped`，Ruff、compileall、`git diff --check` 通过。
- [ ] host tool 超时对真实长耗时页面工具的影响留待最终统一人工测试确认。

## 阶段 6 增量进度（2026-09-04 审计完成）

- [x] 并发 stream 事件不串流，persistence 工厂按请求隔离（定向测试 17 passed）。
- [x] AsyncSession 按请求/连接生命周期管理，AgentLoop 不触碰数据库。
- [x] RequestRegistry 与 AgentRunLifecycle 终态幂等，取消/断线清理 pending Future。
- [x] replay 发送前 append、sequence 断线续接行为有测试锁定。
- [x] 结论：持久化接线保持“协议 Adapter 落库 + AgentRunPersistence 保留 seam”，阶段 6 无行为变更。
- [ ] REST SSE 灰度入口自动化端到端回归待阶段 7 补充。

## 阶段 7 增量进度（自动化部分，持续更新）

- [x] WS `stream_embed_chat` 灰度开关开启时事件顺序与 legacy 流程保持一致（新增 parity 回归）。
- [x] 全量核心回归 `278 passed, 1 skipped`，Ruff、compileall、`git diff --check` 通过。
- [x] WS 普通对话、工具调用、确认、ask_user、取消已由用户真实验证（既有记录）。
- [x] REST 服务层灰度 parity 自动化（2026-09-05）：非流式 `execute_chat` 与
  流式 `stream_chat` 在替身仓库下对照 legacy Graph，锁定引用语义、工具步骤、
  快照参数与事件序列一致性。
- [x] 自动化发现的灰度缺陷已修复：`knowledge_grounded` 引用语义、工具
  step_type 误落 `host_tool`、`input_summary`/快照参数丢失、非流式图片改写
  与 content_blocks 缺失；不修改 REST/SSE/WS 公开协议、数据库模型与权限边界。
- [x] 修复后全量核心回归 `285 passed, 1 skipped`，Ruff、compileall 与
  `git diff --check` 通过。
- [x] thinking/reasoning 灰度 parity 补全（2026-09-05）：AgentRuntime 流式
  发布 `thinking_delta`、非流式与流式携带完整跨轮 `thinking_text`，正文/思考
  提取规则与 legacy 收敛到 `agent_runtime.message_text` 单点。
- [x] thinking parity 修复后全量核心回归 `291 passed, 1 skipped`，Ruff、
  compileall 与 `git diff --check` 通过。
- [x] REST SSE astream 工具轮 parity（2026-09-05）：工具调用/结果的流式事件
  顺序、tool payload、loop step 与工具快照在灰度/legacy 下一致；工具参数
  摘要统一为紧凑 JSON + 300 字符上限。
- [x] astream 工具轮 parity 后全量核心回归 `292 passed, 1 skipped`，Ruff、
  compileall 与 `git diff --check` 通过。
- [x] REST 确认/等待态灰度收尾 parity（2026-09-05）：非流式
  `pending_confirmation_id` 透出与工具/生成步骤落库、REST SSE 等待态收尾
  事件序列均与 legacy 一致；AgentLoop 等待态结果携带工具事件与思考文本，
  WS 等待态事件流语义未变。
- [x] 确认等待 parity 后全量核心回归 `294 passed, 1 skipped`，Ruff、
  compileall 与 `git diff --check` 通过。
- [x] REST SSE/WS 流式模型错误收尾 parity（2026-09-05）：AgentRuntime.stream
  把尚未表达为事件的模型级错误转换为终止 error 事件，灰度下 REST SSE 与
  WS 均以 error 事件终结并落库 failed（loop/生成步骤），与 legacy 一致；
  取消保持异常传播语义不变。
- [x] 错误收尾 parity 后全量核心回归 `298 passed, 1 skipped`，Ruff、
  compileall 与 `git diff --check` 通过。
- [x] REST 非流式模型错误失败落库补全（2026-09-06）：`execute_chat` 在
  模型错误时灰度与 legacy 都补写 failed 的 model_generation 步骤并把 loop
  更新为 failed，随后继续上抛原异常（REST 公开错误响应不变）；模型调用
  分叉收敛到 `_run_execute_chat_model_round`，两路错误 payload 落库一致。
- [x] 非流式失败落库补全后全量核心回归 `298 passed, 1 skipped`，Ruff、
  compileall 与 `git diff --check` 通过。
- [x] 多轮 usage 跨轮累积 parity（2026-09-07）：AgentLoop 与 legacy Graph
  一致地逐轮相加 token 用量，事件 payload 与最终结果均携带累计值；
  `merge_usage()` 收敛到 contracts 单点。
- [x] usage 累积修复后全量核心回归 `300 passed, 1 skipped`，Ruff、
  compileall 与 `git diff --check` 通过。
- [x] max_turns 边界语义按 Pi/legacy 对齐（2026-09-07）：达到上限的那次
  模型响应请求工具时该轮新工具不再执行，转为 `failed(max_turns_reached)`
  回填并发布失败事件，随后执行一次禁工具的收尾模型调用；两路成功执行上限
  轮数一致（N 上限执行 N-1 轮），灰度仅多一条 failed 记录事件。参考 Pi
  `failToolCallsFromTruncatedMessage`（输出上限截断时工具不执行）。
- [x] REST SSE max_turns 收尾 parity 补全（2026-09-07）：新增流式入口
  max_turns 对照用例，灰度与 legacy 均以收尾 `completed`（“已到执行上限，
  基于已有信息回答。”）终结、模型调用 3 次、不卡死不丢尾；灰度把达上限轮
  工具记为 `failed(max_turns_reached)`（记录口径差异）。全量核心回归
  `301 passed, 1 skipped`，Ruff（任务范围）、compileall 与
  `git diff --check` 通过。
- [x] WS max_turns 收尾 parity 补全（2026-09-07）：`stream_embed_chat`
  灰度与 legacy 均以 `message_completed` 终结、loop 落 `completed`、收尾
  正文一致、模型调用 3 次；两路第 1 轮 lookup 步骤 `succeeded`，灰度第 2 轮
  达上限的 lookup 记为 `failed` 工具步骤（legacy 不记录未执行的上限轮调用）。
  同步补齐 WS 灰度工具轮事件到步骤映射的首个自动化覆盖。全量核心回归
  `302 passed, 1 skipped`，Ruff（任务范围）、compileall 与
  `git diff --check` 通过。
- [x] WS confirmation 确认恢复 parity（2026-09-07）：模拟 dispatcher
  “回调内等待页面决策 → 放行”分别驱动 legacy 与灰度；批准后两路都调用
  2 次模型、事件序列一致、pay 步骤 succeeded、loop completed；拒绝后两路
  都把 pay 步骤记为 failed、模型仍正常收尾、loop completed（拒绝不升级整
  请求失败、不伪装成取消、不自动重试）。全量核心回归 `304 passed,
  1 skipped`，Ruff（任务范围）、compileall 与 `git diff --check` 通过。
- [x] WS ask_user 提问恢复 parity（2026-09-07）：模拟 dispatcher 在工具
  回调内等待用户答复后放行，legacy 与灰度都以 `message_completed` 终结、
  模型调用 2 次、事件类型序列一致、ask_user 步骤 succeeded、loop
  completed、收尾正文一致（基于用户选择的“合并”）；提问不误判为终止或
  失败。全量核心回归 `305 passed, 1 skipped`，Ruff（任务范围）、compileall
  与 `git diff --check` 通过。
- [x] WS 灰度取消路径 parity（2026-09-07）：灰度开关开启时在模型流式正文
  首条 message_delta 处取消，`CancelledError` 原样传播，只有用户消息落库、
  不写助手完成消息、loop 保持 running（取消不伪装成失败/完成终态），与
  legacy 取消语义一致。全量核心回归 `306 passed, 1 skipped`，Ruff（任务
  范围）、compileall 与 `git diff --check` 通过。
- [ ] REST 非流式与 REST SSE 的真实人工测试（灰度开关开启）待最终统一测试执行。
- [ ] WS 断线重连后的前端消息列表渲染问题按用户要求延期，不属于本 request 后端验收范围。

## 阶段 8 增量进度（2026-09-08/09：收敛单一 AgentLoopAgentRuntime 并删除 legacy）

- [x] 8A 真实模型缓解迁入 AgentRuntime（用户确认选项甲）：AgentLoop
  `on_model_error` 一次性降级重试钩子，REST 非流式/REST SSE/WS 三协议接入
  context-length 降级与 WS 纯文本拒图降级；`efb64f3`/`14dcac4`。全量核心
  回归 `312 passed, 1 skipped`。
- [x] 8B REST/SSE/WS 生产三协议统一只走 `AgentLoopAgentRuntime`，删除三处
  legacy 分支与 `agent_runtime_enabled` 配置开关；`82c48f5`。
- [x] 8C 删除 legacy 主循环（run_graph/_stream_graph/stream_graph/
  _finish_tool_loop 等）及仅其引用的私有助手、graph_bridge/legacy_adapter 与
  其测试；runtime.py 2226 → 约 1395 行。选项甲删除两处不复现的 legacy 独占
  行为（页面工具预算超限即停 + 固定文案；max_turns 收尾失败回退固定文案）。
- [x] 8D 直连 legacy 测试收敛：已覆盖→删冗余；未覆盖→迁移到新入口单测
  （build_langchain_messages 多模态 user content、build_history_messages 历史
  注入/附件还原）；thinking 提取收口到 message_text.extract_thinking_text。
  收敛后全量核心回归 `283 passed, 1 skipped`，Ruff（任务范围）、compileall、
  `git diff --check` 通过。
- [x] 8E 自动化收尾记录完成（本小节 + verify.md + plan.md + meta.json）。
- [ ] 最终 REST 非流式 / REST SSE 真实人工测试仍待用户执行（按用户要求延后，
  不阻塞自动化）。

## 当前阻塞与解除条件

- 最终验收前置项：REST 非流式与 REST SSE 的真实人工测试（灰度开启），以及
  可选的 host tool 长耗时/超时真实场景回归。REST 人工测试按用户要求延后，
  不阻塞后端自动化持续推进，因此 request 当前保持 `verify/active`。
- 解除条件：用户完成统一人工测试并反馈结果；确认通过后可将 request 置为
  `done` 并完成最终验收记录。
