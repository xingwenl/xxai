---
source: script
request: 2026-10-25-note-app
ranAt: "2026-10-25 15:01:52 CST"
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
apps/ai-sdk prepare: vite v5.4.21 building for production...

   ╭───────────────────────────────────────────────────────────────────╮
   │                                                                   │
   │                Update available! 9.15.9 → 12.15.0.                │
   │   Changelog: https://github.com/pnpm/pnpm/releases/tag/v12.15.0   │
   │            Run "corepack use pnpm@12.15.0" to update.             │
   │                                                                   │
   ╰───────────────────────────────────────────────────────────────────╯

apps/ai-sdk prepare: transforming...
apps/ai-sdk prepare: ✓ 113 modules transformed.
apps/ai-sdk prepare: rendering chunks...
apps/ai-sdk prepare: [vite:dts] Start generate declaration files...
apps/ai-sdk prepare: computing gzip size...
apps/ai-sdk prepare: dist/style.css          47.63 kB │ gzip:   8.49 kB
apps/ai-sdk prepare: dist/xxai-agent.es.js  476.87 kB │ gzip: 146.27 kB
apps/ai-sdk prepare: [vite:dts] Declaration files built in 3208ms.
apps/ai-sdk prepare: dist/style.css            47.63 kB │ gzip:   8.49 kB
apps/ai-sdk prepare: dist/xxai-agent.umd.cjs  323.55 kB │ gzip: 118.56 kB
apps/ai-sdk prepare: ✓ built in 4.57s
apps/ai-sdk prepare: Done
Done in 7.5s using pnpm v9.15.9
结果：通过

### 子应用构建（tsc --noEmit + vite build，等价于 pnpm --dir apps/note build）

```bash
cd apps/note && pnpm build
```


> note-web@0.1.0 build /Users/lixingwen/xw/study/ai-base/apps/note
> tsc --noEmit && vite build

vite v8.3.4 building client environment for production...
transforming...
✓ 275 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.39 kB │ gzip:   0.27 kB
dist/assets/index-8Z4lOWen.css   13.44 kB │ gzip:   3.79 kB
dist/assets/index-D5D3N4oS.js   407.09 kB │ gzip: 125.86 kB

✓ built in 525ms
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
  # 执行：bash /var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.EjyeiqwiWe/dist_probe.sh
```

产物文件齐全：index.html / manifest.json / icon.svg / assets/*.js / #root
manifest 字段： {"id":"note","name":"念记","version":"0.1.0","description":"笔记子应用：记录、阅读并按分类整理笔记，并向桌面助手提供 note_* 方法","icon":"icon.svg","entry":"index.html","type":"iframe","permissions":["storage","tools","notify"]}
  note_create_note → index-D5D3N4oS.js 
  note_list_notes → index-D5D3N4oS.js 
  note_get_note → index-D5D3N4oS.js 
  note_update_note → index-D5D3N4oS.js 
  note_set_category → index-D5D3N4oS.js 
  note_list_categories → index-D5D3N4oS.js 
  note_delete_note → index-D5D3N4oS.js 
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
  # 执行：python3 /var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.EjyeiqwiWe/contract_probe.py
```

tools.json：7 个 → note_create_note, note_delete_note, note_get_note, note_list_categories, note_list_notes, note_set_category, note_update_note
README 方法表：7 个 → note_create_note, note_delete_note, note_get_note, note_list_categories, note_list_notes, note_set_category, note_update_note
dist bundle：7 个 → note_create_note, note_delete_note, note_get_note, note_list_categories, note_list_notes, note_set_category, note_update_note
tools.json ↔ README 方法表：一致
tools.json ↔ dist bundle：一致
README 方法表 ↔ dist bundle：一致
  note_create_note → bundle: index-D5D3N4oS.js, index-D5D3N4oS.js, index-D5D3N4oS.js
  note_delete_note → bundle: index-D5D3N4oS.js, index-D5D3N4oS.js
  note_get_note → bundle: index-D5D3N4oS.js, index-D5D3N4oS.js, index-D5D3N4oS.js, index-D5D3N4oS.js
  note_list_categories → bundle: index-D5D3N4oS.js, index-D5D3N4oS.js
  note_list_notes → bundle: index-D5D3N4oS.js, index-D5D3N4oS.js, index-D5D3N4oS.js, index-D5D3N4oS.js
  note_set_category → bundle: index-D5D3N4oS.js, index-D5D3N4oS.js
  note_update_note → bundle: index-D5D3N4oS.js, index-D5D3N4oS.js
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
  # 执行：bash /var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.EjyeiqwiWe/install_probe.sh
```

--help：通过
安装脚本输出：{"installedTo":"/var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.EjyeiqwiWe/install-plugins/note","zip":null}
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
  # 执行：bash /var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.EjyeiqwiWe/pure_probe.sh
```

空快照： {"version":1,"categories":["思考","灵感","阅读","旅行","工作"]}
长度上限： {"TITLE_MAX_LENGTH":120,"CONTENT_MAX_LENGTH":20000,"TAG_MAX_COUNT":8}
结果：通过

### Markdown 预览渲染（无头 Chrome + CDP：react-markdown 产物、编辑/预览切换、废纸篓、760px）

```bash
  // Harness 探针：2026-10-25-note-app / Markdown 预览渲染
  //
  // 用真实 Chrome（CDP，无第三方依赖）打开 apps/note 的构建产物，验证：
  //   1) 预览态真的把 Markdown 渲染成了 DOM（heading / 有序无序列表 / 引用 / 代码块 /
  //      行内代码 / 表格 / 加粗 / 删除线 / 任务列表），正文里不再残留 `## `、`**` 源码记号；
  //   2) 不产生 <img>（图片降级为占位文本，离线也不发远程请求）、无 script/iframe 等活动内容，
  //      外链带 target=_blank + rel=noopener；
  //   3) 「编辑 / 预览」切换：按钮与 ⌘E 都能切换，偏好写入 localStorage，切回源码态仍是同一份 Markdown；
  //   4) 废纸篓只读预览同样渲染 Markdown；
  //   5) 760px 窄宽下无横向溢出。
  //
  // 退出码：0 通过 / 1 断言失败 / 3 未执行（本机没有 Chrome，或 preview 服务起不来）。
  // 依赖：只依赖本机 Chrome + node 内置 fetch/WebSocket（node >= 22），不装任何 npm 包。
  import { spawn } from 'node:child_process'
  import fs from 'node:fs'
  import path from 'node:path'
  import { fileURLToPath } from 'node:url'
  
  const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')
  const CHROME = process.env.CHROME_BIN ?? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
  const PORT = Number(process.env.NOTE_PREVIEW_PORT ?? 5298)
  const APP = `http://localhost:${PORT}/`
  const SHOT_DIR = process.env.NOTE_SHOT_DIR ?? '/tmp'
  
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
  
  if (!fs.existsSync(CHROME)) {
    console.log(`未执行：没找到 Chrome（${CHROME}），设置 CHROME_BIN 指向本机 Chrome 后可重跑。`)
    process.exit(3)
  }
  if (!fs.existsSync(path.join(ROOT, 'apps/note/dist/index.html'))) {
    console.log('未执行：apps/note/dist 不存在，先跑 `pnpm --dir apps/note build`。')
    process.exit(3)
  }
  
  const checks = []
  const check = (name, pass, detail) => {
    checks.push({ name, pass })
    console.log(`${pass ? '✓' : '✗'} ${name}${pass ? '' : ` ${JSON.stringify(detail)}`}`)
  }
  
  // preview 服务：直接托管 dist，和宿主里加载的是同一份产物
  const server = spawn('pnpm', ['--dir', 'apps/note', 'exec', 'vite', 'preview', '--port', String(PORT), '--strictPort'], {
    cwd: ROOT,
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  let serverLog = ''
  server.stdout.on('data', (chunk) => {
    serverLog += chunk
  })
  server.stderr.on('data', (chunk) => {
    serverLog += chunk
  })
  
  let chrome
  const cleanup = () => {
    try {
      chrome?.kill('SIGKILL')
    } catch {
      /* 已经退出 */
    }
    try {
      server.kill('SIGKILL')
    } catch {
      /* 已经退出 */
    }
  }
  process.on('exit', cleanup)
  
  let reachable = false
  for (let i = 0; i < 60; i += 1) {
    try {
      const res = await fetch(APP)
      if (res.ok) {
        reachable = true
        break
      }
    } catch {
      /* 还没起来 */
    }
    await sleep(250)
  }
  if (!reachable) {
    console.log('未执行：vite preview 没起来（端口被占用或构建产物缺失）。')
    console.log(serverLog.slice(-1200))
    process.exit(3)
  }
  
  const profile = path.join('/tmp', `note-md-chrome-${process.pid}`)
  fs.rmSync(profile, { recursive: true, force: true })
  chrome = spawn(
    CHROME,
    [
      '--headless=new',
      '--disable-gpu',
      '--no-sandbox',
      '--no-first-run',
      '--no-default-browser-check',
      '--use-mock-keychain',
      '--remote-allow-origins=*',
      `--user-data-dir=${profile}`,
      '--remote-debugging-port=0',
      '--window-size=1280,900',
      '--hide-scrollbars',
      'about:blank',
    ],
    { stdio: 'ignore' },
  )
  
  // --remote-debugging-port=0 会让 Chrome 把实际端口写进 DevToolsActivePort
  const portFile = path.join(profile, 'DevToolsActivePort')
  let debugPort = 0
  for (let i = 0; i < 80; i += 1) {
    if (fs.existsSync(portFile)) {
      debugPort = Number(fs.readFileSync(portFile, 'utf8').split('\n')[0])
      if (debugPort) break
    }
    await sleep(150)
  }
  if (!debugPort) {
    console.log('未执行：Chrome 调试端口没起来。')
    process.exit(3)
  }
  
  let targets
  for (let i = 0; i < 60; i += 1) {
    try {
      const res = await fetch(`http://127.0.0.1:${debugPort}/json/list`)
      if (res.ok) {
        targets = await res.json()
        break
      }
    } catch {
      /* 还没起来 */
    }
    await sleep(150)
  }
  const page = targets?.find((t) => t.type === 'page')
  if (!page) {
    console.log('未执行：找不到可调试的页面目标。')
    process.exit(3)
  }
  
  const ws = new WebSocket(page.webSocketDebuggerUrl)
  await new Promise((resolve, reject) => {
    ws.onopen = resolve
    ws.onerror = reject
  })
  let seq = 0
  const pending = new Map()
  const consoleErrors = []
  ws.onmessage = (event) => {
    const message = JSON.parse(event.data)
    if (message.id && pending.has(message.id)) {
      const item = pending.get(message.id)
      pending.delete(message.id)
      message.error ? item.reject(new Error(JSON.stringify(message.error))) : item.resolve(message.result)
    } else if (message.method === 'Runtime.consoleAPICalled' && message.params.type === 'error') {
      consoleErrors.push(message.params.args.map((a) => a.value ?? a.description).join(' '))
    } else if (message.method === 'Runtime.exceptionThrown') {
      consoleErrors.push(`exception: ${message.params.exceptionDetails.exception?.description ?? ''}`)
    }
  }
  const send = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const id = ++seq
      pending.set(id, { resolve, reject })
      ws.send(JSON.stringify({ id, method, params }))
      setTimeout(() => {
        if (pending.has(id)) {
          pending.delete(id)
          reject(new Error(`TIMEOUT ${method}`))
        }
      }, 20000)
    })
  const evaluate = async (expression) => {
    const result = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true })
    if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails).slice(0, 400))
    return result.result.value
  }
  const screenshot = async (file) => {
    const shot = await send('Page.captureScreenshot', { format: 'png' })
    fs.writeFileSync(file, Buffer.from(shot.data, 'base64'))
    console.log(`  截图：${file}`)
  }
  const clickText = (selector, text) =>
    evaluate(`(() => {
      const el = [...document.querySelectorAll(${JSON.stringify(selector)})].find((n) => n.textContent.trim() === ${JSON.stringify(text)})
      if (!el) return 'not-found'
      el.click()
      return 'ok'
    })()`)
  const pressMetaE = async () => {
    for (const type of ['rawKeyDown', 'keyUp']) {
      await send('Input.dispatchKeyEvent', {
        type,
        key: 'e',
        code: 'KeyE',
        windowsVirtualKeyCode: 69,
        nativeVirtualKeyCode: 14,
        modifiers: 4,
      })
    }
  }
  
  await send('Page.enable')
  await send('Runtime.enable')
  await send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false })
  
  // 一个把常用 Markdown 语法都用上的样例笔记
  const now = new Date().toISOString()
  const content = [
    '## 为什么要分抽屉',
    '',
    '把信息**先收进来**再谈整理，比一上来就分类更可持续。',
    '',
    '1. 临时收集：随手记，24 小时内处理',
    '2. 主题笔记：按问题聚合',
    '',
    '> 记笔记的目的不是保存，而是让下一次思考从这里开始。',
    '',
    '### 本周要做的',
    '',
    '- [x] 清空临时收集箱',
    '- [ ] 把「散步地图」补成常青笔记',
    '',
    '参考：[常青笔记法](https://notes.andymatuschak.org/) 与 ~~旧方案~~',
    '',
    '```ts',
    'const drawer = notes.filter((n) => !n.deleted_at)',
    '```',
    '',
    '| 抽屉 | 处理周期 |',
    '| --- | --- |',
    '| 临时收集 | 24 小时 |',
    '',
    '![东京散步路线图](/trip.png)',
  ].join('\n')
  
  const seed = {
    version: 1,
    categories: ['思考', '灵感', '阅读', '旅行', '工作'],
    updated_at: now,
    notes: [
      {
        id: 'md-1',
        title: '周末整理：知识体系的四个抽屉',
        category: '思考',
        tags: ['知识管理'],
        created_at: now,
        updated_at: now,
        deleted_at: null,
        content,
      },
      {
        id: 'md-2',
        title: '会被删掉的笔记',
        category: '灵感',
        tags: [],
        created_at: now,
        updated_at: now,
        deleted_at: null,
        content: '### 废纸篓里也要能看清**加粗**和列表\n\n- 第一项\n- 第二项',
      },
    ],
  }
  
  await send('Page.navigate', { url: APP })
  await sleep(1000)
  await evaluate(`localStorage.setItem('note:data', ${JSON.stringify(JSON.stringify(seed))}); 'ok'`)
  await evaluate(`localStorage.removeItem('note:editor-mode'); 'ok'`)
  await send('Page.reload')
  await sleep(1500)
  await evaluate(`document.querySelectorAll('.note-card')[0].click()`)
  await sleep(500)
  
  const initial = await evaluate(`(() => {
    const view = document.querySelector('.markdown-view')
    const scope = view ?? document
    return {
      viewExists: !!view,
      textareaVisible: !!document.querySelector('.content-input'),
      toolbarVisible: !!document.querySelector('.toolbar'),
      activeTab: document.querySelector('.view-switch button.is-active')?.textContent?.trim() ?? null,
      h2: scope.querySelectorAll('h2').length,
      h3: scope.querySelectorAll('h3').length,
      ol: scope.querySelectorAll('ol > li').length,
      ul: scope.querySelectorAll('ul > li').length,
      taskMarker: (() => {
        const li = [...scope.querySelectorAll('li')].find((n) => n.querySelector("input[type='checkbox']"))
        return li ? getComputedStyle(li).listStyleType : null
      })(),
      blockquote: scope.querySelectorAll('blockquote').length,
      preCode: scope.querySelectorAll('pre code').length,
      tableCells: scope.querySelectorAll('td, th').length,
      strong: scope.querySelectorAll('strong').length,
      del: scope.querySelectorAll('del').length,
      checkboxes: scope.querySelectorAll("input[type='checkbox']").length,
      links: [...scope.querySelectorAll('a')].map((a) => ({ target: a.getAttribute('target'), rel: a.getAttribute('rel') })),
      imgTags: scope.querySelectorAll('img').length,
      imagePlaceholders: scope.querySelectorAll('.md-image').length,
      activeContent: scope.querySelectorAll('script, iframe, object, embed').length,
      rawMarkers: scope.textContent.includes('**') || scope.textContent.includes('## '),
    }
  })()`)
  
  check('预览态渲染出 .markdown-view，且不显示 textarea', initial.viewExists && !initial.textareaVisible, initial)
  check('预览态隐藏 Markdown 工具栏', !initial.toolbarVisible)
  check('顶栏高亮在「预览」', initial.activeTab === '预览', initial.activeTab)
  check('## → h2、### → h3', initial.h2 >= 1 && initial.h3 >= 1, { h2: initial.h2, h3: initial.h3 })
  check('有序/无序列表均渲染为 li', initial.ol === 2 && initial.ul === 2, { ol: initial.ol, ul: initial.ul })
  check('引用 / 代码块 / 表格 / 加粗 / 删除线 / 任务列表齐全',
    initial.blockquote >= 1 && initial.preCode >= 1 && initial.tableCells >= 4 && initial.strong >= 1 && initial.del >= 1 && initial.checkboxes >= 2,
    initial)
  check('任务列表去掉圆点（不复现「圆点 + 复选框」）', initial.taskMarker === 'none', initial.taskMarker)
  check('正文不再残留 ** 与 ## 源码记号', initial.rawMarkers === false)
  check('外链 target=_blank 且 rel 含 noopener', initial.links.length >= 1 && initial.links.every((l) => l.target === '_blank' && String(l.rel).includes('noopener')), initial.links)
  check('不产生 img，图片降级为占位文本', initial.imgTags === 0 && initial.imagePlaceholders === 1, { img: initial.imgTags, ph: initial.imagePlaceholders })
  check('渲染结果里没有 script/iframe 等活动内容', initial.activeContent === 0)
  
  await screenshot(path.join(SHOT_DIR, 'note-markdown-1280.png'))
  
  check('点击「编辑」切回源码态', (await clickText('.view-switch button', '编辑')) === 'ok')
  await sleep(300)
  const editState = await evaluate(`(() => ({
    textarea: !!document.querySelector('.content-input'),
    toolbar: !!document.querySelector('.toolbar'),
    markdown: !!document.querySelector('.markdown-view'),
    stored: localStorage.getItem('note:editor-mode'),
    head: document.querySelector('.content-input')?.value?.slice(0, 8) ?? null,
  }))()`)
  check('编辑态出现 textarea 与工具栏、隐藏渲染视图', editState.textarea && editState.toolbar && !editState.markdown, editState)
  check('切换后偏好写入 localStorage', editState.stored === 'edit', editState.stored)
  check('切回源码态仍是同一份 Markdown', editState.head === '## 为什么要分', editState.head)
  
  await evaluate(`document.querySelector('.content-input').focus(); 'ok'`)
  await pressMetaE()
  await sleep(300)
  const afterShortcut = await evaluate(`(() => ({
    textarea: !!document.querySelector('.content-input'),
    markdown: !!document.querySelector('.markdown-view'),
    stored: localStorage.getItem('note:editor-mode'),
    h2: document.querySelectorAll('.markdown-view h2').length,
  }))()`)
  check('⌘E 切回预览态并重新渲染', !afterShortcut.textarea && afterShortcut.markdown && afterShortcut.h2 >= 1, afterShortcut)
  check('⌘E 也持久化偏好', afterShortcut.stored === 'preview', afterShortcut.stored)
  
  await send('Emulation.setDeviceMetricsOverride', { width: 760, height: 900, deviceScaleFactor: 1, mobile: false })
  await sleep(400)
  const narrow = await evaluate(`(() => ({
    overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    viewWidth: Math.round(document.querySelector('.markdown-view')?.getBoundingClientRect().width ?? 0),
    cols: getComputedStyle(document.querySelector('.app-shell')).gridTemplateColumns,
  }))()`)
  check('760px 下预览态无横向溢出', narrow.overflow <= 0, narrow)
  await screenshot(path.join(SHOT_DIR, 'note-markdown-760.png'))
  
  await send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false })
  await sleep(200)
  const trashFlow = await evaluate(`(async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
    document.querySelectorAll('.note-card')[1]?.click()
    await sleep(400)
    document.querySelector('.menu-wrap button')?.click()
    await sleep(250)
    const del = [...document.querySelectorAll('[role="menuitem"]')].find((n) => n.textContent.includes('废纸篓'))
    if (!del) return { deleted: false }
    del.click()
    await sleep(700)
    document.querySelector('button.nav-row[aria-label="废纸篓"]')?.click()
    await sleep(700)
    document.querySelector('.note-card')?.click()
    await sleep(500)
    const view = document.querySelector('.markdown-view.trash-preview')
    return {
      deleted: true,
      trashView: !!view,
      h3: view?.querySelectorAll('h3').length ?? 0,
      strong: view?.querySelectorAll('strong').length ?? 0,
      li: view?.querySelectorAll('li').length ?? 0,
      rawMarkers: (view?.textContent ?? '').includes('###'),
    }
  })()`)
  check('废纸篓只读预览同样渲染 Markdown', trashFlow.trashView && trashFlow.h3 >= 1 && trashFlow.strong >= 1 && trashFlow.li >= 2 && trashFlow.rawMarkers === false, trashFlow)
  if (trashFlow.trashView) await screenshot(path.join(SHOT_DIR, 'note-markdown-trash.png'))
  
  check('全程无 console 报错', consoleErrors.length === 0, consoleErrors.slice(0, 3))
  
  const failed = checks.filter((c) => !c.pass)
  console.log(`\n${checks.length - failed.length}/${checks.length} 项通过`)
  ws.close()
  cleanup()
  process.exit(failed.length ? 1 : 0)
  # 执行：node tools/harness/verify/2026-10-25-note-markdown.browser.mjs
```

✓ 预览态渲染出 .markdown-view，且不显示 textarea
✓ 预览态隐藏 Markdown 工具栏
✓ 顶栏高亮在「预览」
✓ ## → h2、### → h3
✓ 有序/无序列表均渲染为 li
✓ 引用 / 代码块 / 表格 / 加粗 / 删除线 / 任务列表齐全
✓ 任务列表去掉圆点（不复现「圆点 + 复选框」）
✓ 正文不再残留 ** 与 ## 源码记号
✓ 外链 target=_blank 且 rel 含 noopener
✓ 不产生 img，图片降级为占位文本
✓ 渲染结果里没有 script/iframe 等活动内容
  截图：/tmp/note-markdown-1280.png
✓ 点击「编辑」切回源码态
✓ 编辑态出现 textarea 与工具栏、隐藏渲染视图
✓ 切换后偏好写入 localStorage
✓ 切回源码态仍是同一份 Markdown
✓ ⌘E 切回预览态并重新渲染
✓ ⌘E 也持久化偏好
✓ 760px 下预览态无横向溢出
  截图：/tmp/note-markdown-760.png
✓ 废纸篓只读预览同样渲染 Markdown
  截图：/tmp/note-markdown-trash.png
✓ 全程无 console 报错

20/20 项通过
结果：通过

## 未执行项与原因

- 真实桌面宿主点击安装（需 GUI，本机无自动化）：安装脚本只被验证到「能把 dist 同步到目标插件目录、--json 输出正确、不清理其他插件」；在 pywebview 窗口里打开「念记」卡片、新建/编辑/搜索/删除到废纸篓、重启应用后数据仍在 `~/.desktop-app/plugin-data/note/note.json`，都需要 macOS 图形会话与人工目视，脚本不能替代。
- 全局助手真实模型调用（需后台 Embed Client/Agent 绑定与凭证）：7 个方法是否被真实模型选中、后台 HostToolPolicy 与 schema 指纹是否一致，取决于 AI Base 后台数据与本机凭证；脚本不伪造模型会话、也不写入后台策略（避免污染），只在第 3/4 步证明方法名确实进了产物与契约文件。
- 界面观感（需人工目视）：760px 下无横向溢出、预览态 DOM 结构、切换链路已由第 7 步无头 Chrome 断言并留下截图（`/tmp/note-markdown-1280.png`、`note-markdown-760.png`、`note-markdown-trash.png`）；但字体是否可用、留白与封面渐变的观感、真实点按手感仍需人在宿主窗口里看。
- 宿主内 iframe 常驻与「不打开念记也能用方法」的最终体感：依赖宿主 `tools` 权限预挂载机制，本次不在本脚本里拉起桌面宿主（该链路已由 `tools/harness/verify/2026-10-20-ledger-app.sh` 用同一宿主机制覆盖）。
- 宿主内 iframe 里的 Markdown 渲染：第 7 步在纯浏览器里验证了渲染链路，但 pywebview 窗口里 iframe 的字体回退、滚动与选区行为仍需在真实宿主里看。
- 平台：本机只有 macOS，未在 Windows / Linux 上执行。

## 验收结论

- 已由脚本证明：`apps/note` 能独立构建出合法 iframe 插件（`manifest` 的 id/name/version/type/entry/permissions 逐字段断言通过），`dist` 含 `index.html`/`manifest.json`/`icon.svg`/`assets/*.js`，7 个 `note_*` 方法名逐个在 bundle 中命中并打印了所在文件名；`apps/note/tools.json`、README 方法表与构建产物三方方法集合完全一致（不一致时会打印差异方法名）；安装脚本能把 `dist/` 同步到任意 `--target` 目录、`--json` 只输出 `{installedTo, zip}`、且不会清理 plugins 下的其他插件。
- 已由第 7 步证明：正文用 react-markdown 渲染成真实 DOM（h2/h3/有序无序列表/引用/代码块/表格/加粗/删除线/任务列表逐项命中，源码记号 `## `、`**` 不再出现在渲染结果里），不产生 `<img>` 与 script/iframe（图片降级为占位文本、外链带 noopener），编辑/预览按钮与 ⌘E 都能切换并记住偏好，废纸篓只读预览同样渲染，760px 下无横向溢出。
- 部分证明：数据模型的空快照默认值与长度上限由纯函数自检覆盖（node 类型擦除直跑，无新增依赖）；跨模式迁移、串行写队列等 store 行为不在本脚本内（依赖 `window.desktop`，见未执行项）。
- 尚未证明：真实宿主窗口里的界面交互与视觉、真实模型是否选中方法、窄宽布局。因此只要存在未执行项，本脚本退出码为 3，不能视为已通过人工联调。
- 剩余风险：`note_*` 方法名进 bundle 只能说明「页面会注册它们」，说明不了宿主侧后台策略与绑定是否就绪；真实模型对工具的选择受提示与模型版本影响，本脚本不覆盖模型绕开工具的分支。
