# desktop-front

Desktop 宿主壳前端（React 19 + Vite + Tailwind CSS v4）。构建产物由 `apps/desktop` 的内嵌 FastAPI 托管。

## 开发

- `pnpm dev`：Vite 开发服务器（端口 8443，浏览器单独预览 UI 用）
- `pnpm build`：产出 `dist/`，`apps/desktop` 启动时托管该目录
- `pnpm format`：oxfmt 格式化

## 项目结构

- `src/App.tsx`：宿主壳主组件（应用页 / 设置页 / 插件视图切换）
- `src/components/plugin-view.tsx`：iframe 沙箱加载插件页，load 后注入宿主 SDK
- `src/components/settings.tsx`：设置页（zip 安装 / 启停 / 卸载 / 框架信息）
- `src/lib/api.ts`：`/api/desktop/*` 接口封装
- `src/lib/desktop-sdk.ts`：注入插件 iframe 的 `window.desktop` SDK
- `src/lib/toast.ts`：轻量通知
- `src/index.css`：Tailwind v4 入口与全局样式

## 契约

- 插件协议（`manifest.json`）与 `/api/desktop/*`、`/apps/<id>/*` 接口见 `apps/desktop/README.md`。
- 宿主启动前需先 `pnpm build`（或由打包流程执行）。
- 插件页共享样式：`apps/desktop/scripts/build_css.mjs` 产出 `static/css/tailwind.css`。
