# 前端项目规范

本规范适用于当前仓库的前端项目 `apps/front`，同时服务于 AI 与人类开发者。目标是让后续前端开发在技术栈、分层方式、代码风格、样式风格、数据流与聊天前端交互上保持稳定一致。

## 1. 技术栈

当前前端项目的主技术路径如下：

- 构建工具：`Vite`
- 语言：`TypeScript`
- UI 框架：`React 19`
- 路由：`TanStack Router`
- 服务端状态：`TanStack React Query`
- 本地状态：`Zustand`
- 样式系统：`Tailwind CSS v4`
- 组件体系：`shadcn/ui` + `Radix UI`
- 图标：`lucide-react`
- 实时通信：`socket.io-client`
- 表单：`react-hook-form` + `zod`
- Markdown 渲染：`react-markdown` + `remark-gfm` + `rehype-prism-plus`
- 通知：`sonner`

### 推荐项

- 只沿用当前已存在的主技术路径
- 优先使用仓库里已经形成共识的方案

### 禁用项

- 禁止并行引入第二套主状态管理方案
- 禁止引入与现有主路径冲突的新 UI 框架
- 禁止把“可能会用到”的技术提前混入正式规范

## 2. 目录分层

前端目录按以下方式理解和维护：

- `src/routes`
  - 只放路由入口和路由层壳子
- `src/features`
  - 放业务实现，每个 feature 自带组件、hooks、数据
- `src/components`
  - 放跨 feature 复用组件
- `src/components/ui`
  - 放基础 UI 组件，默认不承载业务逻辑
- `src/api`
  - 放业务接口封装
- `src/lib`
  - 放基础工具、协议封装、无业务归属的工具函数
- `src/stores`
  - 放跨页面共享的客户端状态
- `src/context`
  - 放全局 provider 级上下文
- `src/styles`
  - 放全局样式和主题变量

### 推荐项

- 路由层保持薄，业务主体优先进 `features`
- 只服务单个 feature 的组件，默认不提升到全局 `components`
- 基础 UI 与业务组件严格分层

### 禁用项

- 禁止把复杂业务逻辑直接写进 `routes/*`
- 禁止把业务组件塞进 `components/ui`
- 禁止跨 feature 依赖对方内部实现细节

## 3. React 与 TypeScript 代码风格

### 推荐项

- 默认使用函数组件
- 默认优先使用 `type` 定义类型
- TypeScript 类型导入统一使用 `import { type X }`
- 路由页面只做挂载，页面主体从 `features/*` 导出
- 能在 feature 内闭合的逻辑，不上提为全局 store
- 未使用变量统一以 `_` 前缀处理
- 遵守当前 ESLint 中的 `no-console`、`consistent-type-imports` 等规则

### 禁用项

- 禁止在业务组件中散写 `axios` 请求
- 禁止为了页面私有逻辑随意创建全局 store
- 禁止把所有状态都塞进 Zustand

## 4. 样式与组件风格

本项目样式风格应延续现有 `shadcn-admin` 基础，保持后台一致性，并允许聊天页面做体验优化。

### 推荐项

- 优先使用 `src/components/ui` 中已有组件
- 优先使用语义化 token，如 `bg-background`、`text-muted-foreground`
- 优先使用 `cn()` 组织类名
- 优先使用 `gap-*`
- 宽高相等优先使用 `size-*`
- 新样式优先在业务组件层收敛
- 主题变量统一维护在 `src/styles/theme.css`
- 全局样式入口统一为 `src/styles/index.css`

### 禁用项

- 禁止在业务组件中大量使用原始颜色值替代语义 token
- 禁止为了局部效果随意覆盖全局主题变量
- 禁止复制基础 UI 组件后长期分叉
- 禁止把页面级布局样式塞进 `components/ui`
- 禁止写不可维护的大段样式组合而不收敛成业务组件

## 5. 数据流与实时通信

### 推荐项

- 服务端状态优先 React Query
- 客户端交互状态优先局部状态或最小化 Zustand
- HTTP 接口调用统一收敛在 `src/api`
- 协议层或 socket 层封装统一收敛在 `src/lib`
- socket 行为优先收敛在聊天相关 hooks 与 lib 中

### 禁用项

- 禁止把 React Query 能解决的数据放进 Zustand 长期缓存
- 禁止在多个页面重复实现同一套 socket 连接逻辑
- 禁止把实时事件处理散落到无关组件层

## 6. 聊天前端专项规则

聊天前端是本项目重点业务区，需要单独收紧规范。

### 推荐项

- 聊天相关前端逻辑优先收敛在 `src/features/chats`
- 聊天消息区优先保证信息层级与可读性
- 用户消息、AI 消息、系统状态消息保持稳定视觉区分
- Markdown 内容统一走现有 `.markdown` 样式体系
- 流式回复必须提供一致的 loading / delta / done 状态反馈
- 输入区、发送区、消息列表、滚动行为视为一个整体设计

### 禁用项

- 禁止把聊天 feature 的细节逻辑扩散到多个无关 feature
- 禁止为聊天页面单独再起一套 Markdown 样式系统
- 禁止无规则地分别修改消息渲染、输入区与滚动逻辑

## 7. 开发时的优先级

当前前端开发遵循以下优先级：

1. 保持与现有技术栈一致
2. 保持目录与组件边界清晰
3. 保持样式系统与主题一致
4. 保持数据流与实时通信实现收敛
5. 对聊天前端的优化优先在 `features/chats` 内闭合

## 8. 适用说明

后续若任务聚焦于某一类问题，应优先触发对应的项目级 skill：

- 结构与目录问题：`frontend-architecture`
- 样式与 UI 问题：`frontend-styling`
- 接口、状态、socket 问题：`frontend-data-and-realtime`
- 聊天页面与交互问题：`frontend-chat-ui`
