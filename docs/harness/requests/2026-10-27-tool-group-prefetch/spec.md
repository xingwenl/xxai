---
id: 2026-10-27-tool-group-prefetch
tier: B
risk: medium
approval:
  required: true
  granted: false
  why: ["触及 Agent Loop 的工具绑定边界（架构边界变化）", "预取规则决定模型首轮可见工具集，需确认漏选/多选口径", "新增 ai-sdk 注册载荷字段，属跨 apps 契约变化"]
---

## 目标与范围

**做成什么**

在已上线的「注册全集 + 常驻目录 + `load_tool_group`」之上补三件事：

1. **首轮预取**：入口拿到用户消息后，用零成本关键词规则命中工具组，首轮直接绑定，
   把「一次加载」放在历史最短、缓存代价最低的时刻。
2. **目录恒定**：系统提示词里的工具目录在会话内文本不变，加载组不再改写目录。
3. **组声明统一**：宿主（ai-sdk / 桌面子应用）工具能声明自己属于哪个组，
   与后端内置组的添加方式对齐；后端也提供「注册工具组」的显式入口。

**不做**

- 不把工具组/工具落库，不做管理台分组页与组级开关（用户 2026-10-27 决策：后台改意义不大）。
- 不引入模型分类器 / Jev / embedding 检索：预取只用关键词规则，0 次额外模型调用。
- 不做前置硬过滤：预取只是「提前绑一组」，猜错仍靠 `load_tool_group` 与
  `tool_not_loaded` 全量兜底恢复。
- 不动业务工具语义，不合并 shop 四兄弟（另案），不改前端。

## 来源与方案比较

- 已交付（`1cc178c` / `7b52298` / `6036fc5`）：`apps/backend/app/modules/agent_runtime/tool_groups.py`
  的 `ToolGroupState` 提供 `catalog_text()`（只列**待加载**组）、`loader_tool()`（enum 只含待加载组），
  加载态由 `AgentLoopStep.step_metadata` 的 `tool_group` 键跨轮重放。
- 模型与缓存：默认 `ChatOpenAI` 走 OpenAI 兼容端点（`apps/backend/app/core/config.py:256`
  `model_default_name=deepseek-v4-flash`）。这条线只有**自动前缀缓存**，没有 `cache_control`
  断点、没有原生 deferred tool loading / `tool_search`——Pi 那套「无损加载」在这里不可用。
- 体积基线（实测，cl100k_base）：全量 19 工具 18,198 字符 ≈ 9.1k token；初始绑定
  REST 487 / WS 1,514 字符；目录文本 571；加载 `content` 组后 4,901；`ops` 组 5,842。
- 宿主工具入站契约：`apps/backend/app/modules/host_tool/schemas.py:97-100`
  `HostToolRegistration { name, description, input_schema }`——分组信息在链路上已丢失，
  现在只能靠 `apps/backend/app/modules/agent_runtime/tool_groups.py:33` 的前缀白名单猜。
- ai-sdk：`apps/ai-sdk/src/core/types.ts:185-193` `ToolDefinition` 无 `group`；
  `apps/ai-sdk/src/core/client.ts:1521-1547` 的 `registerTool`/`registerTools` 把定义剥成 wire 载荷。
- 方案比较（同一诉求的三种落法）：**①静态子集/白名单**（Pi 默认 4 个工具、Claude Code
  `--allowedTools`）：确定性最好，但换场景要人工改配置；**②协议级延迟加载**（Anthropic
  `defer_loading` + `tool_reference`、OpenAI `tool_search` / `additional_tools`、Kimi）：
  无损但只有特定模型支持，本项目默认 OpenAI 兼容端点用不上；**③入口预取 + 运行期自取**
  （Pi 扩展的 `search_tools` 示例、本仓库技能的常驻最小元信息 + `load_skill`）：不依赖
  模型能力、猜错可回退，缺点是要维护一份规则表。本例取 ③，用 ① 兜底（`host` 组常驻）。
- 先例：Pi 的默认激活集仅 4 个（`packages/coding-agent/src/core/sdk.ts:256`），
  入口决定初始集合、运行期模型自取；本仓库技能侧同样「常驻最小元信息 + `load_skill`」
  （`apps/backend/app/modules/skill/services.py:212-221`）。

## 缓存影响评估

一次工具组加载会让前缀 miss 两次：`tools` 数组变一次，`catalog_text()` 少了该组又变一次。
按缓存命中 token 约 1/10 计价估算，一次全前缀 miss（system+tools ~10k + 历史 20k）≈
30–40 次「命中轮」省下的量。由此定三条：

- **收益主要来自「加载次数少」，不是「选得准」**：预取把首次加载提前到历史≈0 的时刻，
  同样一次 miss 的绝对代价最小；目录恒定让「加载」只付 `tools` 一次 miss。
- 预取**只增不减**、最多 2 组，且与历史重放集合合并——同域多轮不会重复加载。
- 目录恒定的副作用：模型看不到「哪些组已加载」，只能靠 `load_tool_group` 的 enum
  （仅待加载组）判断；无脑重试已加载组会得到 `failed`，文案提示「已加载，直接调用组内工具」。

## 被否决的选项

- **工具组/工具落库 + 管理台配置**（最初要求，随后收回）：组是工程常量，与代码同源才能
  review 与回滚；落库会制造「库里的组」与「代码里的组」两套真相。否决。
- **模型分类器 / Jev 做预取**：多一次网络往返压在首 token 前，中文能力与延迟都未验证；
  规则版够用，先跑通再谈升级。否决。
- **前置意图硬过滤**：猜错即不可恢复（工具不在上下文里，模型只能收到 `tool_not_found`）。否决。
- **目录随加载态变化**（保持现状）：每次加载打两次 miss，收益被吃掉一半。否决。
- **按平台/Agent 各存一份组定义**：用户定「内置组全局一份」；多份会让同一工具在不同 Agent
  下归组不同，排障成本高。否决。
- **宿主工具继续按名字首段猜组**：`debug_ping`→`debug`、`navigate_to_page`→`navigate`，
  一个前缀一个组，目录会碎成几十个单工具组。改为显式声明 + 白名单回落。否决。
- **组级开关 UI / 前端改动**：用户明确不需要前端侧。否决。

## 停点判断

- **分档 B**：跨 `apps/backend/` 与 `apps/ai-sdk/`，且触及 Agent Loop 的工具绑定边界。
- **未命中 A**：不改 `models.py`（不落库）、不碰 migrations/auth/security，不新建模块目录。
- **审批触发**：架构边界变化（模型首轮可见工具集由入口规则参与决定）+ 契约变化（宿主注册载荷加字段）。
- **需用户确认**：预取关键词表初版权衡、预取组数上限、宿主组声明的字段名与粒度（见「待确认」）。

## 变更点

1. `apps/backend/app/modules/builtin_tool/groups.py`：新增 `DEFAULT_TOOL_GROUPS: tuple[str, ...] = ()`
   （跨会话默认加载组，默认空）与 `register_tool_group(name, title, description) -> None`
   （显式注册组的入口，重复注册报错、与 `TOOL_GROUP_META` 同源）；工具入组仍走
   `@business_tool(group=...)`，启动校验（`builtin_tool/registry.py:115` 附近）改为同时校验组已注册。
2. 新增 `apps/backend/app/modules/agent_runtime/tool_prefetch.py`：
   `PREFETCH_RULES: dict[str, tuple[str, ...]]`（组 → 关键词）、`MIN_PREFETCH_SCORE = 2`、
   `MAX_PREFETCH_GROUPS = 2`、`prefetch_tool_groups(message, available) -> set[str]`：
   按命中的关键词条数打分，取分数 ≥ 阈值的组按分数降序截断到上限；无命中返回空集；
   绝不返回 `available` 之外的组。纯函数、无 IO、无模型调用。
3. `apps/backend/app/modules/agent_runtime/tool_groups.py`：
   - `catalog_text()` 改为列**全部**非 `basic` 组（组名 + 标题 + 说明 + 组内工具名），与 `active` 无关。
   - `handle_loader_call` 对已加载组返回 `failed` + 「已加载，可直接调用组内工具」文案。
   - `ToolGroupState` 增加 `host_groups` / `host_group_meta` 两个映射，`tool_group()`、
     `group_meta()` 优先取声明值，未声明回落 `HOST_TOOL_GROUP_PREFIXES` → `host`。
   - `build_tool_group_state(tools, *, enabled=True, active_groups=None, host_groups=None, host_group_meta=None)`。
4. 三个新消息入口把预取与历史重放合并后传参（`active_groups=prefetch | replayed`，保持单调只增）：
   `conversation/services.py` 的 `_run_execute_chat_model_round`（:511 起）与 `stream_chat`（:904 起）、
   `gateway/runtime.py` 的 `stream_embed_chat`（:625 起）。
5. 宿主组声明链路（前后端添加方式对齐）：
   - `apps/ai-sdk/src/core/types.ts`：`ToolDefinition.group?: string`。
   - `apps/ai-sdk/src/core/client.ts`：`registerTool`/`registerTools` 透传 `group`，并新增
     `registerToolGroups(groups: { name; title?; description? }[])`，同走 `host_tools_register`。
   - `apps/backend/app/modules/host_tool/schemas.py`：`HostToolRegistration` 加 `group: str | None = None`。
   - `apps/backend/app/modules/gateway/router.py` 的 `_handle_host_tools_register`（:161-262）：
     把每项的 `group` 收进连接级 `registered_host_tool_groups`，组元数据收进
     `registered_host_tool_group_meta`；`temporary_tools` 分支同口径。
   - `apps/backend/app/modules/gateway/runtime.py`：两份映射传进 `build_tool_group_state`。

## 验收标准

1. 目录恒定：同一组工具清单下，加载任意组前后 `catalog_text()` 返回**完全相同**的字符串。
2. 预取命中：表驱动用例覆盖 8 个内置组的关键词，每条样例命中预期组；命中组数 ≤ 2；
   与 `available` 求交后不含未启用组。
3. 预取不误伤：无关键词消息返回空集；只含弱命中（1 条）时返回空集（走模型自取）。
4. 宿主声明：注册带 `group="note"` 的工具后 `tool_group()` 返回 `note`、`group_meta()` 用声明标题；
   未声明 `group` 的工具仍按前缀白名单回落，未知前缀归 `host`。
5. 兜底不回退：`tool_not_loaded` 仍自动全量激活并在同轮重试成功（现有测试保持绿）。
6. 入口一致：REST 非流式、REST 流式、WS 三条入口对同一消息得到相同的首轮绑定集合。
7. 质量门槛：`pytest`（agent_runtime / conversation / gateway / host_tool / builtin_tool 分目录跑）、
   `ruff check`、`python3 tools/harness/audit.py` ERROR 0、`tools/harness/verify.sh` 退出码 0。

## 确认记录

用户 2026-10-27 答复：①预取关键词表由我定稿；②不设组数上限，**命中就加载**；
③宿主工具可带 `group` 也可不带（不带则按现状：未声明分组的宿主工具归 `host` 组，
`host` 组默认常驻、全部加载）；组可声明「是否立即加载」，**默认异步加载**。

## 追加变更点（定稿后，取代上文 1/2/3 中冲突部分）

1. `groups.py`：不引入 `DEFAULT_TOOL_GROUPS`，改为 `EAGER_TOOL_GROUPS: set[str]`（常驻组集合，
   默认空）与 `register_tool_group(name, title, description, *, eager=False)`；启动校验
   （`builtin_tool/registry.py`）检查每个业务工具声明的 `group` 已登记且非 `basic`。
2. `tool_prefetch.py`：去掉 `MAX_PREFETCH_GROUPS`，`prefetch_tool_groups` 返回**全部**命中组。
3. `tool_groups.py`：`ToolGroupState` 增加 `eager_groups`，`_eager()` = 内置 `EAGER_TOOL_GROUPS`
   ∪ 连接声明的 eager 组 ∪ `{host}`；`host` 组恒为常驻，故「不带 group 的宿主工具」照旧全部加载。
4. 宿主声明容器落在 `apps/backend/app/modules/host_tool/services.py` 的 `HostToolGroupDeclarations`
   （`groups` / `group_meta` / `eager_groups`），由 `gateway/router.py` 每连接新建、两个发送入口透传。
5. 验收标准相应调整：第 2 条去掉「命中组数 ≤ 2」；新增「`eager` 组首轮绑定且不进
   `load_tool_group` 的 enum」「未声明分组的宿主工具常驻且目录标「常驻」」。
