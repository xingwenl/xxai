# Harness 开发前业界调研实施计划

> **For agentic workers:** 本计划按 Harness 的文档闭环执行，完成后补写 verify 与 acceptance。

**目标：** 将业界调研纳入新功能的标准 Harness 前置阶段，并提供可复用模板。

**范围：** 只修改 `docs/harness/` 文档资产，不修改应用运行时代码。

**技术栈：** Markdown、JSON、Shell 文本检查。

---

### Task 1: 新增调研模板

**文件：**

- Create: `docs/harness/templates/research-template.md`

- [x] 定义调研问题、来源、方案比较、最终决策和剩余风险字段。
- [x] 明确必须记录来源链接、版本或发布日期、调研日期。
- [x] 明确按功能复杂度分级的最低调研深度。

### Task 2: 同步 Harness 主规则

**文件：**

- Modify: `docs/harness/README.md`
- Modify: `docs/harness/backend.md`
- Modify: `docs/harness/templates/spec-template.md`
- Modify: `docs/harness/templates/plan-template.md`
- Modify: `docs/harness/templates/meta-template.json`

- [x] 将标准阶段更新为 `research -> spec -> plan -> implement -> verify -> acceptance`。
- [x] 把 `research.md` 加入 request 最低文件集合和后端任务工作流。
- [x] 在 spec 和 plan 模板中增加对调研结论的引用要求。
- [x] 在 meta 模板中增加 `research` 阶段可表达的状态字段。

### Task 3: 更新示例并记录本次调研

**文件：**

- Modify: `docs/harness/examples/golden-path.md`
- Modify: `docs/harness/examples/fastapi-backend-example.md`
- Create: `docs/harness/requests/2026-07-18-harness-research-first/research.md`

- [x] 在新功能示例中展示先调研再写 spec 和 plan。
- [x] 在 FastAPI 示例中体现官方文档和成熟案例的参考方式。
- [x] 记录本次规则设计的真实参考依据和方案选择。

### Task 4: 文档验证和验收

**文件：**

- Modify: `docs/harness/requests/2026-07-18-harness-research-first/verify.md`
- Modify: `docs/harness/requests/2026-07-18-harness-research-first/acceptance.md`
- Modify: `docs/harness/requests/2026-07-18-harness-research-first/meta.json`

- [x] 检查所有必备文件、阶段顺序和占位符。
- [x] 确认没有修改 `apps/backend/` 运行时代码。
- [x] 更新 request 状态为验收完成。

### Task 5: 增量优化全局策略

**文件：**

- Modify: `docs/harness/policies/global.md`
- Modify: `docs/harness/README.md`
- Modify: `AGENTS.md`

- [x] 同步 `research` 阶段，分离 `phase` 与 `status`。
- [x] 补充调研适用范围、来源质量和外部资料不可用时的处理规则。
- [x] 明确人工确认必须发生在实现之前，并将 README 内部链接改为相对路径。
- [x] 将 README 作为入口指令完整语义的维护位置，压缩 AGENTS 摘要并移除全局策略中的指令细节。
- [x] 补充 `/new`、`/verify`、`/accept` 的完整执行步骤，以及 `/modify`、`/fix` 的调研边界。
- [x] 将 `global.md` 作为 Skill 策略 A/B 的唯一详细来源，压缩 AGENTS 中的重复规则。
- [x] 将 `global.md` 作为 Spec 增量变更和轻量模式的唯一详细来源，压缩 AGENTS 与 README 的重复规则。
- [x] 统一 `research.md` 读取顺序、调研最低要求和调研证据不足的审批条件。
- [x] 在 `global.md` 和 README 中补充 phase/status 合法流转规则。

## 回滚说明

删除本 request 目录，并恢复本次修改的 Harness 文档即可；不会影响后端运行时。

## 人工确认点

无。本次不涉及架构边界、数据模型、API 契约或鉴权权限行为。
