---
id: 2026-10-21-desktop-plugin-config-observability
tier: B
risk: medium
approval:
  required: true
  granted: false
  why: ["插件 manifest 对外契约扩展（新增可选 settings[]，第三方子应用按此登记）", "新增宿主 HTTP 端点与 SDK 公开方法（settings.getConfig / onChanged）"]
---

## 目标与范围

一句话：给桌面子应用补上「声明式配置 + 运行态可观测」——子应用在 manifest 里声明 `settings[]`，宿主设置页自动渲染表单并做类型校验，值落 `~/.desktop-app/plugin-config/<id>.json`；同时新增 `~/.desktop-app/plugin.log` 记录安装/启停/iframe 加载/SDK 注入/方法注册/配置保存，设置页按插件展示运行状态与已注册方法数。

现状痛点（本仓库源码）：
- 子应用配置只存在 iframe 的 localStorage（`apps/desktop/front/src/lib/desktop-sdk.ts:12` 的 `desktop:settings:` 前缀），清缓存即丢，宿主无法展示与备份，插件未加载时也读不到。
- 宿主只知道 `PluginInfo.enabled` 与 `PluginInfo.error`，而后者仅表达 manifest 解析失败（`apps/desktop/desktop_app/registry.py:90`）；iframe 未加载、SDK 注入失败、方法注册被忽略这三类「工具静默失效」（见 `.codex/skills/desktop-agent-subapp/SKILL.md` 硬规则一节）宿主完全不可见。

**不做**：不做热重载（第二刀）、不做插件市场索引（第三刀）；不做 `options_source` 动态数据源；不改既有 `desktop.settings.get/set`（localStorage 同步语义保留）；不改工具注册协议与后端策略指纹；不引入前端测试框架；不改 `plugin-data` 的键规则与 `state.json` 格式。

已知限制（沿用现状，本刀不扩大）：宿主所有插件接口同为 `127.0.0.1` 同源，理论上任何被注入 SDK 的 iframe 都可调其他插件的 config/plugin-data 端点；这与既有 plugin-data 端点同级，不新增提权面。

## 来源与方案比较

实时依据（本机源码与仓库技能，2026-10-21）：
- akm 的声明式配置：`akm/plugins/models.py:5` `SettingDef`（key/label/type/default/description/options/min/max）+ `akm/plugins/models.py:20` `PluginMeta.settings`；宿主按 schema 渲染表单，值存 `~/.akm/config.json` 的 `plugin_configs.{name}`，插件只读。
- akm 的加载日志：`akm/plugins/plugin_manager.py:38` `_append_plugin_launch_log` 把每个插件 `on_load` 结果追加到 `~/.akm/plugin.launch.log`（JSONL），用于排查「重启后插件 503」。
- 本仓库可直接对齐的既有实现：`apps/desktop/desktop_app/plugin_data.py:85` 的「临时文件 + `os.replace`」原子写、`apps/desktop/desktop_app/protocol.py:28` 的 manifest 强校验风格（中文错因）、`apps/desktop/front/src/lib/tool-bridge.ts:28` 的 pub/sub 模块形态、`apps/desktop/tests/conftest.py` 的 `plugin_env` / `seed_plugin` 测试夹具。

方案比较（配置存哪里 × 表单从哪来）：

| 方案 | 配置存哪里 | 表单从哪来 | 结论 |
|---|---|---|---|
| A 现状 | iframe localStorage | 插件自己写 | 清缓存即丢、宿主无法展示，弃 |
| B 复用 plugin-data 保留键 | `plugin-data/<id>/config.json` | 宿主按 `settings[]` 渲染 | 与插件自有键同命名空间，写权限边界混淆 |
| C 独立 plugin-config 目录（采纳） | `~/.desktop-app/plugin-config/<id>.json` | 同上 | 宿主权威配置与插件自有数据分离，与 akm 的 `plugin_configs` 分层一致 |
| D state.json 里加 config 段 | `~/.desktop-app/state.json` | 同上 | state.json 是宿主 UI 状态，无原子写、无大小上限 |

可观测性同理：事件必须由宿主进程写入宿主磁盘（iframe 自己 console 在 DevTools 之外拿不到），所以由前端 `POST /api/desktop/plugin-log` 上报、后端 JSONL 追加，文件语义与 akm 的 `plugin.launch.log` 对齐。

## 被否决的选项

- **复用 plugin-data 的保留键（方案 B）**：宿主配置只准宿主写、插件只读，插件数据归插件读写，两者权限模型不同；共用命名空间后第三方插件用同名键即互相破坏，将来做配置迁移/备份也无法区分来源。
- **存进 `state.json`（方案 D）**：那是插件启停这类宿主 UI 状态，没有原子写、没有大小上限，也不具备「用户数据」语义（用户备份 `~/.desktop-app` 时无法分辨）。
- **继续用 localStorage（方案 A）**：清缓存即丢、设置页无法统一呈现、插件未加载时读不到，正是本刀要修的问题。
- **让插件自己渲染配置界面、宿主只提供 storage**：每个子应用重复实现表单、校验与中文文案；akm 的 `settings[]` 已证明「schema 即 UI」成本最低。
- **manifest 用嵌套 `config` 对象而非 `settings[]` 数组**：数组保序且能携带 label/description/min/max 等 UI 元数据，字段形状与 akm 对齐，后续可平移 `options_source`。
- **把热重载、市场索引并进本刀**：与本刀的配置、可观测性无关，混入会让这次 diff 无法独立回滚。
- **只在浏览器 console 打日志、不落盘**：DevTools 关掉即无证据，「工具静默失效」仍需读源码猜；落盘才可 tail、可被验证脚本断言。

## 停点判断

- 架构边界变化：否（改动全部在 `apps/desktop` 内部，沿用既有 SDK 注入与 plugin-data 分层）
- 数据模型变化：否（宿主无数据库；新增的是本地配置文件格式，不是服务端数据模型）
- API 契约变化：是（manifest 新增可选 `settings[]`；新增 3 个 HTTP 端点；SDK 新增 `settings.getConfig/onChanged`）
- 鉴权或权限行为变化：是（`getConfig` 受既有 `settings` 权限门控，未声明即抛「权限不足」；既有 `settings.get/set` 语义不变）
- 结论：命中「API 契约变化」与「鉴权或权限行为变化」，`approval.required: true`；本文件写完后先确认要点，再写实现代码。

## 变更点

后端 `apps/desktop/desktop_app/`：
- `protocol.py`：新增 `SettingOption{label,value}` 与 `PluginSetting{key,label,type,default,description,options,min,max}`，`PluginManifest` 增 `settings`（默认空数组）；校验 key 正则、键唯一、`type ∈ text|number|boolean|select`、select 必带非空 options 且 default 命中、`min ≤ max`、default 与 type 匹配、最多 32 项。非法声明按现有风格让 manifest 整体报错（中文错因进 `PluginInfo.error`）。
- `registry.py`：`PluginInfo` 增 `settings` 字段并进 `to_dict()`，前端一次 `GET /api/desktop/plugins` 即可渲染表单。
- 新增 `plugin_config.py`：`PluginConfigStore`（`~/.desktop-app/plugin-config/<id>.json`，原子写、64 KiB 上限）、`merge_defaults`（默认值 + 已存值，丢弃未声明键）、`validate_values`（返回中文错因列表）。
- 新增 `plugin_log.py`：`append(plugin_id, event, detail=None, **fields)` 写 `~/.desktop-app/plugin.log`——JSONL、线程锁、超 1 MiB 轮转为 `plugin.log.1`、事件名白名单。
- `server.py`：新增 `GET/PUT /api/desktop/plugins/{id}/config`（PUT 校验失败 400 且不落盘）、`POST /api/desktop/plugin-log`（白名单外 400，detail 截断 4 KiB）；新增轻量守卫 `_require_plugin`（存在且 manifest 无错，不要求 enabled，便于给停用插件改配置）。
- `manager.py`：安装成功/失败、卸载、启停处打日志（沿用现有异常路径，不改返回值与状态文件格式）。

前端 `apps/desktop/front/src/`：
- `lib/api.ts`：`Plugin.settings` 类型、`getPluginConfig` / `savePluginConfig` / `logPluginEvent`。
- `lib/desktop-sdk.ts`：`settings.getConfig()`（异步读宿主配置，受 `settings` 权限门控，未声明走 `denied()`）、`settings.onChanged(cb)`（监听宿主窗口的 `desktop-config-changed`，按 `detail.pluginId` 过滤后回调）。
- 新增 `lib/runtime-status.ts`：运行态 pub/sub（`idle | ready | failed(原因)`），与 `tool-bridge.ts` 同形态，供设置页与后续卡片复用。
- `lib/tool-bridge.ts`：注册/跳过时上报日志；新增 `countPluginTools(pluginId)`。
- `components/plugin-view.tsx`：上报 `iframe_load` / `sdk_injected` / `sdk_inject_failed` 并刷新运行态（配置变更不经过 iframe 转发：SDK 直接订阅宿主窗口事件）。
- `components/settings.tsx`：插件行展示运行态、已注册方法数、manifest 错误；声明了 `settings[]` 的插件有「配置」按钮，点击弹出配置弹窗（实现见「变更点」）。
- `plugins/hello-world/`：演示插件声明 3 项 `settings[]`（text/boolean/select）并调用 `getConfig()` / `onChanged()`，作为「插件不写设置页也能被配置」的活样板（用户确认的增量）。

文档与验证：
- `apps/desktop/README.md`（manifest 字段表 + SDK 新方法 + 日志路径与格式）、`.codex/skills/desktop-agent-subapp/SKILL.md`（子应用侧要声明 `settings[]` 且需要 `settings` 权限才能读到）、`docs/CHANGELOG.md`。
- 新增 `tools/harness/verify/2026-10-21-desktop-plugin-config-observability.sh` 与运行产出的 `verify.md`。

## 验收标准

1. `cd apps/desktop && poetry run pytest tests/ -q` 全绿；新增用例覆盖：settings[] 六类非法声明被拒且错因中文、配置保存与默认值合并正确、非法值 400 且不落盘、plugin-log 白名单外事件 400、轮转与 JSONL 行格式。
2. `pnpm --dir apps/desktop/front build` 通过（含 tsc 类型检查）。
3. headless 探针（临时 HOME + 一个声明 `settings[]` 的测试插件）：设置页出现对应输入控件；改值保存后 `~/.desktop-app/plugin-config/<id>.json` 值正确；`~/.desktop-app/plugin.log` 出现 `config_saved` 与 `iframe_load` 记录。
4. 回归：`ledger`、`bookmarks-organizer`、`hello-world` 未声明 `settings[]` 时设置页不出现配置区，`desktop.settings.get/set` 仍读写 localStorage。
5. `python3 tools/harness/audit.py` 无本次新增 ERROR。

## 变更点（2026-10-21 追加，用户确认）

- 配置表单从设置页内联展开改为**弹窗**：新增通用 `components/dialog.tsx`（遮罩 + 居中卡片 + 标题/说明/底部按钮；支持 Esc 与点遮罩关闭、打开时锁背景滚动并把焦点移入首个输入控件、关闭后归还焦点、通过 portal 渲染到 body 以免被父级 overflow/transform 裁剪），供后续页面复用。
- 新增 `components/plugin-config-dialog.tsx`：字段仍由 `manifest.settings[]` 驱动，内部负责取默认值合并、保存（PUT）、中文错因内联展示；保存成功后关闭弹窗并广播 `desktop-config-changed`，失败保持打开。`settings.tsx` 只保留「点按钮 → 传插件对象给弹窗」。
- 验证脚本相应更新：断言点击「配置」后出现 `role="dialog"`、标题为「<插件名> 配置」、表单字段在弹窗内；保存后断言弹窗自动关闭、运行中 iframe 收到新值；「保存配置」点击范围收敛到弹窗内（设置页「智能体后端」区块有同名按钮）。
- `apps/desktop/README.md` 同步说明弹窗形态与 `Dialog` 组件的复用约定。
