# 验证记录

## 变更文件

- 后端配置、builtin tool registry/services、图片生成/读取执行器、asset 查询仓储。
- 对话运行时、REST/SSE/WebSocket 收尾逻辑中的图片内容块。
- AI SDK AgentClient 资源加载器、ImageContent 及组件属性传递。
- OpenAI 图片配置示例和直接依赖声明。

## 已执行命令

### 后端目标测试

命令：

```bash
cd apps/backend
poetry run pytest tests/builtin_tool tests/conversation/test_runtime.py -q
```

结果：通过，58 个测试通过。

### 图片工具专项测试

命令：

```bash
cd apps/backend
poetry run pytest tests/builtin_tool/test_image_tools.py -q
```

结果：通过，3 个测试通过，覆盖 base64 持久化、未配置密钥、非图片读取拒绝。

### 后端静态检查

命令：

```bash
cd apps/backend
poetry run ruff check app tests/builtin_tool/test_image_tools.py tests/conversation/test_runtime.py
poetry check --lock
```

结果：均通过。

### 图片生成失败回归测试

命令：

```bash
cd apps/backend
poetry run pytest tests/conversation/test_runtime.py tests/builtin_tool/test_image_tools.py -q
```

结果：通过；覆盖 `{"error": {"code": "image_generation_failed"}}` 不再触发 `TypeError`，并保持页面预算错误码识别。

修复后静态检查：

```bash
poetry run ruff check app tests/conversation/test_runtime.py tests/builtin_tool/test_image_tools.py
```

结果：通过。

### AI SDK 类型、测试和构建

命令：

```bash
cd apps/ai-sdk
pnpm run type-check
pnpm run test --run
pnpm run build
```

结果：类型检查通过；14 个测试文件、87 个测试通过；生产构建通过。

### Markdown 图片鉴权回归

- Markdown 中的 `![alt](/api/v1/assets/<asset_id>)` 不再直接作为 `<img src>` 请求。
- SDK 先使用 `AgentClient.loadAsset()` 携带 Bearer Token 获取 Blob，再设置临时 Blob URL。
- 外部公开图片仍保持直连；Blob URL 在内容更新和组件卸载时释放。
- 与上述 SDK 类型检查、测试和构建一并验证通过。

## 例外与未完成项

- `poetry run pytest -q` 全量收集受仓库已有同名测试模块影响：`test_models`、`test_routes`、`test_services` 出现 import file mismatch；因此使用按目录/文件的目标测试完成回归，未修改无关测试收集结构。
- 未调用真实 OpenAI 账号，图片生成使用 fake client 验证；上线前需在已配置 `OPENAI_API_KEY` 的环境做一次联调。
- 未执行浏览器端人工截图回归；SDK 构建和组件类型检查已通过。

### 2026-08-26 执行分发轻量重构验证

本次为行为保持型重构，仅调整 `invoke_builtin_tool` 的分发方式，工具契约、错误码与返回结构不变。

命令：

```bash
cd apps/backend
poetry run ruff check app/modules/builtin_tool/services.py
poetry run pytest tests/builtin_tool tests/conversation/test_runtime.py -q
```

结果：ruff 通过；63 个目标测试全部通过，覆盖 `http_get`、`http_post`、`image_generate`、`image_read` 执行与运行时集成。
