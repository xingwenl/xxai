---
id: 2026-10-21-desktop-app-and-plugin-update
tier: B
risk: medium
approval:
  required: true
  granted: true
  why: ["新增宿主 HTTP 端点 GET /api/desktop/app-update、POST /api/desktop/app-update/download、POST /api/desktop/app-update/reveal、POST /api/desktop/plugin-market/update", "插件市场响应的条目新增 installedVersion/hasUpdate，索引条目新增可选 mirrors（发布契约变化）", "新增发布清单格式 apps/desktop/releases/latest.json 与本地 state.json 新增 updatedAt/previousVersion 字段"]
---

## 目标与范围

一句话：补齐桌面宿主的两条更新链路，并把发布配套做成可执行脚本，让「子应用（插件）升级」和「宿主应用升级」都能从 GitHub/Gitee 拿到经过校验的包。

1. **子应用更新**：插件市场里同一 id 的索引版本高于本机已装版本时，条目显示「更新到 vX」；点击后宿主下载 → 校 sha256/size → 校包内 `manifest.json` 的 id/version → 备份旧目录 → 原子替换 → 保留 `enabled` 与 `plugin-data`/`plugin-config`；失败自动回滚到旧版本。内置插件随宿主更新，不参与；`type=remote` 的纯壳插件不参与。
2. **宿主应用更新**：设置页新增「应用更新」区块，展示当前版本；点「检查更新」拉静态发布清单（GitHub raw 主源 + Gitee raw 镜像回退），有新版本时展示版本号/发布时间/更新说明；「下载并校验」把当前平台产物落到 `~/.desktop-app/updates/<version>/` 并校 sha256/size，然后**引导用户手动安装**（打开所在文件夹 + 查看发布页），宿主不替换自身。
3. **发布配套**：`apps/desktop/scripts/make_release.py` 把 `dist/` 打成各平台 zip、算 sha256/size 并生成/更新 `apps/desktop/releases/latest.json`；同时校验 `app_config.APP_VERSION`、`pyproject.toml` 的 `[project].version`、`front/package.json` 的 `version` 三处一致。README 补 GitHub/Gitee 发布步骤与环境变量。

现状痛点（本仓库源码，2026-10-21）：
- `apps/desktop/desktop_app/manager.py:131` 安装时 `any(p.id == manifest.id ...)` 命中即抛 `PluginExistsError`；`market.install_entry()`（`apps/desktop/desktop_app/market.py:263`）复用它，所以市场对已装插件只能返回 409，前端设置页把已安装条目的按钮禁用成「已安装」（`apps/desktop/front/src/components/settings.tsx:642`），前序 `2026-10-21-desktop-plugin-market` 特意把「自动更新已装插件」推迟到单独一刀。
- 宿主没有任何「检查新版本」能力，`APP_VERSION` 只用于 health/窗口/Info.plist；仓库没有发布清单，也没有 `apps/desktop` 的发布流程。
- 发布侧 `scripts/make_plugin_zip.py` 只打插件包；宿主产物 `dist/WW.app`、`dist/WW/` 需要人工压缩、手算 hash，再手写清单。

**不做**：宿主静默自替换/自动重启（见被否决项）；代码签名与公证（清单校验只到 sha256，和插件市场同一信任模型）；Windows 安装器（NSIS/MSI）与增量/差分更新；插件降级与「回滚到指定旧版本」的 UI（只保留最近 3 份备份目录，供人工恢复）；GitHub Actions 自动发布 workflow（清单与包由本地脚本生成后手动上传，理由见被否决项）；市场评分/下载量；多语言文案。

## 来源与方案比较

官方/成熟案例（调研日期 2026-10-21）：
- Tauri v2 Updater（<https://v2.tauri.app/plugin/updater/>，抓取 HTTP 200）：用「静态 JSON 清单或更新服务器」驱动更新，清单按平台给 `signature` + 下载 `url`，安装前强制验签；文档明确支持 macOS/Windows/Linux，并提供 `installMode` 等安装策略。本刀借它的「静态清单 + 分平台资产」形态，签名降级为 sha256（本项目拿不到签名密钥链也无法通过 macOS 公证）。
- akm（本机 `/Users/lixingwen/xw/git/akm`，版本 0.1.55，2026-10-21 读源码）：`akm/version.py::version_greater()` 是逐段数字比较、支持预发布后缀的完整实现；`akm/menubar.py::_fetch_update_info()` 走 GitHub Releases API 并区分「失败」与「已是最新」；`_pick_zip_download_url()` 只挑与本机架构精确匹配的 zip，匹配不到宁可不更新；`akm/plugins/plugin_manager.py` 用 `version_greater(market_version, installed_version)` 算 `has_update`。本刀移植它的版本比较规则，但把 API 源换成静态 raw 清单。
- 本仓库既有市场实现（`2026-10-21-desktop-plugin-market`）：下载侧 `_validate_url`（生产 https / 本机 file）、5 分钟内存缓存、`read_archive_manifest()` 校验包内清单、`install_entry()` 组装下载+校验+落盘。插件升级复用这套下载校验，只在其后追加「备份 + 替换 + 回滚」。

方案比较（宿主更新来源）：

| 方案 | 做法 | 结论 |
|---|---|---|
| A 静态清单 JSON（采纳） | 仓库 `releases/latest.json`，GitHub raw 主源 + Gitee raw 镜像，资产带 sha256/size/mirrors | 无匿名限流（前序 spec 已否决 `api.github.com`）、GitHub/Gitee 都能托管、离线可 file:// 联调 |
| B GitHub Releases API | `releases/latest` + `assets[].browser_download_url` | 匿名 60 次/小时限流、拿不到 sha256，且 Gitee 无等价 API |
| C 只打开下载页 | 不下载不校验 | 体验最弱，用户仍要手算/信任下载文件，校验形同虚设 |

方案比较（宿主安装方式）：

| 方案 | 做法 | 结论 |
|---|---|---|
| A 下载+校验+引导手动安装（采纳） | 落到 `~/.desktop-app/updates/`，打开目录与发布页 | 未签名产物过不了 Gatekeeper/受 Windows 文件占用限制，手动替换出错面最小 |
| B 静默替换自身并重启 | 退出→换 .app/目录→重启 | macOS 未签名会被拦、Windows 运行中文件不可覆盖，失败即打不开 |
| C 拉起安装器 | 下载后执行 setup.exe/pkg | 需要签名与安装器，本轮无发布流水线支撑 |

方案比较（插件替换方式）：

| 方案 | 做法 | 结论 |
|---|---|---|
| A 备份 → 同盘 rename 换目录 → 失败回滚（采纳） | 备份到 `plugin-backups/<id>/<old>-<ts>/`，原子替换 | 保留旧版本可人工恢复，失败不影响运行 |
| B 允许 `install_zip` 覆盖写 | 直接删旧装新 | 非原子、丢 `enabled`/安装时间，中途失败即半装 |
| C 新版本装成 `<id>-<version>` 并存 | 多目录并存 | 改插件 id 会破坏 `plugin-data`/工具名绑定，不成立 |

## 被否决的选项

- **宿主静默自替换 / 自动重启**：产物未签名未公证，macOS Gatekeeper 会拦、Windows 运行中文件不可覆盖；失败后应用打不开，回滚成本远高于「下载完成后让用户手动安装」。
- **GitHub Releases API 作为唯一更新源**：匿名限流、拿不到 sha256，且 Gitee 无等价 API；与本仓库市场用 raw 静态 JSON 的既定路线一致。
- **GitHub Actions 自动发布 workflow**：当前产物未签名，CI 构建的包同样过不了 Gatekeeper/SmartScreen；macOS runner 成本高且要先解决签名，等签名方案落地再加。
- **插件升级直接删旧装新（不备份）**：升级失败无法回滚，用户只能重装并可能丢 `plugin-config`（配置在 `plugin-config/<id>/`，虽不受目录替换影响，但半装状态会脏）。
- **引入 PyUpdater / tauri-updater / electron-updater 等第三方更新库**：Python 侧没有与本项目打包形态（PyInstaller onedir + pywebview）匹配的成熟自更新库，PyUpdater 需要独立更新服务器与密钥体系，超出「静态清单 + 手动安装」的体量。
- **升级时迁移插件数据或重写 manifest**：`plugin-data/`、`plugin-config/` 按 id 独立存放，升级只换代码目录，不需要迁移；迁移只会引入额外失败面。
- **让前端自己算 `hasUpdate`**：版本比较规则必须单一实现，前端用字符串比较会踩 `0.10.0` vs `0.9.0`，所以由宿主下发 `hasUpdate`。
- **宿主更新清单里塞签名（minisign/GPG）**：与插件市场同一信任模型，本项目没有密钥分发/轮换方案，加签名只是一种「看起来很安全」的空转。

## 停点判断

- 架构边界变化：否（全部改动在 `apps/desktop` 内，复用既有 zip 安装与静态资源模型；新增模块文件不新建包目录）
- 数据模型变化：是（`state.json` 的插件条目新增可选 `updatedAt`/`previousVersion`，旧状态文件可读、缺省即兼容；无数据库）
- API 契约变化：是（新增 4 个端点、市场响应新增字段、索引与发布清单格式为可发布契约）
- 鉴权或权限行为变化：否（更新不改变插件 `permissions` 白名单，也不给插件新增能力；宿主端点仅本机回环可访问，沿用现有模型）
- 结论：命中「数据模型变化 + API 契约变化」，`approval.required: true`；本文件写完后先确认要点，再写实现代码。

## 变更点

后端 `apps/desktop/desktop_app/`：
- 新增 `version.py`：`normalize_version()`、`version_greater(a, b)`（移植 akm 规则：逐段数字比较、无后缀正式版 > 有后缀预发布、非数字段退化字符串、非法输入不抛异常），供插件市场与宿主更新共用。
- 新增 `transfer.py`：从 `market.py` 抽出 `validate_url()`（生产 https / 本机回环 http / file://）、`read_url()`（限字节、超时、中文错误）、`sha256_bytes()`、`read_first(urls, ...)`（按顺序试主源与 mirrors，全失败才抛错并汇总原因）；`market.py` 改为导入它们，行为不变。
- 新增 `app_update.py`：`APP_UPDATE_ENV = "DESKTOP_APP_UPDATE_URL"`、`APP_UPDATE_MIRRORS_ENV = "DESKTOP_APP_UPDATE_MIRRORS"`、`APP_UPDATE_DISABLE_ENV = "DESKTOP_APP_UPDATE"`；`DEFAULT_APP_UPDATE_URL`（GitHub raw `main/apps/desktop/releases/latest.json`）与 Gitee raw 默认镜像；清单解析（`version: 1` 格式版本、`latest`、`publishedAt`、`notes`、`releaseUrl`、`platforms{macos-arm64,macos-x64,windows-x64,linux-arm64,linux-x64}` 每项 `name/url/mirrors/sha256/size`，sha256 64 位十六进制、size 正数）；`platform_key()` 由 `sys.platform` + `platform.machine()` 映射；`get_update_info(refresh=False)` 带 10 分钟缓存，返回 `{enabled, source, current, latest, hasUpdate, notes, publishedAt, releaseUrl, asset, error}`，主源与镜像全失败时给中文原因而不是「已是最新」；`download_asset()` 下载到 `~/.desktop-app/updates/<version>/`（`.part` 后 rename），校 size/sha256，失败清理；`reveal_updates_dir()` 只打开固定的更新目录（macOS `open`、Windows `os.startfile`、Linux `xdg-open`，不接收任意路径）。
- `paths.py`：新增 `updates_dir()`、`plugin_backups_dir()`。
- `manager.py`：新增 `upgrade_zip(zip_path, expected_id, expected_version)`——复用 `_install_zip` 的安全解压/根目录归一化/manifest 校验；仅允许用户插件（内置拒绝）；`version_greater(新, 旧)` 不成立即拒绝；备份旧目录到 `plugin_backups/<id>/<old>-<ts>/` 并只留最近 3 份；同盘 rename 换目录，异常时把备份移回；状态保留 `enabled`/`installedAt`，写 `updatedAt`、`previousVersion`；写 `plugin.log`。
- `plugin_log.py`：`EVENT_NAMES` 增加 `update_ok`、`update_failed`（README 事件表同步）。
- `market.py`：`MarketEntry` 增加可选 `mirrors: tuple[str, ...]`（索引条目可给 Gitee 等镜像下载地址，按序回退）；`fetch_index()` 支持主源失败后按 `DESKTOP_PLUGIN_MARKET_MIRRORS` 回退；新增 `upgrade_entry(manager, entry)`：校验索引版本高于已装版本 → 下载校验（复用 `install_entry` 的 sha256/size/包内 manifest 校验）→ 交 `manager.upgrade_zip()`。
- `server.py`：`GET /api/desktop/plugin-market` 条目补 `installedVersion`/`hasUpdate`；新增 `POST /api/desktop/plugin-market/update {id}`（未装 404、非更高版本 400、下载 502、校验/替换失败 400 且已回滚）、`GET /api/desktop/app-update?refresh=`、`POST /api/desktop/app-update/download`、`POST /api/desktop/app-update/reveal`；`desktop_settings()` 增 `appUpdateUrl`/`appUpdateEnabled`。

前端 `apps/desktop/front/src/`：
- `lib/api.ts`：`MarketEntry` 增 `installedVersion`/`hasUpdate`/`mirrors`；新增 `updateMarketPlugin(id)`；新增 `AppUpdateAsset`/`AppUpdateInfo` 与 `getAppUpdate(refresh)`、`downloadAppUpdate()`、`revealAppUpdates()`；`DesktopSettings` 增 `appUpdateUrl`/`appUpdateEnabled`。
- `components/settings.tsx`：市场条目按钮三态（安装 / 更新到 vX / 已是最新）；新增「应用更新」区块（当前版本、更新源、检查按钮、新版本信息 + notes、平台不支持提示、下载并校验、打开所在文件夹、查看发布页）；框架信息区补更新源与更新目录。

发布配套与文档：
- 新增 `apps/desktop/scripts/make_release.py`：`--dist`/`--version`/`--notes-file`/`--out`/`--asset-base-url`/`--mirror-base-url`/`--json`/`--check-only`；macOS 用 `ditto -c -k --keepParent` 打 `.app`，Windows/Linux 用 `zipfile` 打 onedir 目录；算 sha256/size；默认资产 URL 模板 `https://github.com/xingwenl/xxai/releases/download/desktop-v<version>/<name>`；生成/合并 `releases/latest.json`（只更新当前平台条目，保留其余平台）；三处版本号不一致时非 0 退出并列出差异。
- 新增 `apps/desktop/releases/latest.json`（`{"version": 1, "latest": "0.2.0", "publishedAt": ..., "notes": ..., "platforms": {}}` 骨架，`make_release.py` 后续填充）。
- `apps/desktop/README.md`：新增「### 更新（插件升级 / 宿主升级 / 发布）」一节（清单格式、`make_release.py` 用法、GitHub Releases + Gitee 发行版上传步骤、`DESKTOP_APP_UPDATE*`/`DESKTOP_PLUGIN_MARKET_MIRRORS` 环境变量、未签名说明、插件备份目录与回滚方式）。
- `.codex/skills/desktop-agent-subapp/SKILL.md`、`docs/CHANGELOG.md` 同步。
- 新增 `tools/harness/verify/2026-10-21-desktop-app-and-plugin-update.sh` 与运行产出的 `verify.md`。

## 验收标准

1. `cd apps/desktop && .venv/bin/python -m pytest tests/ -q` 全绿；新增 `tests/test_version.py`（`0.10.0 > 0.9.0`、`1.0.0 > 0.99.99`、`0.2.0 > 0.2.0-beta`、相等为 False、`v` 前缀/非法输入不抛异常）、`tests/test_app_update.py`（清单解析与非法字段、平台键映射、镜像回退、下载 sha256/size 校验、下载失败不落文件）、`tests/test_market.py` 扩展（`hasUpdate` 计算、升级成功保留 enabled/配置、降级与同版本拒绝、sha 不匹配时旧版本目录与状态回滚、`mirrors` 回退）。
2. `pnpm --dir apps/desktop/front build` 通过（含 tsc 类型检查）。
3. API 探针（临时 HOME + `file://` 索引）：已装 v1、索引 v2 → `GET /api/desktop/plugin-market` 的条目 `hasUpdate=true`；`POST .../update` 后插件目录内容为 v2、`plugin-data/<id>/` 与 `enabled` 原样、`plugin-backups/<id>/` 出现 v1 副本；把索引 sha256 改错后再升级 → 400 且目录仍为 v1、状态未变。
4. API 探针（`file://` 发布清单）：`latest` 高于当前版本且含本平台资产时 `GET /api/desktop/app-update` 返回 `hasUpdate=true` 并选中该资产；`POST .../download` 后文件落在 `updates/<version>/` 且 sha256/size 通过；清单 sha256 改错 → 400 且不落文件；主源不可用时自动回退镜像。
5. `python scripts/make_release.py --dist <临时假 dist> --json`：产出 zip 与清单，清单里的 sha256/size 与文件实际值一致；把 `front/package.json` 版本改坏后 `--check-only` 非 0 退出并指出三处不一致。
6. `python3 tools/harness/audit.py` 无本次新增 ERROR，`verify.md` 由 `tools/harness/verify.sh` 生成并显式列出未执行项。

## 变更点（2026-10-21 实现对齐）

实现期相对上文的细化与偏差，均已落到代码与 `verify.md`：

- `version.py` 实际导出 `normalize_version()`、`compare_versions()`、`version_greater()`（比较拆出 `_split_version`/`_compare_prerelease`），比原计划多一个可复用的三值比较。
- `transfer.py` 除 `read_first()` 外还抽出流式下载 `download_to()`/`download_first()`：先写 `<dest>.part`，**替换正式文件之前**校验 size/sha256（`expected_size`/`expected_sha256`），坏包不会覆盖上一次已校验成功的安装包；`market.py` 的 `_read_url`/`_validate_url` 变成薄包装，市场行为不变。
- `market.py` 新增私有 `_download_verified()`（下载 → size → sha256 → 包内 manifest id/version 与索引一致）与 `install_entry` 共用；`upgrade_entry()` 只做「已装且非内置/非 remote、`version_greater` 成立」的前置校验，实际替换仍走 `manager.upgrade_zip()`。
- `manager.py` 把安装期「解压 → 根目录归一化 → manifest 校验」抽成 `_stage_zip` 上下文管理器（安装与升级共用），`MAX_PLUGIN_BACKUPS = 3`。
- `POST /api/desktop/plugin-market/install` 与 `/update` 都改用 `market.fetch_index(refresh=True)` 强制刷新索引：否则 5 分钟缓存里的旧版本会把「刚发布的包」判成「不高于已安装版本」而 400。
- `releases/latest.json` 骨架的 `latest` 留空字符串而不是 `0.2.0`：先发清单但没有真实产物时，宿主应报「清单里没有可用版本」，而不是给 0.2.0 用户误报更新；首次发版由 `make_release.py` 写入。
- `scripts/make_release.py` 的最终参数是 `--check-only/--version/--platform/--asset/--notes/--reset/--github-repo/--gitee-repo`（不发 `--dist/--out/--notes-file/--json`）：资产 URL 由 repo + `desktop-v<version>` tag 模板生成，镜像地址按 Gitee 域名改写；「生成 ZIP」直接复用 `build/build.py` 的 `dist/` 产物。
- `GET /api/desktop/settings` 只新增 `appUpdateUrl`/`appUpdateEnabled`，未加 `updatesDir`；「打开所在文件夹」走 `POST /api/desktop/app-update/reveal`，前端不拼路径。
