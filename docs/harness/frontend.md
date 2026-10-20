# 前端 Harness 规范

本文件约束 `apps/front/` 下的前端任务如何在 Harness 流程内设计、实现、验证和验收。技术栈约束见 `docs/frontend/README.md`，目录分层与样式约束见仓库级技能 `.codex/skills/frontend-architecture.md`、`.codex/skills/frontend-styling.md`，本文件只补充 Harness 流程要求。

## 适用范围

- 新增或修改页面、路由、组件
- 新增或修改前端 API 调用、数据流、状态管理
- 修改与后端接口的契约对接（请求 / 响应字段）
- 修改样式体系、UI 交互
- 修复前端 bug

## 前端任务的最小工作流

涉及 `apps/front/` 的正式任务，默认按以下顺序推进：

1. 在 `docs/harness/requests/<request-id>/` 创建工作区
2. 在 `research.md` 调研业界成熟实现（官方文档、主流框架 / 库、成熟开源项目）
3. 基于调研结论，在 `spec.md` 写清目标、范围、风险、停点判断、验收标准
4. 在 `plan.md` 写清变更文件、实施步骤、测试步骤、回滚方案
5. 再进入代码实现
6. 在 `verify.md` 记录实际执行命令与实际结果
7. 在 `acceptance.md` 给出验收结论与剩余风险

## 推荐目录边界

`apps/front/` 当前按 feature 组织：

- `src/`：应用代码，按功能模块组织
- `src/api/`：后端接口封装，统一通过 api 层访问，不散落裸 fetch
- `src/features/`：业务功能模块
- `src/components/`：共享组件

技术栈约束以 `docs/frontend/README.md` 为准，不得并行引入第二套主状态管理方案或替代主技术栈。

## Spec 阶段必须回答的问题

前端 request 的 `spec.md` 至少要写清：

- 这个页面或功能解决什么问题，入口在哪里
- 谁会使用它，主要交互路径是什么
- 输入、输出、状态流转是什么
- 是否新增或修改 API 契约字段（若涉及，需与后端 request 对齐）
- 是否改动登录、鉴权、权限相关的前端行为
- 回归风险落在哪些已有页面或流程
- 方案基于哪些业界调研结论，为什么选择当前方案而不是其他方案

## Research 阶段必须回答的问题

- 这个功能在业界有哪些成熟实现（官方文档、主流库、成熟开源项目）
- 参考方案的适用条件、收益和限制是什么
- 本项目的技术栈和约束是否适合直接采用
- 最终选择什么方案，哪些方案明确不采用，原因是什么

调研记录必须包含来源链接、版本或发布日期和调研日期，不能只写"业界通常如此"。

如果以下任一答案为"是"，必须等待人工确认：

- 新增或修改与后端的 API 契约
- 修改登录、鉴权、权限相关前端行为
- 引入新的架构边界（新模块、跨页面大联动）
- 引入影响主技术栈的新依赖

## Verify 阶段最低要求

`verify.md` 不能只写"已测试通过"，至少要记录执行命令、预期结果、实际结果、失败项与例外。

本仓库是 pnpm workspace（`apps/ai-sdk`、`apps/front`、`apps/shop`、`apps/desktop/front` 共用根 `pnpm-lock.yaml`），依赖统一在仓库根 `pnpm install` 安装；`apps/front` 通过 `workspace:*` 软链引用 `apps/ai-sdk`，SDK 改动后用 `pnpm build:sdk` 重建 dist。

常见验证命令（以 `apps/front/package.json` 的 scripts 为准）：

- `pnpm --dir apps/front lint`
- `pnpm --dir apps/front build`（含 `tsc -b` 类型检查）
- `pnpm --dir apps/front format:check`

如果因为环境或基线问题无法运行，必须明确写在 `verify.md` 中，不能跳过不记。

## Acceptance 阶段最低要求

`acceptance.md` 至少要回答：

- 当前是否达到 spec 的验收标准
- 哪些验证已经完成
- 还有哪些风险没有消除（如未联调后端、未做浏览器回归）
- 是否还需要人工回归或联调，是否可以合并或归档

## 前端代码约定

- 沿用 `docs/frontend/README.md` 的技术栈与分层，不引入第二套方案
- API 调用统一走封装层，字段名与后端契约保持一致
- 新增或修改接口字段时，先在 spec 或变更记录里说明契约变化，并确认是否触发人工确认
- 代码注释使用中文，说明业务意图、关键约束或非直观实现原因，避免逐行翻译式注释

## 与 monorepo 的关系

request 统一放在根目录 `docs/harness/requests/` 下，不在 `apps/front` 内部另建一套流程。一个 request 可以同时覆盖前端、后端与文档，保持前后端任务规则一致。
