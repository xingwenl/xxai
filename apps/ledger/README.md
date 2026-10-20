# 记账（ledger）

桌面宿主里的记账子应用：**纯网页**，自身不跑服务、不连数据库——数据能力由宿主提供，
同时把记账方法暴露给全局助手，让「帮我把午饭 32 元记到餐饮」这类指令能真正落库。

- 技术栈：React 19 + TypeScript + Vite，无路由、无 UI 框架
- 数据：宿主 `storage`（落到磁盘 JSON）；脱离宿主直接打开时回退浏览器 localStorage
- 对外：注册 5 个 `ledger_*` 工具，宿主据此做后台策略（新增/删除属财务类操作）

## 目录

```
apps/ledger
├── public/manifest.json   宿主插件清单（构建时拷进 dist 根目录）
├── public/icon.svg        应用图标
├── scripts/install-to-desktop.mjs   安装到宿主插件目录
└── src
    ├── App.tsx            单页界面（汇总 / 记一笔 / 明细）
    ├── lib/desktop.ts     window.desktop 适配与就绪等待
    ├── lib/store.ts       数据仓库：串行写入队列 + 订阅
    ├── lib/tools.ts       ledger_* 工具注册
    ├── lib/format.ts      金额与日期格式化
    └── lib/types.ts       数据模型与默认分类
```

## 本地开发

```bash
pnpm install                 # 根目录安装一次即可
pnpm --dir apps/ledger dev   # http://127.0.0.1:5181
```

浏览器直接打开时没有 `window.desktop`，页面进入「浏览器本地」模式：数据写
`localStorage['ledger:data']`，工具不注册。开发模式仍代理 `/api` 到 `127.0.0.1:8765`，
方便宿主后端联调。

## 构建与安装

```bash
pnpm --dir apps/ledger build          # tsc --noEmit + vite build，产物在 apps/ledger/dist
pnpm --dir apps/ledger install:desktop
# 可选：node scripts/install-to-desktop.mjs --zip / --target <目录> / --json
```

安装脚本会把 `dist/` 整体同步到 `~/.desktop-app/plugins/ledger/`（先清空该目录，
不动其他插件），**重启桌面应用**后即可在应用页看到「记账」。

失败时脚本以退出码 1 结束并给出中文提示；`--json` 成功时只打印
`{"installedTo": "...", "zip": "..."}`，便于脚本断言。

## 对外方法

所有方法都是 async，入参为对象；金额对外一律用「元」，内部按「分」存储。

| 方法 | 入参 | 返回 |
| --- | --- | --- |
| `ledger_add_entry` | `amount`（元，必填）、`category`（必填）、`type`（`expense`/`income`，默认 `expense`）、`note`、`occurred_on`（`YYYY-MM-DD`，默认今天） | `{ ok, entry, month_summary }` |
| `ledger_list_entries` | `month`（`YYYY-MM`）、`type`、`category`、`limit`（默认 50，上限 500） | `{ items, total }`，按日期倒序 |
| `ledger_month_summary` | `month`（默认当前月） | `{ month, expense_yuan, income_yuan, balance_yuan, by_category }` |
| `ledger_delete_entry` | `id`（必填） | `{ ok, id }`；记录不存在时报「记录不存在」 |
| `ledger_list_categories` | 无 | `{ expense, income }` |

`ledger_add_entry` / `ledger_delete_entry` 标记为 `sideEffect: 'financial'`，其余为 `none`。

默认分类：支出「餐饮、交通、购物、居住、娱乐、医疗、学习、其他」；收入「工资、奖金、
理财、其他收入」。自定义分类追加到数组尾部并自动去重。

## manifest 与权限

```json
{ "id": "ledger", "type": "iframe", "entry": "index.html",
  "permissions": ["storage", "tools", "notify"] }
```

- `storage`：读写宿主持久化数据（必需）
- `tools`：把 `ledger_*` 方法注册给全局助手
- `notify`：保存 / 删除成功后的轻提示（缺失时静默）

构建时 `base: './'`，所有资源都是相对路径，可以被宿主以任意前缀托管
（`/apps/ledger/`、`file://` 均可），因此不使用 history 路由。

## 数据位置

| 场景 | 位置 |
| --- | --- |
| 桌面宿主 | `~/.desktop-app/plugin-data/ledger/ledger.json` |
| 浏览器直接打开 | `localStorage['ledger:data']` |

首次接入宿主时，若宿主侧还没有数据而浏览器本地已有账目，会整体迁移到宿主，
避免清缓存或换模式导致丢账。所有写入串行执行（read-modify-write 加锁），
界面与工具调用共享同一份内存快照，任一侧改动都会立刻反映到页面。
