# 实施计划

## 变更文件

- `apps/desktop/desktop_app/protocol.py`：`PluginManifest` 新增 `url: str | None`，`type` 校验集合增加 `remote`；remote 时 `url` 必填且为 http/https、`entry` 可省略。
- `apps/desktop/desktop_app/metadata.py`（新增）：元数据抓取器。抓取链：web manifest.json → og 标签 → `<title>` + favicon；图标下载（大小/内容类型限制 + SVG 消毒）；受限 HTTP 客户端（仅公网 http/https、SSRF 校验、重定向逐跳重校验）。
- `apps/desktop/desktop_app/registry.py`：`PluginInfo` 增加 `url` 字段；remote 插件 `entryUrl=url`、`iconUrl=本地图标`、`permissions` 强制为空。
- `apps/desktop/desktop_app/manager.py`：新增 `install_from_url()`（抓取 → 生成 manifest → 下载图标 → 原子落盘 → 记录 state）与 `refresh_metadata()`；插件 id 由域名规范化生成，冲突加后缀。
- `apps/desktop/desktop_app/server.py`：新增 `POST /api/desktop/plugins/install-from-url`、`POST /api/desktop/plugins/{id}/refresh-metadata`。
- `apps/desktop/front/src/lib/api.ts`：`Plugin` 类型增加 `url` 与 `type: "remote"`；新增 `installFromUrl` / `refreshMetadata` 封装。
- `apps/desktop/front/src/components/settings.tsx`：新增「添加应用」表单（URL 输入、自动抓取、可编辑名称/描述/图标、重新抓取按钮）。
- `apps/desktop/front/src/components/plugin-view.tsx`：remote 分支不注入宿主 SDK、sandbox 保持 `allow-scripts allow-same-origin allow-forms`、显示「在系统浏览器打开」降级按钮。
- `apps/desktop/tests/test_metadata.py`（新增）：抓取链降级、SSRF 拒绝、SVG 消毒、图标大小限制。
- `apps/desktop/tests/test_remote_plugin.py`（新增）：安装/重新抓取接口、remote 插件 registry 输出、权限置空。
- `docs/harness/requests/2026-08-21-desktop-url-plugin/`：本 request 六件套。

## 实施步骤

1. 先扩展数据模型：`protocol.py`（url / type=remote 校验）与 `registry.py`（PluginInfo.url、entryUrl、权限置空），补对应单测。
2. 实现 `metadata.py`：受限 HTTP 客户端 + SSRF 校验 + 三级抓取链 + 图标下载/消毒，补单测。
3. 实现 `manager.py` 的 `install_from_url` / `refresh_metadata` 与 `server.py` 两个新接口，补接口单测。
4. 前端：`api.ts` 类型与封装 → `settings.tsx` 添加应用表单 → `plugin-view.tsx` remote 分支 → 前端构建。
5. 验证：`pytest`、`ruff`、前端构建；真实站点手工回归（可嵌入与不可嵌入站点各一个）。
6. 收尾：填写 `verify.md`、`acceptance.md`、同步 `meta.json`。

## 测试步骤

- `cd apps/desktop && poetry run pytest tests/ -v`：预期全部通过，覆盖协议校验、抓取链、SSRF、消毒、安装/刷新接口。
- `cd apps/desktop && poetry run ruff check .`：预期无告警。
- `pnpm --dir apps/desktop/front build`：预期构建成功。
- 真实站点回归（需公网，沙箱可能受限，由用户本机执行或申请网络批准）：安装一个可嵌入站点与一个不可嵌入站点（如 `X-Frame-Options: DENY` 的站点），核对应用页打开与降级行为。

## 回滚说明

- 本次为纯增量：新增字段与接口均为可选扩展，现有 `iframe` / `react` 本地插件不受影响。
- 回滚方式：撤销本次 commit；删除 `~/.desktop-app/plugins/` 下新增的 remote 插件目录即可恢复。
- 重点关注：`protocol.py` 的 type 校验集合变化不得收紧现有合法值；`server.py` 新路由不得影响现有 `/apps/{plugin_id}` 静态托管。

## 人工确认点

- 已确认：方案 A2（iframe 内嵌 + 系统浏览器降级）、纯壳零权限、手动编辑 + 重新抓取按钮。
- 当前无待确认项；若真实站点抓取遇到反爬/网络策略，需向用户说明后按「允许手动填写元数据」降级处理。
