# AI SDK 文件附件与当前会话缓存设计

## 设计结论

采用“统一附件引用、原文件保留、解析结果和 chunks 缓存、embedding 可选”的分层方案。附件只绑定当前会话，不做跨会话共享。图片对 OpenAI-compatible 视觉模型和 Qwen-VL 保留原生输入；文档在模型不支持原生文件时使用服务端解析文本和向量检索；DeepSeek 默认走文本通道。

## 交互与协议

SDK 输入框支持图片缩略图、文档卡片、上传进度、解析状态、删除、拖拽和粘贴图片。上传完成后获得 `assetId`，`message_send` 只携带文本和附件元数据，不发送 Base64。

## 后端与缓存

原文件复用 `ConversationAsset`。新增处理记录、chunk 和 embedding 关系，版本键包含文件内容 hash、解析器版本、分块参数和 embedding 配置。所有读取严格过滤当前 `conversation_id`、主体和 asset。

## 分期

第一期完成上传、解析、切块缓存和图片/文档协议；第二期接入可配置 embedding 与 pgvector 检索；第三期补齐 OCR、表格定位、引用和清理策略。

## 设计依据

详见 [research.md](/Users/lixingwen/xw/study/ai-base/docs/harness/requests/2026-08-25-ai-sdk-file-attachments/research.md)、[spec.md](/Users/lixingwen/xw/study/ai-base/docs/harness/requests/2026-08-25-ai-sdk-file-attachments/spec.md) 和 [plan.md](/Users/lixingwen/xw/study/ai-base/docs/harness/requests/2026-08-25-ai-sdk-file-attachments/plan.md)。
