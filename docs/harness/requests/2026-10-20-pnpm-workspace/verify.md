---
source: script
request: 2026-10-20-pnpm-workspace
ranAt: "2026-10-20 17:00:50 CST"
exitCode: 0
---

## 已执行的命令与结果

工作目录：`/Users/lixingwen/xw/study/ai-base`；日期：2026-10-20 17:00:04 CST

### 1. workspace 声明与锁文件

命令：`ls package.json pnpm-workspace.yaml pnpm-lock.yaml`
package.json
pnpm-lock.yaml
pnpm-workspace.yaml

- ✔ 存在 package.json
- ✔ 存在 pnpm-workspace.yaml
- ✔ 存在 pnpm-lock.yaml

命令：`git ls-files | grep pnpm-lock\.yaml`（应只剩根 lockfile）
```text
<无 app 级 pnpm-lock.yaml>
```
- ✔ app 级 pnpm-lock.yaml 已全部删除

命令：`grep -n "xxai-agent" apps/front/package.json apps/shop/package.json`
apps/front/package.json:65:    "xxai-agent": "workspace:*",
apps/shop/package.json:14:    "xxai-agent": "workspace:*"

### 2. 仓库根 pnpm install --frozen-lockfile

```text
apps/ai-sdk prepare: ✓ 111 modules transformed.
apps/ai-sdk prepare: rendering chunks...
apps/ai-sdk prepare: [vite:dts] Start generate declaration files...
apps/ai-sdk prepare: computing gzip size...
apps/ai-sdk prepare: dist/style.css          45.07 kB │ gzip:   8.07 kB
apps/ai-sdk prepare: dist/xxai-agent.es.js  460.06 kB │ gzip: 140.54 kB
apps/ai-sdk prepare: [vite:dts] Declaration files built in 3179ms.
apps/ai-sdk prepare: dist/style.css            45.07 kB │ gzip:   8.07 kB
apps/ai-sdk prepare: dist/xxai-agent.umd.cjs  312.43 kB │ gzip: 115.64 kB
apps/ai-sdk prepare: ✓ built in 4.32s
apps/ai-sdk prepare: Done
Done in 7.7s using pnpm v9.15.9
```

- ✔ 根 install 退出码 0（用时 8s）

### 3. workspace 软链与 SDK 产物

命令：`readlink apps/front/node_modules/xxai-agent`
../../ai-sdk

- ✔ apps/front/node_modules/xxai-agent -> ../../ai-sdk（软链）

命令：`ls -l apps/ai-sdk/dist/xxai-agent.es.js`
-rw-r--r--@ 1 lixingwen  staff  464727 10 20 17:00 apps/ai-sdk/dist/xxai-agent.es.js

- ✔ 根 install 后 SDK dist 存在（prepare 生效）

### 4. 三个 workspace 前端构建

命令：`pnpm --dir apps/front exec vite build`
```text
[plugin builtin:vite-reporter] 
(!) Some chunks are larger than 500 kB after minification. Consider:
- Using dynamic import() to code-split the application
- Use build.rolldownOptions.output.codeSplitting to improve chunking: https://rolldown.rs/reference/OutputOptions.codeSplitting
- Adjust chunk size limit for this warning via build.chunkSizeWarningLimit.
✓ built in 4.16s
```

- ✔ apps/front 构建通过（用时 8s）
命令：`pnpm --dir apps/shop build`
```text
rendering chunks...
computing gzip size...
dist/index.html                   0.40 kB │ gzip:   0.31 kB
dist/assets/index-D0WT8t_u.css   47.95 kB │ gzip:   8.72 kB
dist/assets/index-DD42fZaY.js   406.16 kB │ gzip: 152.81 kB
✓ built in 833ms
```

- ✔ apps/shop 构建通过（用时 1s）
命令：`pnpm --dir apps/desktop/front build`
```text
computing gzip size...
dist/index.html                   0.39 kB │ gzip:  0.26 kB
dist/assets/index-Dju4RLwQ.css   19.94 kB │ gzip:  5.03 kB
dist/assets/index-BDrHFC9W.js   283.11 kB │ gzip: 84.40 kB

✓ built in 130ms
```

- ✔ apps/desktop/front 构建通过（用时 0s）

### 5. front 镜像增量构建耗时

命令：`docker compose --progress=plain build front`（基线构建，让缓存命中当前源码）
```text
#22 DONE 0.0s

#23 [front] resolving provenance for metadata file
#23 DONE 0.0s
```

- ✔ 基线构建退出码 0（用时 0s）

命令：写入 `apps/ai-sdk/src/__perf_probe.txt` 后重新构建（模拟只改 SDK 源码）
```text

#23 [front] resolving provenance for metadata file
 Service front  Built
#23 DONE 0.0s
```

- ✔ 改 SDK 源码后重建 15s（阈值 ≤60s，改造前 3m07s）

命令：写入 `apps/front/src/__perf_probe.txt` 后重新构建（模拟只改 front 源码）
```text
#22 DONE 0.0s

#23 [front] resolving provenance for metadata file
#23 DONE 0.0s
```

- ✔ 改 front 源码后重建 7s（阈值 ≤30s）

### 6. 新镜像 nginx 冒烟

命令：`curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:18081/`
200

- ✔ 首页 200

命令：index.html 引用的 assets（逐个 curl 状态码并计数）
```text
  15 200
```

- ✔ index.html 引用的静态资源全部 200

命令：`curl -s -o /dev/null -w "%{http_code}" -X POST -H "Content-Type: application/json" -d "{}" http://127.0.0.1:18081/api/v1/auth/login`
422

- ✔ /api 反代可达（空 body 登录返回 422）

### 7. Harness 审计

命令：`python3 tools/harness/audit.py`
```text

v2 requests: 18  存量跳过: 59  ERROR: 0  WARN: 0
```

- ✔ audit.py 退出码 0

## 未执行项与原因

- 浏览器人工点击：本 request 无前端交互变更，不需要人工验收。
- 首次运行时「audit.py」一并为未执行项（verify.md 尚未生成），第二次运行已覆盖。

## 验收结论

- 通过 17 项、失败 0 项；脚本退出码 0。
