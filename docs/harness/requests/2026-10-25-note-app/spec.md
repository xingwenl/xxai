---
id: 2026-10-25-note-app
tier: B
risk: medium
approval:
  required: true
  granted: true
  why: ["新增独立子应用 apps/note 与 pnpm workspace 成员（跨 apps/ 改动）", "新增 7 个 note_* 方法契约：名称与入参 schema 一旦定下会被后台 HostToolPolicy 指纹复用", "新增笔记/分类的 JSON 数据结构，落在宿主 plugin-data"]
---

## 目标与范围

一句话：新建独立子应用 `apps/note`（「念记」），构建产物作为 desktop iframe 插件安装，提供笔记的记录、读取与分类，并向桌面全局助手注册 `note_*` 方法。

- 应用能力（v1）：新建 / 编辑（标题、正文、分类、标签）/ 搜索 / 按分类筛选 / 删除到废纸篓 / 恢复与彻底删除 / 新建自定义分类；正文为纯文本 Markdown。
- 子应用方法（7 个）：`note_create_note`、`note_list_notes`、`note_get_note`、`note_update_note`、`note_set_category`、`note_list_categories`、`note_delete_note`。
- 数据：单份 JSON 快照；宿主 `storage` key `note` → `~/.desktop-app/plugin-data/note/note.json`；无宿主时回退 `localStorage('note:data')`，首次接入宿主时整体迁移。
- 视觉：沿用设计稿 `apps/desktop-note` 的三栏结构与设计语言（深绿 `#29463b`、衬线标题、米白底、7~11px 圆角、小字号、980/760px 两档响应式），去掉全部远程资源、假数据与无功能入口（分享、用户资料、写死计数）。
- 非目标：不做 AI 自动推断分类（分类只由界面或工具显式写入）；不做富文本 HTML 与图片上传；不改宿主 `apps/desktop/` 任何代码；不上架插件市场；不做多用户/云同步/加密；不新增后端接口。

## 来源与方案比较

已核实的宿主契约（本机源码）：
- 权限与 SDK 能力表：`apps/desktop/README.md:189-260`（storage 全异步、`tools.register`、notify、settings 只读）。
- 同形态已落地的子应用：`apps/ledger/tools.json`、`apps/ledger/src/lib/desktop.ts`、`apps/ledger/src/lib/store.ts`、`apps/ledger/src/lib/tools.ts`（2026-10-20 记账子应用，B 档，verify 脚本 `tools/harness/verify/2026-10-20-ledger-app.sh`）。
- 官方参考（核对日期 2026-10-25）：MDN [`contenteditable`](https://developer.mozilla.org/en-US/docs/Web/HTML/Global_attributes/contenteditable)、MDN [`execCommand`（已废弃）](https://developer.mozilla.org/en-US/docs/Web/API/Document/execCommand) —— 富文本编辑需自建序列化/消毒/撤销栈，纯静态子应用承担不起。

| 方案 | 做法 | 结论 |
|---|---|---|
| 独立 `apps/note` + iframe 插件（采纳） | 照 `apps/ledger` 骨架新建项目，`dist/` 即插件；数据与工具沿用宿主通用能力 | 可独立构建/安装，宿主零改动 |
| 直接改造 `apps/desktop-note` | 在设计稿工程上加数据层与方法 | 否决：Figma Make 工程（`.figma/make/*`、`figma:` 占位、远程字体图片），无 manifest/tools.json |
| 宿主内置页面或宿主侧笔记 REST | 笔记逻辑写进 `apps/desktop` | 否决：同 ledger 教训，业务漏进宿主，子应用成空壳 |
| 正文用 contentEditable 富文本 | 存 HTML，工具收发 HTML | 否决：需 HTML 消毒与互转，模型传参不可控 |

## 被否决的选项

- **在 `apps/desktop-note` 设计稿上直接改造**：Figma Make 工程含 `.figma/` 脚本与插件、Google Fonts/Unsplash 远程资源、无 manifest 与 tools.json，改造成本高于照骨架重建；设计稿只作视觉参照，原样保留不改。
- **引入 Tailwind CSS v4 + shadcn/ui**：设计稿样式全是自定义语义类（`.app-shell`/`.note-card`/`.editor-body` 等），Tailwind 只增加依赖、构建插件与类名噪音；界面用一份独立 `styles.css`。
- **保留 Google Fonts（DM Sans / Noto Serif SC）与 Unsplash 封面图**：桌面应用常在离线或内网环境，远程资源导致字体闪烁、封面空白；改用系统字体栈（`'Songti SC'`/`'Noto Serif SC'`/serif、`-apple-system`/`'PingFang SC'`）与本地 CSS 渐变封面色带。
- **contentEditable 富文本并存放 HTML**：需要 HTML 消毒、HTML↔纯文本互转、自定义撤销栈，工具入参 `content` 会变成 HTML 片段；改为纯文本 Markdown + `textarea`，工具栏只插入 Markdown 记号。
- **把笔记存储或工具实现放进宿主 Python 侧**：业务逻辑与文件格式漏进宿主，后续每个子应用都要改宿主；沿用「数据在宿主通用能力、业务在子应用」的边界。
- **把 ledger 的 `store/tools` 抽成公共 workspace 包复用**：两者各约 200 行且会各自演进，抽包新增一个包并耦合发布节奏；本轮复制后各自演进。
- **以 `localStorage` 作为唯一持久化**：清缓存即丢、无法被宿主统一管理，仅作脱离宿主调试时的降级。
- **本轮上架插件市场**：市场索引需维护 zip/sha256，本任务只需本机安装契约，延后。

## 停点判断

- 架构边界变化：命中 —— 新增独立子应用 `apps/note`（workspace 成员 + 插件）。
- 数据模型变化：命中 —— 新增笔记/分类 JSON 结构与软删字段。
- API 契约变化：命中 —— 新增 7 个 `note_*` 方法名、入参 schema 与返回形状。
- 鉴权或权限行为变化：未命中 —— 沿用 `storage`/`tools`/`notify`，不改宿主权限白名单与鉴权。
- 核心资料缺失：未命中 —— 宿主与 SDK 契约已从本机源码核实。
→ `approval.required: true`，实现前需用户确认。

## 变更点

- 新增 `apps/note/`：`package.json`（`note-web`，dev 5182）、`vite.config.ts`（`base:'./'`、`outDir:'dist'`）、`tsconfig.json`、`index.html`、`src/main.tsx`、`src/App.tsx`、`src/styles.css`、`src/lib/types.ts`、`src/lib/format.ts`、`src/lib/desktop.ts`、`src/lib/store.ts`、`src/lib/tools.ts`、`tools.json`（7 个方法唯一契约源）、`public/manifest.json`（id `note`、`permissions:["storage","tools","notify"]`）、`public/icon.svg`、`scripts/install-to-desktop.mjs`、`README.md`。
- `pnpm-workspace.yaml`：追加 `- 'apps/note'`；根 `package.json`：追加 `dev:note` / `build:note`。
- `apps/note/src/lib/store.ts`：串行写队列 + `mutate` 读-改-写 + `useSyncExternalStore` 快照 + localStorage→宿主迁移（照 ledger 模式）。
- `apps/note/src/lib/tools.ts`：`onHostAttach` 一次性注册 7 个方法，入参宽松解析，非法值抛中文错误。
- 新增 `tools/harness/verify/2026-10-25-note-app.sh`：`pnpm --dir apps/note build`、dist 断言（manifest 字段、bundle 内含 7 个方法名）、`tools.json`↔README 方法表↔`tools.ts` 三处一致性、安装脚本探针（`--target` 临时目录 `--json`）、无头浏览器加载探针。
- 新增 `tools/harness/verify/2026-10-25-note-markdown.browser.mjs`（verify 脚本第 7 步）：真实 Chrome + CDP 断言 Markdown 渲染结构、编辑/预览切换、废纸篓预览与 760px 无溢出，并留截图。
- `apps/note/package.json`：新增 `react-markdown@^10` + `remark-gfm@^4`（与 `apps/front` 同版本）；`src/components/markdown-view.tsx` 用它们把正文渲染成 React 元素；`App.tsx` 增加「编辑 / 预览」切换（⌘E、`localStorage['note:editor-mode']`），废纸篓只读预览复用同一组件，图片降级为占位文本、外链 `noopener`。
- `docs/CHANGELOG.md`：新增当日条目。

## 验收标准

1. `pnpm install && pnpm --dir apps/note build` 通过，`dist/` 含 `index.html`、`manifest.json`、`assets/*`；`pnpm --dir apps/note dev` 可独立使用（无宿主时数据落 `localStorage`）。
2. `node apps/note/scripts/install-to-desktop.mjs` 后，桌面应用列表出现「念记」卡片，点开进入三栏界面；新建/编辑/搜索/按分类筛选/删除到废纸篓/恢复均可用，重启桌面应用后数据仍在 `~/.desktop-app/plugin-data/note/note.json`。
3. 全局助手工具集合含 7 个 `note_*` 方法，且启动后不打开「念记」也可用（`tools` 权限静默预挂载）；`DESKTOP_DEV_AGENT=1` 下说「记一条笔记：……，归到灵感」→ 命中 `note_create_note` 与 `note_set_category`，界面即时出现该笔记。
4. `note_list_notes` 的 `query`/`category`/`limit` 过滤与 `note_get_note` 正文返回正确；`note_update_note` 只改传入字段；`note_delete_note` 为软删（列表默认不含，JSON 内仍保留 `deleted_at`）。
5. README 方法表、`tools.json`、`src/lib/tools.ts` 三处方法名一致（verify 脚本 grep 校验）。
6. `bash tools/harness/verify/2026-10-25-note-app.sh` 全部通过并生成 `verify.md`；`python3 tools/harness/audit.py` 无本 request 相关报错。
7. 界面在 1280×720 与 760px 窄宽下不横向溢出（760px 侧栏收为图标列），无控制台报错，无任何远程请求。
