---
id: 2026-10-27-tool-groups-lazy-load
tier: B
risk: medium
approval:
  required: true
  granted: false
  why: ["改动触及 Agent Loop 的工具绑定边界（架构边界变化）", "模型可见工具集合随轮次变化，需确认行为口径与兜底策略"]
---

## 目标与范围

**做成什么**

不再每轮绑定全量工具（实测 19 个业务工具 schema = 18,198 字符 ≈ 9.1k token），
改为「常驻工具目录 + `load_tool_group`」，按域分批加载，加载后在本次运行内单调累加，
下一轮生效。

**不做**

- 不做前置意图识别、不接分类器（含 Jev）：选组只由模型自己决定，不由入口猜。
- 不改任何工具的业务语义、参数与返回值。
- 不新建表、不改 `models.py`：加载态只放运行态，续跑时从 checkpoint 快照推导。
- 不做工具检索 / embedding / 向量召回。
- 不合并 shop 四兄弟（`order_query`/`store_ops_query`/`product_query`/`show_shop_list`），另案。
- 不改 REST / WS 对外协议字段与错误码。

**边界**

只动工具清单组装与绑定这一层（组合根、两个入口收口、模型适配器、工具轮次执行器），
不碰鉴权、数据库、技能加载。

## 来源与方案比较

- Pi（`/Users/lixingwen/xw/git/pi`，2026-10 快照）：注册全集 + 小激活集，默认只激活
  `read/bash/edit/write`（`packages/coding-agent/src/core/sdk.ts:256`、
  `agent-session.ts:2800-2803`）；懒加载靠转录锚点 `addedToolNames`
  （`packages/ai/src/utils/deferred-tools.ts:8-38`）映射到 provider 原生
  `defer_loading`/`tool_reference`（`anthropic-messages.ts:1450-1458`）或
  `additional_tools`/`tool_search`（`openai-responses-shared.ts:314-347`）。
  加载语义是**纯增量**，官方文档原话 "The active-tool change is the signal."
  （`packages/coding-agent/docs/extensions.md:2373-2398`）；不支持原生协议的 provider
  退回全量列表，代价是前缀缓存失效，因此懒加载工具应省略 promptSnippet/promptGuidelines。
- 本仓库既有先例：技能 = 常驻最小元信息（`apps/backend/app/modules/skill/services.py:212-221`）
  + `load_skill`（`apps/backend/app/modules/skill_runner/tools.py:29-62`，slug 用 enum 限定）。
  同一套「常驻目录 + 按需加载」，工具侧缺的正是这一层。
- 体积基线（本次实测，cl100k_base 估算）：全量 18,198 字符 ≈ 9,114 token；按域拆分
  运营 2,383 / 内容 1,902 / 任务 1,339 / 记忆 1,213 / 技能 597 / ask_user 497 / 知识 423 / UI 417。

**方案 A（选中）**：工具声明 `group`，常驻「目录 + `load_tool_group`」，模型自选加载，
会话内单调累加，`tool_not_found` 时自动全量兜底。

**方案 B**：静态分组，每轮只绑定一组。

**方案 C**：保留全量，只压缩描述与参数 schema。

三者成本与失效模式见下节。

## 被否决的选项

- **方案 B（静态分组，每轮只绑一组）**：组由谁选？只能靠规则或前置分类器；一旦选错，
  模型无法表达「我还需要账单组」，跨域任务（先查订单再记账）直接断在第一轮。否决。
- **前置意图识别硬过滤（最初想法）**：工具不在上下文里，模型只收到 `tool_not_found`，
  没有渠道要求加载，不可恢复；且所需工具是轨迹属性、不是单句属性，多轮必然漂移。否决。
- **用 Jev / embedding 分类器选组**：只优化「猜得准」，不优化「猜错能否恢复」；
  且 TypeSafe 六个官方页面均无延迟数字、无多语言声明，中文能力与延迟都是未验证前提。否决。
- **方案 C（只压缩描述与 schema）**：天花板低——`store_ops_query` 单工具 1.7k 字符里
  大头是参数定义不是描述，且工具总量一涨又回到原点。作为 P2 之后的补充做，不作为主线。
- **工具检索 / tool RAG**：19+12 个工具规模不需要检索，召回率不可控，还要额外维护索引。
- **域级 subagent**：跨域任务需要交接，一次交接的成本远高于省下的几千 token。
- **把加载态落到 `models.py` 新字段**：命中 A 档且要迁移；而它可以从 checkpoint 里
  已加载工具名推导，不必新增存储。

## 停点判断

- **分档 B**：改动落在 `apps/backend/app/modules/conversation/services.py`、
  `apps/backend/app/modules/gateway/runtime.py`、`apps/backend/app/modules/agent_runtime/`。
  未命中 B 档路径枚举（不碰 `router.py` / `api/**` / `schemas.py`），但按
  「拿不准按 B」「涉及 Agent Loop 的非局部决策必须先出方案」上调为 B。
- **未命中 A**：不碰 `**/migrations/**`、`**/models.py`、`**/auth/**`、`**/security*.py`，不新建模块目录。
- **审批触发**：架构边界变化（模型可见工具集合随轮次变化）。
- **需用户确认**：分组边界（组名与组内容）、目录粒度（是否列组内工具名）、
  兜底策略（`tool_not_found` 时自动全量加载还是只回复提示）。
- **确认记录**：2026-10-27 用户确认三项——①分组边界同意（`ops`/`memory`/`task`/`content`/
  `knowledge`/`skill`/`ui` + 宿主应用组 + `mcp:<server>`）；②兜底选「自动全量激活 + 回填重试提示」；
  ③目录粒度选「组名 + 一句话 + 组内工具名」。

## 变更点

1. 新增 `apps/backend/app/modules/builtin_tool/groups.py`：`BASIC_GROUP`、`TOOL_GROUP_META`
   （组名 → 标题 + 一句话）、`BUILTIN_TOOL_GROUPS`（18 个业务工具 → 组）。
2. `apps/backend/app/modules/builtin_tool/registry.py`：`BuiltinToolDefinition` 增加 `group`
   字段（缺省 `basic`），`ask_user` 显式归 `basic`；registry 构建后校验「不许有工具没分组」，
   漏登记直接启动失败（两套真相漂移的护栏）。
3. 新增 `apps/backend/app/modules/agent_runtime/tool_groups.py`：分组判定（工具声明 →
   `mcp:<server_id>` → `skill` → 宿主工具名前缀 → `host`）、`ToolGroupState`
   （`catalog_text`/`loader_tool`/`bound_tools`/`pending_groups`/`activate`/`activate_all`/
   `handle_loader_call`）、`build_tool_group_state`（≤1 组时返回 `None`，保留旧行为）。
4. `apps/backend/app/modules/agent_runtime/composition.py`：`make_legacy_tool_invoker` 增加
   `group_state`，拦截 `load_tool_group`，并对「调用未加载工具」做兜底（`activate_all` +
   `tool_not_loaded` + 重试提示）；`build_langchain_runtime` 增加 `tool_group_state` /
   `enable_tool_groups`（默认关闭）。
5. `apps/backend/app/modules/agent_runtime/langchain_adapter.py`：`LangChainModelInvoker` 按
   `ToolGroupState.version` 在每次模型调用前重绑；工具类型判定改用当前绑定集合。
6. `apps/backend/app/modules/agent_runtime/runtime.py`：`from_langchain` 透传 `tool_group_state`。
7. `apps/backend/app/modules/conversation/runtime.py`：`build_system_prompt` 增加
   `tool_catalog` / `capability_tool_names`——目录单独成段，`ask_user` 与图片渲染规则改按
   「本次运行绑定过的工具全集」判断（工具未加载时规则也必须生效）。
8. `apps/backend/app/modules/conversation/services.py`：非流式轮次与 `stream_chat` 建
   `ToolGroupState`，目录进提示词、加载态进 runtime；`resume_stream_chat` 明确**不启用**
   （续跑的系统提示词来自 checkpoint 快照，无法重建目录）。
9. `apps/backend/app/modules/gateway/runtime.py`：WS 同口径建 state；分组模式下不再把
   「当前已绑定工具」逐个写进提示词（会与后续加载集脱节），改由目录承载。
10. 测试：新增 `tests/agent_runtime/test_tool_groups.py`；`tests/conversation/test_runtime.py`
    与 `tests/gateway/test_chat_flow.py` 按新契约增补/调整（含「跳过加载直接调用」的兜底链路）。
11. 新增 `tools/harness/verify/2026-10-27-tool-groups-lazy-load.sh`。

**追加变更点（2026-10-27，加载态跨轮重放）**：
12. `tool_groups.py`：`handle_loader_call` 成功分支带 `metadata: {tool_group: <组名>}`（失败不带）；
    新增 `LOADED_GROUP_METADATA_KEY`、`ToolGroupState.restore(groups)`（不递增 `version`）与 `build_tool_group_state(..., active_groups=...)`。
13. `conversation/repositories.py` 新增 `list_loaded_tool_groups(conversation_id, *, exclude_loop_run_id=None)`
    （只挑 `load_tool_group` 步骤、Python 侧读 `step_metadata`）；`services.py` 抽出 `load_active_tool_groups()`
    接入非流式 / `stream_chat` / `resume_stream_chat`，`gateway/runtime.py` WS 同口径。
14. 修订变更点 8：`resume_stream_chat` 改为启用分组，只恢复本次运行之前的组（`exclude_loop_run_id=loop.id`）
    以对齐检查点目录，中途加载的放弃；`activate_all` 不写 metadata。测试：新增仓储测试 + 4 例单测。

**与初稿的偏差**（初稿变更点 3/4/5/8 已按实现收敛）：

- 不再改 `build_runtime_tools` / `build_runtime_tool_list` / `merge_model_tools`：选择发生在
  组合根（`build_langchain_runtime`）与模型适配器，REST/WS 自动共用一份实现。
- 兜底从 `tool_loop.py` 移到 `make_legacy_tool_invoker`：`ToolRoundExecutor`
  （`apps/backend/app/modules/agent_runtime/tool_loop.py:55`）在本仓库只有导出、没有调用方，
  改它不会生效。
- 分组维度：`HostToolPolicy` 无 app_id 字段（`apps/backend/app/modules/host_tool/models.py:21-42`），
  宿主组只能按工具名前缀（`ledger_*` → `ledger`）推导。
- 错误码：未加载工具用新码 `tool_not_loaded`，`tool_not_found` 保留给真正未知的工具名。

## 验收标准

1. schema 体积（`verify.sh` 实测打印）：初始绑定 REST ≤800 / WS ≤1,700 字符（含 `ask_user`），
   加载任一组后 ≤6,500，全量基线 18,198。实测：REST 487 / WS 1,514 / 最大组 `ops` 5,842。
2. 单测：首轮 `bind_tools` 只含 `basic` + `load_tool_group`；加载 `ops` 后下一轮含 4 个 ops
   工具；重复加载幂等（返回空列表、版本不递增、集合不变）。
3. 单测：模型直接调用未加载工具 → 返回 `tool_not_loaded` 且框架自动全量激活，同一调用重试
   成功；真正未知的工具名仍返回 `tool_not_found`。
4. 测试：工具顺序不同（REST / WS 来源不同）时初始绑定集合与目录文本逐字一致。
5. 现有 `pytest`（agent_runtime / conversation / gateway / builtin_tool / skill_runner /
   workflows）全绿；`ruff check` 与 `ruff format --check` 对改动文件通过。
6. `python3 tools/harness/audit.py` 退出码 0；`tools/harness/verify.sh 2026-10-27-tool-groups-lazy-load`
   产出 `verify.md`。
