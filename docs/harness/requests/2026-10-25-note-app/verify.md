---
source: script
request: 2026-10-25-note-app
ranAt: "2026-10-25 11:01:18 CST"
exitCode: 3
---

## 已执行的命令与结果

### 安装依赖（pnpm --frozen-lockfile，确认 apps/note 已纳入 workspace 且 lockfile 一致）

```bash
pnpm install --frozen-lockfile
```

Scope: all 7 workspace projects
Lockfile is up to date, resolution step is skipped
Already up to date

apps/ai-sdk prepare$ npm run build
apps/ai-sdk prepare: > xxai-agent@0.2.0 build
apps/ai-sdk prepare: > vite build

   ╭───────────────────────────────────────────────────────────────────╮
   │                                                                   │
   │                Update available! 9.15.9 → 12.15.0.                │
   │   Changelog: https://github.com/pnpm/pnpm/releases/tag/v12.15.0   │
   │            Run "corepack use pnpm@12.15.0" to update.             │
   │                                                                   │
   ╰───────────────────────────────────────────────────────────────────╯

apps/ai-sdk prepare: vite v5.4.21 building for production...
apps/ai-sdk prepare: transforming...
apps/ai-sdk prepare: ✓ 113 modules transformed.
apps/ai-sdk prepare: rendering chunks...
apps/ai-sdk prepare: [vite:dts] Start generate declaration files...
apps/ai-sdk prepare: computing gzip size...
apps/ai-sdk prepare: dist/style.css          47.63 kB │ gzip:   8.49 kB
apps/ai-sdk prepare: dist/xxai-agent.es.js  476.87 kB │ gzip: 146.27 kB
apps/ai-sdk prepare: [vite:dts] Declaration files built in 3190ms.
apps/ai-sdk prepare: dist/style.css            47.63 kB │ gzip:   8.49 kB
apps/ai-sdk prepare: dist/xxai-agent.umd.cjs  323.55 kB │ gzip: 118.56 kB
apps/ai-sdk prepare: ✓ built in 4.54s
apps/ai-sdk prepare: Done
Done in 7.1s using pnpm v9.15.9
结果：通过

### 子应用构建（tsc --noEmit + vite build，等价于 pnpm --dir apps/note build）

```bash
cd apps/note && pnpm build
```


> note-web@0.1.0 build /Users/lixingwen/xw/study/ai-base/apps/note
> tsc --noEmit && vite build

vite v8.3.4 building client environment for production...
transforming...
✓ 22 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.39 kB │ gzip:  0.27 kB
dist/assets/index-Bnxllm3l.css   10.94 kB │ gzip:  3.18 kB
dist/assets/index-PsC4vPv3.js   249.28 kB │ gzip: 78.36 kB

✓ built in 295ms
结果：通过

### dist 产物是合法 iframe 插件，且 bundle 内含 7 个 note_* 方法名

```bash
  #!/usr/bin/env bash
  # 断言 apps/note/dist 是一份合法的 iframe 插件产物，且 7 个 note_* 方法名都进了 bundle。
  set -euo pipefail
  
  DIST="apps/note/dist"
  
  # 每一项都单独报错：构建挂了的时候，最需要知道的是「缺哪个文件」，而不是一个静默的 exit 1。
  for artifact in index.html manifest.json icon.svg; do
    if [[ ! -f "$DIST/$artifact" ]]; then
      echo "缺少产物：$DIST/${artifact}（构建是否成功？）" >&2
      exit 1
    fi
  done
  if ! ls "$DIST"/assets/*.js >/dev/null 2>&1; then
    echo "缺少产物：$DIST/assets/*.js（vite 没产出 JS bundle？）" >&2
    exit 1
  fi
  if ! grep -qF 'id="root"' "$DIST/index.html"; then
    echo "index.html 里没有 #root 挂载点" >&2
    exit 1
  fi
  echo "产物文件齐全：index.html / manifest.json / icon.svg / assets/*.js / #root"
  
  # manifest 字段是宿主识别插件与授权能力的唯一依据，逐项断言。
  node -e '
    const assert = require("node:assert");
    const m = require("./apps/note/dist/manifest.json");
    assert.strictEqual(m.id, "note", "manifest.id 必须是 note");
    assert.strictEqual(m.name, "念记");
    assert.strictEqual(m.version, "0.1.0");
    assert.strictEqual(m.type, "iframe", "只支持 iframe 形态");
    assert.strictEqual(m.entry, "index.html");
    for (const permission of ["storage", "tools"]) {
      assert.ok((m.permissions || []).includes(permission), "permissions 缺少 " + permission);
    }
    console.log("manifest 字段：", JSON.stringify(m));
  '
  
  # 逐个方法名断言并打印命中的文件名（别用「grep 到一个就算了」，漏一个方法助手就少一条能力）。
  count=0
  for name in ${NOTE_METHOD_LIST:?NOTE_METHOD_LIST 未设置}; do
    hits="$(grep -l "$name" "$DIST"/assets/*.js || true)"
    if [[ -z "$hits" ]]; then
      echo "bundle 里没有方法名：$name" >&2
      exit 1
    fi
    echo "  ${name} → $(printf '%s\n' "$hits" | sed 's#^.*/##' | tr '\n' ' ')"
    count=$((count + 1))
  done
  if [[ "$count" -ne 7 ]]; then
    echo "bundle 命中的方法数应为 7，实际 ${count}" >&2
    exit 1
  fi
  echo "bundle 方法名断言：通过（${count} 个）"
  # 执行：bash /var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.2asSthA5OT/dist_probe.sh
```

产物文件齐全：index.html / manifest.json / icon.svg / assets/*.js / #root
manifest 字段： {"id":"note","name":"念记","version":"0.1.0","description":"笔记子应用：记录、阅读并按分类整理笔记，并向桌面助手提供 note_* 方法","icon":"icon.svg","entry":"index.html","type":"iframe","permissions":["storage","tools","notify"]}
  note_create_note → index-PsC4vPv3.js 
  note_list_notes → index-PsC4vPv3.js 
  note_get_note → index-PsC4vPv3.js 
  note_update_note → index-PsC4vPv3.js 
  note_set_category → index-PsC4vPv3.js 
  note_list_categories → index-PsC4vPv3.js 
  note_delete_note → index-PsC4vPv3.js 
bundle 方法名断言：通过（7 个）
结果：通过

### 三方方法契约一致（tools.json ↔ README 方法表 ↔ dist bundle，含差异打印）

```bash
  #!/usr/bin/env python3
  """三方方法契约一致性：apps/note/tools.json ↔ apps/note/README.md 方法表 ↔ dist/assets/*.js。
  
  tools.json 是唯一契约源（页面从它取 schema，后台 HostToolPolicy 也由它生成）；
  README 的方法表是文档承诺；bundle 是宿主真正注册到助手手里的东西。
  三处集合必须完全相同，否则「助手认不认得 note_* 方法」就会变成玄学。
  """
  from __future__ import annotations
  
  import json
  import re
  import sys
  from pathlib import Path
  
  ROOT = Path.cwd()
  APP = ROOT / "apps/note"
  
  # README 只取「方法表」的行（| `note_xxx` | …）：正文里提到的 note_* 不参与比对。
  README_ROW = re.compile(r"^\|\s*`(note_[a-z_]+)`")
  # bundle 里的方法名形状是 note_<动词>_<名词>，这个正则不会把 `note:data`、`note-data` 算进来。
  BUNDLE_NAME = re.compile(r"\bnote_[a-z]+_[a-z]+\b")
  
  
  def readme_names() -> list[str]:
      text = (APP / "README.md").read_text(encoding="utf-8")
      return [m.group(1) for m in (README_ROW.match(line) for line in text.splitlines()) if m]
  
  
  def bundle_names() -> tuple[set[str], dict[str, list[str]]]:
      assets = sorted((APP / "dist/assets").glob("*.js"))
      if not assets:
          sys.exit("没有找到 apps/note/dist/assets/*.js，请先构建")
      names: set[str] = set()
      where: dict[str, list[str]] = {}
      for asset in assets:
          for name in BUNDLE_NAME.findall(asset.read_text(encoding="utf-8", errors="ignore")):
              names.add(name)
              where.setdefault(name, []).append(asset.name)
      return names, where
  
  
  def main() -> int:
      tools = [item["name"] for item in json.loads((APP / "tools.json").read_text(encoding="utf-8"))]
      readme = readme_names()
      bundle, where = bundle_names()
  
      print(f"tools.json：{len(tools)} 个 → {', '.join(sorted(tools))}")
      print(f"README 方法表：{len(readme)} 个 → {', '.join(sorted(readme))}")
      print(f"dist bundle：{len(bundle)} 个 → {', '.join(sorted(bundle))}")
  
      ok = True
      sources = [
          ("tools.json", set(tools)),
          ("README 方法表", set(readme)),
          ("dist bundle", bundle),
      ]
      for index, (left_label, left) in enumerate(sources):
          for right_label, right in sources[index + 1:]:
              only_left = sorted(left - right)
              only_right = sorted(right - left)
              if not only_left and not only_right:
                  print(f"{left_label} ↔ {right_label}：一致")
                  continue
              ok = False
              print(f"差异 {left_label} ↔ {right_label}：")
              for name in only_left:
                  print(f"  - 只在 {left_label}：{name}")
              for name in only_right:
                  print(f"  - 只在 {right_label}：{name}")
  
      if len(tools) != 7:
          ok = False
          print(f"契约方法数应恒为 7，实际 {len(tools)}")
  
      for name in sorted(tools):
          print(f"  {name} → bundle: {', '.join(where.get(name, ['未命中']))}")
  
      if not ok:
          print("三方契约一致性：不通过")
          return 1
      print("三方契约一致性：通过")
      return 0
  
  
  if __name__ == "__main__":
      raise SystemExit(main())
  # 执行：python3 /var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.2asSthA5OT/contract_probe.py
```

tools.json：7 个 → note_create_note, note_delete_note, note_get_note, note_list_categories, note_list_notes, note_set_category, note_update_note
README 方法表：7 个 → note_create_note, note_delete_note, note_get_note, note_list_categories, note_list_notes, note_set_category, note_update_note
dist bundle：7 个 → note_create_note, note_delete_note, note_get_note, note_list_categories, note_list_notes, note_set_category, note_update_note
tools.json ↔ README 方法表：一致
tools.json ↔ dist bundle：一致
README 方法表 ↔ dist bundle：一致
  note_create_note → bundle: index-PsC4vPv3.js, index-PsC4vPv3.js, index-PsC4vPv3.js
  note_delete_note → bundle: index-PsC4vPv3.js, index-PsC4vPv3.js
  note_get_note → bundle: index-PsC4vPv3.js, index-PsC4vPv3.js, index-PsC4vPv3.js, index-PsC4vPv3.js
  note_list_categories → bundle: index-PsC4vPv3.js, index-PsC4vPv3.js
  note_list_notes → bundle: index-PsC4vPv3.js, index-PsC4vPv3.js, index-PsC4vPv3.js, index-PsC4vPv3.js
  note_set_category → bundle: index-PsC4vPv3.js, index-PsC4vPv3.js
  note_update_note → bundle: index-PsC4vPv3.js, index-PsC4vPv3.js
三方契约一致性：通过
结果：通过

### 安装脚本探针（--target 临时目录 + --json + 不清理其他插件）

```bash
  #!/usr/bin/env bash
  # 安装脚本探针：--target 到临时目录 + --json 输出断言 + 「不清理其他插件目录」断言。
  set -euo pipefail
  
  target="${PROBE_PLUGIN_DIR:?缺少 PROBE_PLUGIN_DIR}"
  json_out="${PROBE_JSON:?缺少 PROBE_JSON}"
  plugins_dir="$(dirname "$target")"
  
  # --help 不依赖 dist，先验证它可独立运行（编辑器里改脚本后最容易漏的就是用法文本）。
  node apps/note/scripts/install-to-desktop.mjs --help | grep -q "用法："
  echo "--help：通过"
  
  # 哨兵：宿主 plugins 目录下已有的其他插件不能被本脚本清掉。
  mkdir -p "${plugins_dir}/other-plugin"
  echo "<html>keep me</html>" > "${plugins_dir}/other-plugin/index.html"
  
  node apps/note/scripts/install-to-desktop.mjs --target "$target" --json > "$json_out"
  echo "安装脚本输出：$(cat "$json_out")"
  
  test -f "${plugins_dir}/other-plugin/index.html"
  echo "隔壁插件目录未被清理：通过"
  
  test -f "$target/index.html"
  test -f "$target/manifest.json"
  test -f "$target/icon.svg"
  ls "$target"/assets/*.js >/dev/null
  grep -qF 'id="root"' "$target/index.html"
  
  node -e '
    const assert = require("node:assert");
    const fs = require("node:fs");
    const out = JSON.parse(fs.readFileSync(process.env.PROBE_JSON, "utf8"));
    assert.deepStrictEqual(Object.keys(out).sort(), ["installedTo", "zip"], "--json 只应输出 installedTo/zip");
    assert.strictEqual(out.installedTo, process.env.PROBE_PLUGIN_DIR, "installedTo 应是目标目录绝对路径");
    assert.strictEqual(out.zip, null, "未传 --zip 时 zip 应为 null");
    const manifest = JSON.parse(fs.readFileSync(process.env.PROBE_PLUGIN_DIR + "/manifest.json", "utf8"));
    assert.strictEqual(manifest.id, "note");
    assert.strictEqual(manifest.entry, "index.html");
    console.log("--json 输出与目标目录 manifest 断言：通过");
  '
  # 执行：bash /var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.2asSthA5OT/install_probe.sh
```

--help：通过
安装脚本输出：{"installedTo":"/var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.2asSthA5OT/install-plugins/note","zip":null}
隔壁插件目录未被清理：通过
--json 输出与目标目录 manifest 断言：通过
结果：通过

### 纯函数自检（node 类型擦除直跑 src/lib/types.ts：空快照与长度上限）

```bash
  #!/usr/bin/env bash
  # 纯函数自检：直接导入 apps/note/src/lib/types.ts（无外部依赖、无宿主 API），
  # 断言空快照默认值与长度上限。退出码 0 通过 / 3 未执行（环境或导入形态不支持）/ 1 断言失败。
  set -uo pipefail
  
  if ! command -v node >/dev/null 2>&1; then
    echo "未执行：本机没有 node，纯函数自检跳过。"
    exit 3
  fi
  
  cat > "$PROBE_DIR/strip_support.ts" <<'TS'
  const label: string = '类型擦除可用'
  console.log(label)
  TS
  if ! node --experimental-strip-types "$PROBE_DIR/strip_support.ts" >/dev/null 2>&1; then
    echo "未执行：当前 node（$(node -v)）不支持 --experimental-strip-types，且仓库不引入 tsx 等新依赖，纯函数自检跳过。"
    exit 3
  fi
  
  cat > "$PROBE_DIR/pure_probe.ts" <<'TS'
  import assert from 'node:assert'
  
  const entry: string = process.env.NOTE_TYPES_ENTRY ?? ''
  assert.ok(entry.length > 0, '缺少 NOTE_TYPES_ENTRY')
  
  const types: any = await import(entry)
  const data = types.emptyNoteData()
  
  assert.strictEqual(data.version, 1, 'version 必须固定为 1')
  assert.deepStrictEqual(data.categories, [...types.DEFAULT_CATEGORIES], '空快照应含全部内置分类')
  assert.deepStrictEqual(data.notes, [], '空快照不应有笔记')
  assert.ok(types.TITLE_MAX_LENGTH > 0, 'TITLE_MAX_LENGTH 应为正数')
  assert.ok(types.CONTENT_MAX_LENGTH > 0, 'CONTENT_MAX_LENGTH 应为正数')
  assert.ok(types.TAG_MAX_COUNT > 0, 'TAG_MAX_COUNT 应为正数')
  
  console.log('空快照：', JSON.stringify({ version: data.version, categories: data.categories }))
  console.log('长度上限：', JSON.stringify({
    TITLE_MAX_LENGTH: types.TITLE_MAX_LENGTH,
    CONTENT_MAX_LENGTH: types.CONTENT_MAX_LENGTH,
    TAG_MAX_COUNT: types.TAG_MAX_COUNT,
  }))
  TS
  
  output="$(NOTE_TYPES_ENTRY="${NOTE_TYPES_ENTRY:?缺少 NOTE_TYPES_ENTRY}" \
    node --experimental-strip-types "$PROBE_DIR/pure_probe.ts" 2>&1)"
  status=$?
  printf '%s\n' "$output"
  if [[ $status -eq 0 ]]; then
    exit 0
  fi
  # 模块解析 / 语法不支持属「跑不起来」，记未执行；断言失败才是真失败。
  if grep -Eq 'ERR_MODULE_NOT_FOUND|Cannot find module|Unknown file extension|ERR_UNSUPPORTED|Unsupported' <<<"$output"; then
    echo "未执行：apps/note/src/lib/types.ts 当前形态无法被 node 直接导入（见上方错误），纯函数自检跳过。"
    exit 3
  fi
  exit 1
  # 执行：bash /var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.2asSthA5OT/pure_probe.sh
```

空快照： {"version":1,"categories":["思考","灵感","阅读","旅行","工作"]}
长度上限： {"TITLE_MAX_LENGTH":120,"CONTENT_MAX_LENGTH":20000,"TAG_MAX_COUNT":8}
结果：通过

## 未执行项与原因

- 真实桌面宿主点击安装（需 GUI，本机无自动化）：安装脚本只被验证到「能把 dist 同步到目标插件目录、--json 输出正确、不清理其他插件」；在 pywebview 窗口里打开「念记」卡片、新建/编辑/搜索/删除到废纸篓、重启应用后数据仍在 `~/.desktop-app/plugin-data/note/note.json`，都需要 macOS 图形会话与人工目视，脚本不能替代。
- 全局助手真实模型调用（需后台 Embed Client/Agent 绑定与凭证）：7 个方法是否被真实模型选中、后台 HostToolPolicy 与 schema 指纹是否一致，取决于 AI Base 后台数据与本机凭证；脚本不伪造模型会话、也不写入后台策略（避免污染），只在第 3/4 步证明方法名确实进了产物与契约文件。
- 760px 窄宽视觉检查（需人工/浏览器截图）：侧栏收成图标列、三栏不横向溢出、无控制台报错、无远程请求，属于视觉与运行时断言，脚本无法替代截图与目视。
- 宿主内 iframe 常驻与「不打开念记也能用方法」的最终体感：依赖宿主 `tools` 权限预挂载机制，本次不在本脚本里拉起桌面宿主（该链路已由 `tools/harness/verify/2026-10-20-ledger-app.sh` 用同一宿主机制覆盖）。
- 平台：本机只有 macOS，未在 Windows / Linux 上执行。

## 验收结论

- 已由脚本证明：`apps/note` 能独立构建出合法 iframe 插件（`manifest` 的 id/name/version/type/entry/permissions 逐字段断言通过），`dist` 含 `index.html`/`manifest.json`/`icon.svg`/`assets/*.js`，7 个 `note_*` 方法名逐个在 bundle 中命中并打印了所在文件名；`apps/note/tools.json`、README 方法表与构建产物三方方法集合完全一致（不一致时会打印差异方法名）；安装脚本能把 `dist/` 同步到任意 `--target` 目录、`--json` 只输出 `{installedTo, zip}`、且不会清理 plugins 下的其他插件。
- 部分证明：数据模型的空快照默认值与长度上限由纯函数自检覆盖（node 类型擦除直跑，无新增依赖）；跨模式迁移、串行写队列等 store 行为不在本脚本内（依赖 `window.desktop`，见未执行项）。
- 尚未证明：真实宿主窗口里的界面交互与视觉、真实模型是否选中方法、窄宽布局。因此只要存在未执行项，本脚本退出码为 3，不能视为已通过人工联调。
- 剩余风险：`note_*` 方法名进 bundle 只能说明「页面会注册它们」，说明不了宿主侧后台策略与绑定是否就绪；真实模型对工具的选择受提示与模型版本影响，本脚本不覆盖模型绕开工具的分支。
