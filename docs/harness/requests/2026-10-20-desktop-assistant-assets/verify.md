---
source: script
request: 2026-10-20-desktop-assistant-assets
ranAt: "2026-10-21 00:04:43 CST"
exitCode: 3
---

## 已执行的命令与结果

```text
### ai-sdk 上传 MIME 单测（vitest：扩展名映射 / 类型兜底 / accept 只含 MIME）

```bash
cd apps/ai-sdk && ./node_modules/.bin/vitest run src/core/__tests__/upload-mime.test.ts --reporter=dot
```


 RUN  v2.1.9 /Users/lixingwen/xw/study/ai-base/apps/ai-sdk

 ✓ src/core/__tests__/upload-mime.test.ts (10 tests) 5ms

 Test Files  1 passed (1)
      Tests  10 passed (10)
   Start at  00:04:23
   Duration  408ms (transform 40ms, setup 0ms, collect 29ms, tests 5ms, environment 0ms, prepare 87ms)

结果：通过

### ai-sdk 新增 upload-mime.ts 严格类型检查（tsc --strict）

```bash
cd apps/ai-sdk && ./node_modules/.bin/tsc --noEmit --strict --skipLibCheck --target ES2020 --module ESNext --moduleResolution bundler --lib ES2020,DOM src/core/upload-mime.ts
```

结果：通过

### 重建 ai-sdk dist（宿主前端消费的是 dist 产物，不是源码）

```bash
cd apps/ai-sdk && pnpm build
```


> xxai-agent@0.2.0 build /Users/lixingwen/xw/study/ai-base/apps/ai-sdk
> vite build

vite v5.4.21 building for production...
transforming...
✓ 112 modules transformed.
rendering chunks...

[vite:dts] Start generate declaration files...
computing gzip size...
dist/style.css          45.07 kB │ gzip:   8.07 kB
dist/xxai-agent.es.js  461.30 kB │ gzip: 140.88 kB
[vite:dts] Declaration files built in 2909ms.

dist/style.css            45.07 kB │ gzip:   8.07 kB
dist/xxai-agent.umd.cjs  313.49 kB │ gzip: 115.92 kB
✓ built in 4.74s
结果：通过

### 宿主前端类型检查（tsc --noEmit）

```bash
cd apps/desktop/front && ./node_modules/.bin/tsc --noEmit
```

结果：通过

### 宿主前端生产构建（front/dist 由内嵌服务托管）

```bash
cd apps/desktop/front && pnpm build
```


> desktop-front@0.2.0 build /Users/lixingwen/xw/study/ai-base/apps/desktop/front
> vite build

(!) Your Vite config uses features that are unsupported by `configLoader: 'native'`, which is planned to become the default in a future major version of Vite:
  - `__dirname` (vite.config.ts:13:27). Use `import.meta.dirname` instead
Set `VITE_CONFIG_NATIVE_IGNORE_WARNING=true` to suppress this warning.
vite v8.3.4 building client environment for production...
transforming...
✓ 2735 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                                           0.39 kB │ gzip:   0.26 kB
dist/assets/index-BW68stpf.css                           63.99 kB │ gzip:  12.53 kB
dist/assets/array-BifhSqXX.js                             0.10 kB │ gzip:   0.11 kB
dist/assets/pie-XZMESJXO-tfuKYPd6.js                      0.10 kB │ gzip:   0.12 kB
dist/assets/info-OHQRW6UA-B3CJasw7.js                     0.10 kB │ gzip:   0.12 kB
dist/assets/radar-ABXABTNO-wBfycBAq.js                    0.10 kB │ gzip:   0.12 kB
dist/assets/packet-JDAUHWVQ-CSL0Qdkf.js                   0.11 kB │ gzip:   0.12 kB
dist/assets/cynefin-EF2NZ3EQ-CydbI0ar.js                  0.11 kB │ gzip:   0.12 kB
dist/assets/treemap-SAJKECNS-Xg9vF7F2.js                  0.11 kB │ gzip:   0.12 kB
dist/assets/wardley-7MLQ67FV-C6OlmDlY.js                  0.11 kB │ gzip:   0.12 kB
dist/assets/gitGraph-VSP46ZUC-DHQdnVze.js                 0.11 kB │ gzip:   0.12 kB
dist/assets/railroad-I3PHUGI6-1DPP1I5j.js                 0.11 kB │ gzip:   0.12 kB
dist/assets/treeView-D4JQ5SDB-DlG4epUO.js                 0.11 kB │ gzip:   0.12 kB
dist/assets/channel-DukW196G.js                           0.11 kB │ gzip:   0.12 kB
dist/assets/railroad-peg-JR7BVNR7-CKr0Ry_k.js             0.11 kB │ gzip:   0.13 kB
dist/assets/architecture-WOLXFQ4H-SE2FdlXX.js             0.11 kB │ gzip:   0.12 kB
dist/assets/railroad-abnf-LNEFI6M7-DqwFk875.js            0.11 kB │ gzip:   0.13 kB
dist/assets/railroad-ebnf-DWYD2UWJ-CAmjItci.js            0.11 kB │ gzip:   0.13 kB
dist/assets/eventmodeling-K75KTNOO-DNOgxs4b.js            0.11 kB │ gzip:   0.13 kB
dist/assets/init-C-OQMol4.js                              0.14 kB │ gzip:   0.12 kB
dist/assets/chunk-Y2CYZVJY-DsF7k-Jl.js                    0.15 kB │ gzip:   0.14 kB
dist/assets/chunk-2Q5K7J3B-C1jixKkw.js                    0.19 kB │ gzip:   0.16 kB
dist/assets/chunk-JWPE2WC7-DVXcaiue.js                    0.22 kB │ gzip:   0.17 kB
dist/assets/chunk-XXDRQBXY-lcNDbxyz.js                    0.26 kB │ gzip:   0.22 kB
dist/assets/chunk-5VM5RSS4-ZNzvKenW.js                    0.36 kB │ gzip:   0.27 kB
dist/assets/flowDiagram-IUGLLWBU-BmuWFQ4u.js              0.56 kB │ gzip:   0.31 kB
dist/assets/chunk-VQ5W62QI-CtEw8rLT.js                    0.57 kB │ gzip:   0.40 kB
dist/assets/chunk-J5ZVWO5B-oDCd-gWO.js                    0.63 kB │ gzip:   0.43 kB
dist/assets/infoDiagram-MVDRKAX5-BIbjwiX2.js              0.65 kB │ gzip:   0.41 kB
dist/assets/swimlanesDiagram-AYQRV4AK-CXcFT4_h.js         0.83 kB │ gzip:   0.48 kB
dist/assets/sizeCapture-INFHLROL-3uHXrFqA.js              0.87 kB │ gzip:   0.51 kB
dist/assets/chunk-DUW6YSOI-Dgx8z5s3.js                    0.89 kB │ gzip:   0.46 kB
dist/assets/line-BNypT3u7.js                              0.94 kB │ gzip:   0.47 kB
dist/assets/ordinal-BDEzSJ7C.js                           1.17 kB │ gzip:   0.56 kB
dist/assets/chunk-ZAUX2LTX-BFB8GANF.js                    1.41 kB │ gzip:   0.79 kB
dist/assets/railroadDiagram-Y72NRBL7-D4ahfe4h.js          1.65 kB │ gzip:   0.76 kB
dist/assets/abnfDiagram-WEYOIA3C-C7sS_RoW.js              1.84 kB │ gzip:   0.89 kB
dist/assets/chunk-UHW7PFBP-BbsTV78D.js                    1.95 kB │ gzip:   0.95 kB
dist/assets/chunk-55XCU76K-C5-CazqY.js                    1.97 kB │ gzip:   0.88 kB
dist/assets/pegDiagram-ECIUJNBX-B60-JCRP.js               2.01 kB │ gzip:   0.94 kB
dist/assets/ebnfDiagram-V4P3TTPT-unjjAXzG.js              2.05 kB │ gzip:   0.88 kB
dist/assets/dist-DLNfLehF.js                              2.16 kB │ gzip:   0.96 kB
dist/assets/path-fybaL0A-.js                              2.27 kB │ gzip:   0.98 kB
dist/assets/arc-CGN50Rhv.js                               3.47 kB │ gzip:   1.46 kB
dist/assets/diagram-I5XIIV2D-BqUFTEN_.js                  4.34 kB │ gzip:   1.89 kB
dist/assets/defaultLocale-BFoDCU3G.js                     4.63 kB │ gzip:   2.12 kB
dist/assets/chunk-4EMNKR2T-CVWaQfBJ.js                    5.43 kB │ gzip:   2.50 kB
dist/assets/linear-a_QguKQl.js                            5.51 kB │ gzip:   2.25 kB
dist/assets/chunk-YZO67HFG-vTlvRqfB.js                    5.83 kB │ gzip:   2.68 kB
dist/assets/diagram-RJA3I4VV-BOPsHG5D.js                  6.07 kB │ gzip:   2.56 kB
dist/assets/pieDiagram-GNMPY74T-BFw5-g8b.js               6.22 kB │ gzip:   2.59 kB
dist/assets/diagram-ODIL2UCW-lwrmzmOV.js                  8.12 kB │ gzip:   3.64 kB
dist/assets/cynefinDiagram-WF24UDRP-NHDIjXrJ.js           9.94 kB │ gzip:   3.51 kB
dist/assets/chunk-ZCHMQSOR-BnvBlW-9.js                   10.38 kB │ gzip:   4.32 kB
dist/assets/diagram-PFBEJUXE-By4vfICL.js                 10.92 kB │ gzip:   4.25 kB
dist/assets/chunk-HNE4Q36P-4L2CU_oi.js                   14.84 kB │ gzip:   4.19 kB
dist/assets/chunk-2E7WHVMD-jP-SU6o4.js                   15.64 kB │ gzip:   4.35 kB
dist/assets/diagram-CBK3MWTC-BYbNqwLs.js                 15.75 kB │ gzip:   5.52 kB
dist/assets/mermaid-parser.core-B79Zuybe.js              16.44 kB │ gzip:   3.92 kB
dist/assets/ishikawaDiagram-HPEHV2GE-DxmQFgs1.js         17.30 kB │ gzip:   6.53 kB
dist/assets/kanban-definition-FNSA4HC5-CLGJc7Fo.js       20.26 kB │ gzip:   7.15 kB
dist/assets/sankeyDiagram-SY24JHO5-C8hwWvtT.js           22.79 kB │ gzip:   8.25 kB
dist/assets/journeyDiagram-BOSHW7O7-BVtWfnh2.js          23.15 kB │ gzip:   8.16 kB
dist/assets/mindmap-definition-6OY57UG3-CiICvftU.js      23.66 kB │ gzip:   8.06 kB
dist/assets/graphlib-DS17s2tU.js                         23.90 kB │ gzip:   8.31 kB
dist/assets/wardleyDiagram-IVAIDKWA-D8uK96FG.js          25.20 kB │ gzip:   6.55 kB
dist/assets/rough.esm-Dy-Kn_BL.js                        27.10 kB │ gzip:   8.85 kB
dist/assets/gitGraphDiagram-PDYL7XHY-CGaCh8jQ.js         29.01 kB │ gzip:   8.55 kB
dist/assets/timeline-definition-JXYKGLGB-KHj-po31.js     30.45 kB │ gzip:  10.03 kB
dist/assets/erDiagram-KYQIGQAA-Dr9kTVFh.js               30.65 kB │ gzip:  10.57 kB
dist/assets/chunk-7S6XSTFO-DYqfgyJ2.js                   30.75 kB │ gzip:   8.51 kB
dist/assets/requirementDiagram-EQYSW5RA-XdPJBvkW.js      31.07 kB │ gzip:   9.82 kB
dist/assets/quadrantDiagram-D57K4MC3-7zhOA5bQ.js         33.52 kB │ gzip:   9.74 kB
dist/assets/chunk-WQQL4CDK-CRkwTpRh.js                   37.88 kB │ gzip:   8.20 kB
dist/assets/vennDiagram-Q3Y3IDCW-BkS6GN89.js             41.18 kB │ gzip:  15.11 kB
dist/assets/stateDiagram-v2-A6IESKWZ-B453G6M4.js         41.55 kB │ gzip:  13.89 kB
dist/assets/blockDiagram-RJAE7QA3-B9--6-KM.js            42.44 kB │ gzip:  13.87 kB
dist/assets/xychartDiagram-4URNHDU4-CnO5DsN8.js          44.52 kB │ gzip:  12.35 kB
dist/assets/src-BK9CT0Ue.js                              45.66 kB │ gzip:  15.99 kB
dist/assets/dagre-NK4GIZVX-CPriCTmI.js                   47.83 kB │ gzip:  17.11 kB
dist/assets/classDiagram-v2-4MYWR3UA-CnyWcDHe.js         49.70 kB │ gzip:  16.15 kB
dist/assets/chunk-AQDTSKZB-BoE0sW9h.js                   51.23 kB │ gzip:  16.63 kB
dist/assets/chunk-NQOKRVIF-DYo2PTsw.js                   62.79 kB │ gzip:  20.36 kB
dist/assets/c4Diagram-XDPPPE54-D5QOW7gp.js               65.08 kB │ gzip:  18.61 kB
dist/assets/ganttDiagram-R7GPNTJY-BRnmOvJA.js            70.01 kB │ gzip:  23.01 kB
dist/assets/diagram-TYUNFSNR-BrYHjm0O.js                 80.45 kB │ gzip:  25.15 kB
dist/assets/cose-bilkent-JH36ORCC-CLV_Vv8p.js            81.22 kB │ gzip:  21.51 kB
dist/assets/mermaid.core-wsYDS0-U.js                     84.68 kB │ gzip:  29.32 kB
dist/assets/swimlanes-B3ENRKFQ-D1wA5IXc.js              106.44 kB │ gzip:  36.22 kB
dist/assets/chunk-HAGFOTED-C-IKWD_c.js                  115.56 kB │ gzip:  29.27 kB
dist/assets/sequenceDiagram-BLEHNHQU-BoX4r2JF.js        117.67 kB │ gzip:  31.37 kB
dist/assets/architectureDiagram-ZHVYKT53-nKlNC4m8.js    148.87 kB │ gzip:  41.10 kB
dist/assets/usecaseDiagram-WPOLBNNX-Bb0yPAi2.js         187.90 kB │ gzip:  49.20 kB
dist/assets/chunk-DSNLSHJZ-CQnSsx7F.js                  241.36 kB │ gzip:  40.31 kB
dist/assets/katex-B_JcIwqj.js                           258.80 kB │ gzip:  77.65 kB
dist/assets/cytoscape.esm-BegBNzOV.js                   434.75 kB │ gzip: 137.75 kB
dist/assets/index-CZdbr-uh.js                           595.14 kB │ gzip: 198.25 kB
dist/assets/chunk-NGNAAXSQ-C2Wy9Xmz.js                  629.04 kB │ gzip: 127.32 kB
dist/assets/echarts-83w_Cegm.js                       1,124.20 kB │ gzip: 373.58 kB
dist/assets/elk-QONTBCTQ-CVvCVq5J.js                  1,462.89 kB │ gzip: 455.85 kB

✓ built in 1.06s
[plugin builtin:vite-reporter] 
(!) Some chunks are larger than 500 kB after minification. Consider:
- Using dynamic import() to code-split the application
- Use build.rolldownOptions.output.codeSplitting to improve chunking: https://rolldown.rs/reference/OutputOptions.codeSplitting
- Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.
结果：通过

### 宿主构建产物断言（accept 只含 MIME、含 xlsx MIME、走宿主同源 /api/v1）

```bash
bundle_probe
```

产物：apps/desktop/front/dist/assets/index-CZdbr-uh.js
✓ accept 为纯 MIME 列表
✓ 产物内含 xlsx MIME（可用于类型兜底与 file 重建）
✓ 产物内无扩展名 accept token
✓ 渲染层已按宿主同源路径（/api/v1）拼 HTTP 根
结果：通过

### 桌面宿主后端全量测试（排除他人未提交改动导致的既有失败）

```bash
cd apps/desktop && .venv/bin/python -m pytest tests/ -q --deselect tests/test_host_api.py::test_macos_open_treats_hanging_subprocess_as_handed_off
```

........................................................................ [ 31%]
........................................................................ [ 62%]
........................................................................ [ 93%]
..............                                                           [100%]
=============================== warnings summary ===============================
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
  /Users/lixingwen/xw/study/ai-base/apps/desktop/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
230 passed, 1 deselected, 1 warning in 1.87s
结果：通过

### 转发相关文件 lint（ruff）

```bash
cd apps/desktop && .venv/bin/ruff check desktop_app tests/test_agent_proxy.py
```

All checks passed!
结果：通过

### 真实 AI Base 转发链路（xlsx 上传 201 / 会话列表 200 / octet-stream 400 / 401 透传）

```bash
HOME=$HOME PYTHONPATH=apps/desktop apps/desktop/.venv/bin/python probe_forward.py
```

/Users/lixingwen/xw/study/ai-base/apps/desktop/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
  from starlette.testclient import TestClient as TestClient  # noqa
AI Base：http://127.0.0.1:8000 / agent_id=1
✓ xlsx 上传经宿主转发：201 {"success": true, "message": "ok", "code": 0, "data": {"assetId": "2eaedf92ec9c4305aa90b94a922db6bb", "filename": "verify.xlsx", "mimeType": "application/vnd.op
✓ 会话列表经宿主转发：200（不再触发 CORS）
✓ octet-stream 经宿主转发被后端拒绝：400（说明 MIME 兜底必要，且状态码透传）
✓ 无 Authorization 时上游 401 透传（转发不绕过鉴权）
RESULT OK
结果：通过

## 未执行项与原因

- 真机文件面板：macOS pywebview 窗口里点「上传文件」后系统面板实际能选中 `.xlsx`/`.pdf`——脚本只验证了 accept 已改为纯 MIME（且实测这 10 个 MIME 在 `UTType.typeWithMIMEType_` 全部映射成功），没有在 pywebview 窗口里手动点选文件。
- 悬浮窗内的上传交互细节（缩略图、上传进度、失败重试、附件气泡样式）：宿主前端与 ai-sdk 都没有前端测试框架，脚本用类型检查 + 构建 + 真实 HTTP 探针覆盖行为，未做浏览器点击/截图断言。
- 真实模型读取附件内容：探针只证明「后端受理 xlsx（201）」与「MIME 判定正确」，没有用模型真正解析一个有效 xlsx 并总结（需要有效文件、模型支持与额度）。
/Users/lixingwen/xw/study/ai-base/tools/harness/verify/2026-10-20-desktop-assistant-assets.sh: line 230: apps/ai-sdk: is a directory
/Users/lixingwen/xw/study/ai-base/tools/harness/verify/2026-10-20-desktop-assistant-assets.sh: line 230: src/core/__tests__/websocket.test.ts:278: No such file or directory
/Users/lixingwen/xw/study/ai-base/tools/harness/verify/2026-10-20-desktop-assistant-assets.sh: line 230: __promisify__: command not found
/Users/lixingwen/xw/study/ai-base/tools/harness/verify/2026-10-20-desktop-assistant-assets.sh: line 230: upload-mime.ts: command not found
-  的全量 undefined
 ERR_PNPM_RECURSIVE_EXEC_FIRST_FAIL  Command "type-check" not found（vue-tsc）：既有文件  报 TS2741（ 缺失），在本 request 改动前就会失败，与本任务无关，未修复；脚本改为只对新增的  做 Version 5.3.2
tsc: The TypeScript Compiler - Version 5.3.2

COMMON COMMANDS

  tsc
  Compiles the current project (tsconfig.json in the working directory.)

  tsc app.ts util.ts
  Ignoring tsconfig.json, compiles the specified files with default compiler options.

  tsc -b
  Build a composite project in the working directory.

  tsc --init
  Creates a tsconfig.json with the recommended settings in the working directory.

  tsc -p ./path/to/tsconfig.json
  Compiles the TypeScript project located at the specified path.

  tsc --help --all
  An expanded version of this information, showing all possible compiler options

  tsc --noEmit
  tsc --target esnext
  Compiles the current project, with additional settings.

COMMAND LINE FLAGS

--help, -h
Print this message.

--watch, -w
Watch input files.

--all
Show all compiler options.

--version, -v
Print the compiler's version.

--init
Initializes a TypeScript project and creates a tsconfig.json file.

--project, -p
Compile the project given the path to its configuration file, or to a folder with a 'tsconfig.json'.

--build, -b
Build one or more projects and their dependencies, if out of date

--showConfig
Print the final configuration instead of building.

COMMON COMPILER OPTIONS

--pretty
Enable color and formatting in TypeScript's output to make compiler errors easier to read.
type: boolean
default: true

--declaration, -d
Generate .d.ts files from TypeScript and JavaScript files in your project.
type: boolean
default: `false`, unless `composite` is set

--declarationMap
Create sourcemaps for d.ts files.
type: boolean
default: false

--emitDeclarationOnly
Only output d.ts files and not JavaScript files.
type: boolean
default: false

--sourceMap
Create source map files for emitted JavaScript files.
type: boolean
default: false

--target, -t
Set the JavaScript language version for emitted JavaScript and include compatible library declarations.
one of: es3, es5, es6/es2015, es2016, es2017, es2018, es2019, es2020, es2021, es2022, esnext
default: es5

--module, -m
Specify what module code is generated.
one of: none, commonjs, amd, umd, system, es6/es2015, es2020, es2022, esnext, node16, nodenext
default: undefined

--lib
Specify a set of bundled library declaration files that describe the target runtime environment.
one or more: es5, es6/es2015, es7/es2016, es2017, es2018, es2019, es2020, es2021, es2022, es2023, esnext, dom, dom.iterable, webworker, webworker.importscripts, webworker.iterable, scripthost, es2015.core, es2015.collection, es2015.generator, es2015.iterable, es2015.promise, es2015.proxy, es2015.reflect, es2015.symbol, es2015.symbol.wellknown, es2016.array.include, es2017.date, es2017.object, es2017.sharedmemory, es2017.string, es2017.intl, es2017.typedarrays, es2018.asyncgenerator, es2018.asynciterable/esnext.asynciterable, es2018.intl, es2018.promise, es2018.regexp, es2019.array, es2019.object, es2019.string, es2019.symbol/esnext.symbol, es2019.intl, es2020.bigint/esnext.bigint, es2020.date, es2020.promise, es2020.sharedmemory, es2020.string, es2020.symbol.wellknown, es2020.intl, es2020.number, es2021.promise/esnext.promise, es2021.string, es2021.weakref/esnext.weakref, es2021.intl, es2022.array, es2022.error, es2022.intl, es2022.object, es2022.sharedmemory, es2022.string/esnext.string, es2022.regexp, es2023.array/esnext.array, es2023.collection/esnext.collection, esnext.intl, esnext.disposable, esnext.decorators, decorators, decorators.legacy
default: undefined

--allowJs
Allow JavaScript files to be a part of your program. Use the 'checkJS' option to get errors from these files.
type: boolean
default: false

--checkJs
Enable error reporting in type-checked JavaScript files.
type: boolean
default: false

--jsx
Specify what JSX code is generated.
one of: preserve, react, react-native, react-jsx, react-jsxdev
default: undefined

--outFile
Specify a file that bundles all outputs into one JavaScript file. If 'declaration' is true, also designates a file that bundles all .d.ts output.

--outDir
Specify an output folder for all emitted files.

--removeComments
Disable emitting comments.
type: boolean
default: false

--noEmit
Disable emitting files from a compilation.
type: boolean
default: false

--strict
Enable all strict type-checking options.
type: boolean
default: false

--types
Specify type package names to be included without being referenced in a source file.

--esModuleInterop
Emit additional JavaScript to ease support for importing CommonJS modules. This enables 'allowSyntheticDefaultImports' for type compatibility.
type: boolean
default: false

You can learn about all of the compiler options at https://aka.ms/tsc 检查。
- Windows / Linux 的文件面板与 MIME 映射：本机只有 macOS 环境，未在其它平台执行；其它平台不走 `UTType`，但 `file.type` 为空时的扩展名兜底是平台无关的。
- `tests/test_host_api.py::test_macos_open_treats_hanging_subprocess_as_handed_off`：仓库内他人未提交改动导致 `NameError: name 'subprocess' is not defined`（`tests/test_host_api.py:210`），与本 request 无关，已从 pytest 中 deselect，未修复该文件。

## 验收结论

- 已由脚本证明：ai-sdk 的 `accept` 是纯 MIME 列表（产物内不再出现 `.xlsx` 这类扩展名 token），扩展名 → MIME 的映射与 `withResolvedMimeType` 重建有 10 例单测；宿主前端构建产物里渲染层按 `${location.origin}/api/v1` 拼 HTTP 根（不再由 WS endpoint 推导出跨域的 `127.0.0.1:8000`）。
- 已由脚本证明：宿主 `/api/v1/{path:path}` 转发会透传方法、查询串、`Authorization`、`Content-Type` 与原始 body，并透传上游状态码；未配置后端返回 503、路径穿越返回 400、网络错误 502（6 例 pytest）。
- 已由真实链路探针证明（若本机配置可用）：同一个 `POST /api/v1/embed/assets` 用 xlsx MIME 返回 201、`GET /api/v1/embed/conversations` 返回 200，即原报错里「跨域被拦」的两个接口都能正常走通；`application/octet-stream` 仍被后端以「不支持的文件类型」拒绝，说明 MIME 兜底不是可选项。
- 尚未证明：真机文件面板的可用性、悬浮窗上传交互的视觉与手感、模型对附件内容的解析（见上「未执行项」）。因此本脚本退出码为 3（有未执行项），不能视为已完成人工联调。
- 剩余风险：转发接口把 `/api/v1/*` 全量放行到配置的 `baseUrl`，安全边界依赖该地址由用户本人配置（设置页）且 token 由渲染层携带；未新增后端 CORS 豁免，也未放开任何鉴权。
```

## 未执行项与原因

- 脚本未声明未执行项。若确有无法在本机执行的项目，请在验证脚本中补上「## 未执行项与原因」章节。

## 验收结论

- 待人工补写：是否达到 spec.md 的验收标准；剩余风险；是否可归档。
- 脚本退出码：3
