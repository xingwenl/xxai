# Changelog

## - 2026-10-13
- ✨ feat：新增「工作流」能力——无画布的多步编排：定义 N 个有序步骤，agent 步骤跑一轮 Agent、tool 步骤调一次已注册的内置/MCP 工具；步骤之间用数组选择器显式传值（`input_bindings: [{name, value_selector: [step_id, "output"]}]`），提示词里写 `{{step_id.output}}`。定义以 JSON（`nodes` + `edges`，节点/边 id 是稳定字符串而非自增行号）存 `workflows.definition`，每次保存 `version` +1，单条上限 50 步（对齐 Dify 的单执行路径上限）；每次运行把定义快照冻结进 `workflow_runs.definition_snapshot` 并记 `definition_version_id`，因此改定义之后历史运行仍能解释自己（不建版本表、不做 diff 与回滚）。新增 `workflows` / `workflow_runs` / `workflow_step_runs` 三张表（迁移 `20261013_0036`）、`/api/v1/platforms/{platform_id}/workflows` 接口族（列表/创建/详情/修改/删除/手动运行/运行列表/运行详情）与 `/workflows` 前端页面（列表 + 详情 + 手动运行 + 每步结果，步骤用表单式有序列表，无画布与拖拽）。`🧑‍💻 lixingwen`
- ✨ feat：工作流的失败语义与保存期校验——每个步骤可声明 `on_error`（`abort` / `continue_with_default`，`fail_branch` 只在枚举里占位、v1 不实现）与 `max_retries`：失败后用**同一份输入**重试，全部尝试用尽才落 `on_error`，`continue_with_default` 时后续步骤照跑、步骤记录以 `on_error_applied` 如实指出「哪一步是带着兜底值过去的」。保存期即拒绝：引用排在其后的步骤、重复 `step_id`、步骤数超上限、边指向不存在的步骤、agent 步骤误带输入绑定、工具步骤声明 `financial` 之类不可自动批准的 `side_effect`、步骤覆盖的 Agent 属于其它平台（跨租户）。步骤输出走双通道：`model_visible_output` 进下一步（超 50KB 截断并带标记）、`raw_output` 保留全量供界面与审计。`🧑‍💻 lixingwen`
- ✨ feat：工作流接入任务调度器——`tasks` 新增可空 `workflow_id`：绑定了工作流的任务到点触发工作流而不是跑单轮 Agent，未绑定的任务行为一字不变。复用同一套 `FOR UPDATE SKIP LOCKED` 抢占、部分唯一索引保证「同一工作流同时只有一条 running」（PostgreSQL 与 SQLite 两方言都写 `where`）、看门狗按各自 `timeout_seconds` 收敛被强杀留下的 running 记录；跳过原因沿用 `overlapped` / `workflow_paused` / `deadline_missed`，超过 5 分钟宽限的陈年触发点不补跑以免进程重启后成批补跑。执行身份由触发源决定（定时触发沿用任务身份、手动触发用当前登录用户，不在定义里固定存身份），每个步骤一次独立会话，步骤之间天然获得上下文隔离。`🧑‍💻 lixingwen`
- ♻️ refactor：`conversation/services.py` 把原先重复两处的运行时工具清单组装抽成 `build_runtime_tool_list(context)`——工作流的工具步骤与聊天链路必须按同一份清单找工具对象，复制一份迟早漂移。`🧑‍💻 lixingwen`
- 📝 docs：新增 ADR `docs/adr/0002-workflow-orchestration-module-boundary.md`（独立 workflows 模块、定义存 JSON、运行快照必需而版本表可选、失败语义挂在步骤属性上）与 `docs/design/agent-workflow-orchestration-research.md`（对照 Dify / n8n / LangGraph / Temporal / GitHub Actions 的官方实现取证与结论），`CONTEXT.md` 新增工作流、工作流步骤、工作流运行、步骤运行、定义快照、数组选择器 6 个术语。`🧑‍💻 lixingwen`
- 🐛 fix：修掉工作流前端在真实浏览器里打不开的根因——接口层类型是手写的、与后端 payload 不一致，`tsc` 永远绿而界面一渲染就崩或显示空值。后端 `WorkflowRead` 只返回 `definition` 不返回 `steps`，前端改用 `toWorkflow`/`nodeToStep` 适配器按 `seq` 从 `definition.nodes` 还原步骤；运行详情缺 `raw_output_size`/`output_truncated`，改由 `WorkflowStepRunDetail` 的计算字段返回（不落库，避免多一份会漂移的真相）；`Workflow`/`WorkflowRun` 类型里删掉后端并不返回的 `created_at`/`updated_at`，列表「最近运行」改用 `finished_at ?? started_at ?? planned_at`。以上四处均由 Playwright 打真实后端 + 真实前端复验（列表 / 定义 / 运行记录 / 运行明细四屏 14 项断言全过）。`🧑‍💻 lixingwen`
- ✨ feat：工作流补做并收紧三处——①每步可选「失败重试次数」`max_retries`（0–5，用**同一份输入**重试，全部用尽后才落 `on_error`，`retry_count` 记实际尝试次数；这是拷问阶段已批准、第一版漏实现的）；②选择器路径在**保存时**就只接受 `output`：`{{step.other}}` 与非 `output` 的输入绑定直接拒绝且不写库，不再等到运行到一半才报错（`validators.OUTPUT_PATH`，与 runner 共用同一常量）；③运行详情新增计算字段 `raw_output_size`/`output_truncated` 供界面判断截断。前端表单相应新增「失败重试次数」下拉、输出路径只读（只有 `output` 一个合法值），重试徽标按新语义改显示「尝试 N 次」。`🧑‍💻 lixingwen`
- 📝 docs：`docs/harness/requests/2026-10-13-workflow-orchestration/spec.md` 变更点补记第二轮收口，`verify.md` 重新生成（迁移往返、PG/SQLite 部分唯一索引、`pytest tests/workflows` 89 passed、`pytest tests/tasks` 69 passed、`ruff` 全绿、端到端探针含保存期拒绝与重试共 11 步全通过）。`🧑‍💻 lixingwen`

## - 2026-10-01
- ✨ feat：MCP 新增 `MCP_ALLOW_PRIVATE_ENDPOINTS` 开关，支持接入本机/内网自建 MCP 服务——此前 MCP endpoint 一律要求公网可达（`is_global`），`http://127.0.0.1:4545/mcp` 这类本地服务会直接被拒（`MCP endpoint is not public`）。开关默认 `false`（行为不变），置 `true` 后额外放行回环与私网地址，包括容器内访问宿主机的 `host.docker.internal`；链路本地地址（`169.254.0.0/16`、`fe80::/10`，含云元数据 `169.254.169.254`）与其它保留段在开关开启时仍被拒绝。注意两处校验时机不同：`endpoint_url` 写 IP 字面量时在新建/编辑保存即校验，写域名时在同步工具与调用时按解析结果校验；Docker 部署的取值来自根目录 `.env`（`apps/backend/.env` 仅本地直接运行后端时生效）`🧑‍💻 lixingwen`

## - 2026-09-29
- ✨ feat：删除会话改为两步确认——与「清除聊天记录」共用新增的 `useTwoStepConfirm` 状态机：首次点击只把该行删除按钮从 26px 圆形图标放宽成「确认？」胶囊（`aria-label` 同步改为「确认删除会话 X」），3 秒内对同一条再点一次才真正调用 `deleteConversation()`；超时、点到别的行、列表刷新（切换/新建会话）或组件卸载都会复位，同一时刻只有一行处于待确认态。此前删除会话是即点即删，与「清除聊天记录」的确认口径不一致；顺带把清除记录的内联定时器逻辑抽到同一状态机，行为保持不变。新增状态机单测（首点不触发、二次生效并复位、超时取消、切目标重置、数字/字符串 ID 互通），浏览器验证脚本新增删除与清空记录的两次点击、超时自动取消、待确认态可访问名称断言 `🧑‍💻 lixingwen`
- ✨ feat：AI SDK 聊天面板动效与可访问性收口——会话列表收起/展开改为宽度过渡（内容同步淡出、右侧描边同步归零），窄屏抽屉改为位移滑入 + 遮罩淡入，新增 `--agent-motion-*` 动效令牌统一时长与缓动，并在 `prefers-reduced-motion: reduce` 下全部关闭；收起后的列表宽度为 0 且 `visibility: hidden`，不再留 1px 残线占位、也不会被键盘 Tab 命中。连接状态点改为随状态变化（已连接=绿 / 连接中·重连中=琥珀呼吸 / 错误=红 / 未连接=灰），修正此前「连接错误仍显示常亮绿点」的误导，并以 `role="status"` 播报状态变化。新增键盘 `:focus-visible` 焦点环（图标按钮与列表项，输入框沿用自身焦点环）；触屏（`hover: none`）下会话删除按钮由「悬停才显」改为常显，消除「看不见却能盲点删除」；会话标题与新建/删除按钮补 `title` 悬停提示。验证脚本新增过渡中间帧、抽屉位移与遮罩透明度、状态点配色、触摸媒体特性断言 `🧑‍💻 lixingwen`
- ✨ feat：AI SDK 双栏会话列表支持手动收放——header 头像左侧新增会话列表开关（面板图标 + 方向箭头），宽屏点击收起/展开常驻列表（收起后对话区独占整宽，按钮留在头部可再展开），窄屏点击展开列表抽屉（关闭沿用点遮罩/选中会话的既有交互，因为抽屉会盖住 header），按钮带 `aria-label`/`aria-expanded`（「隐藏会话列表」/「显示会话列表」）；原先窄屏头部左侧的汉堡按钮并入该开关，`layout: 'desktop'` 之外的布局不渲染它。README「PC 双栏与会话列表」同步补充该交互，浏览器验证脚本新增按钮位置、收放双向、真实指针命中与 aria 状态断言 `🧑‍💻 lixingwen`

## - 2026-09-21
- ✨ feat：AI SDK 新增「思考模式」与「Agent 过程卡片」两个接入方开关，**默认均为关闭**、显式传 `true` 才开启——`thinking`（顶层）随每次 `message_send` 下发，由后端按厂商翻译为上游参数（DeepSeek 下发顶层 `thinking.type`；其余厂商关闭时用 `reasoning_effort: "none"`），可用 Agent 版本 `model_options.thinking.{on,off}` 显式覆盖映射；`ui.showAgentSteps` 控制是否渲染思考/工具/技能/知识库过程卡片，关闭时只保留对话正文。因上游 DeepSeek 的思考默认是 `enabled`，SDK **显式下发**关闭参数而非省略字段；网关对非布尔 `thinking` 返回 `invalid_thinking`。**升级注意**：旧版本升级后思考与过程卡片将默认不再显示，需显式开启，详见 README「思考模式与过程卡片开关」`🧑‍💻 lixingwen`
- 🐛 fix：修复 `apps/ai-sdk/package-lock.json` 长期不同步导致 CI `npm ci` 失败——lock 版本停留在 `0.1.0`（package.json 已 `0.1.7`）且缺少 `echarts`/`jsdom`/`mermaid`；同时把测试实际依赖但从未声明的 `@vue/server-renderer` 补进 devDependencies（pnpm 严格布局下原先无法解析），并给用到 DOMPurify 的 SSR 测试显式声明 jsdom 环境 `🧑‍💻 lixingwen`

## - 2026-09-20
- 🐛 fix：PC 双栏断点改按「聊天面板自身宽度」判断，并修正适用范围——原先用 `window.innerWidth`，导致 430px 悬浮窗停在宽视口时不降级、260px 常驻列表把对话区挤到 170px；现悬浮/嵌入两种模式一律按面板实际宽度判断，悬浮窗拖拽缩放后重新判断，`layout: 'desktop'` 对 floating 同样生效（把窗口拉宽到 900px 即常驻列表）。同时修复面板在 `isOpen` 后才挂载导致观察器未建立、嵌入式窄容器不降级的问题 `🧑‍💻 lixingwen`
- 🐛 fix：修复 PC 双栏布局下聊天时/聊天后左侧会话列表不刷新——`conversations_changed` 原先只在新建/删除时发出，发消息与回答完成两条路径都不触发，加上 `ChatWidget.handleMessage` 里「先赋值再判断」导致刷新条件恒为假，用户发完消息仍看到「还没有历史会话」。现由 SDK 在「会话从无到有」与「回答完成/失败」两个终态发出该事件，UI 统一由事件刷新，流式期间不重复请求列表接口 `🧑‍💻 lixingwen`
- ✨ feat：AI SDK 支持 PC 双栏布局与左侧会话列表——新增 `ui.layout: 'desktop'`（左列表 + 右对话区）与 `ui.sidebar.width`，窄于 768px 自动退化为单栏并把列表收进抽屉；新增 `listConversations()` / `openConversation()` / `startNewConversation()` / `deleteConversation()` 与 `conversations_changed` 事件，切换会话时原子重置消息、pending 流式态与重放游标，避免「历史消息 + 上一条流式回答」串台 `🧑‍💻 lixingwen`
- ✨ feat：Embed 新增会话列表与删除接口——`GET /api/v1/embed/conversations`（按平台 + token 主体 + Agent 隔离，`created_at` 倒序分页，返回轻量投影）与 `DELETE /api/v1/embed/conversations/{id}`；删除采用**软删除**（只标记 `status='deleted'`），消息、附件与 `model_usage_records` 计费数据一律保留，避免级联销毁用量记录；软删除会话不可再被解析续聊，跨主体访问按 404 处理不泄露存在性 `🧑‍💻 lixingwen`
- 📝 docs：AI SDK README 新增「PC 双栏与会话列表」章节，写明布局约定、会话 API 与软删除语义 `🧑‍💻 lixingwen`

## - 2026-09-19
- 📝 docs：Harness 升级为 v2「按 diff 分档的三道门」——六阶段（research/spec/plan/implement/verify/acceptance）与六份文档收敛为三道门（想清楚/做出来/证明它）与最多两个文件（`spec.md` + `verify.md`）；分档看 diff 路径（A 架构级 / B 契约级 / C 局部），C 档不写文档不建 request、直接一次提交；新增 `docs/harness/HARNESS-V2.md` 作为新任务唯一流程依据，`AGENTS.md` 与 `docs/harness/README.md` 同步改指向。2026-09-20 之前创建的 59 个 request 一律冻结，不迁移、不补文档 `🧑‍💻 lixingwen`
- 🔧 chore：Harness v2 门禁落地——`tools/harness/audit.py` 重写为 v2 分档校验（frontmatter、必需章节、被否决项非空、spec ≤150 行、连续代码块 ≤30 行、A/B 档验证脚本可执行、A 档 ADR 关联），对存量 request 自动跳过；新增 `tools/harness/verify.sh` 运行器与 `tools/harness/verify/_template.sh` 模板，验证证据改由脚本产出并记录 `ranAt`/`exitCode`；新增 `.github/workflows/harness.yml` 在 CI 执行审计并检查验证脚本可执行权限 `🧑‍💻 lixingwen`

## - 2026-09-19
- 🐛 fix：修复「立即运行一次」永不执行、最终被判超时失败——调度器原先只派发自己在本 tick 创建的记录，而手动触发只入队无人认领（记录停在 running 直到被看门狗判 600 秒超时，任务实际从未执行）。现调度器每 tick 额外认领所有已排队记录（含进程重启遗留），统一「到点触发」与「手动触发」的执行路径，并用 `FOR UPDATE SKIP LOCKED` 保证多副本下不重复认领；执行记录口径明确为 `running + started_at IS NULL` = 已排队待执行 `🧑‍💻 lixingwen`
- ✨ feat：任务执行历史支持展开查看执行过程——新增 `GET /tasks/{task_id}/runs/{run_id}/detail`（复用 `build_loop_payload`），前端逐步展示思考、工具调用、结果与错误；对无步骤的记录明确提示「可能从未真正执行」，用于区分「没跑」与「跑了一半失败」 `🧑‍💻 lixingwen`
- 🐛 fix：修复 Embed/AI SDK 链路无法创建定时任务（工具报 `task_requires_user_identity`）——`create_task` 原实现只认后台用户身份，而 Embed 链路只有终端用户 principal；`tasks` 新增 `run_as_end_user_id` 列（迁移 `20260919_0035`），`run_as_type` 扩为 `user`/`end_user`，无人值守执行复用既有 `create_for_principal` 机制以终端用户身份建会话，后台链路行为不变，错误信息改为可操作的中文说明 `🧑‍💻 lixingwen`
- ✨ feat：新增「任务」能力——一条任务 = 智能体 + 指令 + 时间触发规则，到点由独立调度容器无人值守地跑完一轮 Agent 并以新会话落地（新增 `tasks` / `task_runs` 两张表、迁移 `20260919_0034`、`/api/v1/platforms/{platform_id}/tasks` 接口族与 `/tasks` 前端页面），调度采用 `FOR UPDATE SKIP LOCKED` 抢占 + 同事务推进 `next_run_at`，错过触发点不补跑、同一任务串行（重叠触发记为 `skipped(overlapped)`） `🧑‍💻 lixingwen`
- ✨ feat：无人值守运行的审批边界——`auto_approve` 自动批准、`strict_approval` 只批 `navigation`、`financial` 类一律不批准（跳过并给出原因让模型调整），拒绝原因与自动批准次数落执行记录，可追溯到哪条任务的哪次运行 `🧑‍💻 lixingwen`
- ✨ feat：新增内置业务工具 `create_task`，智能体可在会话中创建定时任务（绑定当前会话的执行身份：后台会话绑登录用户、Embed 会话绑终端用户，受最小间隔与平台任务数上限约束） `🧑‍💻 lixingwen`
- ✨ feat：调度看门狗——把超过单次超时仍处于执行中的任务运行标记为失败，兜住进程被杀留下的永久 `running` 记录 `🧑‍💻 lixingwen`
- ♻️ refactor：把 REST 对话的工具分派抽成可复用构造函数 `conversation/tool_dispatch.py`，与无人值守任务共用一份分派逻辑；顺带修复 REST 链路调用 MCP 工具时缺少 `server_id`/`tool_name`/`arguments` 导致的 TypeError `🧑‍💻 lixingwen`
- 🐛 fix：修复宿主工具"页面执行成功但模型总是收到工具执行失败/超时"——审计时间列读写口径统一为带时区 UTC（读侧归一化 + 写侧 aware，ORM 映射对齐迁移），消除"naive 与 aware 相减抛 TypeError"和"naive 写入 timestamptz 偏移 8 小时导致等待窗口为 0"两类静默失败，并补齐 `wait_timeout_seconds` / `Host tool wait window already expired` / `Host tool future registered|released` / `pending_keys` / `Tool step failed detail` / `Tool invocation raised` 日志 `🧑‍💻 lixingwen`
- 🐛 fix：Docker 后端日志按服务分文件落盘（`/app/logs/{api,worker,wechat-bot}/app-<日期>.log`），统一容器时区为 Asia/Shanghai，并给容器 stdout 补充 json-file 体积上限 `🧑‍💻 lixingwen`
- 🐛 fix：微信机器人每分钟心跳改为状态变化时才打 INFO（未变化降为 DEBUG），避免淹没同文件内的真实业务日志 `🧑‍💻 lixingwen`
- 🔍 observability：宿主工具执行链路全量关键日志（网关下发/结果/失败/超时/忽略、工具步骤终态、SDK `[xxai-agent][host-tool]`），并修复 SDK 执行前工具丢失时静默返回导致服务端空等超时 `🧑‍💻 lixingwen`
- 🐛 fix：修复页面注册的宿主工具未绑定给模型导致模型永远无法调用（`merge_model_tools` 合并入口工具与宿主工具），并新增注册/绑定关键排障日志与重放失败降级 `🧑‍💻 lixingwen`
- 📝 docs：补充桌面接入排错说明——AI Base 站点根不能填业务平台地址（路径前缀相同，填错会拿到业务平台的 404 响应） `🧑‍💻 lixingwen`

## - 2026-09-18
- ✨ feat：shop-agent 会话接口支持项目固定的 Embed Client 常量（PROJECT_EMBED_*），凭证只留在服务端，优先级为请求凭证 > 项目常量 > 环境变量 `🧑‍💻 lixingwen`
- ✨ feat：shop-agent 会话接口支持调用方携带自己的 Embed Client 凭证（clientId/clientSecret），一个部署可接入多个 Client，缺省仍沿用服务端配置 `🧑‍💻 lixingwen`
- ✨ feat：shop-agent 会话接口支持可选 agentId 与 hostToolNames，桌面/多 Agent 接入可按调用方选择 Agent 并启用宿主工具 `🧑‍💻 lixingwen`
- ✨ feat：CORS 允许来源改为 CORS_ORIGINS 配置，默认保持原有本地开发来源，便于登记桌面客户端等新来源 `🧑‍💻 lixingwen`
- 📝 docs：补充 AI SDK 桌面客户端（Electron）接入章节：http origin 要求、来源登记、主进程换取 token 与宿主工具生效条件 `🧑‍💻 lixingwen`
- 🐛 fix：修复 ask_user 回答与 MCP/宿主工具回调被入站 requestId 校验静默丢弃，问答链路挂起到超时 `🧑‍💻 lixingwen`
- 🐛 fix：修复流式对话请求级数据库 Session 被跨 Task 并发使用导致 close/commit 相撞（agent_request_failed / IllegalStateChangeError），模型 Task 在 Session 关闭前显式取消并 join，工具执行改用独立 Session `🧑‍💻 lixingwen`
- 🧰 chore：清理调试日志与本机调试残留 `🧑‍💻 lixingwen`

## - 2026-09-17
- ✨ feat：AI SDK 支持 Markdown 内联图表，内置 mermaid/echarts 渲染器与自定义语言注册接缝 `🧑‍💻 lixingwen`
- ✨ feat：接入 OpenCode Zen Go，按会话注入 x-opencode-session 与自有 User-Agent，非 OpenCode 端点零改动 `🧑‍💻 lixingwen`

## - 2026-09-09
- ♻️ refactor：阶段 8 收敛单一 AgentRuntime——删除 legacy 主循环死代码与 graph_bridge/legacy_adapter，直连 legacy 测试迁移到新引擎/共享函数入口 `🧑‍💻 lixingwen`

## - 2026-09-07
- ✨ feat：Agent 主循环统一与灰度 parity 自动化 `🧑‍💻 lixingwen`

## - 2026-09-03
- ✨ feat：工具查询结果跨轮记忆与上下文预算护栏 `🧑‍💻 lixingwen`

## - 2026-09-02
- ✨ feat：Agent 运行时自感知，系统提示词注入模型/配置/版本，新增 get_runtime_info 用量工具 `🧑‍💻 lixingwen`
- ✨ feat：接入店铺运营系统，支持会话级店铺/订单查询与 ShopList 展示 `🧑‍💻 lixingwen`

## - 2026-09-01
- 📝 docs：补充一个服务接入多个 Agent 的接入手册 `🧑‍💻 lixingwen`
- 📝 docs：轻量策略技能引用改为 grill-with-docs `🧑‍💻 lixingwen`
- ♻️ refactor：EmbedRepository 继承 BaseRepository `🧑‍💻 lixingwen`
- ✨ feat：优化技能调用策略并新增 request 审计工具 `🧑‍💻 lixingwen`
- ✨ feat：支持嵌入式模式，聊天 UI 可挂载到指定容器 `🧑‍💻 lixingwen`

## - 2026-08-31
- 🐛 fix：切换国内镜像源修复容器构建，补全 skill-runner 启动 `🧑‍💻 lixingwen`

## - 2026-08-30
- ♻️ refactor：网关事件集中注册并合并对话工具循环 `🧑‍💻 lixingwen`
- ✨ feat：AI SDK 自定义组件端到端打通，支持模型驱动渲染宿主组件 `🧑‍💻 lixingwen`

## - 2026-08-28
- ✨ feat：附件主动检索工具 attachment_search 与截断注入提示 `🧑‍💻 lixingwen`
- ✨ feat：Agent 版本表单暴露附件能力矩阵配置 `🧑‍💻 lixingwen`
- 🐛 fix：附件 embedding 维度配置修正与向量回填脚本 `🧑‍💻 lixingwen`
- 🐛 fix：attachment_search 关键词测试在配置 embedding 后误打真实 API `🧑‍💻 lixingwen`
- ♻️ refactor：内置工具注册表合并为单一来源并直连真实 handler `🧑‍💻 lixingwen`
- ✨ feat：Agent 版本列表展示模型 Base URL 并升级 xxai-agent 至 0.1.5 `🧑‍💻 lixingwen`
- 🧰 chore：移除应用卡片调试日志 `🧑‍💻 lixingwen`
- 🧰 chore：新增 ToolVerse 玻璃拟态仪表盘演示页 `🧑‍💻 lixingwen`
- 📝 docs：新增 DSH「万物皆插件」思想借鉴与落地方案 `🧑‍💻 lixingwen`

## - 2026-08-27
- ✨ feat：会话级 embedding 与 pgvector 检索 `🧑‍💻 lixingwen`
- ✨ feat：文件附件支持加载与点击下载 `🧑‍💻 lixingwen`
- ✨ feat：平台模型注册表、Agent 绑定与前端管理界面 `🧑‍💻 lixingwen`

## - 2026-08-26
- ✨ feat：文件附件上传、解析切块与当前会话缓存（Phase 1） `🧑‍💻 lixingwen`
- ✨ feat：Word/Excel 附件解析依赖与真实样例测试 `🧑‍💻 lixingwen`
- ✨ feat：文档附件解析文本注入模型 `🧑‍💻 lixingwen`
- ♻️ refactor：内置工具执行改为处理器注册表分发 `🧑‍💻 lixingwen`
- ✨ feat：历史附件上下文恢复与文本缓存 `🧑‍💻 lixingwen`

## - 2026-08-25
- ✨ feat：增加图片生成读取与鉴权展示 `🧑‍💻 lixingwen`

## - 2026-08-24
- ✨ feat：ai-sdk 对话新增结构化询问能力（ask_user） `🧑‍💻 lixingwen`
- 🐛 fix：model_tokens 超限不再吞掉已生成回答 `🧑‍💻 lixingwen`
- ✨ feat：ai-sdk 认证后下发 client/agent 信息与配额快照并展示 client 名称 `🧑‍💻 lixingwen`

## - 2026-08-23
- ✨ feat：后台可管理的微信助手并支持对话上下文复用 `🧑‍💻 lixingwen`

## - 2026-08-21
- ✨ feat：增加 Agent 迭代轮数上限并在页面工具预算耗尽时停止 `🧑‍💻 lixingwen`
- ✨ feat：搭建插件化应用框架与 React 宿主壳（zip 安装、宿主 SDK、全屏沉浸） `🧑‍💻 lixingwen`
- ✨ feat：新增书签整理内置 React 子应用并支持插件类型区分 `🧑‍💻 lixingwen`
- ✨ feat：统一应用品牌配置并接入桌面图标 `🧑‍💻 lixingwen`
- ♻️ refactor：应用卡片抽离组件并统一毛玻璃样式 `🧑‍💻 lixingwen`
- ✨ feat：支持从 URL 添加远程壳插件 `🧑‍💻 lixingwen`

## - 2026-08-20
- ✨ feat：新增 pywebview + FastAPI 桌面应用脚手架 `🧑‍💻 lixingwen`

## - 2026-08-13
- ♻️ refactor：抽取运行时工具分发器并修复 embedding 批次超限 `🧑‍💻 lixingwen`
- ✨ feat：AgentLoop 过程可观测与思考内容实时展示落库 `🧑‍💻 lixingwen`
- ✨ feat：聊天窗支持拖拽缩放、本地持久化与清除聊天记录 `🧑‍💻 lixingwen`

## - 2026-08-11
- ✨ feat：完善接入文档与本地工具演示 `🧑‍💻 lixingwen`
- ✨ feat：支持系统提示词与本地会话续聊 `🧑‍💻 lixingwen`

## - 2026-08-10
- 🐛 fix：修复会话历史与会话标识传递 `🧑‍💻 lixingwen`
- 🧰 chore：同步 SDK 与页面交互改动 `🧑‍💻 lixingwen`

## - 2026-08-07
- ✨ feat：增加内置工具并接入 Embed MCP `🧑‍💻 lixingwen`

## - 2026-08-06
- ✨ feat：支持工具场景原生流式对话 `🧑‍💻 lixingwen`
- 🐛 fix：统一错误事件结束对话 `🧑‍💻 lixingwen`
- 🐛 fix：限制模型重试避免请求挂起 `🧑‍💻 lixingwen`
- ⚡ perf：优化知识库与技能按需注入 `🧑‍💻 lixingwen`
- 🐛 fix：修复生成中过程面板实时展示 `🧑‍💻 lixingwen`

## - 2026-08-05
- ✨ feat：增加可观测消息和玻璃态聊天 UI `🧑‍💻 lixingwen`

## - 2026-08-04
- ✨ feat：补知识库绑定智能体入口并增强聊天过程日志 `🧑‍💻 lixingwen`
- 🐛 fix：修复 worker 日志不落到宿主挂载目录 `🧑‍💻 lixingwen`
- ✨ feat：支持全栈容器化与知识库向量配置 `🧑‍💻 lixingwen`
- ✨ feat：支持 Zip 技能包和隔离脚本执行 `🧑‍💻 lixingwen`

## - 2026-08-03
- ✨ feat：新增后端日期文件日志 `🧑‍💻 lixingwen`

## - 2026-08-01
- ✨ feat：增加本地工具演示并修复策略状态更新 `🧑‍💻 lixingwen`

## - 2026-07-31
- ✨ feat：新增模型用量统计后台 `🧑‍💻 lixingwen`
- 🐛 fix：完善 npm 发布包契约 `🧑‍💻 lixingwen`
- ✨ feat：优化短期令牌与用户身份接入 `🧑‍💻 lixingwen`
- ✨ feat：接入 Agent 内部页面导航 `🧑‍💻 lixingwen`
- 🐛 fix：修复宿主工具 Schema 注册 `🧑‍💻 lixingwen`
- 📝 docs：固化 SDK 对话流程与变更规范 `🧑‍💻 lixingwen`
- ✨ feat：完善宿主工具与平台接入 `🧑‍💻 lixingwen`
- ✨ feat：支持 Embed Client 临时页面工具 `🧑‍💻 lixingwen`

## - 2026-07-30
- ✨ feat：完成 Agent SDK Phase 2C 生产增强 `🧑‍💻 lixingwen`
- ✨ feat：接入后台管理前端和 AI 模块 `🧑‍💻 lixingwen`
- ✨ feat：新增模型用量明细表 `🧑‍💻 lixingwen`
- ✨ feat：完善 AI 管理后台配置 `🧑‍💻 lixingwen`
- 📝 docs：记录模型用量统计设计 `🧑‍💻 lixingwen`

## - 2026-07-29
- ✨ feat：完成 Phase 2B 宿主工具自动调用 `🧑‍💻 lixingwen`

## - 2026-07-28
- ✨ feat：完成 Agent SDK 原生 `ai-agent.v1` WebSocket transport、流式消息、引用展示、停止生成和有限重连基础
- 📝 docs：增加 Phase 2A 本地联调手册，并记录真实基础设施验收前置条件

## - 2026-07-26
- 📝 docs：完成可配置 Agent 第一阶段验收 `🧑‍💻 lixingwen`
- 🐛 fix：固定 AI Agent SDK 兼容的 TypeScript 版本 `🧑‍💻 lixingwen`
- 📝 docs：完成第二阶段需求与启动计划 `🧑‍💻 lixingwen`

## - 2026-07-24
- ✨ feat：新增 AI Agent JavaScript SDK，包含核心客户端、WebSocket 传输、工具注册和 UI 组件 `🧑‍💻 lixingwen`

## - 2026-07-23
- ✨ feat：完成用户角色与认证基础能力 `🧑‍💻 lixingwen`

## - 2026-07-20
- ✨ feat：搭建后端基础设施并实现用户模块闭环 `🧑‍💻 lixingwen`
