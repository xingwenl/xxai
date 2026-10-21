---
id: 2026-10-21-subagent-bindings
tier: A
risk: high
approval:
  required: true
  granted: true
  why: ["数据模型变化：新增 agent_subagents 表与迁移", "API 契约变化：新增子智能体绑定端点；delegate_tasks 的 agent 可省略并新增 role；delegatedRuns 新增 usage", "架构边界变化：新增「自克隆子运行」执行形态（子运行可继承父 Agent 配置）", "鉴权或权限行为变化：绑定端点要求平台管理员；派发候选从「全平台已发布」收紧为绑定清单"]
---

## 目标与范围

一句话：给 Agent 增加一张「可派子智能体」绑定表与后台配置页，并让委派工具在没有可用子智能体时能**自克隆父 Agent 配置**临时差遣一个子运行；其余委派形态（单个 `delegate_tasks`、无人值守子运行、深度恒 1、工具范围收缩）一个字不改。

给谁用：平台管理员在 Agent 详情页配置；主 Agent 的模型在运行期从收窄后的候选里挑，或省略 `agent` 走自克隆。

**做**：

- 新表 `agent_subagents`：`parent_agent_id`、`child_agent_id`、`sort_order`、`enabled`；(parent, child) 唯一，两端必须同平台，禁止自指，随 Agent 删除级联。
- 端点：`GET /platforms/{pid}/agents/{aid}/subagents`、`PUT .../subagents`（整表替换，数组顺序即 `sort_order`），均要求平台管理员。
- 候选解析：父 Agent 有绑定 → 绑定内 `enabled` 且当前已发布/启用的子 Agent；无绑定 → 回退「本平台全部已发布 Agent，排除父自己」（存量行为不变）。
- `delegate_tasks`：每项 `agent` 可省略 = 自克隆父 Agent 配置；新增可选 `role` 字符串，作为 `caller_system_prompt` 追加到子运行系统提示；`agent` 不在候选内 → 整体拒绝并回可用清单。
- 工具描述注入：只列候选（slug + name）并加一行自克隆说明。
- 子运行用量：委派子运行写 `model_usage_records`，delegatedRuns 读侧汇总 `usage`。
- 后台 UI：Agent 详情页新增「子智能体」tab（列表、添加、移除、排序、启用）。
- 文档：更新 `CONTEXT.md` 术语，新增 ADR `0015-subagent-bindings.md`，并在 ADR 0005 的 Status 标注被它修订。

**不做**：

- 子运行向前端提问、交互通道、事件直播/混流、确认冒泡（ADR 0005 的结论保持）。
- 子运行内 MCP/宿主工具、深度 ≥2、子运行复用父会话或记忆。
- 任务、工作流链路的用量统计口径变更（它们仍不写用量）。
- 「每个子智能体一个动态工具」形态。

## 来源与方案比较

- Pi subagent extension（本机 `/Users/lixingwen/xw/git/pi/packages/coding-agent/examples/extensions/subagent/`，2026-10-21 读源码）：子智能体来自 `agents/*.md` 预定义配置（frontmatter 含 name/description/tools/model），工具参数按 name 引用单个/并行/链式；未知 name 直接报错并列出可用清单；另带通用 `worker.md` 兜底。没有运行期创建子智能体的接口。
- Claude Code Subagents 官方文档（https://docs.claude.com/en/docs/claude-code/sub-agents ，访问日期 2026-10-21）：子智能体是 `.claude/agents/*.md` 配置文件，frontmatter 声明可用的 tools/model，主 Agent 按 name 调用；未配置即无法派生。
- 结论：成熟形态都是「后台/文件预定义 + 按 name 引用 + 未命中报可用清单」，运行期创建子智能体不是任何一家的一等能力；本方案的「绑定表 + 自克隆兜底」是同一形态的配置化版本。

| 方案 | 说明 | 结论 |
| --- | --- | --- |
| A 绑定表 + 单工具收窄 + 自克隆兜底 | 复用已落地的批量/并发/超时/落库链路，只改候选来源与参数形态 | 采纳 |
| B 每子智能体一个动态工具 `delegate_to_<slug>` | 工具数量随配置增长，模型选错面变大，需动态工具目录与绑定模型二次改造 | 否决 |
| C 独立 teams 聚合根 | 父子只是 agents 间 N:N，另造聚合根与既有版本/发布/工具绑定重复 | 否决 |

## 被否决的选项

1. 方案 B（每子智能体一个动态工具）：工具清单随配置膨胀、描述注入与权限绑定都要重写，收益只是「工具名更像团队」。
2. 方案 C（独立 teams 表/聚合根）：绑定本质是 agents 间 N:N，独立聚合根会与既有版本、发布、工具绑定三套机制重复。
3. 无绑定即禁止派发：存量已绑 `delegate_tasks` 的 Agent 升级后会突然失去委派能力；而委派总开关已经是「有没有绑这个工具」。
4. 新增 `agents.delegation_scope`（all/bound）列：与工具绑定形成双重开关，多一列迁移却没有新增表达力。
5. 自克隆用 `agent: "__self__"` 保留字或独立 `use_self` 布尔：多一个模型要记的保留字/参数，且容易被误填成真实 slug。
6. 绑定关系单独配用途/别名：子 Agent 自己的 name + description 已是唯一事实来源，另配会两处漂移。
7. 允许跨平台绑定：子运行跑在父平台的身份与会话上下文里，跨平台会破坏多租户边界。
8. 本次一并做子运行提问 + 事件直播：要改网关装配链、SDK 与 ChatWidget，ADR 0005 已否决父子混流，成本与本次目标无关。
9. 新建 `delegated_runs` 表记录候选与用量：`agent_loop_runs` 已有父子列与 `run_metadata`，用量可直接用 `model_usage_records` 按子会话聚合。
10. 在 `execute_chat` 里统一写用量：embed 路径已由网关写，统一会双写并改变现有统计口径；只在委派入口开开关。

## 停点判断

命中「架构边界变化」「数据模型变化」「API 契约变化」「鉴权或权限行为变化」→ `approval.required: true`。方案方向已在讨论阶段获用户确认；本 spec 需用户确认后才能写实现代码。

## 变更点

数据模型与迁移

1. `apps/backend/app/modules/agent/models.py`：新增 `SubagentBinding`（表 `agent_subagents`，两列 FK CASCADE、`sort_order`、`enabled`、唯一约束），字段带中文 comment。
2. `apps/backend/migrations/versions/20261021_0045_agent_subagents.py`：建表 + 唯一约束 + 索引，`down_revision = "20261021_0044"`。

后端

3. `apps/backend/app/modules/agent/repositories.py`：绑定读写与 `list_delegatable_agents(platform_id, parent_agent_id)`（有绑定取绑定，无绑定回退已发布并排除父自己）。
4. `apps/backend/app/modules/agent/schemas.py`、`router.py`：`GET/PUT /{agent_id}/subagents`，复用 `_require_platform_admin`。
5. `apps/backend/app/modules/tools/business/delegate_tasks.py`：schema 的 `agent` 改为可选、新增 `role`；候选校验与可用清单错误；`build_agent_catalog_description` 输入改为收窄后的候选。
6. `apps/backend/app/modules/conversation/runtime.py`：`_inject_delegation_catalog` 改用绑定候选，无绑定回退。
7. `apps/backend/app/modules/conversation/services.py`：`execute_unattended_chat` 新增 `role`（透传 `caller_system_prompt` 到 `execute_chat` 的两处 `build_system_prompt`）与 `record_usage`，委派入口开启后写 `model_usage_records`。
8. `apps/backend/app/modules/conversation/serializers.py`、`repositories.py`：delegatedRuns 投影增加 `usage`（按子会话聚合）与 `mode`（取子运行 `run_metadata`）。

前端

9. `apps/front/src/api/agent.ts`：`listAgentSubagents` / `replaceAgentSubagents`。
10. `apps/front/src/features/agents/agent-subagents-tab.tsx`（新）与 `agent-detail-page.tsx`（新 tab、`AgentTabKey`）。
11. `apps/front/src/components/agent-loop/AgentLoopStepCard.vue` 等只读视图：展示子运行 `mode` 与 `usage`。

文档与验证

12. `CONTEXT.md`、`docs/adr/0015-subagent-bindings.md`、ADR 0005 Status 标注、`docs/CHANGELOG.md`。
13. `tools/harness/verify/2026-10-21-subagent-bindings.sh`：迁移往返、绑定端点、候选注入、自克隆、用量、回归。

## 验收标准

1. 迁移可 upgrade/downgrade 往返；`agent_subagents` 唯一约束、CASCADE 与索引生效。
2. `GET/PUT .../subagents`：平台管理员可读写；非本平台管理员 404；自指、跨平台、重复 id 被拒且不落库。
3. 有绑定时工具描述只列绑定内已发布子 Agent；派非候选 slug 整体报错并回可用清单；无绑定时回退全平台已发布（排除自己），存量行为不变。
4. 省略 `agent` + `role`：子运行用父 Agent 配置、新会话执行，`role` 出现在其系统提示，delegatedRuns 里 `mode = "self"`。
5. 每个委派子运行结束写恰好 1 条 `model_usage_records`；delegatedRuns 的 `usage` 与该记录三项 token 一致。
6. 回归：子运行仍无 `delegate_tasks`/MCP/宿主工具；交互式父运行派出的写工具仍被拒。
7. `tools/harness/verify.sh 2026-10-21-subagent-bindings` 退出码 0。
