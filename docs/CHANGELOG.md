# Changelog

## - 2026-09-01
- 📝 docs：补充一个服务接入多个 Agent 的接入手册 `🧑‍💻 lixingwen`

## - 2026-08-31
- 🐛 fix：切换国内镜像源修复容器构建，补全 skill-runner 启动 `🧑‍💻 lixingwen`

## - 2026-08-30
- ♻️ refactor：网关事件集中注册并合并对话工具循环 `🧑‍💻 lixingwen`
- ✨ feat：AI SDK 自定义组件端到端打通，支持模型驱动渲染宿主组件 `🧑‍💻 lixingwen`

## - 2026-08-28
- ✨ feat：附件主动检索工具 attachment_search 与截断注入提示 `🧑‍💻 lixingwen`
- ✨ feat：Agent 版本表单暴露附件能力矩阵配置 `🧑‍💻 lixingwen`
- 🐛 fix：附件 embedding 维度配置修正与向量回填脚本 `🧑‍💻 lixingwen`
- 🐛 fix：attachment_search 关键词测试在配置 embedding 后误打真实 API `🧑‍💻 lixingwen`
- ♻️ refactor：内置工具注册表合并为单一来源并直连真实 handler `🧑‍💻 lixingwen`
- ✨ feat：Agent 版本列表展示模型 Base URL 并升级 xxai-agent 至 0.1.5 `🧑‍💻 lixingwen`
- 🧰 chore：移除应用卡片调试日志 `🧑‍💻 lixingwen`
- 🧰 chore：新增 ToolVerse 玻璃拟态仪表盘演示页 `🧑‍💻 lixingwen`
- 📝 docs：新增 DSH「万物皆插件」思想借鉴与落地方案 `🧑‍💻 lixingwen`

## - 2026-08-27
- ✨ feat：会话级 embedding 与 pgvector 检索 `🧑‍💻 lixingwen`
- ✨ feat：文件附件支持加载与点击下载 `🧑‍💻 lixingwen`
- ✨ feat：平台模型注册表、Agent 绑定与前端管理界面 `🧑‍💻 lixingwen`

## - 2026-08-26
- ✨ feat：文件附件上传、解析切块与当前会话缓存（Phase 1） `🧑‍💻 lixingwen`
- ✨ feat：Word/Excel 附件解析依赖与真实样例测试 `🧑‍💻 lixingwen`
- ✨ feat：文档附件解析文本注入模型 `🧑‍💻 lixingwen`
- ♻️ refactor：内置工具执行改为处理器注册表分发 `🧑‍💻 lixingwen`
- ✨ feat：历史附件上下文恢复与文本缓存 `🧑‍💻 lixingwen`

## - 2026-08-25
- ✨ feat：增加图片生成读取与鉴权展示 `🧑‍💻 lixingwen`

## - 2026-08-24
- ✨ feat：ai-sdk 对话新增结构化询问能力（ask_user） `🧑‍💻 lixingwen`
- 🐛 fix：model_tokens 超限不再吞掉已生成回答 `🧑‍💻 lixingwen`
- ✨ feat：ai-sdk 认证后下发 client/agent 信息与配额快照并展示 client 名称 `🧑‍💻 lixingwen`

## - 2026-08-23
- ✨ feat：后台可管理的微信助手并支持对话上下文复用 `🧑‍💻 lixingwen`

## - 2026-08-21
- ✨ feat：增加 Agent 迭代轮数上限并在页面工具预算耗尽时停止 `🧑‍💻 lixingwen`
- ✨ feat：搭建插件化应用框架与 React 宿主壳（zip 安装、宿主 SDK、全屏沉浸） `🧑‍💻 lixingwen`
- ✨ feat：新增书签整理内置 React 子应用并支持插件类型区分 `🧑‍💻 lixingwen`
- ✨ feat：统一应用品牌配置并接入桌面图标 `🧑‍💻 lixingwen`
- ♻️ refactor：应用卡片抽离组件并统一毛玻璃样式 `🧑‍💻 lixingwen`
- ✨ feat：支持从 URL 添加远程壳插件 `🧑‍💻 lixingwen`

## - 2026-08-20
- ✨ feat：新增 pywebview + FastAPI 桌面应用脚手架 `🧑‍💻 lixingwen`

## - 2026-08-13
- ♻️ refactor：抽取运行时工具分发器并修复 embedding 批次超限 `🧑‍💻 lixingwen`
- ✨ feat：AgentLoop 过程可观测与思考内容实时展示落库 `🧑‍💻 lixingwen`
- ✨ feat：聊天窗支持拖拽缩放、本地持久化与清除聊天记录 `🧑‍💻 lixingwen`

## - 2026-08-11
- ✨ feat：完善接入文档与本地工具演示 `🧑‍💻 lixingwen`
- ✨ feat：支持系统提示词与本地会话续聊 `🧑‍💻 lixingwen`

## - 2026-08-10
- 🐛 fix：修复会话历史与会话标识传递 `🧑‍💻 lixingwen`
- 🧰 chore：同步 SDK 与页面交互改动 `🧑‍💻 lixingwen`

## - 2026-08-07
- ✨ feat：增加内置工具并接入 Embed MCP `🧑‍💻 lixingwen`

## - 2026-08-06
- ✨ feat：支持工具场景原生流式对话 `🧑‍💻 lixingwen`
- 🐛 fix：统一错误事件结束对话 `🧑‍💻 lixingwen`
- 🐛 fix：限制模型重试避免请求挂起 `🧑‍💻 lixingwen`
- ⚡ perf：优化知识库与技能按需注入 `🧑‍💻 lixingwen`
- 🐛 fix：修复生成中过程面板实时展示 `🧑‍💻 lixingwen`

## - 2026-08-05
- ✨ feat：增加可观测消息和玻璃态聊天 UI `🧑‍💻 lixingwen`

## - 2026-08-04
- ✨ feat：补知识库绑定智能体入口并增强聊天过程日志 `🧑‍💻 lixingwen`
- 🐛 fix：修复 worker 日志不落到宿主挂载目录 `🧑‍💻 lixingwen`
- ✨ feat：支持全栈容器化与知识库向量配置 `🧑‍💻 lixingwen`
- ✨ feat：支持 Zip 技能包和隔离脚本执行 `🧑‍💻 lixingwen`

## - 2026-08-03
- ✨ feat：新增后端日期文件日志 `🧑‍💻 lixingwen`

## - 2026-08-01
- ✨ feat：增加本地工具演示并修复策略状态更新 `🧑‍💻 lixingwen`

## - 2026-07-31
- ✨ feat：新增模型用量统计后台 `🧑‍💻 lixingwen`
- 🐛 fix：完善 npm 发布包契约 `🧑‍💻 lixingwen`
- ✨ feat：优化短期令牌与用户身份接入 `🧑‍💻 lixingwen`
- ✨ feat：接入 Agent 内部页面导航 `🧑‍💻 lixingwen`
- 🐛 fix：修复宿主工具 Schema 注册 `🧑‍💻 lixingwen`
- 📝 docs：固化 SDK 对话流程与变更规范 `🧑‍💻 lixingwen`
- ✨ feat：完善宿主工具与平台接入 `🧑‍💻 lixingwen`
- ✨ feat：支持 Embed Client 临时页面工具 `🧑‍💻 lixingwen`

## - 2026-07-30
- ✨ feat：完成 Agent SDK Phase 2C 生产增强 `🧑‍💻 lixingwen`
- ✨ feat：接入后台管理前端和 AI 模块 `🧑‍💻 lixingwen`
- ✨ feat：新增模型用量明细表 `🧑‍💻 lixingwen`
- ✨ feat：完善 AI 管理后台配置 `🧑‍💻 lixingwen`
- 📝 docs：记录模型用量统计设计 `🧑‍💻 lixingwen`

## - 2026-07-29
- ✨ feat：完成 Phase 2B 宿主工具自动调用 `🧑‍💻 lixingwen`

## - 2026-07-28
- ✨ feat：完成 Agent SDK 原生 `ai-agent.v1` WebSocket transport、流式消息、引用展示、停止生成和有限重连基础
- 📝 docs：增加 Phase 2A 本地联调手册，并记录真实基础设施验收前置条件

## - 2026-07-26
- 📝 docs：完成可配置 Agent 第一阶段验收 `🧑‍💻 lixingwen`
- 🐛 fix：固定 AI Agent SDK 兼容的 TypeScript 版本 `🧑‍💻 lixingwen`
- 📝 docs：完成第二阶段需求与启动计划 `🧑‍💻 lixingwen`

## - 2026-07-24
- ✨ feat：新增 AI Agent JavaScript SDK，包含核心客户端、WebSocket 传输、工具注册和 UI 组件 `🧑‍💻 lixingwen`

## - 2026-07-23
- ✨ feat：完成用户角色与认证基础能力 `🧑‍💻 lixingwen`

## - 2026-07-20
- ✨ feat：搭建后端基础设施并实现用户模块闭环 `🧑‍💻 lixingwen`
