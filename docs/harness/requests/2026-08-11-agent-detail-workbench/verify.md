# 验证记录

验证对象：`codex/agent-detail-workbench` 分支，提交 `548adea..7f735d8` 共 13 个提交，覆盖智能体详情工作台全部实施内容。

## 后端验证（2026-08-11）

环境说明：worktree 内 `apps/backend/.venv` 为空目录，验证使用主仓库完整 venv（`/Users/lixingwen/xw/study/ai-base/apps/backend/.venv`）。

```bash
# 静态检查
/Users/lixingwen/xw/study/ai-base/apps/backend/.venv/bin/ruff check \
  app/modules/agent app/modules/knowledge app/__init__.py tests/agent tests/knowledge
# 结果：All checks passed（退出码 0）

# 定向测试
/Users/lixingwen/xw/study/ai-base/apps/backend/.venv/bin/python -m pytest \
  tests/agent tests/knowledge tests/model_usage -q
# 结果：37 passed in 4.43s
```

## 前端验证（2026-08-11）

- 路由树：仓库无 `tsr` CLI，使用 `/tmp/gen-routes.mjs`（调用 router-generator 的 Generator API）重新生成 `routeTree.gen.ts`；确认包含 `/ai/bots/$agentId` 与 `/ai/model-usage`，且生成结果与已提交版本一致。
- ESLint：覆盖 `src/api/agent.ts`、`src/api/knowledge.ts`、`src/features/agents`、`src/features/model-usage/index.tsx`、`src/routes/_authenticated/ai/bots.tsx`、`src/routes/_authenticated/ai/model-usage.tsx` → 0 errors；仅 2 个 `react-refresh/only-export-components` 警告（`agent-version-form.tsx` 为既有模式，`model-usage.tsx` 为路由文件固有模式）。
- Prettier：`--check` 全部通过；期间对 `agent-usage-utils.ts` 与 `agent-usage-utils.test.ts` 执行 `--write` 统一格式并复测通过。
- 类型检查：`pnpm exec tsc --noEmit -p tsconfig.json --ignoreDeprecations 6.0 --typeRoots ./node_modules/@types --types node` 通过（TS6 需要额外参数）。
- 工具函数测试：`tsc` 编译 `agent-usage-utils.ts` 与 `agent-usage-utils.test.ts` 后由 node 执行，退出码 0。

## 全量构建（环境受限，未完成）

沙箱内 `apps/front/node_modules` 是指向主仓库的符号链接且写受限：`tsc -b` 无法写入 `node_modules/.tmp` 的 tsbuildinfo，`vite build` 无法写入 `node_modules/.vite-temp` 的配置临时文件，均在写入阶段 EPERM 失败。属于环境约束而非代码失败，未到达计划中提到的既有 `react-hook-form` 类型基线问题。

## 浏览器联调（环境受限，未执行）

计划 Step 4 为“环境允许时”执行。当前沙箱 Docker daemon 不可访问、无运行中数据库，主仓库后端已停止（127.0.0.1:8000 不可连接）；启动完整前后端栈超出沙箱能力，故桌面/移动端浏览器验证未执行，相关剩余风险记录在 `acceptance.md`。

## 结论

后端定向测试、ruff、前端 ESLint/Prettier、类型检查与工具函数测试全部通过；全量构建与浏览器联调受环境限制未完成，需合入主仓库后在用户正常开发环境补验。

## 修复记录：详情页被列表路由拦截（2026-08-11）

- 现象：访问 `/ai/bots/3` 时停留在列表页，详情页无法进入。
- 根因：`bots.tsx`（列表路由）与 `bots.$agentId.tsx`（详情路由）构成父子路由，且列表路由组件没有 `<Outlet/>`，TanStack Router 渲染父级组件后子路由内容无法输出（已在 `@tanstack/react-router` 源码 `Match.js` 确认：路由有 component 时由组件自行渲染 `Outlet`）。
- 修复：将两个文件重构为目录式兄弟路由 `bots/index.tsx` 与 `bots/$agentId.tsx`（与仓库既有 `users/index.tsx` 等模式一致），详情路由父级改为渲染 `Outlet` 的 `/_authenticated` 布局。
- 验证：重新生成 `routeTree.gen.ts` 后，两路由均为 `/_authenticated` 的子路由；用真实 router 包构造新旧两种树并匹配 `/ai/bots/3`：旧结构匹配含列表路由的 4 层，新结构仅匹配 `__root__ → _authenticated → 详情` 3 层；前端 tsc、ESLint、Prettier 全部通过，`to: '/ai/bots'` 类型引用仍有效。
