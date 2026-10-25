# 念记（note）

桌面宿主里的笔记子应用：**纯网页**，自身不跑服务、不连数据库——数据能力由宿主提供，
同时把 7 个 `note_*` 方法暴露给全局助手，让「记一条笔记：周末去看展，归到灵感」这类指令
能直接落成条目并出现在界面上。

- 技术栈：React 19 + TypeScript + Vite，无路由、无 UI 框架（样式是一份 `styles.css`）
- 数据：宿主 `storage`（落到磁盘 JSON 快照）；脱离宿主直接打开时回退浏览器 `localStorage`
- 对外：注册 7 个 `note_*` 工具，写操作声明 `sideEffect: 'write'`，读操作 `'none'`
- 正文：**纯文本 Markdown**，不是 HTML 富文本（`textarea` + 工具栏插入 Markdown 记号）

## 目录

```
apps/note
├── public/manifest.json   宿主插件清单（构建时拷进 dist 根目录）
├── public/icon.svg        应用图标（手写 SVG，无外链）
├── scripts/install-to-desktop.mjs   安装到宿主插件目录
├── tools.json             7 个 note_* 方法的唯一契约源
└── src
    ├── main.tsx           入口
    ├── App.tsx            三栏界面（分类 / 列表 / 编辑器）
    ├── styles.css         设计语言（深绿 #29463b、衬线标题、米白底）
    ├── lib/desktop.ts     window.desktop 适配与就绪等待
    ├── lib/store.ts       数据仓库：串行写入队列 + 订阅 + localStorage→宿主迁移
    ├── lib/tools.ts       note_* 工具注册
    ├── lib/format.ts      日期与摘要格式化
    └── lib/types.ts       数据模型、默认分类与长度上限
```

## 本地开发

```bash
pnpm install                 # 根目录安装一次即可
pnpm --dir apps/note dev     # http://127.0.0.1:5182
```

浏览器直接打开时没有 `window.desktop`，页面进入「浏览器本地」模式：数据写
`localStorage['note:data']`，`note_*` 方法不注册。开发模式仍代理 `/api` 到
`127.0.0.1:8765`，方便宿主后端联调。

## 构建与安装

```bash
pnpm --dir apps/note build            # tsc --noEmit + vite build，产物在 apps/note/dist
pnpm --dir apps/note install:desktop
# 等价手动调用，可选参数见下表：
node apps/note/scripts/install-to-desktop.mjs [--zip] [--target <目录>] [--json]
```

| 参数 | 作用 |
| --- | --- |
| 无参数 | 把 `dist/` 同步到 `~/.desktop-app/plugins/note/`（先清空该目录，不动其他插件） |
| `--zip` | 先打包成 `apps/note-0.1.0.zip`，再安装 |
| `--target <目录>` | 自定义安装目录（`~` 会被展开；拒绝覆盖 `dist/` 与项目根目录） |
| `--json` | 成功时只打印 `{"installedTo": "...", "zip": "..."}`，便于脚本断言 |
| `-h, --help` | 打印用法 |

失败时脚本以退出码 1 结束并给出中文提示。安装完成后**重启桌面应用**，应用页即可看到
「念记」卡片；`dist/` 里的 `manifest.json`、`icon.svg` 与 `assets/*` 都由宿主按相对路径加载。

## 界面

- **三栏**：左栏分类（含「全部笔记」「废纸篓」与各分类计数）、中栏列表（搜索框 + 条目摘要 +
  更新时间）、右栏编辑器（标题、分类、标签、正文）。
- **搜索**：标题 / 正文 / 标签做不区分大小写的关键词匹配，输入即过滤（与 `note_list_notes`
  的 `query` 语义一致）。
- **分类**：内置「思考、灵感、阅读、旅行、工作」，可在界面新建自定义分类；分类名不存在时
  工具调用会自动登记，不会静默丢笔记。
- **废纸篓**：删除是**软删除**（列表默认不含），可恢复或彻底删除；彻底删除才会从 JSON 里移除。
- **自动保存**：编辑器内容变更后自动落盘（串行写队列，读-改-写），不需要「保存」按钮；
  数据同时被界面与工具调用共享，任一侧修改都会立刻反映到另一侧。

980px 以下侧栏收窄，760px 以下收为图标列，保证窄窗口不横向溢出。

## AI 方法

所有方法都是 async，入参为对象；正文一律是纯文本 Markdown。**契约唯一来源是
`apps/note/tools.json`**：`src/lib/tools.ts` 从这里取得 schema，宿主的后台配置脚本也从这里
生成 HostToolPolicy，改签名时只改这一个文件，然后重新构建。

| 方法名 | 入参 | 返回 | sideEffect |
| --- | --- | --- | --- |
| `note_create_note` | `content`（必填）、`title`、`category`（缺省「思考」）、`tags`（字符串数组，最多 8 个） | `{ note, categories }`：`note` 含 `id`/`title`/`category`/`tags`/`created_at` | `write` |
| `note_list_notes` | `query`、`category`、`limit`（缺省 20，最大 200） | `{ items, total }`：`items` 每项含 `id`/`title`/`category`/`excerpt`/`tags`/`created_at`/`updated_at`，按更新时间倒序 | `none` |
| `note_get_note` | `id`（必填） | `{ note }`：含 `id`/`title`/`content`/`category`/`tags`/`created_at`/`updated_at`；不存在时报「笔记不存在」 | `none` |
| `note_update_note` | `id`（必填）、`title`、`content`、`category`、`tags`（整体替换，空数组即清空） | `{ note }`：更新后的笔记，未传字段保持不变 | `write` |
| `note_set_category` | `id`、`category`（均必填；新分类名会自动登记） | `{ note, categories }` | `write` |
| `note_list_categories` | 无 | `{ categories, total }`：每项含 `name`/`count`，按数量倒序，不含废纸篓 | `none` |
| `note_delete_note` | `id`（必填） | `{ ok, id, deleted_at }`：软删进废纸篓，可在界面恢复 | `write` |

列表接口只返回 `excerpt` 摘要，需要正文全文时再调用 `note_get_note`——避免一次工具返回把
几十条正文塞进上下文。默认分类为「思考、灵感、阅读、旅行、工作」，自定义分类追加到
`categories` 尾部并去重。

## manifest 与权限

```json
{ "id": "note", "name": "念记", "type": "iframe", "entry": "index.html",
  "permissions": ["storage", "tools", "notify"] }
```

- `storage`：读写宿主持久化数据（必需，缺了读写会被宿主拒绝）
- `tools`：把 `note_*` 方法注册给全局助手（缺了助手看不到任何笔记能力）
- `notify`：保存 / 删除成功后的轻提示（缺失时静默，不报错）

构建时 `base: './'`，所有资源都是相对路径，宿主可以任意前缀托管（`/apps/note/`、`file://`
均可），因此不使用 history 路由。

## 数据位置与格式

| 场景 | 位置 |
| --- | --- |
| 桌面宿主 | `~/.desktop-app/plugin-data/note/note.json`（`storage` key `note`） |
| 浏览器直接打开 | `localStorage['note:data']` |

整份数据是**单个 JSON 快照**（宿主 plugin-data 的单值上限 256 KiB，超限写入会被宿主拒绝，
因此正文有 20000 字符上限、标签最多 8 个）：

```json
{
  "version": 1,
  "categories": ["思考", "灵感", "阅读", "旅行", "工作"],
  "notes": [
    {
      "id": "…", "title": "…", "content": "纯文本 Markdown", "category": "灵感",
      "tags": ["展览"], "created_at": "ISO", "updated_at": "ISO", "deleted_at": null
    }
  ],
  "updated_at": "ISO"
}
```

- `deleted_at` 为 `null` 表示正常笔记；非空表示在废纸篓里（软删，**数据仍在**，界面可恢复）。
- 读取时对缺失字段做收敛（`version` 固定为 1），不会因为旧快照少字段直接白屏。
- 首次接入宿主时，若宿主侧还没有数据而浏览器本地已有笔记，会整体迁移到宿主，避免清缓存
  或换模式导致丢笔记。所有写入串行执行（读-改-写加锁），界面与工具调用共享同一份内存快照。

## 故障排查

**助手看不到 `note_*` 工具**，按下面顺序查：

1. **iframe 是否加载**：方法在页面运行后才注册。宿主首页会对声明了 `tools` 权限的子应用
   静默预挂载，但装好后仍需重启桌面应用；打开「念记」一次也能确认页面本身没报错。
2. **manifest 是否含 `tools`**：`dist/manifest.json` 的 `permissions` 缺 `tools` 时，
   `desktop.tools.register` 会被宿主直接拒绝，控制台有中文报错。
3. **是否在 `desktop-ready` 之后注册**：必须等宿主就绪（`window.desktop` 可用）再调用
   `register`，抢在就绪前注册会丢。
4. **后台策略 / 绑定 / schema 指纹不一致**：AI Base 网关会按「JSON 键排序 + 无空格」的
   sha256 比对页面注册的 schema 与后台 HostToolPolicy，并对未匹配的工具**静默忽略**（模型
   不会报错，只是「就是不用」）。改了 `apps/note/tools.json` 就要重新构建 + 重跑后台配置
   脚本，确保指纹、Agent 绑定、来源白名单三者一起更新。
5. **离线验证**：`DESKTOP_DEV_AGENT=1` 启动宿主会用规则式本地 mock 网关（
   `/api/v1/ws/agents/local`），不接真实模型也能验证「注册 → 工具调用 → 回结果」整条链路；
   说「记一条笔记：……」看是否命中 `note_create_note`。
6. **数据没落盘**：确认装的是宿主模式而不是浏览器直开（后者写 `localStorage`）；再用宿主
   的 plugin-data 接口读 `note` key 看快照是否存在。

## 接真实模型

宿主设置页「智能体后端」填写 AI Base 地址与 Embed Client 凭证后，全局助手直接由真实 Agent
驱动；本子应用不需要改代码，只需保证构建产物已安装、页面已被打开过（方法在页面运行后注册）。
后台一次性准备（策略 + 绑定 + 来源白名单）见
[apps/desktop/README.md](../desktop/README.md) 的「接真实模型（AI Base）」一节。
