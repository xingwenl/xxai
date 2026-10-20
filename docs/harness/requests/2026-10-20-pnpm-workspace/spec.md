---
id: 2026-10-20-pnpm-workspace
tier: B
risk: medium
approval:
  required: true
  granted: true
  why: ["跨 apps/ 改动（B 档）", "引入新的依赖管理边界：pnpm workspace + 单一根 lockfile", "front 镜像构建方式随之重写", "2026-10-20 用户确认纳入范围：ai-sdk + front + shop + desktop/front 四个 pnpm 应用全部进 workspace"]
---

## 目标与范围

- 把仓库改成 pnpm workspace：`apps/front`、`apps/ai-sdk`、`apps/shop`、`apps/desktop/front` 共用一份根 `pnpm-lock.yaml` 与一次 `pnpm install`，`xxai-agent` 由 `file:` 复制改为软链。
- 用户问题：改 SDK 源码走 `docker compose build front` 仍要 ~27s 重建 front 依赖层（原基线 3m07s），本地还要「重建 dist → 回宿主重跑 `pnpm install`」两步。
- 非目标：不迁移 `apps/backend`（Python）、`apps/desktop`（npm + Tailwind CLI）、`apps/chrome-extension`（无 package.json）；不改业务代码、API 契约、数据库、鉴权；不动 `apps/ai-sdk/package-lock.json` 与 `.github/workflows/publish-ai-sdk.yml`（SDK 发布仍走 `npm ci`）。

## 来源与方案比较

- [pnpm Workspace 文档](https://pnpm.io/workspaces)（本地 pnpm 9.15.9，调研日 2026-10-20）：根 `pnpm-workspace.yaml` 声明成员；`workspace:` 协议拒绝解析到非本地包；`sharedWorkspaceLockfile` 默认 true → 单一根 lockfile + 根 `node_modules`（硬链）+ 各包软链；`workspace:*` 在 pack/publish 时替换为实际版本。采用者：Vite 2021-09-26、Vue 2021-10-09、Next.js 2022-05-29、Angular 2025-07-31。
- 本机实测（`tmp/ws-test`、`tmp/ws-test2`）：根 `pnpm install` 会执行成员包的 `prepare`（dist 自动生成）、宿主 `node_modules/<pkg>` 是 `../../<pkg>` 软链、只生成根 lockfile；**但**在 workspace 根之下、未被 `packages` 匹配的目录里跑 `pnpm install`，会打印 `Scope: all 3 workspace projects` 并静默忽略该目录依赖（不建它自己的 `node_modules`）。
- 方案 A（选中）：全部 pnpm 应用纳入 workspace + Docker 单 install 层。收益：一次 install、SDK 改动不再让宿主重装（Docker 27s → ~15s）、干净克隆 install 即得 dist。限制：根 `node_modules` 变大（软链共享，无重复复制）。
- 方案 B：维持现状 + 只做 Docker 层缓存（上一轮已做）。限制：SDK 改动仍触发 front 依赖层（27s）、两份 ~500MB 安装、`file:` 复制的 dist 仍会 stale。
- 方案 C：SDK 发布到 npm 用版本号安装。限制：本地联调依赖发布节奏，见「被否决的选项」。

## 被否决的选项

- **只把 `apps/front` + `apps/ai-sdk` 纳入 workspace**：`apps/shop`、`apps/desktop/front` 里跑 `pnpm install` 会静默指向根 workspace，依赖装不上（本机实测），只能用 `--ignore-workspace` 兜底，文档与 DX 更差。
- **SDK 走 npm registry 版本号安装**：本地开发每次改 SDK 都要先发布/改版本号，联调节奏被发布流程绑死；且现有 `file:` 方案已支撑两个宿主。
- **`injectWorkspacePackages: true`（硬链复制而非软链）**：dist 变化后注入副本不会同步，官方文档需 `syncInjectedDepsAfterScripts` 另行补丁，软链没有这层状态。
- **保留各 app 的 `pnpm-lock.yaml` 再加根 lockfile**：pnpm 只认根 lockfile，子锁文件变成死文件，制造「各自可装」的误导。
- **把 `apps/desktop`、`apps/chrome-extension` 一并纳入**：它们不是 pnpm 项目（npm 不读 `pnpm-workspace.yaml`），纳入只会引入无关安装。

## 停点判断

- 架构边界变化：是——依赖管理从「每 app 独立 lock + `file:` 复制」改为「根单一 lock + workspace 软链」。
- 数据模型变化：否。
- API 契约变化：否。
- 鉴权或权限行为变化：否。
- 结论：`approval.required: true`；实现前需用户确认（范围含是否纳入 shop / desktop-front）。

## 变更点

- 新增根 `package.json`（private + `packageManager: pnpm@9.15.9` + `build:sdk` 脚本）与 `pnpm-workspace.yaml`（四个成员目录）。
- `apps/front/package.json`、`apps/shop/package.json`：`xxai-agent` 改为 `workspace:*`；子包现有 `packageManager` 声明保留（同版本，无冲突）。
- 删除 `apps/front/pnpm-lock.yaml`、`apps/shop/pnpm-lock.yaml`、`apps/ai-sdk/pnpm-lock.yaml`、`apps/desktop/front/pnpm-lock.yaml`，新增根 `pnpm-lock.yaml`。
- 重写 `apps/front/Dockerfile`：单 build 阶段（COPY 四个 manifest + workspace 文件 + 根 lock → 带 cache mount 的 `pnpm install --frozen-lockfile --ignore-scripts` → COPY `apps/ai-sdk` 源码 + `pnpm --filter xxai-agent build` → COPY `apps/front` 源码 + `pnpm --filter shadcn-admin exec vite build`），nginx 阶段不变；顺带把镜像内 pnpm 版本从 10.12.1 订正为 9.15.9。
- 同步文档：`apps/front/README.md`（安装段）、`apps/ai-sdk/README.md`（`file:` 复制说明）、`apps/shop/README.md`（本地开发安装）、`docs/harness/frontend.md`（根安装命令）、`docs/CHANGELOG.md`。
- 验证脚手架 `tools/harness/verify/2026-10-20-pnpm-workspace.sh`：根 install、软链与 dist、三个宿主构建、Docker 增量耗时、镜像冒烟、`audit.py`。

## 验收标准

1. 仓库根 `pnpm install --frozen-lockfile` 退出 0，只生成根 `pnpm-lock.yaml`；`git ls-files` 中不再有 app 级 `pnpm-lock.yaml`。
2. `apps/front/node_modules/xxai-agent` 是软链且指向 `apps/ai-sdk`；根 install 后 `apps/ai-sdk/dist/xxai-agent.es.js` 存在（`prepare` 生效）。
3. `pnpm --dir apps/front exec vite build`、`pnpm --dir apps/shop build`、`pnpm --dir apps/desktop/front build` 均退出 0。
4. `docker compose build front` 退出 0；只改 ai-sdk 源码后的重建 ≤60s（本机实测 15~26s，改造前 3m07s），只改 front 源码 ≤30s（实测 6~13s）。
5. 新镜像 nginx 容器首页与 index.html 引用资源全 200，`POST /api/v1/auth/login` 经反代返回 422。
6. `python3 tools/harness/audit.py` 退出 0（无 ERROR）。
