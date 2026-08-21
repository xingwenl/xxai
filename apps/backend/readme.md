<!-- 启动worker -->
# docker compose up --build --force-recreate worker -d

## 关键配置项

- `AGENT_MAX_ITERATIONS`：单次对话任务中 Agent 工具循环的最大迭代轮数（每轮 = 一次 LLM 调用，含其工具执行），默认 `20`；达到上限后停止调用工具并追加一次不带工具的收尾回复。设置为 `0` 或负值表示不设限。
