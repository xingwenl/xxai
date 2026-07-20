# 验收结论

## 验收标准核对

- [x] 主规则明确 `research -> spec -> plan -> implement -> verify -> acceptance`。
- [x] 新 request 最低文件集合包含 `research.md`。
- [x] 调研模板包含来源、方案比较、最终决策和剩余风险。
- [x] FastAPI 规则和示例要求新功能先参考业界成熟案例。
- [x] 本次未修改 `apps/backend/` 运行时代码。
- [x] `global.md` 与 README、AGENTS 的阶段顺序一致。
- [x] `global.md` 已分离 `phase` 与 `status`，并定义 `done`、`blocked` 的语义。
- [x] 已明确 research 的适用范围、来源质量、资料不可用处理和实现前人工确认节点。
- [x] README 内部链接不依赖当前机器的绝对路径。
- [x] README 明确 `AGENTS.md`、全局策略、专项规范和 request 文档的读取顺序。
- [x] README 是入口指令完整语义的唯一维护位置，AGENTS 仅保留最小动作摘要。
- [x] `/new`、`/modify`、`/fix`、`/verify`、`/accept` 的职责和文档要求没有相互冲突。
- [x] Skill 策略 A/B 只在 `global.md` 中完整定义，AGENTS 仅保留最小强制动作。
- [x] Spec 增量变更和轻量模式只在 `global.md` 中完整定义，AGENTS 与 README 仅保留入口说明和引用。
- [x] 三份规则文件都包含 `research.md` 的读取和调研要求，且小功能要求官方来源加成熟案例。
- [x] 核心功能缺少关键调研资料时，会触发实现前人工确认。
- [x] `research`、`spec`、`plan`、`implement`、`verify`、`acceptance` 的流转条件已经明确。

## 验收结论

已完成文档结构、JSON、占位符和运行时代码范围检查，达到验收标准。

## 剩余风险

- 当前没有自动检查来源链接有效性和时效性。
- 调研质量仍需要在具体功能 request 中结合领域复杂度判断。

## 人工验收记录

- 验收人：用户已确认采用该流程设计
- 验收日期：2026-07-18
- 结论：通过，可用于后续新功能开发
