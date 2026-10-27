---
id: 2026-10-27-tool-groups-admin-view
tier: B
risk: low
approval:
  required: true
  granted: true
  why: ["新增后端只读接口并改前端智能体详情页（跨 apps/ 改动）", "用户此前决策「工具组不用 DB、不在后台改」，需确认只读展示是否属于同一否决范围"]
---

## 目标与范围

**做成什么**

工具组已经上线（`1cc178c` 分组按需加载、`f2921f4` 首轮预取与组常驻声明），
但管理台完全看不到它们：智能体详情页的「内置工具」「宿主工具」两处都是扁平列表，
运营看到 18 个工具平铺、不知道它们分属哪组、哪组是常驻、哪组要模型自己加载。
本次只补**只读展示**：

1. 新增接口 `GET /platforms/{platform_id}/tool-groups`，返回该平台的内置组与
   宿主组清单（组名、中文标题、一句话说明、是否常驻/eager、组内工具名）。
2. 智能体详情页的内置工具、宿主工具两处 section 按组渲染：组标题 + 组说明 +
   「常驻」/「按需加载」徽标，组内仍是逐工具开关，开关语义一个字不改。

**不做**

- 不做组级总开关、不做组级启停：那会改变绑定语义，本次只读。
- 不给任何表加 `group` 列、不做迁移：`HostToolPolicy` 保持现状。
- 不做管理台「配置分组」页（用户 2026-10-27 决策：在后台改意义不大）。
  本接口无写入口，组的成员关系仍由代码常量与注册声明决定。
- 不展示 MCP 组：MCP 已有独立的 `mcp-tools-section.tsx`，server 维度信息在 MCP 模块。
- 不改现有 `GET .../builtin-tools`、`GET .../host-tools` 的响应契约。

## 来源与方案比较

**来源**：用户 m01622「好的 继续」，接续我给出的「管理台只读分组展示」候选；
现状代码为 `apps/backend/app/modules/builtin_tool/schemas.py`（`BuiltinToolCatalogRead`
无 group）、`apps/backend/app/modules/builtin_tool/router.py:31`（`_catalog_read` 不带 group）、
`apps/front/src/api/builtin-tools.ts`（类型无 group）、
`apps/front/src/features/agents/builtin-tools-section.tsx`（扁平列表 + 每行 Switch）、
`apps/front/src/features/agents/host-tools-section.tsx`（同上）。

**方案比较（选 A）**

- **A. 新增只读分组接口 + 前端分组渲染（采用）**：分组的唯一真相仍是运行期判定函数
  `tool_group()` / `group_meta()`（`apps/backend/app/modules/agent_runtime/tool_groups.py:64`、`:98`），
  接口只是把它们的结果序列化出来，不引入第二套分组逻辑，也不产生需要同步的状态。
- **B. 改现有 list 接口，把 group/title 塞进每个工具**：要同时改两条既有契约与前端全部
  消费点，且同样的组元信息在每个工具上重复 N 次；`AgentBuiltinToolRead` 已被别处使用。
- **C. 前端自己按名字前缀猜组**：等于第二套分组规则，与后端 `HOST_TOOL_GROUP_PREFIXES`
  迟早漂移（`7b52298` 刚把「猜前缀」收紧成白名单，不应在前端重新放开）。

## 被否决的选项

- 给 `HostToolPolicy` 加 `group` 列 + 迁移：A 档开销，且页面注册链路（入站
  `HostToolRegistration` 只有 name/description/input_schema）根本带不上组，列里只能存
  推导结果，属于把可由函数算出的事实固化成需要同步的状态。
- 组级总开关 / 组级启停：改变「绑定哪些工具」的语义，等于把按需加载换成人工配置，
  与上一版 spec 的「不做后台配置」一致地排除。
- 前端按名称前缀猜组：见方案 C，会造成第二套真相。
- 只加一个「组」文本徽标、不做分组布局：信息量最低的一版，运营仍要自己把 18 行
  归类，省下的只是后端那一个接口。
- 把运行期观测（`5b987be` 的统计）也搬进管理台：另一件事，且需要真实样本先攒够。

## 停点判断

B 档：新增 `schemas.py` 类型、新增 `router.py` 端点、跨 `apps/` 改前端。
`approval.required: true`——本次要用户确认「只读展示」不在此前「后台改意义不大」
的否决范围内。确认前不写实现代码。

## 变更点

1. `apps/backend/app/modules/builtin_tool/schemas.py`：新增 `ToolGroupRead`
   （`group` / `title` / `description` / `eager` / `tool_names`）与
   `ToolGroupCatalogRead`（`builtin: list[ToolGroupRead]`、`host: list[ToolGroupRead]`）。
   既有 `BuiltinToolCatalogRead` / `AgentBuiltinToolRead` 不动。
2. `apps/backend/app/modules/builtin_tool/router.py`：新增
   `GET /platforms/{platform_id}/tool-groups`（沿用 `_require_admin`）。实现复用
   `list_builtin_tools()`（按 `tool.group` 归并，「basic」组单选）、
   `HostToolRepository`（按平台取策略，用 `tool_group(policy)` 归组）与
   `group_meta()`；`eager` 取 `group in EAGER_TOOL_GROUPS` 或 `group == HOST_GROUP`。
   组排序：`basic` 最先，其后 eager 组，其余按标题排序，`host` 兜底组最后。
3. `apps/front/src/api/builtin-tools.ts`：新增 `ToolGroup` / `ToolGroupCatalog` 类型与
   `listToolGroups(platformId)`；不动 `AgentBuiltinTool`。
4. `apps/front/src/features/agents/builtin-tools-section.tsx`：按 `builtin` 分组渲染
   （组头 = 标题 + 说明 + 「常驻 / 按需加载」徽标），组内保留现有行与 Switch；
   组清单里没覆盖到的工具落到末尾「未分组」块，避免工具消失。
5. `apps/front/src/features/agents/host-tools-section.tsx`：按 `host` 分组渲染，
   同上；开关仍走既有 `bindAgentHostTool` / `unbindAgentHostTool`。
6. 不做数据迁移、不改 `host_tool` 的模型与既有接口、不改任何工具执行路径。

## 验收标准

1. 新接口返回的内置组并集覆盖 `list_builtin_tools()` 的全部工具，一个不漏、一个不多
   （单测断言两个集合相等）；每组 `tool_names` 与 `tool.group` 一致。
2. 宿主组判定与运行期同源：`note_*` → `note`、`ledger_*` → `ledger`、`page_*` → `page`、
   未登记前缀 → `host`，且与 `agent_runtime.tool_groups.tool_group()` 的返回逐条一致。
3. `basic`（常驻）与 `host`（兜底常驻）标记为 eager，其余内置组标记为按需加载。
4. 前端两处 section 按组渲染、组内开关可用；接口未覆盖的工具出现在「未分组」块，
   不出现「工具从页面消失」。
5. 既有接口契约不变：`/agents/{id}/builtin-tools`、`/host-tools` 的响应字段与前端
   既有消费点无破坏（前端类型检查无新增错误）。
6. 验证：新增/更新后端单测（builtin_tool、host_tool，含上述 1–3 条断言）、
   `pytest tests/builtin_tool tests/host_tool tests/agent_runtime`、`ruff check`、
   前端 `prettier --check` / `eslint` / `tsc -p tsconfig.app.json`、
   `python3 tools/harness/audit.py`、
   `bash tools/harness/verify.sh 2026-10-27-tool-groups-admin-view` 全绿。

## 待确认

1. 只读展示是否可做——**已确认可做**（用户经提问选项确认）：此前「后台改意义不大」的
   否决针对**落库 + 在后台编辑分组**，本次只有读接口与展示。
2. 分组展示粒度——**已确认「组头 + 组内逐工具开关」**。
3. 宿主组是否展示——**已确认一起展示**。

## 确认记录与偏差

- 2026-10-27：上述三项经提问得到用户答复（全部选择推荐项）后进入实现。
- 前端全量 `pnpm --dir apps/front build` 在仓库基线即失败（3 个 `.test.ts` 缺
  `@types/node` 的 TS2591），故验收改为「`tsc -p tsconfig.app.json` 只剩这 3 个
  预存在错误」，已在 verify.md 记录。
