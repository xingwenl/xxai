# 验证记录

## 验证范围

- Harness 主规则、后端规则、模板和示例是否都纳入 `research` 阶段。
- 本 request 的文件是否完整、是否存在未处理占位符。
- 本次是否保持运行时代码不变。

## 执行记录

### 0. 检查全局策略一致性

- 命令：`rg -n "research|phase|status|blocked|done|外部资料|人工确认" docs/harness/policies/global.md docs/harness/README.md AGENTS.md`
- 预期：三份规则文件都包含 `research`；`global.md` 将 `done`、`blocked` 定义为状态，并明确实现前人工确认。
- 实际：已确认规则一致，`global.md` 已区分阶段和状态，并补充调研来源质量、资料不可用和人工确认规则。

### 0.1. 检查 README 链接

- 命令：`rg -n "\(/Users/|backend\.md\)" docs/harness/README.md`
- 预期：不包含当前机器绝对路径，内部链接使用相对路径。
- 实际：`README.md` 使用 `backend.md` 相对链接，未发现 `/Users/` 绝对路径。

### 0.2. 检查规则读取顺序

- 命令：`sed -n '11,35p' docs/harness/README.md`
- 预期：明确 `AGENTS.md`、`policies/global.md`、专项规范和当前 request 的读取顺序。
- 实际：已明确四层规则顺序，并规定冲突时上层规则优先、用户当前明确要求优先。

### 0.3. 检查入口指令职责

- 命令：`rg -n "^## /|^## 常用入口|/new|/modify|/fix|/verify|/accept" AGENTS.md docs/harness/README.md docs/harness/policies/global.md`
- 预期：README 提供完整指令说明；AGENTS 仅保留最小动作；global 不提供重复的完整指令定义。
- 实际：五个入口均在 README 中有完整说明，AGENTS 仅保留摘要，global 仅在通用规则中引用入口类型。

### 0.4. 检查 Skill 策略职责

- 命令：`rg -n "策略 A|策略 B|Skills 调用|brainstorming|writing-plans" AGENTS.md docs/harness/policies/global.md`
- 预期：策略 A/B 的完整触发条件和执行动作只出现在 `global.md`；AGENTS 只保留读取策略和升级原则。
- 实际：已确认 `global.md` 是 Skill 策略的唯一详细来源，AGENTS 不再重复维护策略清单。

### 0.5. 检查增量与轻量规则职责

- 命令：`rg -n "Spec 增量|轻量模式|变更记录|轻量策略|policies/global.md" AGENTS.md docs/harness/README.md docs/harness/policies/global.md`
- 预期：增量变更和轻量模式的完整规则只出现在 `global.md`；AGENTS 与 README 只保留最小入口动作和链接。
- 实际：已确认 `global.md` 保留完整规则，AGENTS 和 README 已压缩为入口说明。

### 0.6. 检查调研、审批和阶段流转一致性

- 命令：`rg -n "research\.md|官方来源|成熟案例|关键业界资料|research -> spec|spec -> plan|plan -> implement|implement -> verify|verify -> acceptance|acceptance -> done" AGENTS.md docs/harness/README.md docs/harness/policies/global.md`
- 预期：三份规则文件对调研要求和人工确认条件一致；阶段流转条件完整。
- 实际：已确认 `research.md` 读取顺序已补齐，小功能统一要求官方来源加成熟案例，核心资料不足会触发人工确认，阶段流转条件已在 README 和 global.md 明确。

### 1. 检查 request 文件完整性

- 命令：`find docs/harness/requests/2026-07-18-harness-research-first -maxdepth 1 -type f | sort`
- 预期：包含 `acceptance.md`、`meta.json`、`plan.md`、`research.md`、`spec.md`、`verify.md`。
- 实际：已包含 `acceptance.md`、`meta.json`、`plan.md`、`research.md`、`spec.md`、`verify.md`。

### 2. 检查流程与占位符

- 命令：`rg -n "research|TODO|TBD|待补充" docs/harness`
- 预期：核心规则和模板包含 `research`；不存在未处理占位符。
- 实际：核心规则和模板包含 `research`；未发现未处理的 `TODO`、`TBD` 或 `待补充` 占位符。

### 3. 检查运行时代码未变化

- 命令：`git status --short -- apps/backend`
- 预期：没有本次任务引入的变更。
- 实际：`apps/backend/` 仍显示仓库原有的未跟踪目录，但本次任务未修改其中任何运行时代码。

## 失败项与例外

当前没有失败项。由于本次没有运行时代码变更，不执行 pytest、ruff 或 uvicorn。
