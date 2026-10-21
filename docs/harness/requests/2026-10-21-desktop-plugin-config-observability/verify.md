---
source: script
request: 2026-10-21-desktop-plugin-config-observability
ranAt: "2026-10-21 12:04:39 CST"
exitCode: 3
---

## 已执行的命令与结果

### 后端单测全绿（含新增 plugin_config 用例）

```bash
cd apps/desktop && .venv/bin/python -m pytest tests/ -q
```

........................................................................ [ 27%]
........................................................................ [ 54%]
........................................................................ [ 82%]
..............................................                           [100%]
=============================== warnings summary ===============================
.venv/lib/python3.12/site-packages/fastapi/testclient.py:1
  /Users/lixingwen/xw/study/ai-base/apps/desktop/.venv/lib/python3.12/site-packages/fastapi/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
    from starlette.testclient import TestClient as TestClient  # noqa

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
262 passed, 1 warning in 1.47s
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
✓ 2736 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                                           0.39 kB │ gzip:   0.26 kB
dist/assets/index-CEAvDUPv.css                           64.02 kB │ gzip:  12.54 kB
dist/assets/array-BifhSqXX.js                             0.10 kB │ gzip:   0.11 kB
dist/assets/pie-XZMESJXO-Db62g6uk.js                      0.10 kB │ gzip:   0.12 kB
dist/assets/info-OHQRW6UA-CUyH6aZV.js                     0.10 kB │ gzip:   0.12 kB
dist/assets/radar-ABXABTNO-H6X7pYTD.js                    0.10 kB │ gzip:   0.12 kB
dist/assets/packet-JDAUHWVQ-CBmeYk37.js                   0.11 kB │ gzip:   0.12 kB
dist/assets/cynefin-EF2NZ3EQ-46TAdInZ.js                  0.11 kB │ gzip:   0.12 kB
dist/assets/treemap-SAJKECNS-H9WZjqHr.js                  0.11 kB │ gzip:   0.12 kB
dist/assets/wardley-7MLQ67FV-DRAM0-n_.js                  0.11 kB │ gzip:   0.12 kB
dist/assets/gitGraph-VSP46ZUC-CawP_P74.js                 0.11 kB │ gzip:   0.12 kB
dist/assets/railroad-I3PHUGI6-DNjSw5XV.js                 0.11 kB │ gzip:   0.12 kB
dist/assets/treeView-D4JQ5SDB-B1wUGpIa.js                 0.11 kB │ gzip:   0.12 kB
dist/assets/channel-CmgdlPZ4.js                           0.11 kB │ gzip:   0.12 kB
dist/assets/railroad-peg-JR7BVNR7-Cfc3HgD1.js             0.11 kB │ gzip:   0.13 kB
dist/assets/architecture-WOLXFQ4H-Bw8n3D8r.js             0.11 kB │ gzip:   0.13 kB
dist/assets/railroad-abnf-LNEFI6M7-BIKlFSuo.js            0.11 kB │ gzip:   0.13 kB
dist/assets/railroad-ebnf-DWYD2UWJ-B-J4kuPE.js            0.11 kB │ gzip:   0.13 kB
dist/assets/eventmodeling-K75KTNOO-Da-BUB64.js            0.11 kB │ gzip:   0.13 kB
dist/assets/init-C-OQMol4.js                              0.14 kB │ gzip:   0.12 kB
dist/assets/chunk-Y2CYZVJY-DsF7k-Jl.js                    0.15 kB │ gzip:   0.14 kB
dist/assets/chunk-2Q5K7J3B-C1jixKkw.js                    0.19 kB │ gzip:   0.16 kB
dist/assets/chunk-JWPE2WC7-DVXcaiue.js                    0.22 kB │ gzip:   0.17 kB
dist/assets/chunk-XXDRQBXY-Ch_pZg_W.js                    0.26 kB │ gzip:   0.22 kB
dist/assets/chunk-5VM5RSS4-ZNzvKenW.js                    0.36 kB │ gzip:   0.27 kB
dist/assets/flowDiagram-IUGLLWBU-DOu4nshx.js              0.56 kB │ gzip:   0.31 kB
dist/assets/chunk-VQ5W62QI-D01VDxu8.js                    0.57 kB │ gzip:   0.40 kB
dist/assets/chunk-J5ZVWO5B-oDCd-gWO.js                    0.63 kB │ gzip:   0.43 kB
dist/assets/infoDiagram-MVDRKAX5-Dcb36lVT.js              0.65 kB │ gzip:   0.41 kB
dist/assets/swimlanesDiagram-AYQRV4AK-DpwfU8i-.js         0.83 kB │ gzip:   0.48 kB
dist/assets/sizeCapture-INFHLROL-3uHXrFqA.js              0.87 kB │ gzip:   0.51 kB
dist/assets/chunk-DUW6YSOI-Dgx8z5s3.js                    0.89 kB │ gzip:   0.46 kB
dist/assets/line-2yyFyQns.js                              0.94 kB │ gzip:   0.47 kB
dist/assets/ordinal-BDEzSJ7C.js                           1.17 kB │ gzip:   0.56 kB
dist/assets/chunk-ZAUX2LTX-DGKIYEGd.js                    1.41 kB │ gzip:   0.79 kB
dist/assets/railroadDiagram-Y72NRBL7-DHcPokNw.js          1.65 kB │ gzip:   0.76 kB
dist/assets/abnfDiagram-WEYOIA3C-BRaWUq3h.js              1.84 kB │ gzip:   0.89 kB
dist/assets/chunk-UHW7PFBP-DH1TVO9t.js                    1.95 kB │ gzip:   0.95 kB
dist/assets/chunk-55XCU76K-D_yVN7SU.js                    1.97 kB │ gzip:   0.88 kB
dist/assets/pegDiagram-ECIUJNBX-nJHEPaAS.js               2.01 kB │ gzip:   0.94 kB
dist/assets/ebnfDiagram-V4P3TTPT-DKhyxW0E.js              2.05 kB │ gzip:   0.89 kB
dist/assets/dist-CPNN1oTm.js                              2.16 kB │ gzip:   0.96 kB
dist/assets/path-fybaL0A-.js                              2.27 kB │ gzip:   0.98 kB
dist/assets/arc-kB5lQwpG.js                               3.47 kB │ gzip:   1.46 kB
dist/assets/diagram-I5XIIV2D-DnwRAb-J.js                  4.34 kB │ gzip:   1.89 kB
dist/assets/defaultLocale-BFoDCU3G.js                     4.63 kB │ gzip:   2.12 kB
dist/assets/chunk-4EMNKR2T-Bas2UHYa.js                    5.43 kB │ gzip:   2.49 kB
dist/assets/linear-DtuKCBK8.js                            5.51 kB │ gzip:   2.25 kB
dist/assets/chunk-YZO67HFG-CclXn3rq.js                    5.83 kB │ gzip:   2.68 kB
dist/assets/diagram-RJA3I4VV-BmXh39cs.js                  6.07 kB │ gzip:   2.57 kB
dist/assets/pieDiagram-GNMPY74T-Dn_Ew2IF.js               6.22 kB │ gzip:   2.60 kB
dist/assets/diagram-ODIL2UCW--6zivgk1.js                  8.12 kB │ gzip:   3.64 kB
dist/assets/cynefinDiagram-WF24UDRP-aUbXG0Nw.js           9.94 kB │ gzip:   3.51 kB
dist/assets/chunk-ZCHMQSOR-vNxFWP3S.js                   10.38 kB │ gzip:   4.32 kB
dist/assets/diagram-PFBEJUXE-DgSAnGhm.js                 10.92 kB │ gzip:   4.26 kB
dist/assets/chunk-HNE4Q36P-BEfPy6jk.js                   14.84 kB │ gzip:   4.19 kB
dist/assets/chunk-2E7WHVMD-ot5XYbb4.js                   15.64 kB │ gzip:   4.35 kB
dist/assets/diagram-CBK3MWTC-Z7zOV8xv.js                 15.75 kB │ gzip:   5.52 kB
dist/assets/mermaid-parser.core-DuFE3OjL.js              16.44 kB │ gzip:   3.92 kB
dist/assets/ishikawaDiagram-HPEHV2GE-CPZx9yyJ.js         17.30 kB │ gzip:   6.53 kB
dist/assets/kanban-definition-FNSA4HC5-YTxzrC5B.js       20.26 kB │ gzip:   7.15 kB
dist/assets/sankeyDiagram-SY24JHO5-Dik7WMkY.js           22.79 kB │ gzip:   8.25 kB
dist/assets/journeyDiagram-BOSHW7O7-D_fEigDJ.js          23.15 kB │ gzip:   8.16 kB
dist/assets/mindmap-definition-6OY57UG3-UogrcS8_.js      23.66 kB │ gzip:   8.06 kB
dist/assets/graphlib-DS17s2tU.js                         23.90 kB │ gzip:   8.31 kB
dist/assets/wardleyDiagram-IVAIDKWA-BNuHZLka.js          25.20 kB │ gzip:   6.55 kB
dist/assets/rough.esm-Dy-Kn_BL.js                        27.10 kB │ gzip:   8.85 kB
dist/assets/gitGraphDiagram-PDYL7XHY-BM0M1BsC.js         29.01 kB │ gzip:   8.55 kB
dist/assets/timeline-definition-JXYKGLGB-CgthCsxi.js     30.45 kB │ gzip:  10.03 kB
dist/assets/erDiagram-KYQIGQAA-DJ9sZY5h.js               30.65 kB │ gzip:  10.57 kB
dist/assets/chunk-7S6XSTFO-DZbQOF83.js                   30.75 kB │ gzip:   8.51 kB
dist/assets/requirementDiagram-EQYSW5RA-BS2VZaG3.js      31.07 kB │ gzip:   9.82 kB
dist/assets/quadrantDiagram-D57K4MC3-BE1QkTYn.js         33.52 kB │ gzip:   9.74 kB
dist/assets/chunk-WQQL4CDK-ixMvEmze.js                   37.88 kB │ gzip:   8.20 kB
dist/assets/vennDiagram-Q3Y3IDCW-5HY91YmY.js             41.18 kB │ gzip:  15.12 kB
dist/assets/stateDiagram-v2-A6IESKWZ-CsCNHPpu.js         41.55 kB │ gzip:  13.89 kB
dist/assets/blockDiagram-RJAE7QA3-BoSa2oAw.js            42.44 kB │ gzip:  13.86 kB
dist/assets/xychartDiagram-4URNHDU4-LMap7i6Z.js          44.52 kB │ gzip:  12.35 kB
dist/assets/src-C4Yaa4Cx.js                              45.66 kB │ gzip:  15.99 kB
dist/assets/dagre-NK4GIZVX-2RZmfpg6.js                   47.83 kB │ gzip:  17.11 kB
dist/assets/classDiagram-v2-4MYWR3UA-DRBBd_77.js         49.70 kB │ gzip:  16.16 kB
dist/assets/chunk-AQDTSKZB-CUxNEJ-z.js                   51.23 kB │ gzip:  16.64 kB
dist/assets/chunk-NQOKRVIF-cwURmWWL.js                   62.79 kB │ gzip:  20.36 kB
dist/assets/c4Diagram-XDPPPE54-WA7zOoCU.js               65.08 kB │ gzip:  18.60 kB
dist/assets/ganttDiagram-R7GPNTJY-zg3xY_c-.js            70.01 kB │ gzip:  23.01 kB
dist/assets/diagram-TYUNFSNR-C_sTE84S.js                 80.45 kB │ gzip:  25.15 kB
dist/assets/cose-bilkent-JH36ORCC-DRlydHxp.js            81.22 kB │ gzip:  21.51 kB
dist/assets/mermaid.core-FMPInHX3.js                     84.68 kB │ gzip:  29.32 kB
dist/assets/swimlanes-B3ENRKFQ-CMkMozmC.js              106.44 kB │ gzip:  36.22 kB
dist/assets/chunk-HAGFOTED-vm2gV4j0.js                  115.56 kB │ gzip:  29.27 kB
dist/assets/sequenceDiagram-BLEHNHQU-QsadbTgW.js        117.67 kB │ gzip:  31.37 kB
dist/assets/architectureDiagram-ZHVYKT53-B1DNJ6af.js    148.87 kB │ gzip:  41.10 kB
dist/assets/usecaseDiagram-WPOLBNNX-Cl6ykJ5m.js         187.90 kB │ gzip:  49.21 kB
dist/assets/chunk-DSNLSHJZ-CXF4HKBt.js                  241.36 kB │ gzip:  40.31 kB
dist/assets/katex-B_JcIwqj.js                           258.80 kB │ gzip:  77.65 kB
dist/assets/cytoscape.esm-BegBNzOV.js                   434.75 kB │ gzip: 137.75 kB
dist/assets/index-CLL19ks6.js                           601.19 kB │ gzip: 199.57 kB
dist/assets/chunk-NGNAAXSQ-C2Wy9Xmz.js                  629.04 kB │ gzip: 127.32 kB
dist/assets/echarts-Bp-k6mue.js                       1,124.20 kB │ gzip: 373.58 kB
dist/assets/elk-QONTBCTQ-BUOVLY3g.js                  1,462.89 kB │ gzip: 455.85 kB

✓ built in 737ms
[plugin builtin:vite-reporter] 
(!) Some chunks are larger than 500 kB after minification. Consider:
- Using dynamic import() to code-split the application
- Use build.rolldownOptions.output.codeSplitting to improve chunking: https://rolldown.rs/reference/OutputOptions.codeSplitting
- Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.
结果：通过

### 浏览器级探针（临时 HOME + 无头 Chrome/CDP：配置表单 → 保存落盘 → 运行中 iframe 实时更新 → 事件日志）

```bash
browser_probe
```

内部依次：HTTP 保存配置并核对落盘 / 非法值 400 / 首页点击卡片打开插件页读配置 / 切到设置页点开表单 / 改值保存 / 核对 iframe 实时收到新值 / 核对 plugin.log；探针脚本见 `/var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.w3Eg69Gf7t/cdp_check.py`。

浏览器：/Applications/Google Chrome.app/Contents/MacOS/Google Chrome
启动宿主：HOME=/var/folders/lr/0c65dm215n36_2_m8nt6fpnm0000gn/T/tmp.w3Eg69Gf7t/home port=51720
✓ 插件列表带 settings[]：demo-settings 三项、hello-world 三项、bookmarks-organizer 为空
✓ 配置已原子落盘：{"greeting":"验证问候","refresh":12,"verbose":true}
✓ 非法值返回 400 且未覆盖已保存配置（detail：{"detail":"配置项「刷新间隔」不能大于 300.0（当前 999）"}）
✓ 插件页 iframe 通过 settings.getConfig() 读到宿主配置：「验证问候」
✓ 点击「配置」后展开 settings[] 表单：问候语 / 首页问候语 / 刷新间隔 / 详细日志
✓ 只有声明 settings[] 的插件有配置入口（hello-world + demo-settings），展开后按钮变为「收起配置」
✓ 设置页保存后，运行中的插件 iframe 通过 settings.onChanged 立即收到「实时问候」
✓ 设置页保存后配置落盘：{"greeting":"实时问候","refresh":12,"verbose":true}
✓ plugin.log 含 config_saved / iframe_load / sdk_injected：
{"ts": "2026-10-21T04:04:35.329186+00:00", "plugin": "demo-settings", "event": "config_saved", "keys": "greeting,refresh,verbose"}
{"ts": "2026-10-21T04:04:38.225055+00:00", "plugin": "demo-settings", "event": "iframe_load", "detail": "/apps/demo-settings/index.html"}
{"ts": "2026-10-21T04:04:38.226171+00:00", "plugin": "demo-settings", "event": "sdk_injected"}
{"ts": "2026-10-21T04:04:38.665594+00:00", "plugin": "demo-settings", "event": "config_saved", "keys": "greeting,refresh,verbose"}
✓ 日志只记键名，不含配置值
结果：通过

### Harness 审计（本次新增无 ERROR）

```bash
python3 tools/harness/audit.py
```

ERROR  2026-10-20-personal-knowledge-base: v2 request 缺少 verify.md

v2 requests: 24  存量跳过: 59  ERROR: 1  WARN: 0

其余 ERROR（与本 request 无关，见「未执行项与原因」）：
ERROR  2026-10-20-personal-knowledge-base: v2 request 缺少 verify.md
结果：通过（本 request 未新增其它 ERROR）

## 未执行项与原因

- 真机 GUI：在 pywebview 窗口里打开设置页、展开「配置」、改动并保存、观察控件外观与交互手感——需要 macOS 图形会话与人工目视。脚本用无头 Chrome + CDP 复现了同一条链路（插件页 iframe → 设置页 → 保存 → onChanged 实时更新）并断言了 DOM 文本，但没有在真窗口里目视确认视觉与手感。
- 前端没有测试框架：设置页配置表单与运行态徽章的渲染由浏览器级探针做 DOM 断言覆盖，没有组件单测覆盖 `renderConfigField` 的全部分支（number 空值、select 选项、boolean 勾选）。
- 运行态徽章的失败分支：探针只覆盖了「运行中」徽章，没有构造一个 `sdk_inject_failed` 场景去目视「运行失败：原因」的展示。
- `tests/test_host_api.py` 的 `test_macos_open_*` 用例属于工作区中他人未提交的 WIP，其文件顶部缺 `import subprocess`；本次运行前已临时补该行（不随本 request 提交），因此全量 pytest 通过。在纯净 HEAD 上该用例不存在。
- Harness 审计还报出以下 ERROR，均指向工作区中他人未提交的 request，与本 request 无关：
  - ERROR  2026-10-20-personal-knowledge-base: v2 request 缺少 verify.md
- Windows / Linux：本机只有 macOS 环境，未在其它平台执行。

## 验收结论

- 已由单测证明：`settings[]` 的六类非法声明（非法 key、number 默认布尔、select 缺候选项、select 默认值不在候选项、min>max、text 带 max/text 默认值非字符串、boolean 默认值非布尔）在加载期被 pydantic 拒绝；默认值合并会丢弃未声明键；`validate_values` 一次性返回全部中文错因；配置以紧凑 JSON + 原子替换落 `plugin-config/<id>.json`，坏文件与非法插件 id 被拒；HTTP 端点返回默认值、保存后日志出现 `config_saved` 且只含键名、非法提交 400 且不覆盖、插件停用期间仍可读写配置；`plugin.log` 是 JSONL、detail 截断到 4096 字符、超 1 MiB 轮转、未知事件名被拒、非法插件 id 归一为 `unknown`；内置 `hello-world` 声明了三项 `settings[]`。
- 已由前端构建证明：`tsc` 类型检查与 `vite build` 通过（包含新增的 `runtime-status.ts`、`PluginSetting` 类型、`getPluginConfig`/`savePluginConfig`/`logPluginEvent`）。
- 已由浏览器级探针证明：临时 HOME 下的宿主设置页点开「配置」后展开 `settings[]` 表单（问候语 / 描述 / 刷新间隔 / 详细日志），且只有声明了 `settings[]` 的插件才有该按钮；插件 iframe 用 `getConfig()` 读到已保存配置；在设置页改值并保存后，宿主广播使**运行中的 iframe** 通过 `onChanged` 立即收到新值；保存经 HTTP 与设置页两条路径都原子落盘，非法值 400 且不覆盖；`plugin.log` 含 `config_saved` / `iframe_load` / `sdk_injected`，且不记录配置值。
- 尚未证明：真窗口里的视觉与手感、运行失败徽章的展示（见上「未执行项」），以及 Windows / Linux 平台。因此本脚本退出码为 3（有未执行项），不能视为已完成人工联调。
- 已知边界：宿主所有插件接口同源，任意被注入 SDK 的 iframe 理论上可调其它插件的 config 端点——与既有 `plugin-data` 端点同级，本刀未新增提权面（spec「已知限制」）。
