# Demo 说明

本目录包含 xxai-agent SDK 的演示页面：

## 如何运行

### 1. 首先构建项目

```bash
cd apps/ai-sdk
npm install
npm run build
```

### 2. 启动 Demo 服务器

```bash
npm run demo
```

然后在浏览器中访问：

- UMD 版本：http://localhost:5174/index.html
- ESM 版本：http://localhost:5174/esm.html
- 嵌入式模式：http://localhost:5174/embedded.html

## Demo 说明

### index.html (UMD 版本)

使用 UMD 格式的包，通过全局变量 `XXAIAgent` 访问 SDK 功能。适合在不支持 ES Module 的旧浏览器或者直接 script 标签引入的场景。

### esm.html (ESM 版本)

使用 ES Module 格式的包，通过 `import` 语句引入 SDK。适合现代浏览器开发环境。

### embedded.html (嵌入式模式)

演示 `ui.container` 驱动的嵌入式模式：聊天 UI 直接渲染进页面指定容器并填满容器，
页面提供容器高度切换与主题切换控制，右下角同时挂一个 floating 实例用于对比两种模式。

## 功能演示

Demo 页面包含以下功能：
- 右下角悬浮聊天按钮
- 打开/关闭/切换聊天窗口
- Mock 实现的聊天功能
