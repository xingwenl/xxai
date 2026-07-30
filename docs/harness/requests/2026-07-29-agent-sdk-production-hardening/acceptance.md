# 验收记录

## 验收结论

Phase 2C 生产核心增强的连接/消息配额、token 签发配额、metrics endpoint、协议兼容、ESM/UMD 发布治理、模型 usage 采集、model token quota 扣减和 SDK `metadata.usage` 映射已完成实现和自动化验证。request 可标记为 done。

## 变更范围

- 后端新增 Redis 配额模块、Prometheus 指标、`/metrics`、协议版本/能力返回和生产配置项。
- SDK 增加 auth 版本声明、session capability 保存、兼容错误处理和 package 验证脚本。
- 新增中文兼容矩阵、运行手册、research/spec/plan/verify 文档。

## 剩余风险

- 尚未执行真实 Redis/PostgreSQL 多实例压测和反向代理矩阵。
- 多实例 Redis/PostgreSQL 压测和反向代理矩阵仍未执行。
- npm 默认 cache 存在权限问题，使用临时 cache 完成了 pack 验证。
- 多标签页、离线、可访问性、国际化/主题和数据合规不属于本 request。

## 验证证据

- 后端全量 pytest：`152 passed, 1 skipped`。
- 真实 Redis token_issue 配额：第一次允许、第二次超限。
- SDK Vitest：`13 passed`。
- SDK type-check/build/package verification：全部通过。
- Ruff、Poetry check 和 `git diff --check`：全部通过。
