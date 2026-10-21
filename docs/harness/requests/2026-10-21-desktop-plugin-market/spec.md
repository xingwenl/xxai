---
id: 2026-10-21-desktop-plugin-market
tier: B
risk: medium
approval:
  required: true
  granted: false
  why: ["新增宿主 HTTP 端点 GET /api/desktop/plugin-market 与 POST /api/desktop/plugin-market/install", "新增插件索引文件格式（第三方可发布契约）与 sha256 校验路径"]
---

## 目标与范围

一句话：第三刀给桌面宿主补上「插件市场」——维护者在仓库里发一份索引，用户在设置页/命令行按 id 一键安装，下载的 zip 必须与索引里的 sha256 逐字节一致：

1. **索引**：仓库内 `apps/desktop/market/index.json` 是默认市场源（GitHub raw 托管，避开 `api.github.com` 匿名限流），格式含插件 id / 名称 / 版本 / 下载地址 / sha256 / 大小。
2. **安装**：宿主下载 zip → 校验大小上限与 sha256 → 校验包内 `manifest.json` 的 id 与索引一致 → 复用既有 `manager.install_zip()` 落盘（不新写解压逻辑）。
3. **CLI**：`apps/desktop/scripts/plugin_market.py` 提供 `list` / `install` / `entry` / `verify` 四个子命令，与宿主共用 `desktop_app/market.py`，维护者用 `entry` 把新 zip 的 sha256/size 直接打印成索引条目。

现状痛点（本仓库源码）：
- 目前只有两条安装入口：`apps/desktop/desktop_app/server.py:155` 上传 zip（用户得自己去网上找包）、`:177` 安装 remote 壳插件（只存 URL，零权限）。没有任何「可信来源 + 完整性校验」的发现/安装通道。
- `apps/desktop/desktop_app/security.py:10` 已有 `MAX_ZIP_SIZE`/`MAX_ENTRIES`/双轮校验，`manager.install_zip()`（`apps/desktop/desktop_app/manager.py:97`）已封装「归一化根目录 + 冲突检测 + 事件日志」，市场只需在下载侧加一道 hash 门。
- 发布侧只有 `apps/desktop/scripts/make_plugin_zip.py` 打 zip，不打 hash，维护者要手算 sha256 才能写索引。

**不做**：索引签名/GPG（本轮只做 sha256，签名留待有发布流程时再议）；远程索引的服务端（静态 JSON 足够，谁托管都行）；插件的下载量/评分/评论；自动更新已装插件（本轮只做首次安装）；市场卡片进首页（放设置页，不占首屏）；不新增第三方依赖（用 `urllib` + `hashlib` + `zipfile`）。

## 来源与方案比较

实时依据（本机源码，2026-10-21）：
- akm 的市场实现（`/Users/lixingwen/xw/git/akm/akm/server.py` 与 `plugins/plugins.json`）：索引放仓库、tag `plugin-market`、走 `raw.githubusercontent.com`、下载后校 sha256、上传包上限 20MB/500 文件/解压后 100MB、插件名正则校验。本刀照抄这套形态并按本仓库体量缩到单文件索引。
- 可复用形态：`manager.install_zip()` + `PluginExistsError/PluginError` 的错误分层、`PluginLog` 事件日志、`paths.user_plugins_dir()`。

方案比较（索引托管）：

| 方案 | 来源 | 结论 |
|---|---|---|
| A 仓库内 JSON + raw.githubusercontent（采纳） | 仓库 | 零服务端、走 CDN、无匿名限流，发布只是提 PR |
| B 打进应用包内的静态清单 | 应用包 | 发新插件就得发新版本，失去「市场」意义 |
| C 自建 HTTP 服务 | 自建 | 本轮无人运维，过度设计 |
| D GitHub Releases API 列表 | api.github.com | 匿名 60 次/小时限流，且拿不到 sha256 |

方案比较（下载校验位置）：

| 方案 | 校验方式 | 结论 |
|---|---|---|
| A 下载侧先校 sha256，再交给 manager（采纳） | hashlib + 已有 zip 校验 | 职责清晰，manager 仍是唯一落盘方 |
| B 让 manager 接受 expected_sha256 参数 | 混进落盘流程 | 上传 zip 的路径不需要 hash，参数会变成死配置 |
| C 只信 https 不校 hash | — | CDN/仓库被投毒即执行任意本地代码，不可接受 |

## 被否决的选项

- **索引签名 / GPG 验签**：sha256 只保证「下载到的字节与索引里写的一致」，索引本身的可信度靠仓库权限与 HTTPS；本轮没有密钥分发与轮换方案，做了也是自欺。
- **自动更新已安装插件**：更新要处理「运行中插件被替换、用户数据迁移、版本回滚」，比首次安装重一个数量级，单独一刀再说。
- **市场列表进首页**：首页已经有概览卡与工具网格，市场的使用频率是「一次性安装」，藏进设置页更合适。
- **新增 `requests`/`httpx` 依赖**：桌面后端目前只用标准库，`urllib.request` 足够，且打包体积与 PyInstaller 兼容性都更稳。
- **让 `manager.install_zip()` 接收 expected_sha256**：上传路径无 hash 可校，会给落盘函数加一个永远为 None 的参数；改为在 `market.py` 里下载校验完再调用。
- **把索引写进 `state.json` 或 `plugin-data`**：那是用户本机状态与插件自有数据，索引是发布侧的只读契约，混进去会互相污染。
- **市场安装走 remote 壳（只存 URL）**：当前 remote 插件权限恒为空、SDK 不注入，装不了真正有能力的子应用，市场要装的是 iframe 包。

## 停点判断

- 架构边界变化：否（全部在 `apps/desktop` 内，复用既有 iframe + zip 安装模型）
- 数据模型变化：否（无数据库；索引是仓库里的静态 JSON；不写 `state.json` 新字段）
- API 契约变化：是（新增 `GET /api/desktop/plugin-market`、`POST /api/desktop/plugin-market/install`；新增索引文件格式；`/api/desktop/settings` 增 `marketUrl`）
- 鉴权或权限行为变化：否（市场安装的插件仍按自身 manifest 的 `permissions` 走既有白名单，市场不额外放权）
- 结论：命中「API 契约变化」，`approval.required: true`；本文件写完后先确认要点，再写实现代码。

## 变更点

后端 `apps/desktop/desktop_app/`：
- 新增 `market.py`：`MARKET_ENV = "DESKTOP_PLUGIN_MARKET_URL"`、`MARKET_DISABLE_ENV = "DESKTOP_PLUGIN_MARKET"`、`DEFAULT_MARKET_URL`；`MAX_INDEX_BYTES = 256 * 1024`、`MAX_MARKET_PLUGINS = 200`、`CACHE_TTL_SECONDS = 300`、`FETCH_TIMEOUT_SECONDS = 10`；`MarketError`；`MarketEntry`（宽松解析 + 严格校验：`id` 匹配 `PLUGIN_ID_PATTERN`、`sha256` ≥ 并等于 64 位十六进制、`download` 只接受 `https` / `file` 或回环地址的 `http`、`size` 可选但出现时须等于实际字节数且 ≤ `MAX_ZIP_SIZE`）；`fetch_index()` 带 5 分钟内存缓存与 `refresh=True` 旁路；`install_entry()` 下载 → 校 sha256 → 用 `zipfile` 读包内 `manifest.json` 校验 id/version 与索引一致 → 交 `manager.install_zip()`。
- `server.py`：新增 `GET /api/desktop/plugin-market`（`{enabled, source, plugins, installed}`，获取失败 502 且带中文原因）、`POST /api/desktop/plugin-market/install {id}`（不存在 404、已安装 409、校验失败 400、下载失败 502）；`desktop_settings()` 增 `"marketUrl"`。
- `scripts/plugin_market.py`（新）：`list` / `install <id>` / `entry <zip>` / `verify <zip> --sha256`，复用 `market.py` 与 `PluginManager`。
- `scripts/make_plugin_zip.py`：打完包额外打印 sha256 与字节数，方便直接贴进索引。

前端 `apps/desktop/front/src/`：
- `lib/api.ts`：`MarketEntry{id,name,version,description?,download,sha256,size?,permissions?}`、`PluginMarket{enabled,source,plugins,installed}`、`getPluginMarket()`、`installMarketPlugin(id)`；`DesktopSettings` 增 `marketUrl`。
- `components/settings.tsx`：新增「插件市场」区块——打开设置页时拉一次（失败只显示中文原因，不打断页面其余部分），列表展示名称/版本/说明/大小 + 「安装」按钮，已安装显示「已安装 vX」；安装成功后 toast + 重拉插件列表 + 重拉市场（installed 状态）。
- 说明性文案：市场源地址、sha256 校验中、下载失败原因。

文档与验证：
- `apps/desktop/README.md`：新增「### 插件市场（market）」一节（索引格式示例、`plugin_market.py entry` 生成条目、默认源与两个环境变量、sha256 与 id 校验规则）、设置页 bullet 补市场区块、FAQ（市场列表为空 / 安装报 sha256 不匹配）。
- 新增 `apps/desktop/market/index.json`（`{"version": 1, "plugins": []}`）作为默认源骨架。
- `.codex/skills/desktop-agent-subapp/SKILL.md`、`docs/CHANGELOG.md`。
- 新增 `tools/harness/verify/2026-10-21-desktop-plugin-market.sh` 与运行产出的 `verify.md`。

## 验收标准

1. `cd apps/desktop && .venv/bin/python -m pytest tests/ -q` 全绿；新增 `tests/test_market.py` 覆盖：索引校验（非法 id / 非 64 位 sha256 / `http` 非回环拒绝 / size 超 20MB / 超过 200 条）、`file://` 索引与 zip 的正常安装、sha256 不匹配时不落盘且插件目录不残留、包内 manifest id 与索引不一致拒绝、已安装返回冲突、缓存 TTL 与 `refresh` 旁路、市场关闭时 `enabled:false`。
2. `pnpm --dir apps/desktop/front build` 通过（含 tsc 类型检查）。
3. headless 探针：临时 HOME + 本地回环 HTTP 提供索引与 zip（用 `make_plugin_zip.py` 现打 hello-world 包），打开设置页看到「插件市场」区块与条目，点「安装」后插件出现在应用页、`plugin.log` 含 `install_ok`、`~/.desktop-app/plugins/<id>/` 落盘；同一条目再点安装显示「已安装」。
4. CLI：`python scripts/plugin_market.py entry <zip>` 输出的 sha256/size 与 `shasum -a 256` 一致；`install` 在临时 HOME 下能装成功；`verify` 在不匹配时退出码非 0。
5. `python3 tools/harness/audit.py` 无本次新增 ERROR。

## 变更点（2026-10-21 实现对齐，用户已确认方案）

实现时相对上面正文的细化，均不扩大范围：

- `read_archive_manifest()` 从「manifest.json 只在根目录或唯一子目录」放宽为「包里只能有一个 `manifest.json`（根目录或任意一层子目录）」，因为既有 `make_plugin_zip.py` 产出的是 `plugins/<id>/manifest.json`；多个 manifest 仍拒绝，提示「插件包结构不合法」。
- 索引里的 `size` 与 `permissions` 都是可选字段：`size` 出现时必须等于实际字节数且 ≤ `MAX_ZIP_SIZE`；未知 `permissions` 只记 warning 不阻断上架（与 `protocol.unknown_permissions()` 的宽松策略一致）。
- `apps/desktop/market/index.json` 不是空骨架，首条即内置 `hello-world`（`download` 指向本仓库 main 分支 raw 地址，包体提交在 `apps/desktop/market/packages/hello-world-0.1.0.zip`），用户首次打开设置页就能看到真实条目。
- 形成闭环的发布流程写进 `apps/desktop/README.md`：`make_plugin_zip.py`（顺带打印 sha256/size 与索引条目）→ 包放 `market/packages/` → 条目写 `market/index.json` → 提 PR；`plugin_market.py entry` 也可从任意 zip 生成条目。
- 验证脚本用 `file://` 索引与 `file://` 包地址（`_read_url()` 已支持），而不是正文里写的「本地回环 HTTP」：少一个临时静态服务器，断言相同（解析/下载/校验/落盘链路完全一致）。
- 前端市场区块在正文之外补了三个状态：读取中、市场关闭（`DESKTOP_PLUGIN_MARKET=0`）、错误态 + 「重试」按钮；条目行展示权限与包大小，已安装条目按钮禁用并显示「已安装」。
