# 设计说明

## 目标

- 本次 request 解决什么问题：桌面宿主壳支持「从 URL 添加远程壳插件」——输入公网网址，自动抓取元数据（或手动填写）后安装为插件，应用页点击以 iframe 内嵌打开，站点拒绝嵌入时降级为系统浏览器打开。
- 目标用户与受影响对象：桌面应用用户；受影响模块为 `apps/desktop` 的 manifest 协议、插件注册表、插件管理、内嵌 API 与宿主前端。
- 完成后可验证结果：输入 URL 可安装 remote 插件并出现在应用页；remote 插件纯壳运行（无宿主 SDK、零权限）；可嵌入站点 iframe 打开、不可嵌入站点提示并以系统浏览器打开；支持手动编辑与重新抓取元数据。
- 调研结论引用：`research.md` 选择方案 A（A2 形态），抓取链采用「web manifest.json → og 标签 → title + favicon」，安全上采用 SSRF 防护与图标消毒。

## 范围

- 新增 remote 插件类型与 `url` 字段：`apps/desktop/desktop_app/protocol.py` 扩展 `PluginManifest`。
- 新增元数据抓取器：`apps/desktop/desktop_app/metadata.py`（抓取链、图标下载与消毒、SSRF 防护）。
- 注册表与管理器支持 remote 插件：`registry.py` 生成 `entryUrl=url`、`PluginInfo` 增加 `url` 字段；`manager.py` 新增 `install_from_url` 与 `refresh_metadata`。
- 新增宿主接口：`POST /api/desktop/plugins/install-from-url`、`POST /api/desktop/plugins/{id}/refresh-metadata`。
- 前端：设置页新增「添加应用」入口（URL 输入 + 自动抓取 + 可编辑表单 + 重新抓取按钮）；`plugin-view.tsx` 支持 remote 分支（不注入 SDK、sandbox 收紧、系统浏览器降级按钮）。
- 测试与文档：新增 `tests/test_metadata.py`、`tests/test_remote_plugin.py`；本 request 的 Harness 六件套文档。

## 非目标

- 不做本地化快照（方案 B）、离线缓存与自动更新（留二期）。
- 不做远程插件的宿主能力授权流程（纯壳固定零权限）。
- 不做插件分享与商店。
- 不改变现有 iframe / react 本地插件的协议与行为（保持向后兼容）。

## 风险

- 兼容性风险：manifest 新增字段为可选扩展，旧插件不受影响；`type` 校验扩集合，已存在的 `iframe` / `react` 行为不变。
- 安全风险：远程内容不可信，纯壳零权限 + 不注入 SDK 可隔离宿主能力；SSRF 与 SVG 消毒需配套测试覆盖。
- 联调风险：真实站点抓取依赖公网可达性，沙箱验证可能受限，需用户本机回归。
- 数据风险：remote 插件卸载仅删除用户目录下对应目录，不影响内置插件与本地插件。

## 停点判断

- 是否涉及架构边界变化：是（新增 remote 插件类型与独立渲染路径）
- 是否涉及数据模型变化：是（`PluginManifest` 新增 `type: "remote"` 与 `url` 字段）
- 是否涉及 API 契约变化：是（新增两个宿主接口）
- 是否涉及鉴权或权限行为变化：是（remote 插件强制零权限、不注入宿主 SDK，新增 SSRF 防护约束）
- 结论：进入实现前需人工确认。用户已在 2026-08-21 对话中确认：方案 A2、纯壳、手动编辑 + 重新抓取按钮、独立窗口默认系统浏览器。

## 验收标准

- 在设置页输入公网 URL 安装 remote 插件：自动抓取名称/描述/图标并落盘到 `~/.desktop-app/plugins/{id}/`，`manifest.json` 含 `type: "remote"` 与 `url`，registry 列表与应用页可见。
- 本地 URL（`http://localhost:<port>`、`http://127.0.0.1:<port>`、私有网段地址）同样可安装；链路本地（169.254）、组播、`0.0.0.0` 与保留地址仍被拒绝并返回明确错误。
- 用户可手动编辑 name/description/icon，保存后插件列表立即生效。
- 「重新抓取」按钮可重新抓取并更新元数据，不改变插件 id 与 url。
- 可嵌入站点（无 X-Frame-Options / frame-ancestors 拒绝）在应用页 iframe 内打开；不可嵌入站点安装时给出提示，打开时提供「在系统浏览器打开」按钮且可正常打开。
- remote 插件页面中 `window.desktop` 为 `undefined`，`manifest.permissions` 为空，`PluginInfo.permissions` 为空。
- 安装与抓取拒绝内网/回环/链路本地地址（含重定向跳入内网）；SVG 图标中的 `<script>` 与事件处理器被移除后保存。
- `poetry run pytest tests/ -v` 全部通过；`poetry run ruff check .` 无告警；`pnpm --dir apps/desktop/front build` 成功。
- Harness 文档齐全：`research.md`、`spec.md`、`plan.md`、`verify.md`、`acceptance.md`、`meta.json`。

## 变更记录

### 初始版本

- 时间：2026-08-21
- 变更原因：首次创建 request
- 变更内容：建立「从 URL 添加远程壳插件」初始设计：方案 A2、纯壳零权限、三级元数据抓取链、手动编辑 + 重新抓取、系统浏览器降级
- 影响章节：全部
- 是否触发人工确认：是（数据模型 / API 契约 / 权限行为变化；用户已口头确认，详见停点判断）

### 2026-08-21 第 1 次变更

- 变更原因：实现「安装后手动编辑」需要已安装 remote 插件元数据的更新落点
- 变更内容：`PATCH /api/desktop/plugins/{id}` 在原有 `enabled` 基础上向后兼容扩展 `name` / `description` / `iconUrl` 字段（原 `SetEnabledRequest` 扩展为 `PluginPatchRequest`，旧请求体不变）；`POST /api/desktop/plugins/install-from-url` 响应增加 `frameable` 嵌入性预检结果；remote 插件 id 由域名生成，同 URL 重复安装返回 409
- 影响章节：范围、API 契约
- 是否触发人工确认：否（均属已批准设计范围内的向后兼容扩展）

### 2026-08-21 第 2 次变更

- 变更原因：用户明确要求支持本地 URL（`localhost` / 127.0.0.1 / 局域网地址）作为远程插件
- 变更内容：SSRF 地址校验由「仅公网」放宽为「公网 + 回环 + 私有网段」；仍拒绝链路本地、组播、保留与未指定地址；`validate_public_url` 更名为 `validate_fetchable_url`；设置页提示文案同步更新
- 影响章节：范围、风险、停点判断、验收标准
- 是否触发人工确认：是（鉴权 / 权限边界变化；用户 2026-08-21 明确要求支持本地 URL）

### 2026-08-21 fix：remote 插件 iframe 空白

- 变更原因：用户反馈远程插件页面实际已加载但显示空白
- 变更内容：`.plugin-frame` 默认 `opacity: 0`、仅加 `.is-ready` 后显示，而 `is-ready` 原只在 SDK 注入的 `onLoad` 回调中添加；remote 纯壳分支跳过 SDK 注入导致 iframe 永远透明。修复：remote 分支 iframe 直接带 `is-ready` 类
- 影响章节：前端渲染路径
- 是否触发人工确认：否（纯前端显示修复）
- 关联计划更新：已同步更新 `verify.md`
