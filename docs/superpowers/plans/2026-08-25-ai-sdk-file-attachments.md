# AI SDK 文件附件与当前会话缓存 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按 Harness request `2026-08-25-ai-sdk-file-attachments` 分期实现当前会话文件上传、解析切块缓存、供应商适配和可选向量检索。

**Architecture:** SDK 上传后引用 `assetId`；后端按会话权限保存原文件并异步生成派生文本和 chunks；provider adapter 根据模型能力选择原生图片/文件或检索文本。第二期复用现有 pgvector，而不是引入独立向量数据库。

**Tech Stack:** Vue/TypeScript、FastAPI、SQLAlchemy/Alembic、Celery、LlamaIndex、PostgreSQL pgvector。

---

## 执行前置

- 先阅读 request 下的 `research.md`、`spec.md` 和 `plan.md`。
- 实现前补充确认 OCR 方案、embedding 默认模型/维度、文件大小/保留时长和 Worker 配置。
- 每个任务按 TDD 顺序先写失败测试，再实现，再运行目标测试。

## 执行顺序

1. 先实现 Phase 1 的协议、模型、上传、解析、切块和 SDK 输入框。
2. 完成 Phase 1 的后端与 SDK 验证后，再实现 provider 能力矩阵。
3. 最后接入 embedding/pgvector，避免第一期被向量服务配置阻塞。
4. 按 request 的 `verify.md` 和 `acceptance.md` 记录真实命令和剩余风险。

## 关键验收命令

```bash
poetry run pytest tests/asset tests/attachment tests/conversation tests/gateway tests/knowledge -q
poetry run ruff check app tests
poetry run alembic upgrade head
pnpm --dir apps/ai-sdk test
pnpm --dir apps/ai-sdk typecheck
pnpm --dir apps/ai-sdk build
```

## 回滚

停止上传入口和 Worker，回滚应用代码；确认新资产清理后再回滚迁移。保留既有 `ConversationAsset` 图片下载和旧消息协议兼容。
