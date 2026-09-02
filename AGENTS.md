# AGENTS

本仓库采用 Harness Engineering 方式进行 AI 辅助开发。

必须遵守的阶段顺序：
1. research
2. spec
3. plan
4. implement
5. verify
6. acceptance

开发新功能时，必须先了解业界成熟案例，再确定 spec 和 plan。调研结果记录在 request 的 `research.md` 中，至少包含来源、方案比较和最终决策。

AI 默认可以连续推进，但若任务涉及以下变更，在进入实现或完成前必须等待人工确认：

- 架构边界变化
- 数据模型变化
- API 契约变化
- 鉴权或权限行为变化
- 核心功能缺少关键业界资料，无法可靠完成方案比较

**写代码前必须先与用户对齐方案**：任何任务完成或更新 `spec.md`（含 `/new`、`/modify`、`/fix` 的增量变更记录）后，必须先把方案要点发给用户确认；用户确认前不得进入后续 `plan`/实现阶段写代码。

AI 生成的正式文档必须使用中文。
不产生仓库变更的问答、代码解释和讨论，不创建 request。

## 代码编写约定

- 后端在 `models.py` 中定义表结构时，每个字段必须通过 ORM/数据库字段定义的 `comment` 元数据添加清晰的中文备注，说明字段含义或用途。
- 编写代码时，应根据逻辑复杂度和维护需要增加必要的中文注释；注释应解释业务意图、关键约束或非直观实现原因，避免添加无意义的逐行翻译式注释。


详细规则见 `docs/harness/README.md`。

## Harness 入口指令

AI 识别到以下指令时，先执行对应的最小动作；完整语义、适用场景和示例统一维护在 [docs/harness/README.md](docs/harness/README.md)：

- `/new <主题>`：创建新 request，先调研，再按 `research -> spec -> plan` 推进
- `/modify <request-id 或主题>`：判断是否仍属原闭环；可复用时记录增量，否则转 `/new`
- `/fix <request-id 或主题>`：复用原 request，记录 bugfix 变更
- `/verify <request-id>`：更新 `verify.md`，记录真实验证证据
- `/accept <request-id>`：更新 `acceptance.md`，记录验收结论和剩余风险

## Skills 调用分流

AI 执行 `/new`、`/modify` 或 `/fix` 时，必须先读取并遵守 [`docs/harness/policies/global.md`](docs/harness/policies/global.md) 中的 Skill 调用策略：复杂度不明确或存在高风险信号时采用复杂策略（先完成上下文梳理和方案确认），轻量策略也必须保留变更记录和最小验证。

## 增量与轻量变更

`/modify`、`/fix` 的 request 复用、变更记录、轻量模式和升级条件，统一遵守 [`docs/harness/policies/global.md`](docs/harness/policies/global.md)。任何增量都必须留下变更记录和最小验证证据；触发架构、数据模型、API 或权限审批条件时，先确认再实现。

## 专项规范

- 涉及 `apps/backend/`：必读 [docs/harness/backend.md](docs/harness/backend.md)
- 涉及 `apps/front/`：必读 [docs/harness/frontend.md](docs/harness/frontend.md)
- 仓库级技能（`.codex/skills/`）：Codex 会自动索引该目录；任务匹配其描述时，先读取并遵守对应 `SKILL.md`（如 `.codex/skills/backend-basic-crud-table/`、`.codex/skills/frontend-architecture.md`、`.codex/skills/frontend-styling.md`）

## Git 管理约定

本仓库统一按**单仓库 monorepo** 管理（本地目录 `ai-base`，GitHub remote `xingwenl/xxai`）：

- 根仓库是唯一 Git 仓库，`apps/front`、`apps/backend`、`apps/ai-sdk` 等都是根仓库下的普通目录
- 支持 worktree 并行开发，分支统一使用 `codex/<topic>` 前缀
- 前端、后端、文档改动统一在根仓库提交
- 一个任务尽量形成可独立回滚的单次提交或一组连续提交
- 不要把无关任务的改动混入同一次提交

提交信息使用 Conventional Commits 格式（`feat:`/`fix:`/`refactor:`/`docs:` 等），主题用中文概括；涉及文档改动时同步更新 `docs/CHANGELOG.md`。

推荐提交流程：

1. 在根仓库确认任务范围
2. 按 `research -> spec -> plan -> implement -> verify -> acceptance` 推进
3. 先完成最小验证，再执行 Git 提交
4. 若同时修改前端、后端、Harness 文档，优先在根仓库一次性提交闭环结果
