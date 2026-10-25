---
id: 2026-10-25-plugin-assets
tier: A
risk: medium
approval:
  required: true
  granted: false
  why: ["新模块目录：desktop_app/plugin_assets.py 承担插件二进制资产存储", "API 契约变化：新增 /api/desktop/plugin-assets/* 端点与宿主 SDK assets 命名空间", "鉴权或权限行为变化：manifest.permissions 白名单新增 assets 能力"]
---

## 目标与范围

- 做成什么：宿主给子应用提供**插件资产**（plugin-assets）存储——二进制文件落 `~/.desktop-app/plugin-assets/<pluginId>/`，文件名由服务端按内容哈希生成；REST 提供上传/列表/读取/删除四个入口，宿主 SDK 暴露 `sdk.assets`；子应用在正文里用同源路径 `/api/desktop/plugin-assets/<id>/<key>` 引用图片，`<img>` 直接可渲染。
- 给谁用：声明 `assets` 权限的宿主子应用（本轮只有念记：「粘贴/拖拽图片 → 存为资产 → 正文插入 Markdown 图片」）；宿主壳与 SDK 侧同步提供能力与文档。
- 为什么现在做：念记正文只存纯文本 Markdown，粘贴图片被浏览器直接丢弃；而宿主现有的 plugin-data 是 256 KiB 的 JSON 键值，放不下截图（一张截屏 1~3 MB）。
- 不做：音视频/PDF/任意类型（白名单只有 png/jpeg/webp/gif）；图片进插件市场分发；多账户隔离；资产加密；跨设备同步；正文里渲染外链图片（沿用上一轮否决）；真机 GUI 人工验收（见 verify.md 未执行项）。

## 来源与方案比较

- **Joplin 3.x REST API 的资源（resource）模型**（https://joplinapp.org/help/api/references/rest_api/ ，2026-10-25 取用）：附件作为独立 resource 存文件、正文只引用 id。说明「二进制与文本分开存、正文只留引用」是成熟笔记应用的共同形态；本设计照此把图片放文件、把 `![](/api/desktop/plugin-assets/note/<key>)` 放正文。
- **OWASP File Upload Cheat Sheet**（https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html ，2026-10-25 取用）：采纳三条——类型白名单、校验文件魔数而非只信 Content-Type、存储文件名不可由客户端决定。
- **MDN `X-Content-Type-Options`**（https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/X-Content-Type-Options ，2026-10-25 取用）：`nosniff` 才能让声明的 Content-Type 生效，避免资产被浏览器猜成 HTML 执行。
- **方案 A（选中）**：二进制独立落盘 + 同源只读 GET + SDK `assets.put/list/delete`。不受 256 KiB JSON 上限约束、正文仍是标准 Markdown、重启后仍在，AI 工具读到的正文与用户看到的一致。
- **方案 B**：base64 内联进笔记 JSON（`data:image/webp;base64,…`）。零宿主动手，但体积按 4/3 膨胀，256 KiB 下三五张就满，且每次自动保存都要重写全部图片字节。
- **方案 C**：客户端 localStorage/IndexedDB 存 blob + `blob:` URL。不进宿主数据目录、换机与卸载即丢，`blob:` URL 也无法跨会话持久。
- 选 A 的理由：唯一同时满足「不碰 JSON 上限」「正文是标准 Markdown」「重启后还在」的方案；代价是宿主多一层文件存储与配额管理，用配额（单文件 2 MiB、单插件 64 MiB / 500 个）把它约束住。

## 被否决的选项

- **base64 内联笔记 JSON（方案 B）**：配额与整份重写成本都不可接受；否决。
- **localStorage/IndexedDB + blob URL（方案 C）**：数据不落宿主目录、跨会话失效；否决。
- **复用 `storage` 权限存二进制**：权限粒度变粗，凡声明 storage 的插件自动获得写文件能力；否决，新增 `assets`。
- **允许 svg 等矢量/可执行类型**：同源 SVG 可携带脚本，打开即等价宿主 XSS；否决，白名单只放位图且校验魔数。
- **客户端传文件名当 key**：重名、非法字符、路径穿越、删除误伤引用都要额外处理；否决，key 由服务端按内容 sha256 生成（顺带天然去重）。
- **正文存宿主绝对地址**（`http://127.0.0.1:8765/api/...`）：换端口/换机器全断并暴露本地地址；否决，存站内路径 `/api/desktop/plugin-assets/...`。
- **预览里渲染外链图片**：离线与隐私都不成立；否决（沿用 `2026-10-25-note-app` 口径）。
- **不做孤儿回收**：删完笔记图还在磁盘上默默占配额，用户看到「空间不足」无从下手；否决，删笔记/清废纸篓时扫正文引用回收。
- **模型侧把图片换成「[图片] 描述」**：改写工具返回正文会让 AI 与用户看到的正文分叉；否决，只在 tools.json 的 description 里说明「正文中的图片是本地资产路径，模型读不到像素」。

## 停点判断

- 分档 A：新增模块目录 `apps/desktop/desktop_app/plugin_assets.py`；同时命中「API 契约变化」（四个新端点 + SDK 命名空间）与「鉴权或权限行为变化」（manifest 权限白名单新增 `assets`）。
- `approval.required: true`，需用户确认后再写实现代码。
- 需要 ADR：文件存储与 JSON 存储的边界、配额策略、同源 GET 的鉴权取舍都属「后来者会问为什么」的决定，写进 `docs/adr/0017-plugin-assets.md`。
- 两轮拷问已在开发前完成（2026-10-25，5+6 个决策点），结论落在「被否决的选项」；术语「插件资产」写入 `CONTEXT.md`。

## 变更点

- `apps/desktop/desktop_app/plugin_assets.py`（新增）：`PluginAssetStore`（put/get/list/delete/usage），白名单 png/jpeg/webp/gif + 魔数校验，单文件 2 MiB、单插件 64 MiB 与 500 个上限，临时文件 + `os.replace` 原子写，读写同一把锁。
- `apps/desktop/desktop_app/paths.py`：新增 `plugin_assets_dir()`（`~/.desktop-app/plugin-assets`）。
- `apps/desktop/desktop_app/protocol.py`：`KNOWN_PERMISSIONS` 增加 `assets`。
- `apps/desktop/desktop_app/server.py`：新增四个端点——`GET/POST /api/desktop/plugin-assets/{plugin_id}`、`GET/DELETE /api/desktop/plugin-assets/{plugin_id}/{key}`；写操作校验「已启用 + 声明 assets」，读取只校验插件已知并带 `nosniff` 与长缓存头。
- `apps/desktop/tests/test_plugin_assets.py`（新增）：存储语义（去重、魔数拒绝、配额、key 校验、重启后仍在）与 REST 契约（权限、415、413、204、缓存头）。
- `apps/desktop/front/src/lib/api.ts`：新增资产的四个 REST 客户端函数。
- `apps/desktop/front/src/lib/desktop-sdk.ts`：`sdk.assets = { put, list, delete, usage }`，未声明权限时 `denied('assets')`。
- `apps/desktop/README.md`：权限表加 `assets`，SDK 章节补资产接口与配额说明。
- `apps/note/src/lib/image-asset.ts`（新增）：粘贴/拖拽文件的客户端压缩（长边 ≤1600、WebP q0.8，失败回退 JPEG）与上传封装。
- `apps/note/src/App.tsx`：编辑态 textarea 的 `onPaste` 与编辑区拖拽落图，成功后光标处插入 `![](/api/desktop/plugin-assets/note/<key>)`，失败给中文提示；删除笔记/清空废纸篓时按剩余正文引用回收孤儿资产。
- `apps/note/src/components/markdown-view.tsx`：只把本站资产路径渲染成 `<img>`（`loading="lazy"`、`alt` 兜底），其余图片仍降级为占位文字。
- `apps/note/public/manifest.json`：permissions 增加 `assets`；`apps/note/tools.json`：描述里说明图片是本地资产路径、模型读不到像素。
- `apps/note/src/styles.css`：正文图片样式、拖拽浮层、上传中提示。
- `apps/note/README.md`、`tools/harness/verify/2026-10-25-plugin-assets.sh`（新增，6~7 步，含无头 Chrome 端到端粘贴/拖拽探针）。

## 验收标准

1. `python3 -m pytest apps/desktop/tests/test_plugin_assets.py -q` 全通过，覆盖去重、415（非白名单类型/魔数不符）、413（超大与配额）、404、204、key 非法。
2. 桌面后端全量 pytest 无新增失败；`ruff check apps/desktop/desktop_app` 通过。
3. 宿 host 前端 `pnpm --dir apps/desktop/front build` 通过，`sdk.assets` 未声明权限时走 `denied('assets')`。
4. `pnpm --dir apps/note build` 通过，dist 里能 grep 到 `plugin-assets`、`onPaste` 逻辑与三个 SDK 调用。
5. 无头 Chrome 探针：在宿主同源下打开念记，合成 paste 与 drop 事件各一次 → 断言资产文件真的落到临时 HOME 的 `plugin-assets/note/`、正文出现 `![](/api/desktop/plugin-assets/note/…)`、预览态渲染出 `<img>` 且 `naturalWidth > 0`、外链图片仍为占位文字、760px 无横向溢出、无 console 报错。
6. 删除该笔记后，资产目录里对应文件被回收（`GET /api/desktop/plugin-assets/note` 的 usage 回落）。
7. `python3 tools/harness/audit.py` 对本 request 无报错，verify.md 由脚本产出且显式列出未执行项。
