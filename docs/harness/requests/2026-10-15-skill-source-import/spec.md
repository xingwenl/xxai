---
id: 2026-10-15-skill-source-import
tier: B
risk: medium
approval:
  required: true
  granted: false
  why: ["API 契约变化：新增 /platforms/{platform_id}/skill-packages/source-skills 与 /import-source", "新增服务端出网行为：由 API 进程主动抓取 GitHub，需 host 白名单与体积/超时上限"]
---

## 目标与范围

一句话：给 ai-base 加「按 GitHub 源添加技能」的能力——管理员给出仓库源并选定技能，平台服务端拉取并导入为既有的 `SkillPackage`，体验对标 `npx skills add <source> --skill <name>`。

- 使用者：平台管理员，鉴权沿用既有 `_require_admin`（`apps/backend/app/modules/skill/router.py:39`）。
- 复用既有导入链路，不改落库模型：`parse_skill_package()`（`apps/backend/app/modules/skill/importers.py:56`）→ `store_skill_package_files()`（同文件 `:123`）→ `import_skill_package()`（`apps/backend/app/modules/skill/services.py:35`）。
- 支持的源格式（对标参照实现的 Source Formats）：`owner/repo`、`https://github.com/owner/repo`、`https://github.com/owner/repo/tree/<ref>/<subpath>`，另可显式传 `ref`。
- 三个入口共用一个内核：后端两个接口、前端技能页入口、`tools/skills-cli` 薄命令行包装。
- 对标 `--list`：先列后选；列表接口只读、不落库。

**不做**（非目标）：

- 不在服务端执行 `npx` / `git` / 任何第三方代码。
- 不支持 GitLab、Azure Repos、任意 git URL、SSH 与私有仓库（首期）。
- 不支持 `-a/--agent`、`-g/--global`、`--copy`、symlink——这些是「装到本机 agent 目录」的概念，平台侧没有对应物。
- 不做 `skills update` / `remove` 对标项，不做定时同步与版本追踪。
- 不新增数据库表/列/索引，不做 Alembic 迁移。
- 不做技能名模糊匹配：`skill` 未命中即 4xx 并回显可选清单。

## 来源与方案比较

- **参照实现**：`vercel-labs/skills`，npm 包 `skills@1.7.2`（bin `skills` / `add-skill`，`engines.node >= 22.20.0`），"The open agent skills ecosystem"，调研日期 2026-10-15。README 定义的源格式、`-s/--skill`（`'*'` 全装）、`-l/--list`、`-a/--agent`、`-g/--global`，以及限制：单次下载 10 MiB、解压 25 MiB、1000 文件。
- **实测参照仓库**：`travisjneuman/.claude`（默认分支 `master`，非 `main`）。技能布局为 `skills/<name>/SKILL.md`，共 181 个技能目录；SKILL.md 带 YAML frontmatter（`name`/`description`，另有 Claude 专有 `context`/`agent`）。注意该仓库**不含** `document-skills`，文档类是 `agent-documentation-writer` 与 `codebase-documenter`。
- **平台既有链路已可直接吃下这种结构**：`skills/<name>/SKILL.md` 归档后，`_classify_file` 判定为 `role=skill`，无 `.codex-plugin/plugin.json` 时为 `package_type=skill`，单候选时包名取 frontmatter 的 `name`。既有上限 `MAX_ZIP_BYTES=25MiB` / `MAX_ENTRY_COUNT=300` / `MAX_FILE_BYTES=5MiB` 对单个技能目录绰绰有余。
- **本机实测出网可达性**（2026-10-15）：`api.github.com` 200、`codeload.github.com` 301、`objects.githubusercontent.com` 可达；`raw.githubusercontent.com` 超时不可达。因此取文件**不能走 raw**。

方案比较：

1. **服务端复刻源解析 + 复用既有导入链路**（选定）。按需取文件、不整仓下载：预览用 `GET /repos/{o}/{r}/git/trees/{ref}?recursive=1` 一次列树；导入用 `GET /repos/{o}/{r}/contents/{skill_dir}` 列出该技能目录，再逐文件 `Accept: application/vnd.github.raw` 取内容，案内存 zip 交给 `parse_skill_package`。
2. **服务端 shell 执行 `npx skills add`**：否决（见下）。
3. **客户端 CLI 打包后走既有 zip 上传**：否决（见下）。

**为什么不用 codeload 整仓 tarball**（原方案，实测后改掉）：本机 2026-10-15 实测到 GitHub 的吞吐只有 ~30-40 KB/s——`git/trees?recursive=1`（236 KB）耗时 7.6 s；`codeload.github.com/.../tar.gz/refs/heads/master` 限时 25 s 只下到 941 KB。参照仓库整包 ~9 MB，按此速率需 ~250 s，同步 HTTP 请求无法承受。而技能目录通常只有 1-5 个文件（实测 `agent-cli-developer` 仅 1 个 5356 字节的 `SKILL.md`），逐文件取只需 1 次目录列表 + N 次文件，实测单文件 1.3 s ⇒ 一次导入 ~3-8 s，比 tarball 快 30 倍以上。**代价是请求数由 1 变为 N**，这正是 `GITHUB_TOKEN` 的价值：未认证 REST 限流 60 次/小时（一次导入约 2-6 次请求，即每小时约 10-30 个技能），认证后 5000 次/小时。故 `GITHUB_TOKEN` 做成**可选**配置：默认匿名可用，配置后解除限流；接口在限流余量不足时给出明确提示。**注意 token 只提升额度，不提升带宽。**

## 被否决的选项

- **服务端直接执行 `npx skills add`**：后端镜像是 `python:3.12-slim`（`apps/backend/Dockerfile:1`），无 Node 也无 npx，要加就得改后端基础镜像；更关键的是 `skills add` 的产物落在 `./<agent>/skills/`、`~/<agent>/skills/` 这类本机目录，与平台 `SkillPackage` + `storage_key` + DB 落库模型对不上；且在 API 进程里跑运行时从网络下载的第三方包，越过了仓库既有边界——上传代码只在受限 runner 里执行（`docs/harness/requests/2026-08-04-skill-script-runner/spec.md`）。
- **直接 `git clone`（或依赖 git 二进制）**：后端镜像无 git；clone 会拖全仓库历史与无关目录（参照仓库 700+ 条目），而按 ref 取目录树的思路只要目录树。
- **codeload 整仓 tarball 流式解压**：只需 1 次请求，但要下整仓（参照仓库 ~9 MB / 实测 ~250 s），且大仓库更不可控；改用 contents API 逐文件后只需数秒（见「来源与方案比较」）。
- **用 `git/blobs/{sha}` 逐文件取内容**：树里虽然有 blob sha，但返回的是 base64 包在 JSON 里，体积膨胀 ~33%，且对小文件要额外解包；`contents` 接口配 `Accept: application/vnd.github.raw` 实测直接返回原始字节（5.3 KB 文件 1.3 s）。blobs 只作为单文件 >1 MiB 时 `contents` 不返回内容的兜底。
- **只取技能目录下的 `SKILL.md`、丢弃 `scripts/` `references/` `assets/`**：会让带脚本的技能包失去可执行文件，与既有 `_classify_file` 的 role 分类能力冲突；必须整目录收录，脚本执行仍由 `allow_script_execution`（默认 False）单独把关。
- **支持任意 URL 抓取（对标 `npx skills add https://example.com/x.zip`）**：由服务端抓任意 URL 即 SSRF，可达云 metadata 与内网端点。首期把 host 硬白名单限定为 `api.github.com` / `codeload.github.com`。
- **前端浏览器直接抓 GitHub**：受 CORS 限制，且平台侧无法控制用户的网络与凭据，拿不到统一审计。
- **新增独立 `git` 拉取微服务**：为一个只读 HTTP 拉取新建服务，架构成本远大于收益；API 进程内已有成熟 `httpx.AsyncClient` 出网先例（如 `apps/backend/app/modules/tools/basic/http_get.py:219`）。

## 停点判断

- 是否涉及架构边界变化：否。解析器作为新文件放在既有 `app/modules/skill/` 内，不新建模块目录、不新增服务。
- 是否涉及数据模型变化：否。不加表/列/索引/迁移；来源信息记进既有 `SkillPackage.manifest`（如 `source_url` / `source_ref` / `source_path`）。
- 是否涉及 API 契约变化：**是**。新增 `POST /platforms/{platform_id}/skill-packages/source-skills` 与 `POST /platforms/{platform_id}/skill-packages/import-source`。
- 是否涉及鉴权或权限行为变化：否。沿用 `_require_admin`，非本平台管理员维持 404。
- 核心功能缺少关键资料：否。持有 `skills@1.7.2` 官方 README 与实测仓库结构。
- 结论：命中 API 契约变化 ⇒ `approval.required: true`，实现前需人工确认。

## 变更点

- `apps/backend/app/modules/skill/source_resolver.py`（新增文件）：源字符串 → `(owner, repo, ref, subpath)`；host 白名单校验；`git/trees?recursive=1` 列树并按 `SKILL.md` 定位技能目录；`contents` 逐文件取原始字节；组装内存 zip。安全：拒绝绝对路径/`..` 穿越/符号链接/超限，单文件 >1 MiB 走 blobs 兜底。
- `apps/backend/app/modules/skill/schemas.py`：新增 `SkillSourcePreviewRequest` / `SkillSourceSkillItem` / `SkillSourcePreviewData` / `SkillSourceImportRequest`，复用既有 `SkillPackageImportResult`。
- `apps/backend/app/modules/skill/router.py`：新增两个 POST 路由，均沿用 `_require_admin` 与 `success_response`。
- `apps/backend/app/modules/skill/services.py`：新增 `preview_source_skills()` 与 `import_from_source()`；后者组装 zip 后**直接调用既有 `import_skill_package()`**，不另写落库逻辑。同时给 `import_skill_package()` 加一个可选 `package_name` 参数：显式传入时以用户填写的名称为准（否则 SKILL.md 里的 `name` 会把页面填的名称覆盖掉），既有 zip 上传调用点不传该参数、行为不变。
- `apps/backend/app/core/config.py`：新增源导入开关、出网超时、单次文件数与体积上限、可选 `github_token`。token 只提升限流额度（60→5000 次/小时），不改变带宽。
- `apps/front/src/api/skills.ts` + `apps/front/src/features/skills/index.tsx`：在既有 zip 导入入口旁加「从 GitHub 添加」对话框，先列出技能再勾选导入；新增 `SkillSourcePreviewData` / `SkillSourceSkillItem` / `SkillSourceImportPayload` 类型与 `previewSkillSource()` / `importSkillPackageFromSource()`，导入响应复用既有 `SkillImportResult`（来源信息由后端写进 `manifest`，前端不改 `SkillPackage` 类型）。
- `apps/backend/tests/skill/test_skill_source_resolver.py` + `apps/backend/tests/skill/test_skill_source_routes.py`（新增）：解析、白名单拒绝零出网、符号链接与越级路径、zip 组装、路由注册与 404 边界。
- `tools/skills-cli/skills.py`（新增）：`skills add <source> --skill <name> [-r <ref>] --platform <id>` 与 `skills add <source> --list`，仅做参数解析与调用上面两个接口，不重复实现解析。
- `tools/harness/verify/2026-10-15-skill-source-import.sh`：逐条跑验收标准。

## 验收标准

1. `POST .../skill-packages/source-skills` 对 `travisjneuman/.claude` 返回 ≥1 条技能，每条含 `name`/`slug`/`path`，且不产生任何库表写入。
2. `POST .../skill-packages/import-source` 选定 `agent-cli-developer` 后，`skill_packages` 增 1 行、`skills` 增 1 行且 `instruction_template` 非空、`skill_package_files` 只含该技能目录下的文件。
3. 非白名单 host（如 `http://169.254.169.254/`、`https://evil.example/x.zip`）被 4xx 拒绝，且不发起出网请求（可用本地 HTTP 记录器断言零请求）。
4. 路径穿越、符号链接、超限归档（>25 MiB 或 >300 条目）均 4xx 拒绝，且临时目录被清理。
5. 非本平台管理员调用两个接口均返回 404，与既有 `_require_admin` 行为一致。
6. `python3 tools/harness/audit.py` 通过；`tools/harness/verify.sh 2026-10-15-skill-source-import` 退出码为 0 或 3（未执行项已显式列出）。
7. 前端技能页可完成「输入源 → 列出技能 → 勾选 → 导入」，导入后新包出现在技能包列表。
