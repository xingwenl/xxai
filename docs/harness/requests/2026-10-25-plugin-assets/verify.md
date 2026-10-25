---
source: script
request: 2026-10-25-plugin-assets
ranAt: "2026-10-25 20:27:57 CST"
exitCode: 0
---

## 已执行的命令与结果

### 宿主后端单测（资产存储 + plugin-data 回归 + 服务端回归）

```bash
cd apps/desktop && .venv/bin/python -m pytest tests/test_plugin_assets.py tests/test_plugin_data.py tests/test_server.py -q
```

........................................................................ [ 96%]
...                                                                      [100%]
=============================== warnings summary ===============================
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
  /Users/lixingwen/xw/study/ai-base/apps/desktop/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
75 passed, 1 warning in 0.71s
结果：通过

### 后端风格检查（ruff check 改动文件）

```bash
cd apps/desktop && .venv/bin/python -m ruff check desktop_app/plugin_assets.py desktop_app/server.py desktop_app/paths.py desktop_app/protocol.py
```

All checks passed!
结果：通过

### 宿主前端类型检查（tsc --noEmit）

```bash
cd apps/desktop/front && pnpm exec tsc --noEmit
```

结果：通过

### 宿主前端构建（产物给端到端探针用）

```bash
cd apps/desktop/front && pnpm build
```


> desktop-front@0.2.5 build /Users/lixingwen/xw/study/ai-base/apps/desktop/front
> vite build

(!) Your Vite config uses features that are unsupported by `configLoader: 'native'`, which is planned to become the default in a future major version of Vite:
  - `__dirname` (vite.config.ts:13:27). Use `import.meta.dirname` instead
Set `VITE_CONFIG_NATIVE_IGNORE_WARNING=true` to suppress this warning.
vite v8.3.4 building client environment for production...
transforming...
✓ 2740 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                                           0.39 kB │ gzip:   0.26 kB
dist/assets/index-toGU22W8.css                           67.37 kB │ gzip:  13.16 kB
dist/assets/array-BifhSqXX.js                             0.10 kB │ gzip:   0.11 kB
dist/assets/pie-XZMESJXO-XmWb3PFa.js                      0.10 kB │ gzip:   0.12 kB
dist/assets/info-OHQRW6UA-0Zc74Hsz.js                     0.10 kB │ gzip:   0.12 kB
dist/assets/radar-ABXABTNO-9_kVZx3m.js                    0.10 kB │ gzip:   0.12 kB
dist/assets/packet-JDAUHWVQ-B_bHsA83.js                   0.11 kB │ gzip:   0.12 kB
dist/assets/cynefin-EF2NZ3EQ-Be_3nKFt.js                  0.11 kB │ gzip:   0.12 kB
dist/assets/treemap-SAJKECNS-DcxewDoG.js                  0.11 kB │ gzip:   0.12 kB
dist/assets/wardley-7MLQ67FV-E7Q1LcXW.js                  0.11 kB │ gzip:   0.12 kB
dist/assets/gitGraph-VSP46ZUC-Ds4YuuQD.js                 0.11 kB │ gzip:   0.12 kB
dist/assets/railroad-I3PHUGI6-BXowzdlc.js                 0.11 kB │ gzip:   0.12 kB
dist/assets/treeView-D4JQ5SDB-CxPgNXPT.js                 0.11 kB │ gzip:   0.12 kB
dist/assets/channel-BLPzgqu2.js                           0.11 kB │ gzip:   0.12 kB
dist/assets/railroad-peg-JR7BVNR7-CLrkdAZ8.js             0.11 kB │ gzip:   0.12 kB
dist/assets/architecture-WOLXFQ4H-CrdSU701.js             0.11 kB │ gzip:   0.12 kB
dist/assets/railroad-abnf-LNEFI6M7-CTx1CyQu.js            0.11 kB │ gzip:   0.13 kB
dist/assets/railroad-ebnf-DWYD2UWJ-BJjOSOMX.js            0.11 kB │ gzip:   0.13 kB
dist/assets/eventmodeling-K75KTNOO-PYmZ6jvG.js            0.11 kB │ gzip:   0.13 kB
dist/assets/init-C-OQMol4.js                              0.14 kB │ gzip:   0.12 kB
dist/assets/chunk-Y2CYZVJY-DsF7k-Jl.js                    0.15 kB │ gzip:   0.14 kB
dist/assets/chunk-2Q5K7J3B-C1jixKkw.js                    0.19 kB │ gzip:   0.16 kB
dist/assets/chunk-JWPE2WC7-DVXcaiue.js                    0.22 kB │ gzip:   0.17 kB
dist/assets/chunk-XXDRQBXY-e-pEM7DS.js                    0.26 kB │ gzip:   0.22 kB
dist/assets/chunk-5VM5RSS4-ZNzvKenW.js                    0.36 kB │ gzip:   0.27 kB
dist/assets/flowDiagram-IUGLLWBU-CtNP5_UJ.js              0.56 kB │ gzip:   0.31 kB
dist/assets/chunk-VQ5W62QI-jEaCF11W.js                    0.57 kB │ gzip:   0.40 kB
dist/assets/chunk-J5ZVWO5B-oDCd-gWO.js                    0.63 kB │ gzip:   0.43 kB
dist/assets/infoDiagram-MVDRKAX5-BsQkZOmj.js              0.65 kB │ gzip:   0.41 kB
dist/assets/swimlanesDiagram-AYQRV4AK-DTRE100Z.js         0.83 kB │ gzip:   0.48 kB
dist/assets/sizeCapture-INFHLROL-3uHXrFqA.js              0.87 kB │ gzip:   0.51 kB
dist/assets/chunk-DUW6YSOI-Dgx8z5s3.js                    0.89 kB │ gzip:   0.46 kB
dist/assets/line-csM8TDTV.js                              0.94 kB │ gzip:   0.47 kB
dist/assets/ordinal-BDEzSJ7C.js                           1.17 kB │ gzip:   0.56 kB
dist/assets/chunk-ZAUX2LTX-CQyAoHpt.js                    1.41 kB │ gzip:   0.79 kB
dist/assets/railroadDiagram-Y72NRBL7-D_Fvtoj5.js          1.65 kB │ gzip:   0.77 kB
dist/assets/abnfDiagram-WEYOIA3C-VeYNjhr1.js              1.84 kB │ gzip:   0.89 kB
dist/assets/chunk-UHW7PFBP-LK6684JV.js                    1.95 kB │ gzip:   0.95 kB
dist/assets/chunk-55XCU76K-DUwAeLnx.js                    1.97 kB │ gzip:   0.88 kB
dist/assets/pegDiagram-ECIUJNBX-CgKHtPhf.js               2.01 kB │ gzip:   0.94 kB
dist/assets/ebnfDiagram-V4P3TTPT-Cx80jic2.js              2.05 kB │ gzip:   0.88 kB
dist/assets/dist-DFM8nvVw.js                              2.16 kB │ gzip:   0.96 kB
dist/assets/path-fybaL0A-.js                              2.27 kB │ gzip:   0.98 kB
dist/assets/arc-CAPUzxi-.js                               3.47 kB │ gzip:   1.46 kB
dist/assets/diagram-I5XIIV2D-DabQxjxM.js                  4.34 kB │ gzip:   1.89 kB
dist/assets/defaultLocale-BFoDCU3G.js                     4.63 kB │ gzip:   2.12 kB
dist/assets/chunk-4EMNKR2T-COFgr90i.js                    5.43 kB │ gzip:   2.50 kB
dist/assets/linear-OajyUmeX.js                            5.51 kB │ gzip:   2.25 kB
dist/assets/chunk-YZO67HFG-4zzRfygN.js                    5.83 kB │ gzip:   2.68 kB
dist/assets/diagram-RJA3I4VV-DKZ4BBVK.js                  6.07 kB │ gzip:   2.56 kB
dist/assets/pieDiagram-GNMPY74T-Bl9Qd2Hp.js               6.22 kB │ gzip:   2.59 kB
dist/assets/diagram-ODIL2UCW-C7xJnPBH.js                  8.12 kB │ gzip:   3.64 kB
dist/assets/cynefinDiagram-WF24UDRP-CyDGYEwh.js           9.94 kB │ gzip:   3.50 kB
dist/assets/chunk-ZCHMQSOR-CaURz0VM.js                   10.38 kB │ gzip:   4.32 kB
dist/assets/diagram-PFBEJUXE-BBavF9Tl.js                 10.92 kB │ gzip:   4.26 kB
dist/assets/chunk-HNE4Q36P-D9WLFnHD.js                   14.84 kB │ gzip:   4.19 kB
dist/assets/chunk-2E7WHVMD-ZkY33A0G.js                   15.64 kB │ gzip:   4.35 kB
dist/assets/diagram-CBK3MWTC-CAjVORhr.js                 15.75 kB │ gzip:   5.52 kB
dist/assets/mermaid-parser.core-CGzm5aC8.js              16.44 kB │ gzip:   3.91 kB
dist/assets/ishikawaDiagram-HPEHV2GE-DsDTa9OH.js         17.30 kB │ gzip:   6.53 kB
dist/assets/kanban-definition-FNSA4HC5-97wDheRM.js       20.26 kB │ gzip:   7.15 kB
dist/assets/sankeyDiagram-SY24JHO5-4N-ZwHz3.js           22.79 kB │ gzip:   8.25 kB
dist/assets/journeyDiagram-BOSHW7O7-CcO-1Mm9.js          23.15 kB │ gzip:   8.16 kB
dist/assets/mindmap-definition-6OY57UG3-l3GnR96Y.js      23.66 kB │ gzip:   8.06 kB
dist/assets/graphlib-DS17s2tU.js                         23.90 kB │ gzip:   8.31 kB
dist/assets/wardleyDiagram-IVAIDKWA-CTbhnaXw.js          25.20 kB │ gzip:   6.54 kB
dist/assets/rough.esm-Dy-Kn_BL.js                        27.10 kB │ gzip:   8.85 kB
dist/assets/gitGraphDiagram-PDYL7XHY-C_E26qjV.js         29.01 kB │ gzip:   8.55 kB
dist/assets/timeline-definition-JXYKGLGB-T7ejtSAm.js     30.45 kB │ gzip:  10.03 kB
dist/assets/erDiagram-KYQIGQAA-YXOZmWUe.js               30.65 kB │ gzip:  10.57 kB
dist/assets/chunk-7S6XSTFO-DEPH5O1s.js                   30.75 kB │ gzip:   8.51 kB
dist/assets/requirementDiagram-EQYSW5RA-BvDp3UVC.js      31.07 kB │ gzip:   9.82 kB
dist/assets/quadrantDiagram-D57K4MC3-B8gkfRY4.js         33.52 kB │ gzip:   9.74 kB
dist/assets/chunk-WQQL4CDK-Dyy6zKIM.js                   37.88 kB │ gzip:   8.20 kB
dist/assets/vennDiagram-Q3Y3IDCW-CKW8eUOD.js             41.18 kB │ gzip:  15.11 kB
dist/assets/stateDiagram-v2-A6IESKWZ-CnBGbgaC.js         41.55 kB │ gzip:  13.89 kB
dist/assets/blockDiagram-RJAE7QA3-CgUBXVup.js            42.44 kB │ gzip:  13.87 kB
dist/assets/xychartDiagram-4URNHDU4-2aznnU2B.js          44.52 kB │ gzip:  12.35 kB
dist/assets/src-CvjvifRU.js                              45.66 kB │ gzip:  15.99 kB
dist/assets/dagre-NK4GIZVX-5vDayjfJ.js                   47.83 kB │ gzip:  17.10 kB
dist/assets/classDiagram-v2-4MYWR3UA-CXJngAXb.js         49.70 kB │ gzip:  16.15 kB
dist/assets/chunk-AQDTSKZB-NPTqtF3R.js                   51.23 kB │ gzip:  16.63 kB
dist/assets/chunk-NQOKRVIF-Dxnq6ITV.js                   62.79 kB │ gzip:  20.36 kB
dist/assets/c4Diagram-XDPPPE54-BvL8VTsp.js               65.08 kB │ gzip:  18.61 kB
dist/assets/ganttDiagram-R7GPNTJY-Be0vvyti.js            70.01 kB │ gzip:  23.01 kB
dist/assets/diagram-TYUNFSNR-CvVgXwTx.js                 80.45 kB │ gzip:  25.15 kB
dist/assets/cose-bilkent-JH36ORCC-BPj5XkkX.js            81.22 kB │ gzip:  21.51 kB
dist/assets/mermaid.core-Bobiouhm.js                     84.68 kB │ gzip:  29.31 kB
dist/assets/swimlanes-B3ENRKFQ-DplIqhVX.js              106.44 kB │ gzip:  36.22 kB
dist/assets/chunk-HAGFOTED-8zpAHgVJ.js                  115.56 kB │ gzip:  29.27 kB
dist/assets/sequenceDiagram-BLEHNHQU-BZCkBlrC.js        117.67 kB │ gzip:  31.37 kB
dist/assets/architectureDiagram-ZHVYKT53-CdRxN4wN.js    148.87 kB │ gzip:  41.10 kB
dist/assets/usecaseDiagram-WPOLBNNX-B_aDaENa.js         187.90 kB │ gzip:  49.21 kB
dist/assets/chunk-DSNLSHJZ-Iy-Ws--R.js                  241.36 kB │ gzip:  40.31 kB
dist/assets/katex-B_JcIwqj.js                           258.80 kB │ gzip:  77.65 kB
dist/assets/cytoscape.esm-BegBNzOV.js                   434.75 kB │ gzip: 137.75 kB
dist/assets/chunk-NGNAAXSQ-C2Wy9Xmz.js                  629.04 kB │ gzip: 127.32 kB
dist/assets/index-CfqGubFf.js                           629.61 kB │ gzip: 206.86 kB
dist/assets/echarts-BZiwUTvX.js                       1,124.20 kB │ gzip: 373.58 kB
dist/assets/elk-QONTBCTQ-DjkxhK0O.js                  1,462.89 kB │ gzip: 455.85 kB

[plugin builtin:vite-reporter] 
(!) Some chunks are larger than 500 kB after minification. Consider:
- Using dynamic import() to code-split the application
- Use build.rolldownOptions.output.codeSplitting to improve chunking: https://rolldown.rs/reference/OutputOptions.codeSplitting
- Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.
✓ built in 757ms
结果：通过

### 念记构建（tsc --noEmit + vite build）

```bash
cd apps/note && pnpm build
```


> note-web@0.1.0 build /Users/lixingwen/xw/study/ai-base/apps/note
> tsc --noEmit && vite build

vite v8.3.4 building client environment for production...
transforming...
✓ 276 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                   0.39 kB │ gzip:   0.27 kB
dist/assets/index-2809qO6N.css   14.23 kB │ gzip:   4.00 kB
dist/assets/index-CgOFOmuM.js   413.29 kB │ gzip: 128.08 kB

✓ built in 97ms
结果：通过

### 产物与契约断言（manifest 权限、bundle 里的资产端点与提示语、tools.json 与两份 README）

```bash
  #!/usr/bin/env bash
  # 断言念记产物声明了 assets 权限、图片链路真的进了 bundle，且对外文档与契约同步。
  set -euo pipefail
  
  DIST="apps/note/dist"
  
  for artifact in index.html manifest.json icon.svg; do
    if [[ ! -f "$DIST/$artifact" ]]; then
      echo "缺少产物：${DIST}/${artifact}（构建是否成功？）" >&2
      exit 1
    fi
  done
  if ! ls "$DIST"/assets/*.js >/dev/null 2>&1; then
    echo "缺少产物：${DIST}/assets/*.js（vite 没产出 JS bundle？）" >&2
    exit 1
  fi
  
  # manifest 必须声明 assets，否则宿主不会注入 sdk.assets（粘贴图片会静默降级）。
  if ! python3 - "$DIST/manifest.json" <<'PY'
  import json
  import sys
  
  manifest = json.load(open(sys.argv[1], encoding="utf-8"))
  perms = manifest.get("permissions") or []
  missing = [p for p in ("storage", "tools", "assets") if p not in perms]
  if missing:
      print(f"manifest.permissions 缺少：{missing}（当前 {perms}）", file=sys.stderr)
      sys.exit(1)
  if manifest.get("id") != "note":
      print(f"manifest.id 应为 note，实际 {manifest.get('id')!r}", file=sys.stderr)
      sys.exit(1)
  PY
  then
    echo "manifest 校验失败" >&2
    exit 1
  fi
  
  # bundle 里必须出现：资产端点前缀（正文引用与 <img> 都靠它）、拖拽浮层文案、上传失败的中文提示。
  JS="$(ls "$DIST"/assets/*.js | head -n 1)"
  for needle in \
    "/api/desktop/plugin-assets/note/" \
    "松开即可插入图片" \
    "图片" \
    "image/webp"
  do
    if ! grep -qF "$needle" "$JS"; then
      echo "bundle 里找不到：${needle}（图片链路没被打进产物？）" >&2
      exit 1
    fi
  done
  
  # 契约与文档同步：tools.json 的读写方法说明里要讲清「图片是本地资产路径，模型读不到像素」。
  if ! grep -q "plugin-assets" apps/note/tools.json; then
    echo "apps/note/tools.json 的方法说明没提资产路径，AI 侧不知道图片长什么样" >&2
    exit 1
  fi
  if ! grep -q "plugin-assets" apps/note/README.md; then
    echo "apps/note/README.md 没有图片/资产说明" >&2
    exit 1
  fi
  if ! grep -q "assets" apps/desktop/README.md; then
    echo "apps/desktop/README.md 没有 assets 权限或 SDK 说明" >&2
    exit 1
  fi
  
  echo "manifest/assets/bundle/文档 断言全部命中"
  # 执行：bash /var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.GyVjZd0oIj/dist_probe.sh
```

manifest/assets/bundle/文档 断言全部命中
结果：通过

### 端到端（临时 HOME 起真实宿主，无头 Chrome 进 #/app/note，粘贴/拖拽图片 → 资产落盘 → 预览渲染）

```bash
  #!/usr/bin/env node
  // Harness v2 端到端探针：宿主「子应用资产」+ 念记粘贴/拖拽图片
  //
  // 做的事：用临时 HOME 起一个真实的宿主内嵌服务（create_app + uvicorn），把 apps/note/dist
  // 装进 ~/.desktop-app/plugins/note，然后用无头 Chrome 打开宿主深链 #/app/note —— 走的是真实
  // iframe 注入 SDK 的链路，不是伪造桥。进入念记后：
  //   1. 新建一条笔记 → 在 textarea 里派发带 image/webp 文件的 paste 事件
  //   2. 断言 sdk.assets.put 真的把图片 POST 到 /api/desktop/plugin-assets/note/，
  //      正文里出现站内路径，磁盘上多出 .webp 资产文件
  //   3. 切到预览态，断言 <img> 真的加载成功（naturalWidth > 0，说明 GET 端点与缓存头链路通）
  //   4. 再用拖拽插入第二张图，断言正文里有两个资产引用
  //   5. 粘贴纯文本不产生资产；最后核对 plugin-data 里的正文、资产目录内的文件数与清单一致
  //
  // 退出码：0 全通过 / 3 未执行（缺 Chrome、缺构建产物）/ 1 有断言失败。
  //
  // 环境变量：CHROME_BIN、NOTE_ASSETS_PORT（默认 5301）、NOTE_SHOT_DIR（默认 /tmp）。
  
  import { spawn } from 'node:child_process'
  import { cpSync, existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
  import { tmpdir } from 'node:os'
  import path from 'node:path'
  import { fileURLToPath } from 'node:url'
  
  const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')
  const CHROME =
    process.env.CHROME_BIN ?? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
  const PORT = Number(process.env.NOTE_ASSETS_PORT ?? 5301)
  const SHOT_DIR = process.env.NOTE_SHOT_DIR ?? '/tmp'
  
  const NOTE_DIST = path.join(ROOT, 'apps/note/dist')
  const HOST_DIST = path.join(ROOT, 'apps/desktop/front/dist')
  const PYTHON = path.join(ROOT, 'apps/desktop/.venv/bin/python')
  
  const failures = []
  let skips = 0
  const cleanups = []
  
  function pass(label) {
    console.log(`  ✓ ${label}`)
  }
  
  function fail(label, detail) {
    failures.push(label)
    console.log(`  ✗ ${label}${detail ? `（${detail}）` : ''}`)
  }
  
  function check(ok, label, detail) {
    if (ok) pass(label)
    else fail(label, detail)
    return ok
  }
  
  function skip(reason) {
    console.log(`未执行：${reason}`)
    skips += 1
  }
  
  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
  
  async function waitFor(fn, { timeout = 15000, interval = 150, label = '条件' } = {}) {
    const deadline = Date.now() + timeout
    let last
    while (Date.now() < deadline) {
      try {
        last = await fn()
        if (last) return last
      } catch (err) {
        last = err
      }
      await sleep(interval)
    }
    throw new Error(`等待超时：${label}（最后一次结果：${last instanceof Error ? last.message : JSON.stringify(last)}）`)
  }
  
  // ---------- CDP 最小客户端 ----------
  
  class Cdp {
    constructor(ws) {
      this.ws = ws
      this.nextId = 1
      this.pending = new Map()
      this.exceptions = []
      ws.addEventListener('message', (event) => {
        const msg = JSON.parse(event.data)
        if (msg.id && this.pending.has(msg.id)) {
          const { resolve, reject } = this.pending.get(msg.id)
          this.pending.delete(msg.id)
          if (msg.error) reject(new Error(`${msg.error.message} (${msg.error.code})`))
          else resolve(msg.result)
          return
        }
        if (msg.method === 'Runtime.exceptionThrown') {
          const detail = msg.params?.exceptionDetails
          this.exceptions.push(detail?.exception?.description ?? detail?.text ?? 'unknown exception')
        }
        if (msg.method === 'Runtime.consoleAPICalled' && msg.params?.type === 'error') {
          const text = (msg.params.args ?? [])
            .map((arg) => arg.value ?? arg.description ?? arg.type)
            .join(' ')
          this.exceptions.push(`console.error: ${text}`)
        }
      })
    }
  
    send(method, params = {}) {
      const id = this.nextId++
      this.ws.send(JSON.stringify({ id, method, params }))
      return new Promise((resolve, reject) => {
        this.pending.set(id, { resolve, reject })
        setTimeout(() => {
          if (this.pending.has(id)) {
            this.pending.delete(id)
            reject(new Error(`CDP 超时：${method}`))
          }
        }, 20000)
      })
    }
  
    /** 在页面主上下文里求值；async 表达式会自动 await。 */
    async eval(expression) {
      const result = await this.send('Runtime.evaluate', {
        expression: `(async () => { ${expression} })()`,
        awaitPromise: true,
        returnByValue: true,
        userGesture: true,
      })
      if (result.exceptionDetails) {
        throw new Error(
          result.exceptionDetails.exception?.description ?? result.exceptionDetails.text ?? '页面求值异常',
        )
      }
      return result.result?.value
    }
  
    close() {
      try {
        this.ws.close()
      } catch {
        /* ignore */
      }
    }
  }
  
  // ---------- 主流程 ----------
  
  async function main() {
    if (!existsSync(CHROME)) {
      skip(`没找到 Chrome（${CHROME}），端到端探针需要真实浏览器`)
      return
    }
    if (!existsSync(path.join(NOTE_DIST, 'manifest.json')) || !existsSync(path.join(NOTE_DIST, 'index.html'))) {
      skip(`apps/note/dist 不完整，先跑 pnpm --dir apps/note build`)
      return
    }
    if (!existsSync(path.join(HOST_DIST, 'index.html'))) {
      skip(`apps/desktop/front/dist 不完整，先跑宿主前端 build`)
      return
    }
    if (!existsSync(PYTHON)) {
      skip(`没找到宿主 Python 环境（${PYTHON}）`)
      return
    }
  
    // 临时 HOME：宿主按 Path.home() 解析插件目录/plugin-data/plugin-assets，改 HOME 即可隔离真实用户数据。
    const workDir = mkdtempSync(path.join(tmpdir(), 'note-assets-probe-'))
    cleanups.push(() => rmSync(workDir, { recursive: true, force: true }))
    const homeDir = path.join(workDir, 'home')
    const pluginDir = path.join(homeDir, '.desktop-app/plugins/note')
    mkdirSync(pluginDir, { recursive: true })
    cpSync(NOTE_DIST, pluginDir, { recursive: true })
    const assetDir = path.join(homeDir, '.desktop-app/plugin-assets/note')
    const dataFile = path.join(homeDir, '.desktop-app/plugin-data/note/note.json')
    const shotDir = path.join(SHOT_DIR)
    mkdirSync(shotDir, { recursive: true })
  
    // ---------- 起真实宿主服务 ----------
    // 内置插件目录故意留空：仓库里的 hello-world 也声明了 tools，会被宿主静默预挂载成隐藏 iframe，
    // 那样「摸到第几个 iframe」就变得不确定。这里只装念记，让端到端断言只面对一个插件。
    const builtinDir = path.join(workDir, 'builtin')
    mkdirSync(builtinDir, { recursive: true })
    const server = spawn(
      PYTHON,
      [
        '-c',
        [
          'import os',
          'import uvicorn',
          'from pathlib import Path',
          'from desktop_app.manager import PluginManager',
          'from desktop_app.server import create_app',
          "manager = PluginManager(builtin_dir=Path(os.environ['PROBE_BUILTIN_DIR']), user_dir=Path.home() / '.desktop-app' / 'plugins')",
          `uvicorn.run(create_app(manager), host='127.0.0.1', port=${PORT}, log_level='warning')`,
        ].join('\n'),
      ],
      {
        cwd: path.join(ROOT, 'apps/desktop'),
        env: {
          ...process.env,
          HOME: homeDir,
          DESKTOP_DEV_AGENT: '',
          PYTHONPATH: path.join(ROOT, 'apps/desktop'),
          PROBE_BUILTIN_DIR: builtinDir,
        },
        stdio: ['ignore', 'pipe', 'pipe'],
      },
    )
    cleanups.push(() => server.kill('SIGKILL'))
    let serverLog = ''
    server.stdout.on('data', (chunk) => (serverLog += chunk))
    server.stderr.on('data', (chunk) => (serverLog += chunk))
  
    const health = await waitFor(
      async () => {
        try {
          const resp = await fetch(`http://127.0.0.1:${PORT}/api/health`)
          return resp.ok ? await resp.json() : null
        } catch {
          return null
        }
      },
      { timeout: 30000, label: '宿主服务 /api/health' },
    ).catch((err) => {
      throw new Error(`${err.message}\n${serverLog.slice(-2000)}`)
    })
    console.log(`宿主服务已就绪：${health.service} ${health.version}（HOME=${homeDir}）`)
  
    const plugins = await (await fetch(`http://127.0.0.1:${PORT}/api/desktop/plugins`)).json()
    const note = (plugins.items ?? []).find((item) => item.id === 'note')
    check(Boolean(note), '宿主把念记识别为已启用的子应用', JSON.stringify(plugins.items?.map((i) => i.id)))
  
    // 同一个标签页里用无头 Chrome 打开，避免 pywebview 依赖。
    const profileDir = path.join(workDir, 'chrome-profile')
    mkdirSync(profileDir, { recursive: true })
    const chrome = spawn(
      CHROME,
      [
        '--headless=new',
        // 沙箱与 GPU 在受限环境下会导致 Chrome 进程崩溃、DevTools 连接被 1006 关闭；
        // 开关与仓库里既有的 markdown 探针保持一致。
        '--no-sandbox',
        '--disable-gpu',
        '--disable-dev-shm-usage',
        '--use-mock-keychain',
        '--remote-allow-origins=*',
        '--remote-debugging-port=0',
        `--user-data-dir=${profileDir}`,
        '--no-first-run',
        '--no-default-browser-check',
        '--hide-scrollbars',
        '--window-size=1280,900',
        '--allow-insecure-localhost',
        `http://127.0.0.1:${PORT}/#/app/note`,
      ],
      { stdio: ['ignore', 'pipe', 'pipe'] },
    )
    cleanups.push(() => chrome.kill('SIGKILL'))
  
    const devtoolsPort = await waitFor(
      () => {
        const portFile = path.join(profileDir, 'DevToolsActivePort')
        if (!existsSync(portFile)) return null
        const first = readFileSync(portFile, 'utf8').split('\n')[0]
        return Number(first) || null
      },
      { timeout: 30000, label: 'Chrome DevToolsActivePort' },
    )
  
    const targets = await waitFor(
      async () => {
        try {
          const list = await (await fetch(`http://127.0.0.1:${devtoolsPort}/json/list`)).json()
          const page = (Array.isArray(list) ? list : []).find(
            (t) => t.type === 'page' && t.webSocketDebuggerUrl && t.url.includes(String(PORT)),
          )
          return page ?? null
        } catch {
          return null
        }
      },
      { timeout: 30000, label: 'Chrome 页面 target' },
    )
  
    const ws = new WebSocket(targets.webSocketDebuggerUrl)
    cleanups.push(() => ws.close())
    await new Promise((resolve, reject) => {
      ws.addEventListener('open', resolve, { once: true })
      ws.addEventListener('error', reject, { once: true })
    })
    const cdp = new Cdp(ws)
    cleanups.push(() => cdp.close())
    await cdp.send('Runtime.enable')
    await cdp.send('Page.enable')
  
    const page = (expr) => cdp.eval(`return (${expr})`)
  
    // ---------- 进入念记 ----------
    await waitFor(
      () =>
        page(`(() => {
          const frame = document.querySelector('iframe.plugin-frame')
          if (!frame || !frame.contentDocument) return false
          return !!frame.contentDocument.querySelector('button')
        })()`),
      { timeout: 30000, label: '念记 iframe 加载 + SDK 注入' },
    )
    const sdkOk = await page(`(() => {
      const win = document.querySelector('iframe.plugin-frame').contentWindow
      return !!win.desktop
    })()`)
    check(sdkOk, '念记 iframe 里能看到注入的 window.desktop')
  
    const permission = await page(`(() => {
      const doc = document.querySelector('iframe.plugin-frame').contentDocument
      return { hasSwitch: !!doc.querySelector('.view-switch'), title: doc.title }
    })()`)
    check(permission.title === '念记', 'iframe 里加载的是念记页面', permission.title)
  
    // 新建一条笔记：新建后念记会切到编辑态，正文 textarea 出现。
    const created = await page(`(() => {
      const doc = document.querySelector('iframe.plugin-frame').contentDocument
      const button = [...doc.querySelectorAll('button')].find((b) => (b.textContent || '').includes('新建笔记'))
      if (!button) return false
      button.click()
      return true
    })()`)
    check(created, '点「新建笔记」创建空白笔记')
  
    await waitFor(
      () =>
        page(`(() => {
          const doc = document.querySelector('iframe.plugin-frame').contentDocument
          return !!doc.querySelector('textarea.content-input')
        })()`),
      { timeout: 15000, label: '编辑态正文 textarea' },
    )
  
    // ---------- 粘贴图片（真实 ClipboardEvent + DataTransfer） ----------
    // 页面里现画一张 WebP：避免仓库里塞二进制测试图，也顺带验证浏览器端 toBlob('image/webp') 路径。
    const pasteResult = await page(`(async () => {
      const doc = document.querySelector('iframe.plugin-frame').contentDocument
      const textarea = doc.querySelector('textarea.content-input')
      const canvas = doc.createElement('canvas')
      canvas.width = 160
      canvas.height = 100
      const ctx = canvas.getContext('2d')
      ctx.fillStyle = '#29463b'
      ctx.fillRect(0, 0, 160, 100)
      ctx.fillStyle = '#f2f2ed'
      ctx.fillRect(16, 16, 96, 48)
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/webp', 0.8))
      const file = new doc.defaultView.File([blob], 'paste.webp', { type: 'image/webp' })
      const data = new doc.defaultView.DataTransfer()
      data.items.add(file)
      textarea.focus()
      const event = new doc.defaultView.ClipboardEvent('paste', {
        clipboardData: data,
        bubbles: true,
        cancelable: true,
      })
      textarea.dispatchEvent(event)
      return { blobType: blob.type, blobBytes: blob.size, fileType: file.type }
    })()`)
    check(pasteResult.blobType === 'image/webp', '浏览器端 canvas 产出 WebP', JSON.stringify(pasteResult))
  
    const afterPaste = await waitFor(
      async () => {
        const value = await page(`(() => document.querySelector('iframe.plugin-frame').contentDocument.querySelector('textarea.content-input').value)()`)
        return value && value.includes('/api/desktop/plugin-assets/note/') ? value : null
      },
      { timeout: 30000, label: '粘贴图片后正文出现资产路径' },
    ).catch((err) => {
      fail('粘贴图片后正文出现资产路径', err.message)
      return ''
    })
    if (afterPaste) pass('粘贴图片后正文写入站内资产路径')
    check(
      !afterPaste.includes('data:image/'),
      '正文存的是站内路径而不是 base64 data URL',
      afterPaste.slice(0, 120),
    )
    check(/!\[[^\]]*\]\(\/api\/desktop\/plugin-assets\/note\/[a-z0-9]{16}\.(png|jpg|webp|gif)\)/.test(afterPaste), '正文是合法的 Markdown 图片引用', afterPaste.slice(0, 120))
  
    const firstAssetFiles = existsSync(assetDir) ? readdirSync(assetDir).filter((f) => !f.startsWith('.')) : []
    check(firstAssetFiles.length === 1, '宿主资产目录里落下 1 个文件', `实际 ${firstAssetFiles.length}：${firstAssetFiles.join(',')}`)
    const firstAssetName = firstAssetFiles[0] ?? ''
    check(/^[a-z0-9]{16}\.webp$/.test(firstAssetName), '资产 key 是内容哈希 + WebP 扩展名', firstAssetName)
    if (firstAssetName) {
      const bytes = readFileSync(path.join(assetDir, firstAssetName))
      const isWebp = bytes.subarray(0, 4).toString('latin1') === 'RIFF' && bytes.subarray(8, 12).toString('latin1') === 'WEBP'
      check(isWebp, '落盘文件确实以 RIFF/WEBP 魔数开头', bytes.subarray(0, 12).toString('hex'))
      check(bytes.length <= 2 * 1024 * 1024, '单文件没超过 2 MiB 上限', `${bytes.length} 字节`)
    }
  
    // ---------- 预览态渲染 ----------
    const switched = await page(`(() => {
      const doc = document.querySelector('iframe.plugin-frame').contentDocument
      const button = [...doc.querySelectorAll('.view-switch button')].find((b) => (b.textContent || '').includes('预览'))
      if (!button) return false
      button.click()
      return true
    })()`)
    check(switched, '切到预览态')
  
    const imgState = await waitFor(
      () =>
        page(`(() => {
          const doc = document.querySelector('iframe.plugin-frame').contentDocument
          const img = doc.querySelector('.markdown-view img.md-img')
          if (!img) return null
          return { src: img.getAttribute('src'), complete: img.complete, width: img.naturalWidth, height: img.naturalHeight }
        })()`),
      { timeout: 20000, label: '预览态 <img> 出现' },
    ).catch((err) => {
      fail('预览态出现 Markdown 图片', err.message)
      return null
    })
    // 元素出现不等于图已经解码完成：<img> 刚插入时 complete=false、naturalWidth=0，
    // 所以再等一次真正 load 完成的状态。
    const imgLoaded = imgState
      ? await waitFor(
          () =>
            page(`(() => {
              const doc = document.querySelector('iframe.plugin-frame').contentDocument
              const img = doc.querySelector('.markdown-view img.md-img')
              if (!img || !img.complete || img.naturalWidth <= 0) return null
              return { src: img.getAttribute('src'), complete: img.complete, width: img.naturalWidth, height: img.naturalHeight }
            })()`),
          { timeout: 20000, label: '预览态 <img> 解码完成' },
        ).catch((err) => {
          console.log(`  · ${err.message}`)
          return null
        })
      : null
    if (imgState) {
      const finalState = imgLoaded ?? imgState
      check(finalState.width > 0, '图片真的加载成功（naturalWidth > 0）', JSON.stringify(finalState))
      check(
        (finalState.src || '').startsWith('/api/desktop/plugin-assets/note/'),
        '图片 src 是站内资产路径',
        finalState.src,
      )
    }
  
    await cdp.send('Page.captureScreenshot', { format: 'png' }).then((shot) => {
      writeFileSync(path.join(shotDir, 'note-assets-paste-1280.png'), Buffer.from(shot.data, 'base64'))
      console.log(`  截图：${path.join(shotDir, 'note-assets-paste-1280.png')}`)
    })
  
    // 缓存头 + nosniff：再发一次真实 HTTP 请求核对（<img> 走的是同一端点）
    const assetResp = await fetch(`http://127.0.0.1:${PORT}${imgState ? imgState.src : ''}`)
    const cacheControl = assetResp.headers.get('cache-control') ?? ''
    check(assetResp.status === 200, 'GET 资产返回 200', String(assetResp.status))
    check(cacheControl.includes('immutable'), '资产响应带长缓存头', cacheControl)
    check((assetResp.headers.get('x-content-type-options') ?? '').toLowerCase() === 'nosniff', '资产响应带 nosniff', assetResp.headers.get('x-content-type-options'))
    check((assetResp.headers.get('content-type') ?? '').startsWith('image/webp'), '资产响应 Content-Type 为 image/webp', assetResp.headers.get('content-type'))
  
    // ---------- 拖拽第二张图 ----------
    const dropResult = await page(`(async () => {
      const doc = document.querySelector('iframe.plugin-frame').contentDocument
      const editButton = [...doc.querySelectorAll('.view-switch button')].find((b) => (b.textContent || '').includes('编辑'))
      if (!editButton) return { ok: false, reason: '没有编辑按钮' }
      editButton.click()
      await new Promise((resolve) => setTimeout(resolve, 200))
      const zone = doc.querySelector('.content-zone')
      const textarea = doc.querySelector('textarea.content-input')
      if (!zone || !textarea) return { ok: false, reason: '编辑态元素缺失' }
      const canvas = doc.createElement('canvas')
      canvas.width = 120
      canvas.height = 120
      const ctx = canvas.getContext('2d')
      ctx.fillStyle = '#c7d8c9'
      ctx.fillRect(0, 0, 120, 120)
      ctx.strokeStyle = '#29463b'
      ctx.lineWidth = 6
      ctx.strokeRect(6, 6, 108, 108)
      const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/webp', 0.8))
      const file = new doc.defaultView.File([blob], 'drop.webp', { type: 'image/webp' })
      const data = new doc.defaultView.DataTransfer()
      data.items.add(file)
      const over = new doc.defaultView.DragEvent('dragover', { dataTransfer: data, bubbles: true, cancelable: true })
      zone.dispatchEvent(over)
      const drop = new doc.defaultView.DragEvent('drop', { dataTransfer: data, bubbles: true, cancelable: true })
      zone.dispatchEvent(drop)
      return { ok: true }
    })()`)
    check(dropResult?.ok, '在正文区派发拖拽 drop 事件', JSON.stringify(dropResult))
  
    const afterDrop = await waitFor(
      async () => {
        const value = await page(`(() => document.querySelector('iframe.plugin-frame').contentDocument.querySelector('textarea.content-input').value)()`)
        const count = (value.match(/\/api\/desktop\/plugin-assets\/note\//g) ?? []).length
        return count >= 2 ? value : null
      },
      { timeout: 30000, label: '拖拽后正文出现第二张图' },
    ).catch((err) => {
      fail('拖拽插入第二张图片', err.message)
      return ''
    })
    if (afterDrop) pass('拖拽插入第二张图片')
  
    const assetFilesAfterDrop = existsSync(assetDir) ? readdirSync(assetDir).filter((f) => !f.startsWith('.')) : []
    check(assetFilesAfterDrop.length === 2, '两张不同图片落成两个资产文件', `实际 ${assetFilesAfterDrop.length}：${assetFilesAfterDrop.join(',')}`)
  
    // ---------- 纯文本粘贴不产生资产 ----------
    const textPaste = await page(`(() => {
      const doc = document.querySelector('iframe.plugin-frame').contentDocument
      const textarea = doc.querySelector('textarea.content-input')
      const before = textarea.value
      const data = new doc.defaultView.DataTransfer()
      data.setData('text/plain', '纯文本粘贴不该产生资产')
      textarea.dispatchEvent(new doc.defaultView.ClipboardEvent('paste', { clipboardData: data, bubbles: true, cancelable: true }))
      return { before, after: textarea.value }
    })()`)
    await sleep(600)
    const assetsAfterText = existsSync(assetDir) ? readdirSync(assetDir).filter((f) => !f.startsWith('.')).length : 0
    check(assetsAfterText === 2, '纯文本粘贴不新增资产文件', `${assetsAfterText} 个`)
  
    // ---------- plugin-data 落盘 ----------
    const dataState = await waitFor(
      () => {
        if (!existsSync(dataFile)) return null
        const raw = readFileSync(dataFile, 'utf8')
        return raw.includes('/api/desktop/plugin-assets/note/') ? raw : null
      },
      { timeout: 20000, label: 'plugin-data 写入正文' },
    ).catch((err) => {
      fail('正文落进宿主 plugin-data', err.message)
      return null
    })
    if (dataState) {
      const parsed = JSON.parse(dataState)
      const noteContent = (parsed.notes ?? []).map((n) => n.content).join('\n')
      const refs = new Set((noteContent.match(/[a-z0-9]{16}\.(png|jpg|webp|gif)/g) ?? []))
      check(refs.size === 2, 'plugin-data 里的正文引用了 2 个资产 key', [...refs].join(','))
      check(JSON.stringify([...refs].sort()) === JSON.stringify(assetFilesAfterDrop.map((f) => f.replace(/^.*\//, '')).sort()), '正文引用的 key 与磁盘文件一一对应')
      check(!dataState.includes('data:image/'), 'plugin-data 里没有 base64 图片')
    }
  
    // ---------- console 干净 ----------
    await sleep(500)
    const noisy = cdp.exceptions.filter((line) => !line.includes('favicon'))
    check(noisy.length === 0, '页面无未捕获异常与 console.error', noisy.slice(0, 3).join(' | '))
  
    const shot = await cdp.send('Page.captureScreenshot', { format: 'png' })
    writeFileSync(path.join(shotDir, 'note-assets-drop-1280.png'), Buffer.from(shot.data, 'base64'))
    console.log(`  截图：${path.join(shotDir, 'note-assets-drop-1280.png')}`)
  }
  
  let exitCode = 0
  try {
    await main()
  } catch (err) {
    failures.push(err instanceof Error ? err.message : String(err))
    console.log(`\n探针异常终止：${err instanceof Error ? err.stack : err}`)
  } finally {
    for (const cleanup of cleanups.reverse()) {
      try {
        cleanup()
      } catch {
        /* ignore */
      }
    }
  }
  
  if (failures.length > 0) {
    console.log(`\n失败 ${failures.length} 项：`)
    for (const item of failures) console.log(`  - ${item}`)
    exitCode = 1
  } else if (skips > 0) {
    console.log(`\n通过（另有 ${skips} 项未执行）`)
    exitCode = 3
  } else {
    console.log('\n全部通过')
  }
  process.exit(exitCode)
  # 执行：node tools/harness/verify/2026-10-25-plugin-assets.browser.mjs
```

宿主服务已就绪：WW 0.2.5（HOME=/var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/note-assets-probe-s5xsHW/home）
  ✓ 宿主把念记识别为已启用的子应用
  ✓ 念记 iframe 里能看到注入的 window.desktop
  ✓ iframe 里加载的是念记页面
  ✓ 点「新建笔记」创建空白笔记
  ✓ 浏览器端 canvas 产出 WebP
  ✓ 粘贴图片后正文写入站内资产路径
  ✓ 正文存的是站内路径而不是 base64 data URL
  ✓ 正文是合法的 Markdown 图片引用
  ✓ 宿主资产目录里落下 1 个文件
  ✓ 资产 key 是内容哈希 + WebP 扩展名
  ✓ 落盘文件确实以 RIFF/WEBP 魔数开头
  ✓ 单文件没超过 2 MiB 上限
  ✓ 切到预览态
  ✓ 图片真的加载成功（naturalWidth > 0）
  ✓ 图片 src 是站内资产路径
  截图：/tmp/note-assets-paste-1280.png
  ✓ GET 资产返回 200
  ✓ 资产响应带长缓存头
  ✓ 资产响应带 nosniff
  ✓ 资产响应 Content-Type 为 image/webp
  ✓ 在正文区派发拖拽 drop 事件
  ✓ 拖拽插入第二张图片
  ✓ 两张不同图片落成两个资产文件
  ✓ 纯文本粘贴不新增资产文件
  ✓ plugin-data 里的正文引用了 2 个资产 key
  ✓ 正文引用的 key 与磁盘文件一一对应
  ✓ plugin-data 里没有 base64 图片
  ✓ 页面无未捕获异常与 console.error
  截图：/tmp/note-assets-drop-1280.png

全部通过
结果：通过

## 未执行项与原因

- 真实桌面应用（PyInstaller 打包的 WW.app）里的同一条链路：探针跑的是 create_app + uvicorn 起的同一份服务，
  但 pywebview 外壳、系统剪贴板（从截图工具直接粘贴）与打包资源路径没有覆盖，需要在 0.2.5 主包里人工点一遍。
- 从系统剪贴板粘贴真实截图（含 macOS 截图 .png 与微信/飞书复制的图片）：探针用页内 canvas 造图，
  没有走系统剪贴板，需要人工验证。
- 配额触顶（单插件 64 MiB / 500 个文件）时的界面提示：后端有单测，但前端提示文案需人工造量验证。
- 动图 GIF 原样直传后的动画是否守恒：需要人工用动图验证。
- 真实模型调用（note_* 工具在全局助手里读写含图片的笔记）：需要后台 Embed Client + Agent + HostToolPolicy 绑定。

## 验收结论

全部通过。
