# 设计说明

## 目标

- 完善仓库内 Harness Engineering 基础设施，使其能够支撑正式的 FastAPI 后端项目协作
- 为后续 `/new`、`/modify`、`/fix` 提供可复用的 request 工作区、规范文档和样例
- 让 Harness 本身具备可追溯、可扩展、可审阅的工程资产形态

## 范围

- 更新 `docs/harness/README.md` 作为正式入口
- 补齐 `docs/harness/backend.md` 的 FastAPI 后端规范
- 强化 `docs/harness/templates/` 下的模板内容
- 新增 `meta.json` 模板
- 新增一个 FastAPI 后端 request 示例文档
- 为本次改造创建正式 request 工作区并完成全流程记录

## 非目标

- 本次不实现自动化脚本，如 `tools/harness/check.mjs`
- 本次不直接新增业务接口或数据库模型
- 本次不定义前端专项开发规范
- 本次不引入 CI、Git hooks 或自动生成器

## 风险

- 如果规范写得过细，后续小任务会有执行负担
- 如果规范写得过空，正式项目中又无法提供足够约束
- 当前仓库尚无自动化校验脚本，短期内仍需依赖人工检查文档完整性

## 停点判断

- 架构边界变化：否，本次仅完善工程规范与文档结构
- 数据模型变化：否
- API 契约变化：否
- 鉴权或权限行为变化：否
- 结论：本次无需额外人工审批，可直接进入实现

## 验收标准

- `docs/harness/README.md` 明确说明目录职责、阶段流程、request 工作区和人工确认条件
- `docs/harness/backend.md` 形成可执行的 FastAPI 后端规范，而不是空文件
- `docs/harness/templates/` 中的模板均带有填写提示，能够直接复用
- 新增 `meta-template.json`
- 新增至少一份 FastAPI 后端 Harness 示例
- 本次 request 补齐 `spec.md`、`plan.md`、`verify.md`、`acceptance.md`、`meta.json`

## 变更记录

### 初始版本

- 时间：2026-07-18
- 变更原因：首次创建 request，正式推进 Harness 工程完善
- 变更内容：定义本次改造目标、范围、风险和验收标准
- 影响章节：全部
- 是否触发人工确认：否
