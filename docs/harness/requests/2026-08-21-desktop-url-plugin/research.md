# 业界调研记录

## 调研问题

- 本次要解决什么问题？
  - 在桌面宿主壳（`apps/desktop`）中支持「从 URL 添加远程壳插件」：用户输入一个公网网址，系统自动抓取站点元数据（名称、描述、图标），保存为本地插件目录（`manifest.json` + 图标），应用页点击后以 iframe 内嵌打开；站点拒绝嵌入时降级为系统浏览器打开。
- 调研结果将影响哪些范围、架构、接口或实现决策？
  - 影响 `PluginManifest` 数据模型（新增 `type: "remote"` 与 `url` 字段）、宿主 API 契约（新增安装与重新抓取接口）、前端渲染路径（remote 类型不注入宿主 SDK）、安全边界（SSRF 防护、图标消毒、远程内容零权限）。

## 功能复杂度

- 级别：普通业务功能
- 选择理由：新增独立功能闭环，跨后端数据模型、API 契约与前端渲染，但无存量数据迁移、不触碰现有本地插件行为，风险集中在安全边界。
- 最低调研要求：官方标准（Web App Manifest、Open Graph）、浏览器嵌入限制（X-Frame-Options / CSP frame-ancestors）、iframe 沙箱、SSRF 防护生产实践，以及一个成熟产品形态（PWA / 浏览器快捷方式）作为对照。

## 参考依据

### 来源 1

- 类型：官方标准
- 名称：W3C Web App Manifest（Web Application Manifest 规范）
- 链接：https://www.w3.org/TR/appmanifest/（编辑版 https://w3c.github.io/manifest/）
- 版本或发布日期：W3C Working Draft 2025-03-07（2026-07-22 编辑版仍在维护）
- 调研日期：2026-08-21
- 核心做法：站点通过 `<link rel="manifest">` 暴露 `manifest.json`，其中 `name` / `short_name` / `description` / `icons` / `start_url` 是安装型 Web 应用的标准元数据；规范明确建议安装 UI 展示图标、名称、起始 URL 与源，并允许用户在安装前查看和修改这些信息。
- 对本项目的启发：抓取链第一优先读取站点 manifest.json，直接获得名称、描述与多尺寸图标；安装 UI 应展示抓取结果并允许用户修改（与本项目「手动编辑」设计一致）。

### 来源 2

- 类型：官方协议
- 名称：Open Graph Protocol
- 链接：https://ogp.me/
- 版本或发布日期：协议持续维护（2010 年发布，ogp.me 为官方定义）
- 调研日期：2026-08-21
- 核心做法：页面 `<meta property="og:title|og:description|og:image">` 提供面向分享卡片的标题、描述与图片 URL，是链接预览类抓取的通用约定。
- 对本项目的启发：站点没有 manifest.json 时，降级解析 `og:*` 元标签获取名称、描述与图标候选。

### 来源 3

- 类型：官方文档
- 名称：MDN X-Frame-Options
- 链接：https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/X-Frame-Options
- 版本或发布日期：2026-07-07 更新
- 调研日期：2026-08-21
- 核心做法：`X-Frame-Options: DENY / SAMEORIGIN` 指示浏览器是否允许页面被 `<iframe>` 嵌入；命中即白屏，且跨域 iframe 无法可靠检测加载失败。
- 对本项目的启发：安装时通过后端预检响应头判断可嵌入性，并始终提供「在系统浏览器打开」的降级按钮，避免依赖不可靠的运行时检测。

### 来源 4

- 类型：官方文档
- 名称：MDN CSP frame-ancestors
- 链接：https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/frame-ancestors
- 版本或发布日期：2025-07-03 更新
- 调研日期：2026-08-21
- 核心做法：`Content-Security-Policy: frame-ancestors <source-list>` 是 X-Frame-Options 的现代替代，允许列出可嵌入的父级源；两者需同时检查。
- 对本项目的启发：预检逻辑必须同时解析 `X-Frame-Options` 与 `CSP frame-ancestors`，两者任一拒绝即判定不可嵌入。

### 来源 5

- 类型：官方文档
- 名称：MDN `<iframe>` sandbox 属性
- 链接：https://developer.mozilla.org/en-US/docs/Web/HTML/Element/iframe
- 版本或发布日期：MDN 持续维护
- 调研日期：2026-08-21
- 核心做法：`sandbox` 属性对嵌套内容施加额外限制；无 `allow-same-origin` 时内容被视为唯一源，登录态与第三方资源访问受限。
- 对本项目的启发：remote 插件若要正常登录与加载资源，需要 `allow-scripts allow-same-origin allow-forms`；因纯壳设计不注入宿主 SDK，该组合风险可控，同时不加 `allow-top-navigation`。

### 来源 6

- 类型：生产实践 / 安全权威
- 名称：OWASP Server-Side Request Forgery Prevention Cheat Sheet
- 链接：https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html
- 版本或发布日期：仓库长期维护（本条目最后更新 2018-12-20 附近，持续更新）
- 调研日期：2026-08-21
- 核心做法：对用户可控 URL 的服务端请求必须做输入校验，并限制可访问网络范围，防止探测内网；解析与请求间需防 DNS rebinding。
- 对本项目的启发：抓取与预检统一走受限 HTTP 客户端：仅允许 http/https、拒绝私网/回环/链路本地地址，重定向逐跳重新校验。

### 来源 7

- 类型：官方规范
- 名称：HTML 标准 `<link rel="icon">`（favicon）约定
- 链接：https://html.spec.whatwg.org/multipage/semantics.html#rel-icon
- 版本或发布日期：WHATWG Living Standard
- 调研日期：2026-08-21
- 核心做法：`<link rel="icon">` / `apple-touch-icon` 声明站点图标，`/favicon.ico` 为历史兜底位置。
- 对本项目的启发：抓取链最后一级从 `apple-touch-icon` → `icon` → `/favicon.ico` 选取图标；下载后做大小限制与 SVG 消毒。

## 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| 方案 A：远程壳（本地只存 manifest + 图标 + 元数据，`entry` 指向远程 URL，iframe 内嵌，A2 降级系统浏览器） | 实现最轻、与现有 registry/权限模型完全兼容、任何公网站点都能添加 | 离线不可用；部分站点拒绝嵌入（已用预检 + 系统浏览器降级兜底） | 高，本期实施 |
| 方案 B：本地化快照（抓取整站静态资源存本地） | 离线可用、完全可控 | 动态站点抓不全、快照易碎、体积与更新成本高 | 低，二期再评估 |
| 方案 C：混合（manifest.json 有则 PWA 式安装，无则退回远程壳） | 元数据质量最好 | 复杂度高于 A | 中，抓取链已吸收 C 的元数据部分，快照部分留二期 |

## 最终决策

- 选择方案：方案 A（A2 形态：iframe 内嵌 + 预检 + 系统浏览器降级），元数据抓取链采用「web manifest.json → og 标签 → title + favicon」三级降级。
- 选择原因：与现有「本地插件目录 + manifest + registry 扫描」模型完全兼容，用户目录新增 remote 插件即可被现有列表/启停/卸载流程复用；纯壳设计避免远程第三方代码获得宿主能力，安全边界清晰。
- 不选择其他方案的原因：方案 B 的实现成本与维护负担大，且与「纯壳」定位冲突；方案 C 的快照部分无本期需求，只复用其元数据抓取思想。
- 对后续 spec、plan 或人工确认的影响：涉及 manifest 数据模型与宿主 API 契约变化，按 Harness 规则进入实现前需人工确认；用户已在 2026-08-21 对话中确认「先 A（A2）」「纯壳」「手动编辑 + 重新抓取按钮」「独立窗口默认系统浏览器」。

### 2026-08-21 决策变更：支持本地 URL

- 变更原因：用户明确要求将本地地址（如 `http://localhost:3000`、本机局域网服务）也添加为远程插件。
- 变更内容：SSRF 校验由「仅公网」放宽为「允许公网 + 本机回环（localhost/127.0.0.1/::1）+ 私有网段（RFC1918、ULA）」，仍拒绝链路本地（169.254.0.0/16、fe80::/10）、组播、保留与未指定地址；重定向逐跳仍按同一规则校验。
- 权衡依据：安装动作只能由宿主设置页触发（remote 插件为纯壳、不注入 SDK、无宿主能力），第三方页面无法利用该接口做内网探测；放开回环与私有网段属于本机场景的合理取舍。OWASP SSRF 建议的「防火墙网络隔离」对桌面单机应用不适用，应用层校验保留为剩余防线。
- 影响：属鉴权 / 权限边界变化，已获用户 2026-08-21 对话确认。

## 剩余风险

- 资料时效性：X-Frame-Options / CSP 为长期稳定机制，规范仍在维护，无时效风险。
- 与本项目上下文的差异：OWASP SSRF 建议对目标网络做完整隔离（防火墙层），本项目桌面应用只做应用层 IP 校验，对 DNS rebinding 采用「解析后校验 + 逐跳重校验」缓解，强度略低于网络隔离。
- 本地 URL 放开后的残余风险：若用户手动添加内网管理后台等敏感地址，其内容会在纯壳 iframe 中展示（等同于浏览器访问），风险与浏览器一致；抓取仅在用户主动发起安装/刷新时发生，无第三方触达路径。
- 尚未验证的假设：真实站点抓取依赖公网可达性，沙箱内验证可能受限，需用户本机人工回归；部分站点 `robots.txt` 或风控可能拒绝抓取，属可接受的降级（允许用户手动填写元数据）。
