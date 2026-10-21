---
source: script
request: 2026-10-21-desktop-plugin-market
ranAt: "2026-10-21 13:57:33 CST"
exitCode: 3
---

## 已执行的命令与结果

### 后端单测全绿（含新增 market 用例）

```bash
cd apps/desktop && .venv/bin/python -m pytest tests/ -q
```

........................................................................ [ 23%]
........................................................................ [ 46%]
........................................................................ [ 70%]
........................................................................ [ 93%]
...................                                                      [100%]
=============================== warnings summary ===============================
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
  /Users/lixingwen/xw/study/ai-base/apps/desktop/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
307 passed, 1 warning in 1.82s
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
dist/assets/index-DcOmO1pU.css                           67.17 kB │ gzip:  13.11 kB
dist/assets/array-BifhSqXX.js                             0.10 kB │ gzip:   0.11 kB
dist/assets/pie-XZMESJXO-BhDJhhJR.js                      0.10 kB │ gzip:   0.12 kB
dist/assets/info-OHQRW6UA-CRMtRomj.js                     0.10 kB │ gzip:   0.12 kB
dist/assets/radar-ABXABTNO-DhdPi2ZM.js                    0.10 kB │ gzip:   0.12 kB
dist/assets/packet-JDAUHWVQ-Bl5osy69.js                   0.11 kB │ gzip:   0.12 kB
dist/assets/cynefin-EF2NZ3EQ-CasOXVo-.js                  0.11 kB │ gzip:   0.12 kB
dist/assets/treemap-SAJKECNS-CBNiqrcO.js                  0.11 kB │ gzip:   0.12 kB
dist/assets/wardley-7MLQ67FV-DU92SrZa.js                  0.11 kB │ gzip:   0.12 kB
dist/assets/gitGraph-VSP46ZUC-Cenp0P4j.js                 0.11 kB │ gzip:   0.12 kB
dist/assets/railroad-I3PHUGI6-DgKIx2nM.js                 0.11 kB │ gzip:   0.12 kB
dist/assets/treeView-D4JQ5SDB-BfkJWXA1.js                 0.11 kB │ gzip:   0.12 kB
dist/assets/channel-Dnhw07Sx.js                           0.11 kB │ gzip:   0.12 kB
dist/assets/railroad-peg-JR7BVNR7-DocnVJEX.js             0.11 kB │ gzip:   0.13 kB
dist/assets/architecture-WOLXFQ4H-FZ9waR3Z.js             0.11 kB │ gzip:   0.13 kB
dist/assets/railroad-abnf-LNEFI6M7-Dm4x29e1.js            0.11 kB │ gzip:   0.13 kB
dist/assets/railroad-ebnf-DWYD2UWJ-DL8wEmbw.js            0.11 kB │ gzip:   0.13 kB
dist/assets/eventmodeling-K75KTNOO-CD7cyAW_.js            0.11 kB │ gzip:   0.13 kB
dist/assets/init-C-OQMol4.js                              0.14 kB │ gzip:   0.12 kB
dist/assets/chunk-Y2CYZVJY-DsF7k-Jl.js                    0.15 kB │ gzip:   0.14 kB
dist/assets/chunk-2Q5K7J3B-C1jixKkw.js                    0.19 kB │ gzip:   0.16 kB
dist/assets/chunk-JWPE2WC7-DVXcaiue.js                    0.22 kB │ gzip:   0.17 kB
dist/assets/chunk-XXDRQBXY-CMlUCYlV.js                    0.26 kB │ gzip:   0.22 kB
dist/assets/chunk-5VM5RSS4-ZNzvKenW.js                    0.36 kB │ gzip:   0.27 kB
dist/assets/flowDiagram-IUGLLWBU-QbUAF0TY.js              0.56 kB │ gzip:   0.31 kB
dist/assets/chunk-VQ5W62QI-CB9IrFIo.js                    0.57 kB │ gzip:   0.40 kB
dist/assets/chunk-J5ZVWO5B-oDCd-gWO.js                    0.63 kB │ gzip:   0.43 kB
dist/assets/infoDiagram-MVDRKAX5-ChQD32M6.js              0.65 kB │ gzip:   0.41 kB
dist/assets/swimlanesDiagram-AYQRV4AK-D1BtAH2s.js         0.83 kB │ gzip:   0.48 kB
dist/assets/sizeCapture-INFHLROL-3uHXrFqA.js              0.87 kB │ gzip:   0.51 kB
dist/assets/chunk-DUW6YSOI-Dgx8z5s3.js                    0.89 kB │ gzip:   0.46 kB
dist/assets/line-SMigt-eh.js                              0.94 kB │ gzip:   0.47 kB
dist/assets/ordinal-BDEzSJ7C.js                           1.17 kB │ gzip:   0.56 kB
dist/assets/chunk-ZAUX2LTX-C-zz1qkO.js                    1.41 kB │ gzip:   0.78 kB
dist/assets/railroadDiagram-Y72NRBL7-Dfk9EnG4.js          1.65 kB │ gzip:   0.76 kB
dist/assets/abnfDiagram-WEYOIA3C-DnrMxI9w.js              1.84 kB │ gzip:   0.89 kB
dist/assets/chunk-UHW7PFBP-Bh6tH7b9.js                    1.95 kB │ gzip:   0.95 kB
dist/assets/chunk-55XCU76K-BvqO2c4f.js                    1.97 kB │ gzip:   0.88 kB
dist/assets/pegDiagram-ECIUJNBX-C89JDJxa.js               2.01 kB │ gzip:   0.94 kB
dist/assets/ebnfDiagram-V4P3TTPT-DAi1nTNb.js              2.05 kB │ gzip:   0.88 kB
dist/assets/dist-Af-zZ0XY.js                              2.16 kB │ gzip:   0.96 kB
dist/assets/path-fybaL0A-.js                              2.27 kB │ gzip:   0.98 kB
dist/assets/arc-CehKi3tZ.js                               3.47 kB │ gzip:   1.46 kB
dist/assets/diagram-I5XIIV2D-Bg3_vYuh.js                  4.34 kB │ gzip:   1.89 kB
dist/assets/defaultLocale-BFoDCU3G.js                     4.63 kB │ gzip:   2.12 kB
dist/assets/chunk-4EMNKR2T-CVvVby_4.js                    5.43 kB │ gzip:   2.50 kB
dist/assets/linear-CRPUkV2E.js                            5.51 kB │ gzip:   2.25 kB
dist/assets/chunk-YZO67HFG-B-WVvpKZ.js                    5.83 kB │ gzip:   2.68 kB
dist/assets/diagram-RJA3I4VV-C2Jog79m.js                  6.07 kB │ gzip:   2.56 kB
dist/assets/pieDiagram-GNMPY74T-Cyfrl3wx.js               6.22 kB │ gzip:   2.59 kB
dist/assets/diagram-ODIL2UCW-C883OScv.js                  8.12 kB │ gzip:   3.64 kB
dist/assets/cynefinDiagram-WF24UDRP-uhWS_-sH.js           9.94 kB │ gzip:   3.51 kB
dist/assets/chunk-ZCHMQSOR-Cum5L5P2.js                   10.38 kB │ gzip:   4.32 kB
dist/assets/diagram-PFBEJUXE-BHt-SPsJ.js                 10.92 kB │ gzip:   4.26 kB
dist/assets/chunk-HNE4Q36P-Ikb8Lgl6.js                   14.84 kB │ gzip:   4.19 kB
dist/assets/chunk-2E7WHVMD-C4ozilzI.js                   15.64 kB │ gzip:   4.35 kB
dist/assets/diagram-CBK3MWTC-CYBrjtHj.js                 15.75 kB │ gzip:   5.52 kB
dist/assets/mermaid-parser.core-BdUv3KWg.js              16.44 kB │ gzip:   3.91 kB
dist/assets/ishikawaDiagram-HPEHV2GE-C3Jeu_he.js         17.30 kB │ gzip:   6.53 kB
dist/assets/kanban-definition-FNSA4HC5-CQf78z_q.js       20.26 kB │ gzip:   7.15 kB
dist/assets/sankeyDiagram-SY24JHO5-B8XU-KCX.js           22.79 kB │ gzip:   8.26 kB
dist/assets/journeyDiagram-BOSHW7O7-BFJTap6V.js          23.15 kB │ gzip:   8.16 kB
dist/assets/mindmap-definition-6OY57UG3-BBm6BQIg.js      23.66 kB │ gzip:   8.06 kB
dist/assets/graphlib-DS17s2tU.js                         23.90 kB │ gzip:   8.31 kB
dist/assets/wardleyDiagram-IVAIDKWA-DROFFeBz.js          25.20 kB │ gzip:   6.54 kB
dist/assets/rough.esm-Dy-Kn_BL.js                        27.10 kB │ gzip:   8.85 kB
dist/assets/gitGraphDiagram-PDYL7XHY-CEDp_Ccy.js         29.01 kB │ gzip:   8.55 kB
dist/assets/timeline-definition-JXYKGLGB-ZN5ZwZXU.js     30.45 kB │ gzip:  10.03 kB
dist/assets/erDiagram-KYQIGQAA-B7mtctzv.js               30.65 kB │ gzip:  10.57 kB
dist/assets/chunk-7S6XSTFO-DSgkMnLB.js                   30.75 kB │ gzip:   8.51 kB
dist/assets/requirementDiagram-EQYSW5RA-C2rKxBXi.js      31.07 kB │ gzip:   9.82 kB
dist/assets/quadrantDiagram-D57K4MC3-Qih4QQud.js         33.52 kB │ gzip:   9.74 kB
dist/assets/chunk-WQQL4CDK-DmqXdiM_.js                   37.88 kB │ gzip:   8.20 kB
dist/assets/vennDiagram-Q3Y3IDCW-DKfkKLdx.js             41.18 kB │ gzip:  15.11 kB
dist/assets/stateDiagram-v2-A6IESKWZ-DGu8AAEY.js         41.55 kB │ gzip:  13.89 kB
dist/assets/blockDiagram-RJAE7QA3-BqdXrQVg.js            42.44 kB │ gzip:  13.87 kB
dist/assets/xychartDiagram-4URNHDU4-BOFlyiOL.js          44.52 kB │ gzip:  12.35 kB
dist/assets/src-DugTsRdb.js                              45.66 kB │ gzip:  15.99 kB
dist/assets/dagre-NK4GIZVX-DGc4UDtC.js                   47.83 kB │ gzip:  17.11 kB
dist/assets/classDiagram-v2-4MYWR3UA-CGpjJo8U.js         49.70 kB │ gzip:  16.15 kB
dist/assets/chunk-AQDTSKZB-C5l15PjR.js                   51.23 kB │ gzip:  16.63 kB
dist/assets/chunk-NQOKRVIF-LYyhVl2-.js                   62.79 kB │ gzip:  20.36 kB
dist/assets/c4Diagram-XDPPPE54-DoNsjc2T.js               65.08 kB │ gzip:  18.60 kB
dist/assets/ganttDiagram-R7GPNTJY-UnOkXN6b.js            70.01 kB │ gzip:  23.01 kB
dist/assets/diagram-TYUNFSNR-D_x2POsh.js                 80.45 kB │ gzip:  25.15 kB
dist/assets/cose-bilkent-JH36ORCC-DqyIjH5y.js            81.22 kB │ gzip:  21.51 kB
dist/assets/mermaid.core-BRjBX_xe.js                     84.68 kB │ gzip:  29.33 kB
dist/assets/swimlanes-B3ENRKFQ-BzqEsgqy.js              106.44 kB │ gzip:  36.22 kB
dist/assets/chunk-HAGFOTED-DOB_Bveb.js                  115.56 kB │ gzip:  29.27 kB
dist/assets/sequenceDiagram-BLEHNHQU-DITh20AA.js        117.67 kB │ gzip:  31.37 kB
dist/assets/architectureDiagram-ZHVYKT53-DPe_3DQz.js    148.87 kB │ gzip:  41.10 kB
dist/assets/usecaseDiagram-WPOLBNNX-C6-xBmeu.js         187.90 kB │ gzip:  49.20 kB
dist/assets/chunk-DSNLSHJZ-C8UE-88Y.js                  241.36 kB │ gzip:  40.31 kB
dist/assets/katex-B_JcIwqj.js                           258.80 kB │ gzip:  77.65 kB
dist/assets/cytoscape.esm-BegBNzOV.js                   434.75 kB │ gzip: 137.75 kB
dist/assets/index-BHBTj_hJ.js                           622.98 kB │ gzip: 205.32 kB
dist/assets/chunk-NGNAAXSQ-C2Wy9Xmz.js                  629.04 kB │ gzip: 127.32 kB
dist/assets/echarts-9c1FOp5B.js                       1,124.20 kB │ gzip: 373.58 kB
dist/assets/elk-QONTBCTQ-DcoRmCwb.js                  1,462.89 kB │ gzip: 455.85 kB

✓ built in 909ms
[plugin builtin:vite-reporter] 
(!) Some chunks are larger than 500 kB after minification. Consider:
- Using dynamic import() to code-split the application
- Use build.rolldownOptions.output.codeSplitting to improve chunking: https://rolldown.rs/reference/OutputOptions.codeSplitting
- Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.
结果：通过

### 后端市场探针（临时 HOME + file:// 索引：列表 / 安装落盘 / 400·404·409 / 日志）

```bash
market_api_probe
```

内部：起宿主 → GET 市场列表 → POST 安装 market-probe → 校验落盘、插件列表与 plugin.log → 依次触发 sha256 不符、size 不符、未知 id、重复安装，断言状态码与中文 detail 且失败不落盘。

夹具：/var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.Uqudko4s17/market/index.json
启动宿主：HOME=/var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.Uqudko4s17/home-api port=54208 DESKTOP_PLUGIN_MARKET_URL=file:///var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.Uqudko4s17/market/index.json
✓ GET /api/desktop/plugin-market 返回 enabled/source/条目/已安装映射
✓ POST install market-probe 返回 200 与插件信息（含 settings[]）
✓ 安装包已落到用户插件目录：/var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.Uqudko4s17/home-api/.desktop-app/plugins/market-probe
✓ 插件列表同时含内置 hello-world 与新装的 market-probe
✓ market-bad: HTTP 400 且 detail 含「sha256 校验失败」
✓ market-size: HTTP 400 且 detail 含「大小与索引不一致」
✓ no-such-plugin: HTTP 404 且 detail 含「市场里没有插件」
✓ market-probe: HTTP 409 且 detail 含「」
✓ 校验失败的插件均未落盘
✓ plugin.log 记录了 install_ok
结果：通过

### 市场开关与索引缺失回归（DESKTOP_PLUGIN_MARKET=0 / 索引 404 → 502）

```bash
market_switch_probe
```

内部：起宿主（市场关闭）→ 列表返回 enabled:false 空载荷、安装 400、settings.marketUrl 为空串；再起宿主指向不存在的索引 → 列表 502。

启动宿主：DESKTOP_PLUGIN_MARKET=0（关闭市场）port=54231
✓ DESKTOP_PLUGIN_MARKET=0 时市场返回 enabled:false 空载荷
✓ 关闭开关时安装返回 400「插件市场未启用」
✓ 市场关闭时 /api/desktop/settings 的 marketUrl 为空串
✓ 索引文件缺失时列表返回 502 且 detail 指向插件索引
结果：通过

### CLI 探针（plugin_market.py list / install / entry / verify）

```bash
market_cli_probe
```

内部：隔离 HOME 运行 CLI，断言 list 含条目、install 落盘、entry 生成索引条目、verify 对正确/错误 sha256 的退出码。

✓ CLI list 列出市场条目：
    市场源：file:///var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.Uqudko4s17/market/index.json
    - market-probe  v0.1.0  [未安装]  1 KB  市场探针
        市场验证探针
    - market-bad  v0.1.0  [未安装]  1 KB  sha 错误探针
        sha256 故意写错
    - market-size  v0.1.0  [未安装]  0 KB  大小错误探针
        size 故意写错
✓ CLI install 把 market-probe 装进了隔离 HOME：已安装：market-probe v0.1.0 → /var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.Uqudko4s17/home-cli/.desktop-app/plugins/market-probe
✓ CLI entry 从 zip 生成索引条目（id/sha256/size/permissions）
✓ CLI verify 对正确 sha256 退出码 0
✓ CLI verify 对错误 sha256 退出码非 0
结果：通过

### 浏览器级探针（临时 HOME + file:// 索引 + 无头 Chrome/CDP：设置页市场区块 → 点安装 → 已安装标记）

```bash
browser_probe
```

内部：打开 `#/settings` → 等「插件市场」区块与条目 → 断言已安装标记 → 点「安装」→ 等条目变已安装、应用管理出现新插件 → 校验落盘与 plugin.log；探针脚本见 `/var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.Uqudko4s17/cdp_market.py`，页面快照见 `/var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.Uqudko4s17/settings.html`。

浏览器：/Applications/Google Chrome.app/Contents/MacOS/Google Chrome
夹具：/var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.Uqudko4s17/market-browser/index.json
启动宿主：HOME=/var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.Uqudko4s17/home-browser port=54257 DESKTOP_PLUGIN_MARKET_URL=file:///var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.Uqudko4s17/market-browser/index.json
✓ 设置页「插件市场」区块渲染出索引条目「市场探针」
✓ 市场区块用「已安装」标记区分本机已有插件
✓ 点击「安装」后市场区块自动刷新（条目变为已安装）
✓ 应用管理列表出现刚安装的「市场探针」
✓ 界面安装后插件目录已落盘：market-probe
✓ plugin.log 记录了界面触发的 install_ok
结果：通过

### Harness 审计（本次新增无 ERROR）

```bash
python3 tools/harness/audit.py
```

ERROR  2026-10-20-personal-knowledge-base: v2 request 缺少 verify.md
ERROR  2026-10-21-desktop-plugin-market: v2 request 缺少 verify.md

v2 requests: 27  存量跳过: 59  ERROR: 2  WARN: 0

（预期：本 request 的 verify.md 由本次运行生成，审计运行时它尚不存在。）
其余 ERROR（与本 request 无关，见「未执行项与原因」）：
ERROR  2026-10-20-personal-knowledge-base: v2 request 缺少 verify.md
结果：通过（本 request 未新增其它 ERROR）

## 未执行项与原因

- 真实线上市场：默认索引地址指向 `https://raw.githubusercontent.com/xingwenl/xxai/main/apps/desktop/market/index.json`，本次提交尚未推送，因此线上 raw 地址还取不到文件；脚本用 `file://` 索引覆盖了同一套解析与安装链路，**「推送到 main 后线上地址是否可读」未验证**。
- 真机 GUI：在 pywebview 窗口里观察市场区块的视觉、安装按钮手感与安装成功提示——需要 macOS 图形会话与人工目视；脚本用无头 Chrome + CDP 断言了区块文本、点击安装、已安装标记与应用列表更新。
- 前端没有测试框架：市场区块的渲染分支（未启用 / 读取中 / 错误重试 / 空索引 / 已安装）中，未启用与错误态只由后端探针覆盖语义，没有前端单测。
- 未验证「索引里插件版本高于本机已装版本」的升级场景：当前市场只做首次安装，已安装同名插件直接 409（不做覆盖/升级）。
- 未验证 20 MiB / 200 条目 / 256 KiB 索引上限的真实边界（单测用较小体积断言逻辑，没有生成超大包）。
- 未验证代理、TLS 证书异常、重定向等网络细节：`_read_url` 只做了超时与大小上限，真实 HTTPS 下载链路未在脚本里跑过。
- 审计可能仍报告工作区中他人未提交 request 的 ERROR（如 `2026-10-20-personal-knowledge-base` 缺 verify.md），与本 request 无关。
- Harness 审计还报出以下 ERROR，均指向工作区中他人未提交的 request，与本 request 无关：
  - ERROR  2026-10-20-personal-knowledge-base: v2 request 缺少 verify.md
- Windows / Linux：本机只有 macOS 环境，未在其它平台执行。

## 验收结论

- 已由单测证明：索引解析与小写化、9 类非法索引被拒、外部 http 被拒/回环 http 允许、300 秒缓存与 `refresh` 强制重取、`is_enabled` 环境语义、`read_archive_manifest` 的根/单层包装与坏包拒绝、`install_entry` 的 size 与 sha256 校验、HTTP 列表/关闭/缺索引 502/坏索引 400/安装落盘/sha256 失败 400/manifest id 不一致 400/未知 id 404/重复安装 409。
- 已由前端构建证明：`tsc` 类型检查与 `vite build` 通过（含新增的市场 API 类型、设置页市场区块）。
- 已由后端探针证明：临时 HOME 下市场列表返回索引条目与本机已安装映射；安装 market-probe 后用户插件目录落盘、插件列表可见、plugin.log 有 install_ok；sha256 不符 / size 不符 / 未知 id / 重复安装分别返回 400/400/404/409 且失败不落盘；关闭市场时列表空载荷、安装 400、settings.marketUrl 为空；索引缺失时列表 502。
- 已由 CLI 探针证明：隔离 HOME 下 `list`/`install`/`entry`/`verify` 四个子命令行为符合预期（含错误 sha256 的非 0 退出码）。
- 已由浏览器级探针证明：设置页「插件市场」区块渲染索引条目、内置插件显示已安装标记、点「安装」后区块自动刷新且应用管理列表出现新插件、落盘与 install_ok 日志成立。
- 尚未证明：线上 raw 索引的真实可读性（提交未推送）、真窗口视觉、已安装插件的版本升级、20 MiB/200 条等上限的真实边界、HTTPS 代理与重定向（见上「未执行项」）。因此本脚本退出码为 3（有未执行项），不能视为已完成人工联调。
