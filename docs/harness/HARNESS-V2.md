# Harness v2：按 diff 分档的轻量闭环

> 本文件是自本文件生效之日起**新任务**的唯一流程依据。
> 存量 `docs/harness/requests/` 下的历史 request 一律冻结，不迁移、不回填、不补文档。

## 为什么改

旧的六阶段（research → spec → plan → implement → verify → acceptance）产出六份文档，实践数据说明它重错了位置：

- 文档量与收口率负相关：`done` 的 request 平均 26.7 KB，卡在 acceptance 的平均 37.9 KB，卡在其它阶段的平均 52.1 KB。
- 检查点退化为噪音：49/59 个 request 触发人工确认（83%），人读不完等于没确认。
- 状态靠手维护并已失真：`meta.json` 出现过非法值、缺字段、以及 `approvalGranted=false` 却有 4 条 approved 记录的情况。
- 复述性文档吃掉大量预算：出现过 3411 行的 `plan.md`，其中 2856 行是代码块。

v2 保留两样真正不可伪造的东西——**来源可追溯**和**真实验证命令**——其余全部砍掉或合并。

## 核心结构

### 三道门，不是六个阶段

| 门 | 做什么 | 完成判据（可核对） |
|---|---|---|
| **1 想清楚** | 确定范围、来源、被否决的选项、验收标准 | `spec.md` 写完，要点已发给用户并获确认 |
| **2 做出来** | 写代码 | 实现完成，且 `verify.sh` 已写好 |
| **3 证明它** | 跑验证、留证据 | `verify.sh` 真实跑过，输出已落进 `verify.md` |

没有独立的 `research` / `plan` / `acceptance` 阶段。调研结论是 `spec.md` 的一节，计划是提交信息与 `spec.md` 的「变更点」，验收结论是 `verify.md` 的末尾三行。

### 两个文件，最多

```text
docs/harness/requests/<request-id>/
  spec.md                        # C 档没有；A/B 档必有
  verify.md                      # 三档都有
tools/harness/verify/<request-id>.sh   # A/B 档必有
```

不再产出 `plan.md`、`acceptance.md`、`meta.json`、独立的 `research.md`。

## 分档规则

分档由 **diff 命中的路径**决定，不由主观判断决定。命中即取最高档。

| 档 | 触发条件（任一命中） | 产出 | 人工确认 | 拷问 |
|---|---|---|---|---|
| **A 架构级** | `**/migrations/**`、`**/models.py`、`**/auth/**`、`**/security*.py`、新建模块目录、跨服务边界重构 | `spec.md` + ADR + `verify.sh` | 必须 | 必须（两轮封顶） |
| **B 契约级** | `**/schemas.py`、`**/router.py`、`**/api/**`、跨 `apps/` 改动 | `spec.md` + `verify.sh` | 必须 | 不需要 |
| **C 局部** | 以上都不碰 | 无文档 | 不需要 | 不需要 |

补充规则：

- 分档只能**上调**，不能下调。AI 自评偏低时用户可要求升档。
- 无法判断命中哪一档时，按 **B** 处理。
- C 档不建 request 目录，动机与验证写在提交信息里。

## 各档的执行方式

### C 档：直接做

1. 改代码。
2. 跑一次最小验证（相关单测、`ruff check`、或手工核对）。
3. 一次提交，提交信息写清动机与验证方式：

```text
fix(wechat_bot): 心跳降噪，未变化时降为 DEBUG

动机：每分钟 INFO 心跳淹没同文件内的业务日志。
验证：poetry run pytest tests/wechat_bot -q → 12 passed
```

C 档不写文档、不建 request、不请求确认。

### B 档：先写 spec，确认后实现

1. 按 `templates/spec-template.md` 写 `spec.md`（≤150 行）。
2. **把方案要点发给用户确认**（目标、范围、被否决的选项、停点判断）——这是唯一的人工检查点。
3. 用户确认后写代码。
4. 写 `tools/harness/verify/<id>.sh`，执行它，把输出落进 `verify.md`。
5. 提交。

### A 档：B 档 + 拷问 + ADR

在 B 档第 1 步与第 2 步之间插入拷问：

1. 调用 `grilling` 技能，把设计当决策树。
   - **第一轮**问完当前 frontier（前置已定的全部问题），每题自带推荐答案。
   - **第二轮**问第一轮答案新暴露出来的问题。
   - **两轮封顶**，不再追问。
2. 拷问中确定的领域术语当场写入 `CONTEXT.md`；术语冲突当场指出并消解。
3. 拷问结论写进 `spec.md` 的「被否决的选项」一节。
4. 若决策同时满足以下三条，写一篇 ADR 到 `docs/adr/`：
   - 难以回退（改主意的代价是真实的）
   - 不明所以（未来的读者会问"为什么这么做"）
   - 真有权衡（存在过真实备选，且为具体理由选了它）
   三条缺一就不写。ADR 照 `docs/adr/0001-*.md` 的形态，一段话也可以。

> 指针注意：调用时**直接调用 `grilling` 与 `domain-modeling`**，不要调用 `grill-with-docs`——后者是仅 5 行的路由器且禁止模型自动调用，容易落空。

## `spec.md` 规格

硬上限 **150 行**。固定骨架：

```md
---
id: YYYY-MM-DD-topic
tier: A | B
risk: low | medium | high
approval:
  required: true
  granted: false
  why: ["API 契约变化"]
---

## 目标与范围
## 来源与方案比较
## 被否决的选项
## 停点判断
## 变更点
## 验收标准
```

各节要求：

| 节 | 要求 |
|---|---|
| 目标与范围 | 一句话说清做成什么；明确**不做**什么 |
| 来源与方案比较 | 至少 1 个官方或成熟案例，带链接 + 版本/日期；比较 2~3 个方案；说明适用条件与限制 |
| **被否决的选项** | **必填非空**。每个被否决方案写：方案、否决理由。这是防止重开已死方案的唯一机制 |
| 停点判断 | 命中哪条审批触发条件；未命中写"未命中" |
| 变更点 | 改动哪些文件/模块，一句话一个；**禁止超过 30 行的连续代码块** |
| 验收标准 | 3~7 条**可核对**的条目，不用"体验良好"这类描述 |

审批触发条件（命中即 `approval.required: true`）：

- 架构边界变化
- 数据模型变化
- API 契约变化
- 鉴权或权限行为变化
- 核心功能缺少关键资料，无法可靠比较方案

## `verify.md` 规格

内容由脚本产出，不手写散文。

`tools/harness/verify/<id>.sh` 要求：

- 逐条执行真实验证命令（pytest / ruff / curl / docker compose config 等）。
- 结尾必须显式列出**未执行项与原因**（缺环境、缺权限、需人工联调）。
- **退出码即验证结论**：
  - `0`：全部通过，无未执行项
  - `3`：其余通过，但存在未执行项
  - `1`：有验证项失败
  - `2`：脚本自身用法或环境错误

`verify.md` 固定骨架（frontmatter 记录 `ranAt` 与 `exitCode`，由运行器写入）：

```md
## 已执行的命令与结果
## 未执行项与原因
## 验收结论
```

**验收结论三行以内**：是否达到 `spec.md` 的验收标准、剩余风险、是否可归档。

真实执行过的命令和自曝的未验证项是整套体系最有价值的产出，必须保留；凭空写"已测试通过"视为验证未完成。

## 工具与门禁

| 工具 | 作用 |
|---|---|
| `tools/harness/audit.py` | 校验 v2 request 的产物一致性；存量目录自动跳过 |
| `tools/harness/verify.sh <id>` | 执行 `tools/harness/verify/<id>.sh`，把真实输出写入 `verify.md` |
| `tools/harness/verify/_template.sh` | 验证脚本模板，复制后替换命令即可 |
| `.github/workflows/harness.yml` | 在 CI 跑 `audit.py`，ERROR 直接失败；并检查验证脚本可执行 |

`audit.py` 对**新机制生效后创建**的 request 检查：

- `spec.md` / `verify.md` 的 frontmatter 字段完整、枚举合法
- `spec.md` 含全部六个必需章节，「被否决的选项」非空
- `spec.md` ≤ 150 行，且无超过 30 行的连续代码块
- `verify.md` 的 `source` 为 `script`，且含「未执行项与原因」
- A/B 档存在可执行的 `verify/<id>.sh`
- A 档在 `docs/adr/` 下有引用本 request 的 ADR（判据未同时成立时，在 `spec.md` 说明为何不写）

对 2026-09-20 之前创建的 request 目录**一律跳过**，不报错、不告警。

## 规则读取顺序

执行任务前按此顺序读取：

1. 仓库根 `AGENTS.md`：仓库级强制约束
2. 本文件 `docs/harness/HARNESS-V2.md`：流程、分档、检查点
3. 专项规范：涉及 `apps/backend/` 读 `backend.md`，涉及 `apps/front/` 读 `frontend.md`
4. 当前 request 的 `spec.md`（A/B 档）

规则冲突时优先遵守上层规则；用户在当前对话中的明确要求优先于本文件。

## 与旧规则的关系

- 本文件生效后新建的任务，全部按本文件执行。
- 旧六阶段流程、`policies/global.md` 的增量与轻量规则、`templates/` 下的 `plan`/`acceptance`/`meta`/`research` 模板，仅对存量 request 仍有解释力，对新任务不再适用。
- 存量 `docs/harness/requests/` 下的 59 个目录保持原样，不要求补齐 `verify.sh`、不要求改写 frontmatter、不参与 `audit.py` 校验。
