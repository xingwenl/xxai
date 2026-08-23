# 验收记录：集成微信 ClawBot（iLink）机器人服务（MVP）

## 验收状态

- 状态：待人工联调（自动验证已完成，端到端扫码联调未执行）

## 对照 `spec.md` 验收标准

- [x] `docker compose config` 解析成功且包含 `wechat-bot-worker` 服务。
- [x] `poetry run pytest tests/wechat_bot -q` 全绿（3 个用例）。
- [x] `poetry run pytest tests/conversation/test_runtime.py -q` 全绿（35 个用例，无回归）。
- [x] 模块语法与静态检查通过（compileall、ruff）。
- [ ] 人工联调：设置 `WECHAT_BOT_ENABLED=true` 与模型密钥后运行 worker，扫码登录，发送文字消息能收到纯文本回复（待用户执行）。

## 剩余风险

- 依赖社区 SDK：真实扫码联调时若 `wechatbot-sdk` API 与文档有出入，需微调 `worker.py`。
- 微信平台条款限制：只能被动回复、腾讯保留限速/拦截与终止权利。
- 本 request 未标记 `done`，等待用户扫码联调后完成验收。

## 增量变更记录（轻量）

- 2026-08-23 第 2 次变更（登录状态持久化）：自动验证已通过（6 个单测 + 35 个回归 + ruff/compileall/compose 解析），
  人工部分（重启容器免扫码）待用户下次启动 worker 时确认。
- 2026-08-23 第 3 次变更（绑定后台智能体）：自动验证已通过（8 个单测 + 53 个 agent/conversation 回归 + ruff/compose 解析），
  人工部分（微信回复与智能体人设一致）待用户配置 `WECHAT_BOT_AGENT_ID` 后确认。
