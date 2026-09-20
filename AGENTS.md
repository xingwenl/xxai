# AGENTS

本仓库采用 Harness v2 方式进行 AI 辅助开发。流程、分档规则、文档规格的**唯一依据**是 [docs/harness/HARNESS-V2.md](docs/harness/HARNESS-V2.md)，动手前先读它。

## 三道门

1. **想清楚**：确定范围、来源、被否决的选项、验收标准（A/B 档写 `spec.md` 并获用户确认）
2. **做出来**：写代码（A/B 档同时写 `tools/harness/verify/<id>.sh`）
3. **证明它**：跑验证脚本，真实输出落进 `verify.md`

## 分档：看 diff 路径，不看自觉

- **A 架构级**：碰 `**/migrations/**`、`**/models.py`、`**/auth/**`、`**/security*.py`、新建模块目录 → `spec.md` + ADR + 拷问（两轮封顶）
- **B 契约级**：碰 `**/schemas.py`、`**/router.py`、`**/api/**`、跨 `apps/` 改动 → `spec.md`
- **C 局部**：以上都不碰 → 不写文档、不建 request，直接一次提交

命中即取最高档，拿不准按 B。分档只能上调。

## 停点

A/B 档在 `spec.md` 写完后，必须先把方案要点发给用户确认，用户确认前不写实现代码。C 档直接做。

审批触发条件（命中即 `approval.required: true`）：架构边界变化、数据模型变化、API 契约变化、鉴权或权限行为变化、核心功能缺少关键资料无法可靠比较方案。

## 硬约束

- 正式文档用中文；不产生仓库变更的问答、代码解释和讨论不创建 request。
- `spec.md` ≤150 行，连续代码块 ≤30 行；「被否决的选项」必须非空。
- `verify.md` 由 `tools/harness/verify.sh <id>` 产出，必须显式列出未执行项；不写"已测试通过"。
- 提交前跑 `python3 tools/harness/audit.py`。
- 2026-09-20 之前创建的 request 属于存量，冻结不动、不迁移、不补文档。

## 代码编写约定

- 后端在 `models.py` 中定义表结构时，每个字段必须通过 ORM/数据库字段定义的 `comment` 元数据添加清晰的中文备注，说明字段含义或用途。
- 编写代码时，应根据逻辑复杂度和维护需要增加必要的中文注释；注释应解释业务意图、关键约束或非直观实现原因，避免添加无意义的逐行翻译式注释。


详细规则见 `docs/harness/HARNESS-V2.md`。

## Harness 入口指令

AI 识别到以下指令时，先执行对应的最小动作；完整语义、适用场景和示例统一维护在 [docs/harness/HARNESS-V2.md](docs/harness/HARNESS-V2.md)：

- `/new <主题>`：判断分档；A/B 档建 request 并写 `spec.md`，C 档直接实现
- `/modify <request-id 或主题>`：在原 request 的 `spec.md` 变更点中追加本次改动
- `/fix <request-id 或主题>`：C 档直接修；触发 A/B 档条件时按 A/B 档走
- `/verify <request-id>`：跑 `tools/harness/verify.sh <request-id>`，用真实输出刷新 `verify.md`

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

## 重要开发
涉及 Agent Loop、工具执行、Skill/Command 加载、上下文压缩、会话持久化、事件回放、权限边界等非局部架构决策时，先调研至少一个成熟 Agent 项目的实际实现或官方资料，再提出方案。
   - 优先阅读本机源码，不先做网络搜索：Pi 位于 `/Users/lixingwen/xw/git/pi`

推荐提交流程：

1. 在根仓库确认任务范围与分档
2. A/B 档：写 `spec.md` → 用户确认 → 实现 → `tools/harness/verify.sh` → 提交；C 档：实现 → 最小验证 → 提交
3. 先完成最小验证，再执行 Git 提交
4. 若同时修改前端、后端、Harness 文档，优先在根仓库一次性提交闭环结果
