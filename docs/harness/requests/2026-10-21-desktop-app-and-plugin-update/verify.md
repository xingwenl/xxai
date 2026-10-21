---
source: script
request: 2026-10-21-desktop-app-and-plugin-update
ranAt: "2026-10-21 17:05:26 CST"
exitCode: 0
---

## 已执行的命令与结果

### 版本比较单测

```bash
( cd /Users/lixingwen/xw/study/ai-base/apps/desktop && /Users/lixingwen/xw/study/ai-base/apps/desktop/.venv/bin/python -m pytest tests/test_version.py -q )
```

..................                                                       [100%]
18 passed in 0.01s
结果：通过

### apps/desktop 全量测试

```bash
( cd /Users/lixingwen/xw/study/ai-base/apps/desktop && /Users/lixingwen/xw/study/ai-base/apps/desktop/.venv/bin/python -m pytest tests/ -q )
```

........................................................................ [ 19%]
........................................................................ [ 39%]
........................................................................ [ 59%]
........................................................................ [ 79%]
........................................................................ [ 99%]
..                                                                       [100%]
=============================== warnings summary ===============================
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
  /Users/lixingwen/xw/study/ai-base/apps/desktop/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
362 passed, 1 warning in 2.08s
结果：通过

### 插件升级端到端（临时 HOME + file:// 索引）

```bash
plugin_upgrade_probe
```

/var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.btmVUpgicQ/plugin-market
✓ 升级成功：版本/内容换新、数据与状态保留、旧版本备份、无临时残留
✓ 错误语义：同版本 400、未安装 404、坏包 400 且本机版本不变
结果：通过

### 宿主更新端到端（临时 HOME + file:// 清单 + 镜像回退）

```bash
# 主源指向不可达路径、镜像指向 file:// 清单，验证回退与下载校验
```

/var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.btmVUpgicQ/app-update
✓ GET /api/desktop/app-update 走镜像回退拿到清单： 9.9.9
✓ 下载校验落盘、downloadedPath 回填、reveal 打开固定目录
✓ 坏 sha 返回 400 且不残留文件
结果：通过

### scripts/make_release.py（打包 / 清单 / 版本一致性）

```bash
make_release_probe
```

✓ 三处版本号一致：1.2.3
清单文件: releases/latest.json
⚠ 清单文件还不存在，首次发版会创建
✓ 三处版本号一致：1.2.3
打包 WW → dist/releases/WW-1.2.3-macos-arm64.zip
✓ 产物：/private/var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.btmVUpgicQ/fakeproj/dist/releases/WW-1.2.3-macos-arm64.zip
  sha256: 84eab1aca1d545c3abeb04c77501858b94eb052c12030fd768bb96eee2a97f18
  size:   136
✓ 清单已更新：releases/latest.json（latest=1.2.3）

下一步：
  1. 上传 WW-1.2.3-macos-arm64.zip 到 GitHub Release（tag desktop-v1.2.3）
  2. 同步到 Gitee Release（镜像清单与安装包，GitHub 不可达时宿主会回退）
  3. 提交 releases/latest.json 与版本号变更，再推送 main 分支
✓ 打包出 WW-1.2.3-macos-arm64.zip，清单 sha256/size/url/mirrors 一致、可执行位保留
✓ 版本号漂移被 --check-only 拦截
结果：通过

### 仓库内 make_release.py --check-only

```bash
( cd /Users/lixingwen/xw/study/ai-base/apps/desktop && /Users/lixingwen/xw/study/ai-base/apps/desktop/.venv/bin/python scripts/make_release.py --check-only )
```

✓ 三处版本号一致：0.2.0
清单文件: releases/latest.json
清单版本号: <空>
平台资产:   <空>
⚠ 清单里还没有任何平台资产，首次发版后由本脚本写入
✓ 清单校验通过
结果：通过

### 前端构建（pnpm build）

```bash
( cd /Users/lixingwen/xw/study/ai-base/apps/desktop/front && pnpm build )
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
dist/assets/index-Du5FL4kO.css                           67.37 kB │ gzip:  13.15 kB
dist/assets/array-BifhSqXX.js                             0.10 kB │ gzip:   0.11 kB
dist/assets/pie-XZMESJXO-B5aTcZxM.js                      0.10 kB │ gzip:   0.12 kB
dist/assets/info-OHQRW6UA-LFE3dweP.js                     0.10 kB │ gzip:   0.12 kB
dist/assets/radar-ABXABTNO-3Zcvl2aj.js                    0.10 kB │ gzip:   0.12 kB
dist/assets/packet-JDAUHWVQ-D1vIHpci.js                   0.11 kB │ gzip:   0.12 kB
dist/assets/cynefin-EF2NZ3EQ-hsnjT74K.js                  0.11 kB │ gzip:   0.12 kB
dist/assets/treemap-SAJKECNS-DoLD97TC.js                  0.11 kB │ gzip:   0.12 kB
dist/assets/wardley-7MLQ67FV-BaTDNlt8.js                  0.11 kB │ gzip:   0.12 kB
dist/assets/gitGraph-VSP46ZUC-DrU0Bva_.js                 0.11 kB │ gzip:   0.12 kB
dist/assets/railroad-I3PHUGI6-BueNFx_9.js                 0.11 kB │ gzip:   0.12 kB
dist/assets/treeView-D4JQ5SDB-C8d3QazL.js                 0.11 kB │ gzip:   0.12 kB
dist/assets/channel-ChnTiK5q.js                           0.11 kB │ gzip:   0.12 kB
dist/assets/railroad-peg-JR7BVNR7-DszWVeE3.js             0.11 kB │ gzip:   0.13 kB
dist/assets/architecture-WOLXFQ4H-D6LUSA5l.js             0.11 kB │ gzip:   0.12 kB
dist/assets/railroad-abnf-LNEFI6M7-CrkHxOJw.js            0.11 kB │ gzip:   0.13 kB
dist/assets/railroad-ebnf-DWYD2UWJ-DUA8iQ76.js            0.11 kB │ gzip:   0.13 kB
dist/assets/eventmodeling-K75KTNOO-HCTYErzO.js            0.11 kB │ gzip:   0.13 kB
dist/assets/init-C-OQMol4.js                              0.14 kB │ gzip:   0.12 kB
dist/assets/chunk-Y2CYZVJY-DsF7k-Jl.js                    0.15 kB │ gzip:   0.14 kB
dist/assets/chunk-2Q5K7J3B-C1jixKkw.js                    0.19 kB │ gzip:   0.16 kB
dist/assets/chunk-JWPE2WC7-DVXcaiue.js                    0.22 kB │ gzip:   0.17 kB
dist/assets/chunk-XXDRQBXY-fETmDeJ7.js                    0.26 kB │ gzip:   0.22 kB
dist/assets/chunk-5VM5RSS4-ZNzvKenW.js                    0.36 kB │ gzip:   0.27 kB
dist/assets/flowDiagram-IUGLLWBU-CodxQcx8.js              0.56 kB │ gzip:   0.31 kB
dist/assets/chunk-VQ5W62QI-DPrfhEMW.js                    0.57 kB │ gzip:   0.40 kB
dist/assets/chunk-J5ZVWO5B-oDCd-gWO.js                    0.63 kB │ gzip:   0.43 kB
dist/assets/infoDiagram-MVDRKAX5-DQHW5_9K.js              0.65 kB │ gzip:   0.41 kB
dist/assets/swimlanesDiagram-AYQRV4AK-S_tWXp6K.js         0.83 kB │ gzip:   0.48 kB
dist/assets/sizeCapture-INFHLROL-3uHXrFqA.js              0.87 kB │ gzip:   0.51 kB
dist/assets/chunk-DUW6YSOI-Dgx8z5s3.js                    0.89 kB │ gzip:   0.46 kB
dist/assets/line-D1s_0rEk.js                              0.94 kB │ gzip:   0.47 kB
dist/assets/ordinal-BDEzSJ7C.js                           1.17 kB │ gzip:   0.56 kB
dist/assets/chunk-ZAUX2LTX-DDEzxlbu.js                    1.41 kB │ gzip:   0.79 kB
dist/assets/railroadDiagram-Y72NRBL7-DW8KCuMJ.js          1.65 kB │ gzip:   0.76 kB
dist/assets/abnfDiagram-WEYOIA3C-Cpift09v.js              1.84 kB │ gzip:   0.89 kB
dist/assets/chunk-UHW7PFBP-BDloBZwp.js                    1.95 kB │ gzip:   0.95 kB
dist/assets/chunk-55XCU76K-hERR7GqH.js                    1.97 kB │ gzip:   0.88 kB
dist/assets/pegDiagram-ECIUJNBX-Bv4xhQjO.js               2.01 kB │ gzip:   0.94 kB
dist/assets/ebnfDiagram-V4P3TTPT-CC5iqG6p.js              2.05 kB │ gzip:   0.89 kB
dist/assets/dist-BJT66xfW.js                              2.16 kB │ gzip:   0.96 kB
dist/assets/path-fybaL0A-.js                              2.27 kB │ gzip:   0.98 kB
dist/assets/arc-CV7nvEYk.js                               3.47 kB │ gzip:   1.46 kB
dist/assets/diagram-I5XIIV2D-D7IbBsL2.js                  4.34 kB │ gzip:   1.89 kB
dist/assets/defaultLocale-BFoDCU3G.js                     4.63 kB │ gzip:   2.12 kB
dist/assets/chunk-4EMNKR2T-W5mPe9To.js                    5.43 kB │ gzip:   2.50 kB
dist/assets/linear-BNnA8FCK.js                            5.51 kB │ gzip:   2.25 kB
dist/assets/chunk-YZO67HFG-CuwNSu2y.js                    5.83 kB │ gzip:   2.68 kB
dist/assets/diagram-RJA3I4VV-DBfBwinn.js                  6.07 kB │ gzip:   2.56 kB
dist/assets/pieDiagram-GNMPY74T-DG4mxeS8.js               6.22 kB │ gzip:   2.59 kB
dist/assets/diagram-ODIL2UCW-BlFsonZx.js                  8.12 kB │ gzip:   3.64 kB
dist/assets/cynefinDiagram-WF24UDRP-iTfADX08.js           9.94 kB │ gzip:   3.51 kB
dist/assets/chunk-ZCHMQSOR-Bi27V9hf.js                   10.38 kB │ gzip:   4.32 kB
dist/assets/diagram-PFBEJUXE-CVkZVqFh.js                 10.92 kB │ gzip:   4.25 kB
dist/assets/chunk-HNE4Q36P-BszjMcid.js                   14.84 kB │ gzip:   4.19 kB
dist/assets/chunk-2E7WHVMD-sATT3Pno.js                   15.64 kB │ gzip:   4.35 kB
dist/assets/diagram-CBK3MWTC-BzoLih0S.js                 15.75 kB │ gzip:   5.52 kB
dist/assets/mermaid-parser.core-CpGjKjCx.js              16.44 kB │ gzip:   3.91 kB
dist/assets/ishikawaDiagram-HPEHV2GE-CFO0EYvH.js         17.30 kB │ gzip:   6.53 kB
dist/assets/kanban-definition-FNSA4HC5-BlnrOkLO.js       20.26 kB │ gzip:   7.15 kB
dist/assets/sankeyDiagram-SY24JHO5-FZkVzCIu.js           22.79 kB │ gzip:   8.25 kB
dist/assets/journeyDiagram-BOSHW7O7-n57X9DnY.js          23.15 kB │ gzip:   8.16 kB
dist/assets/mindmap-definition-6OY57UG3-Bazip6h7.js      23.66 kB │ gzip:   8.06 kB
dist/assets/graphlib-DS17s2tU.js                         23.90 kB │ gzip:   8.31 kB
dist/assets/wardleyDiagram-IVAIDKWA-BhyzyrcF.js          25.20 kB │ gzip:   6.55 kB
dist/assets/rough.esm-Dy-Kn_BL.js                        27.10 kB │ gzip:   8.85 kB
dist/assets/gitGraphDiagram-PDYL7XHY-ClsSN9gG.js         29.01 kB │ gzip:   8.55 kB
dist/assets/timeline-definition-JXYKGLGB-DhfWGwVY.js     30.45 kB │ gzip:  10.03 kB
dist/assets/erDiagram-KYQIGQAA-Ben3U8qq.js               30.65 kB │ gzip:  10.57 kB
dist/assets/chunk-7S6XSTFO-mEWpfyf3.js                   30.75 kB │ gzip:   8.51 kB
dist/assets/requirementDiagram-EQYSW5RA-DVmwt6yz.js      31.07 kB │ gzip:   9.82 kB
dist/assets/quadrantDiagram-D57K4MC3-BzrXlEPD.js         33.52 kB │ gzip:   9.74 kB
dist/assets/chunk-WQQL4CDK-CkbYl6B0.js                   37.88 kB │ gzip:   8.20 kB
dist/assets/vennDiagram-Q3Y3IDCW-BubyFlJn.js             41.18 kB │ gzip:  15.11 kB
dist/assets/stateDiagram-v2-A6IESKWZ-CiPfhDuN.js         41.55 kB │ gzip:  13.89 kB
dist/assets/blockDiagram-RJAE7QA3-C5OgFL-R.js            42.44 kB │ gzip:  13.86 kB
dist/assets/xychartDiagram-4URNHDU4-DinX1uQF.js          44.52 kB │ gzip:  12.35 kB
dist/assets/src-CXoRU3Tk.js                              45.66 kB │ gzip:  15.99 kB
dist/assets/dagre-NK4GIZVX-DwZF3WAf.js                   47.83 kB │ gzip:  17.10 kB
dist/assets/classDiagram-v2-4MYWR3UA-C2IJtjBT.js         49.70 kB │ gzip:  16.15 kB
dist/assets/chunk-AQDTSKZB-D-DbPVNB.js                   51.23 kB │ gzip:  16.63 kB
dist/assets/chunk-NQOKRVIF-CjdhA5BL.js                   62.79 kB │ gzip:  20.36 kB
dist/assets/c4Diagram-XDPPPE54-OPZF2x3U.js               65.08 kB │ gzip:  18.61 kB
dist/assets/ganttDiagram-R7GPNTJY-CANzPCZD.js            70.01 kB │ gzip:  23.01 kB
dist/assets/diagram-TYUNFSNR-Bp9Qw8xj.js                 80.45 kB │ gzip:  25.14 kB
dist/assets/cose-bilkent-JH36ORCC-CPT_58DU.js            81.22 kB │ gzip:  21.51 kB
dist/assets/mermaid.core-B8IBlSuo.js                     84.68 kB │ gzip:  29.32 kB
dist/assets/swimlanes-B3ENRKFQ-BaCGyMmq.js              106.44 kB │ gzip:  36.22 kB
dist/assets/chunk-HAGFOTED-BjrzM46R.js                  115.56 kB │ gzip:  29.27 kB
dist/assets/sequenceDiagram-BLEHNHQU-DOOln4-U.js        117.67 kB │ gzip:  31.37 kB
dist/assets/architectureDiagram-ZHVYKT53-DOz7ixQ6.js    148.87 kB │ gzip:  41.10 kB
dist/assets/usecaseDiagram-WPOLBNNX-2NiSKvIo.js         187.90 kB │ gzip:  49.20 kB
dist/assets/chunk-DSNLSHJZ-CtV5rh3f.js                  241.36 kB │ gzip:  40.31 kB
dist/assets/katex-B_JcIwqj.js                           258.80 kB │ gzip:  77.65 kB
dist/assets/cytoscape.esm-BegBNzOV.js                   434.75 kB │ gzip: 137.75 kB
dist/assets/index-Bn0mAk0c.js                           628.56 kB │ gzip: 206.59 kB
dist/assets/chunk-NGNAAXSQ-C2Wy9Xmz.js                  629.04 kB │ gzip: 127.32 kB
dist/assets/echarts-CNcUJtm3.js                       1,124.20 kB │ gzip: 373.58 kB
dist/assets/elk-QONTBCTQ-CKk4yOJ8.js                  1,462.89 kB │ gzip: 455.85 kB

✓ built in 884ms
[plugin builtin:vite-reporter] 
(!) Some chunks are larger than 500 kB after minification. Consider:
- Using dynamic import() to code-split the application
- Use build.rolldownOptions.output.codeSplitting to improve chunking: https://rolldown.rs/reference/OutputOptions.codeSplitting
- Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.
结果：通过

### Harness audit

```bash
/Users/lixingwen/xw/study/ai-base/apps/desktop/.venv/bin/python tools/harness/audit.py
```

ERROR  2026-10-20-personal-knowledge-base: v2 request 缺少 verify.md

v2 requests: 30  存量跳过: 59  ERROR: 1  WARN: 0

注：以上 ERROR 均与本 request 无关（仓库其他 request 缺少 verify.md），按「无新增 ERROR」判定通过。
结果：通过

## 未执行项与原因

- Harness audit 仍报与本 request 无关的既有 ERROR（仓库其他 request 缺少 verify.md），未纳入本次验收，也未在本脚本内修别人的 request。

## 验收结论

- 版本比较单测与 apps/desktop 全量测试：通过（见上）。
- 插件升级链路：通过（hasUpdate 标记、备份、plugin-data 保留、同版本 400 / 未安装 404 / 坏包 400 且不破坏本机版本）。
- 宿主更新链路：通过（镜像回退、下载后 size/sha256 校验、坏包 400 且不覆盖已下载安装包、downloadedPath 回填）。
- make_release.py：通过（打包、清单 sha256/size/url/mirrors、可执行位、版本漂移拦截）。
- 前端构建：见上方结果；Harness audit：本 request 无新增 ERROR。
- 剩余风险：未在真实 GitHub/Gitee 网络环境跑过发布与下载（夹具用 file:// 替代）；未在 Windows / Linux 真机验证安装包替换。
- 脚本退出码：0
