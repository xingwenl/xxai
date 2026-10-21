---
source: script
request: 2026-10-21-desktop-plugin-dev-reload-dashboard
ranAt: "2026-10-21 13:41:19 CST"
exitCode: 3
---

## 已执行的命令与结果

### 后端单测全绿（含新增 dev_reload / dashboard 权限用例）

```bash
cd apps/desktop && .venv/bin/python -m pytest tests/ -q
```

........................................................................ [ 25%]
........................................................................ [ 51%]
........................................................................ [ 77%]
...............................................................          [100%]
=============================== warnings summary ===============================
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
  /Users/lixingwen/xw/study/ai-base/apps/desktop/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
279 passed, 1 warning in 1.79s
结果：通过

### 前端类型检查与生产构建

```bash
cd apps/desktop && pnpm --dir front build
```


> desktop-front@0.2.0 build /Users/lixingwen/xw/study/ai-base/apps/desktop/front
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
dist/assets/index-CP-siVg9.css                           64.31 kB │ gzip:  12.61 kB
dist/assets/array-BifhSqXX.js                             0.10 kB │ gzip:   0.11 kB
dist/assets/pie-XZMESJXO-B3Q81CZ1.js                      0.10 kB │ gzip:   0.12 kB
dist/assets/info-OHQRW6UA-BUYAjYI6.js                     0.10 kB │ gzip:   0.12 kB
dist/assets/radar-ABXABTNO-VISUDuS6.js                    0.10 kB │ gzip:   0.12 kB
dist/assets/packet-JDAUHWVQ-vFGb8xxY.js                   0.11 kB │ gzip:   0.12 kB
dist/assets/cynefin-EF2NZ3EQ-Icj_HIsj.js                  0.11 kB │ gzip:   0.12 kB
dist/assets/treemap-SAJKECNS-5UacLcAy.js                  0.11 kB │ gzip:   0.12 kB
dist/assets/wardley-7MLQ67FV-Byvd1hOP.js                  0.11 kB │ gzip:   0.12 kB
dist/assets/gitGraph-VSP46ZUC-DLkEm5wo.js                 0.11 kB │ gzip:   0.12 kB
dist/assets/railroad-I3PHUGI6-BImCSewF.js                 0.11 kB │ gzip:   0.12 kB
dist/assets/treeView-D4JQ5SDB-DGlL3q4K.js                 0.11 kB │ gzip:   0.12 kB
dist/assets/channel-BXVJEJU0.js                           0.11 kB │ gzip:   0.12 kB
dist/assets/railroad-peg-JR7BVNR7-CbugS7pe.js             0.11 kB │ gzip:   0.13 kB
dist/assets/architecture-WOLXFQ4H-DMsXViJ_.js             0.11 kB │ gzip:   0.12 kB
dist/assets/railroad-abnf-LNEFI6M7-lAslzVcK.js            0.11 kB │ gzip:   0.13 kB
dist/assets/railroad-ebnf-DWYD2UWJ-Btg_EH6Q.js            0.11 kB │ gzip:   0.13 kB
dist/assets/eventmodeling-K75KTNOO-Bs1clVAf.js            0.11 kB │ gzip:   0.13 kB
dist/assets/init-C-OQMol4.js                              0.14 kB │ gzip:   0.12 kB
dist/assets/chunk-Y2CYZVJY-DsF7k-Jl.js                    0.15 kB │ gzip:   0.14 kB
dist/assets/chunk-2Q5K7J3B-C1jixKkw.js                    0.19 kB │ gzip:   0.16 kB
dist/assets/chunk-JWPE2WC7-DVXcaiue.js                    0.22 kB │ gzip:   0.17 kB
dist/assets/chunk-XXDRQBXY-BM-KLZcu.js                    0.26 kB │ gzip:   0.22 kB
dist/assets/chunk-5VM5RSS4-ZNzvKenW.js                    0.36 kB │ gzip:   0.27 kB
dist/assets/flowDiagram-IUGLLWBU-DzEr8soV.js              0.56 kB │ gzip:   0.31 kB
dist/assets/chunk-VQ5W62QI-DS45te34.js                    0.57 kB │ gzip:   0.40 kB
dist/assets/chunk-J5ZVWO5B-oDCd-gWO.js                    0.63 kB │ gzip:   0.43 kB
dist/assets/infoDiagram-MVDRKAX5-CWvGlJeN.js              0.65 kB │ gzip:   0.41 kB
dist/assets/swimlanesDiagram-AYQRV4AK-CDI_f1qr.js         0.83 kB │ gzip:   0.48 kB
dist/assets/sizeCapture-INFHLROL-3uHXrFqA.js              0.87 kB │ gzip:   0.51 kB
dist/assets/chunk-DUW6YSOI-Dgx8z5s3.js                    0.89 kB │ gzip:   0.46 kB
dist/assets/line-B6MBBJ2L.js                              0.94 kB │ gzip:   0.47 kB
dist/assets/ordinal-BDEzSJ7C.js                           1.17 kB │ gzip:   0.56 kB
dist/assets/chunk-ZAUX2LTX-Dgqg9-wb.js                    1.41 kB │ gzip:   0.79 kB
dist/assets/railroadDiagram-Y72NRBL7-TGWMkSCY.js          1.65 kB │ gzip:   0.76 kB
dist/assets/abnfDiagram-WEYOIA3C-B6xxRnep.js              1.84 kB │ gzip:   0.89 kB
dist/assets/chunk-UHW7PFBP-DHE_Z1rE.js                    1.95 kB │ gzip:   0.95 kB
dist/assets/chunk-55XCU76K-BOgTGB8U.js                    1.97 kB │ gzip:   0.88 kB
dist/assets/pegDiagram-ECIUJNBX-CcUWtQrd.js               2.01 kB │ gzip:   0.94 kB
dist/assets/ebnfDiagram-V4P3TTPT-CwJkAujk.js              2.05 kB │ gzip:   0.88 kB
dist/assets/dist-CgSmEPAk.js                              2.16 kB │ gzip:   0.96 kB
dist/assets/path-fybaL0A-.js                              2.27 kB │ gzip:   0.98 kB
dist/assets/arc-DNavHMxP.js                               3.47 kB │ gzip:   1.46 kB
dist/assets/diagram-I5XIIV2D-jRAagWN1.js                  4.34 kB │ gzip:   1.89 kB
dist/assets/defaultLocale-BFoDCU3G.js                     4.63 kB │ gzip:   2.12 kB
dist/assets/chunk-4EMNKR2T-Bd3ZT809.js                    5.43 kB │ gzip:   2.49 kB
dist/assets/linear-BGfxv0Ph.js                            5.51 kB │ gzip:   2.25 kB
dist/assets/chunk-YZO67HFG-BCIV4E3b.js                    5.83 kB │ gzip:   2.68 kB
dist/assets/diagram-RJA3I4VV-DA1wl9_v.js                  6.07 kB │ gzip:   2.56 kB
dist/assets/pieDiagram-GNMPY74T-ajXa_RjG.js               6.22 kB │ gzip:   2.59 kB
dist/assets/diagram-ODIL2UCW-CNO9X2mz.js                  8.12 kB │ gzip:   3.64 kB
dist/assets/cynefinDiagram-WF24UDRP-DdUKHI7Q.js           9.94 kB │ gzip:   3.51 kB
dist/assets/chunk-ZCHMQSOR-DMTthFSs.js                   10.38 kB │ gzip:   4.32 kB
dist/assets/diagram-PFBEJUXE-Ig95yurw.js                 10.92 kB │ gzip:   4.25 kB
dist/assets/chunk-HNE4Q36P-BK5d6hgk.js                   14.84 kB │ gzip:   4.19 kB
dist/assets/chunk-2E7WHVMD-Bpvvdtnq.js                   15.64 kB │ gzip:   4.35 kB
dist/assets/diagram-CBK3MWTC-CcbwL0-a.js                 15.75 kB │ gzip:   5.52 kB
dist/assets/mermaid-parser.core-CZmy0L1i.js              16.44 kB │ gzip:   3.92 kB
dist/assets/ishikawaDiagram-HPEHV2GE-DvD2Rryi.js         17.30 kB │ gzip:   6.53 kB
dist/assets/kanban-definition-FNSA4HC5-DXs6ni3v.js       20.26 kB │ gzip:   7.15 kB
dist/assets/sankeyDiagram-SY24JHO5-Dfz8mUmS.js           22.79 kB │ gzip:   8.25 kB
dist/assets/journeyDiagram-BOSHW7O7-47K-ryC_.js          23.15 kB │ gzip:   8.16 kB
dist/assets/mindmap-definition-6OY57UG3-iguyZAwu.js      23.66 kB │ gzip:   8.06 kB
dist/assets/graphlib-DS17s2tU.js                         23.90 kB │ gzip:   8.31 kB
dist/assets/wardleyDiagram-IVAIDKWA-IHw2_H5c.js          25.20 kB │ gzip:   6.54 kB
dist/assets/rough.esm-Dy-Kn_BL.js                        27.10 kB │ gzip:   8.85 kB
dist/assets/gitGraphDiagram-PDYL7XHY-6P80Fft0.js         29.01 kB │ gzip:   8.55 kB
dist/assets/timeline-definition-JXYKGLGB-U8YjKdKE.js     30.45 kB │ gzip:  10.03 kB
dist/assets/erDiagram-KYQIGQAA-44IJyGVn.js               30.65 kB │ gzip:  10.57 kB
dist/assets/chunk-7S6XSTFO-BZe0xnok.js                   30.75 kB │ gzip:   8.51 kB
dist/assets/requirementDiagram-EQYSW5RA-BdI8dPMW.js      31.07 kB │ gzip:   9.82 kB
dist/assets/quadrantDiagram-D57K4MC3-DmemQDsN.js         33.52 kB │ gzip:   9.74 kB
dist/assets/chunk-WQQL4CDK-BdAasubQ.js                   37.88 kB │ gzip:   8.20 kB
dist/assets/vennDiagram-Q3Y3IDCW-DliEdSH1.js             41.18 kB │ gzip:  15.11 kB
dist/assets/stateDiagram-v2-A6IESKWZ-Bi6gjy3m.js         41.55 kB │ gzip:  13.89 kB
dist/assets/blockDiagram-RJAE7QA3-qElQaFRb.js            42.44 kB │ gzip:  13.87 kB
dist/assets/xychartDiagram-4URNHDU4-DBAjKgh1.js          44.52 kB │ gzip:  12.35 kB
dist/assets/src-CMJndcsu.js                              45.66 kB │ gzip:  15.99 kB
dist/assets/dagre-NK4GIZVX-lqacWG6B.js                   47.83 kB │ gzip:  17.10 kB
dist/assets/classDiagram-v2-4MYWR3UA-DzaBRaH6.js         49.70 kB │ gzip:  16.15 kB
dist/assets/chunk-AQDTSKZB-Cmj5sXbE.js                   51.23 kB │ gzip:  16.63 kB
dist/assets/chunk-NQOKRVIF-Byjp8_M3.js                   62.79 kB │ gzip:  20.36 kB
dist/assets/c4Diagram-XDPPPE54-BuISn8qK.js               65.08 kB │ gzip:  18.60 kB
dist/assets/ganttDiagram-R7GPNTJY-8RRuJDE9.js            70.01 kB │ gzip:  23.01 kB
dist/assets/diagram-TYUNFSNR-C1wTt2CK.js                 80.45 kB │ gzip:  25.14 kB
dist/assets/cose-bilkent-JH36ORCC-nqS9tN8Q.js            81.22 kB │ gzip:  21.51 kB
dist/assets/mermaid.core-C8X9DMq6.js                     84.68 kB │ gzip:  29.32 kB
dist/assets/swimlanes-B3ENRKFQ-kAgJQLro.js              106.44 kB │ gzip:  36.21 kB
dist/assets/chunk-HAGFOTED-D3LCDmHW.js                  115.56 kB │ gzip:  29.27 kB
dist/assets/sequenceDiagram-BLEHNHQU-DPtSnZLG.js        117.67 kB │ gzip:  31.37 kB
dist/assets/architectureDiagram-ZHVYKT53-JAu5OIH7.js    148.87 kB │ gzip:  41.10 kB
dist/assets/usecaseDiagram-WPOLBNNX-B6szAG_i.js         187.90 kB │ gzip:  49.20 kB
dist/assets/chunk-DSNLSHJZ-x9-CR_1_.js                  241.36 kB │ gzip:  40.31 kB
dist/assets/katex-B_JcIwqj.js                           258.80 kB │ gzip:  77.65 kB
dist/assets/cytoscape.esm-BegBNzOV.js                   434.75 kB │ gzip: 137.75 kB
dist/assets/index-BS163RpF.js                           615.23 kB │ gzip: 203.50 kB
dist/assets/chunk-NGNAAXSQ-C2Wy9Xmz.js                  629.04 kB │ gzip: 127.32 kB
dist/assets/echarts-IuLgbuNx.js                       1,124.20 kB │ gzip: 373.58 kB
dist/assets/elk-QONTBCTQ-s02hwCuf.js                  1,462.89 kB │ gzip: 455.85 kB

✓ built in 1.04s
[plugin builtin:vite-reporter] 
(!) Some chunks are larger than 500 kB after minification. Consider:
- Using dynamic import() to code-split the application
- Use build.rolldownOptions.output.codeSplitting to improve chunking: https://rolldown.rs/reference/OutputOptions.codeSplitting
- Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.
结果：通过

### 未开启 DESKTOP_DEV_RELOAD 时的端点回归

```bash
revision_disabled_probe
```

内部：临时 HOME 起宿主 → GET /api/desktop/plugin-revision 断言 enabled:false → GET /api/desktop/settings 断言 devReload:false。

启动宿主（未设置 DESKTOP_DEV_RELOAD）：HOME=/var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.UrkKDvQCqp/home-disabled port=57407
✓ 未开启时 GET /api/desktop/plugin-revision 返回 enabled:false 且无插件指纹
✓ /api/desktop/settings 的 devReload 为 false
结果：通过

### 浏览器级探针（临时 HOME + DESKTOP_DEV_RELOAD=1 + 无头 Chrome/CDP：概览卡 → 进入子应用 → 改盘上文件后自动重载）

```bash
browser_probe
```

内部依次：首页概览卡渲染 / 点击卡片进入子应用 / 改盘上 index.html / 不刷新页面等 iframe 文本更新 / 概览卡指标同步 / 返回首页状态未丢；探针脚本见 `/var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.UrkKDvQCqp/cdp_check.py`。

浏览器：/Applications/Google Chrome.app/Contents/MacOS/Google Chrome
启动宿主：HOME=/var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.UrkKDvQCqp/home port=57416 DESKTOP_DEV_RELOAD=1
✓ 首页出现 hello-world 概览卡（概览区 + 标题）
✓ 探针插件的概览卡出现在首页（未打开子应用）
✓ 点击卡片进入子应用，iframe 显示「版本一」
✓ 改盘上 index.html 后 iframe 自动重新加载为「版本二」（未刷新整页）
✓ 返回首页后概览卡指标已随热重载更新为「版本二」
✓ 返回首页后插件卡片仍在（页面状态未被打断）
✓ plugin.log 含 reload-probe 的 iframe_load：
{"ts": "2026-10-21T05:41:14.425275+00:00", "plugin": "reload-probe", "event": "sdk_injected"}
{"ts": "2026-10-21T05:41:14.425351+00:00", "plugin": "reload-probe", "event": "iframe_load", "detail": "/apps/reload-probe/index.html"}
{"ts": "2026-10-21T05:41:14.428820+00:00", "plugin": "hello-world", "event": "iframe_load", "detail": "/apps/hello-world/index.html"}
{"ts": "2026-10-21T05:41:14.428866+00:00", "plugin": "hello-world", "event": "sdk_injected"}
{"ts": "2026-10-21T05:41:18.937102+00:00", "plugin": "reload-probe", "event": "iframe_load", "detail": "/apps/reload-probe/index.html"}
{"ts": "2026-10-21T05:41:18.937327+00:00", "plugin": "reload-probe", "event": "sdk_injected"}
结果：通过

### Harness 审计（本次新增无 ERROR）

```bash
python3 tools/harness/audit.py
```

ERROR  2026-10-20-personal-knowledge-base: v2 request 缺少 verify.md

v2 requests: 26  存量跳过: 59  ERROR: 1  WARN: 0

其余 ERROR（与本 request 无关，见「未执行项与原因」）：
ERROR  2026-10-20-personal-knowledge-base: v2 request 缺少 verify.md
结果：通过（本 request 未新增其它 ERROR）

## 未执行项与原因

- 真机 GUI：在 pywebview 窗口里观察概览卡视觉、点击手感与热重载时的 toast 提示——需要 macOS 图形会话与人工目视。脚本用无头 Chrome + CDP 复现了同一条链路（首页概览卡 → 打开子应用 → 改文件 → iframe 自动重载）并断言了 DOM 文本。
- 前端没有测试框架：概览卡的截断上限（标题 ≤40、指标 ≤4 条、最近 ≤5 条）与 `dashboard-bridge` 的订阅/清理由浏览器级探针间接覆盖，没有组件单测覆盖全部字段分支；`desktop.dashboard.publish` 未声明权限时抛「权限不足」的错误文案只由类型与实现保证，未在探针里构造该场景。
- 热重载未覆盖 react 类型子应用（`bookmarks-organizer`）：它是宿主编译产物，需要 `pnpm build` 后重启宿主，README 已写明；探针只覆盖 iframe 类型插件。
- 多窗口：热重载按页面各自轮询，未验证两个宿主窗口同时打开时的表现（预期各自独立重载，没有跨窗口同步）。
- `tests/test_host_api.py` 的 `test_macos_open_*` 用例属于工作区中他人未提交的 WIP，其文件顶部缺 `import subprocess`；本次运行前已临时补该行（不随本 request 提交），因此全量 pytest 通过。在纯净 HEAD 上该用例不存在。
- Harness 审计还报出以下 ERROR，均指向工作区中他人未提交的 request，与本 request 无关：
  - ERROR  2026-10-20-personal-knowledge-base: v2 request 缺少 verify.md
- Windows / Linux：本机只有 macOS 环境，未在其它平台执行（`os.walk` 与 mtime_ns 跨平台行为一致，但未实测）。

## 验收结论

- 已由单测证明：`DESKTOP_DEV_RELOAD` 的 truthy/falsy 解析、未开启时端点返回 `enabled:false` 空载荷、开启后列出内置与用户插件且指纹为 12 位十六进制、只改一个插件只让该插件指纹变化、`node_modules`/`__pycache__`/`.git`/`dist` 改动不影响 revision、`/api/desktop/settings` 的 `devReload` 随环境变量翻转、`dashboard` 进入权限白名单且 `unknown_permissions()` 为空。
- 已由前端构建证明：`tsc` 类型检查与 `vite build` 通过（包含新增的 `dashboard-bridge.ts`、`dashboard-cards.tsx`、`PluginView` 的 `reloadToken` 与 `App.tsx` 的 revision 轮询）。
- 已由浏览器级探针证明：临时 HOME 下首页「概览」区同时出现内置 hello-world 与探针插件的概览卡；点击探针卡片进入子应用；直接修改盘上 `index.html` 后**不刷新宿主页面**，iframe 自动重新加载为新文本；重新发布的概览卡指标同步更新；返回首页后插件与页面状态未丢。
- 已由端点回归证明：未设置 `DESKTOP_DEV_RELOAD` 时 `GET /api/desktop/plugin-revision` 返回 `enabled:false`、`revision` 为空、`plugins` 为空，`/api/desktop/settings` 的 `devReload` 为 false。
- 尚未证明：真窗口里的视觉与手感、react 类型子应用的热重载（本就不做）、多窗口并发、Windows / Linux 平台（见上「未执行项」）。因此本脚本退出码为 3（有未执行项），不能视为已完成人工联调。
- 已知边界：热重载依赖前端轮询（1.5s 间隔），最坏场景下改动生效有约 1.5s 延迟；概览卡是内存态，宿主页面刷新后由插件重新 publish。
