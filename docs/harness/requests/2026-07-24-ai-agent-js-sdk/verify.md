# 验证记录

## 执行命令

### 2026-08-10 文档增量验证

- `git diff --check` - 验证 README 和 Harness 文档没有空白错误。
- `rg -n "api/v1/embed/tokens|client_secret|external_user_id|无后端代理" apps/ai-sdk/README.md` - 验证 README 覆盖 token 获取、身份来源和无代理边界。
- `npm run verify-package`（工作目录 `apps/ai-sdk`）- 验证 SDK 包入口和现有构建产物仍完整。
- `rg -n '^```' apps/ai-sdk/README.md | wc -l` - 验证 Markdown 代码围栏数量为偶数。
- `sed -n '1,420p' apps/ai-sdk/README.md` - 人工核对安装、初始化、代理示例、生命周期、工具和安全清单章节。

### 2026-07-31 增量验证

- `cd apps/ai-sdk && npm run test -- --run` - 验证 token provider 上下文、空 token 和重连行为及既有 SDK 回归。
- `cd apps/ai-sdk && npm run type-check` - 验证 TypeScript/Vue 类型。
- `cd apps/ai-sdk && npm run build` - 验证 ESM、UMD 和类型声明产物。
- `cd apps/backend && poetry run pytest tests/embed -q` - 验证 Embed Client、token exchange 和外部用户映射回归。
- `git diff --check` - 验证文档和代码没有空白错误。

- `npm install` - 安装依赖（已完成）
- `npm run build` - 构建项目（已完成）

## 预期结果

- 安装成功，所有依赖正确下载
- 项目结构完整，符合预期
- 运行 `npm run build` 能够成功构建 ESM 和 UMD 格式
- 运行 `npm run dev` 能够正常启动 Demo 页面

## 实际结果

### 2026-08-10 文档增量结果

- ✅ README 已合并为单一接入入口，覆盖生产、本地 Demo 和无后端代理边界。
- ✅ 文档中的生产接口、响应结构和现有后端实现一致。
- ✅ 明确未将尚未实现的 Public Client/OIDC 接口描述为当前可用能力。
- ✅ SDK 包入口校验通过，代码围栏数量为 42 个且成对。
- ✅ `git diff --check` 通过。

### 2026-07-31 增量结果

- ✅ SDK 全量测试通过：5 个测试文件、18 个测试通过。
- ✅ `npm run type-check` 通过。
- ✅ `npm run build` 通过，生成 ESM、UMD、CSS 和类型声明。
- ✅ 后端 Embed 测试通过：14 个测试通过。
- ✅ `git diff --check` 通过。
- ✅ 测试证明 SDK 每次认证向 provider 传递连接上下文、空 token 不发送 auth、重连重新获取 token。
- ✅ 文档明确 `getToken` 返回短期 Embed Access Token，`external_user_id` 来自接入方服务端业务身份。
- ✅ 新增 `docs/runbooks/agent-sdk-usage.md`，覆盖生产接入、本地 Demo、消息事件和宿主工具使用方法。

- ✅ 项目目录结构已创建完成
- ✅ 所有源代码文件已实现
- ✅ package.json 配置正确
- ✅ TypeScript 配置文件已添加
- ✅ Vite 配置文件已添加
- ✅ Demo 页面已创建
- ✅ README 文档已编写
- ✅ 修复 Vue 组件中的 defineProps 问题（ChatWidget.vue、FloatingButton.vue、ChatInput.vue）
- ✅ 修复 vite.config.ts 中的字符串语法错误
- ✅ 修复 TypeScript 类型警告
- ✅ 构建成功，生成了 ESM 和 UMD 包
- ✅ 类型声明文件成功生成

**修复内容：**
- 所有 Vue 组件中的 `withDefaults(defineProps<Props>(), { ... })` 现在都正确赋值
- 避免了重复调用 defineProps 的问题
- 修复了 vite.config.ts 中的字符串语法错误
- 修复了 TypeScript 类型警告

## 失败项与例外

### 2026-07-31

- 首次按计划执行的 `npm run typecheck` 因仓库不存在该脚本失败；package.json 实际脚本为 `type-check`，已使用正确命令重新验证通过。
- 未执行真实第三方平台联调；生产接入方仍需确认其 token 代理从登录态取得 `external_user_id`。

- 无
