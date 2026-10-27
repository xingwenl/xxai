---
source: script
request: 2026-10-27-tool-group-prefetch
ranAt: "2026-10-27 16:03:46 CST"
exitCode: 0
---

## 已执行的命令与结果

### 1. 预取规则：命中即加载、单关键词不预取、不越界
```
PASS  消息='每天定时把上周的订单和库存下载成图片' → ['content', 'ops', 'task']
PASS  消息='帮我查一下订单和库存' → ['ops']
PASS  消息='订单呢' → []
PASS  消息='' → []
PASS  消息='订单和库存' → []
PASS  消息='用 PDF 和 http 下载附件' → ['content']
PASS  7 个组的关键词表自检通过（阈值 2）
```

### 2. 目录恒定 + 预取不改目录 + enum 只列未加载组
```
PASS  预取与显式加载都不改目录文本（系统提示词不失效）
PASS  load_tool_group 的 enum 只列未加载组：knowledge、skill、ui
```

### 3. 组常驻语义：eager 组与未声明分组的宿主工具首轮绑定
```
PASS  不带 group → host 组常驻；带 group → 默认按需；eager=True → 首轮绑定
```

### 4. 相关单元测试（分目录执行，规避测试模块同名收集冲突）
```
$ pytest tests/agent_runtime/test_tool_prefetch.py -q
.........                                                                [100%]
9 passed in 2.35s
$ pytest tests/agent_runtime/test_tool_groups.py -q
.......................                                                  [100%]
23 passed in 1.91s
$ pytest tests/builtin_tool/test_groups.py -q
...                                                                      [100%]
3 passed in 2.00s
$ pytest tests/host_tool/test_group_declarations.py -q
...                                                                      [100%]
3 passed in 2.02s
$ pytest tests/conversation/test_repository_loaded_tool_groups.py -q
..                                                                       [100%]
2 passed in 1.92s

--- 受影响包的回归
$ pytest tests/agent_runtime -q
.......                                                                  [100%]
151 passed in 1.92s
$ pytest tests/conversation -q
...........................                                              [100%]
171 passed in 7.07s
$ pytest tests/gateway -q
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
123 passed, 1 skipped, 1 warning in 2.69s
$ pytest tests/builtin_tool -q
.....................................................................    [100%]
69 passed in 2.83s
$ pytest tests/host_tool -q
................                                                         [100%]
16 passed in 1.84s
```

### 5. 静态检查（Python + ai-sdk 类型）
```
All checks passed!
$ npx tsc --noEmit
（tsc 无输出即通过）
```

## 未执行项与原因

- 预取命中率与首 token 延迟收益：需要真实用户消息分布与供应商缓存/计费指标，本地只有规则单测（见 ADR 0011）。
- 真实模型下的「猜错后恢复」体验：需可用外部模型密钥与线上多轮流量，本地用单测覆盖 tool_not_loaded 兜底。
- 桌面宿主（ledger / note）真实调用 registerToolGroups：ai-sdk 侧只做到类型检查与实际页面链路之外的单元覆盖。
- 组元数据落库与管理台展示：本轮明确不做（用户 2026-10-27 决策）。

## 验收结论

通过：预取规则、目录恒定与 enum 收窄、eager/宿主声明语义、相关单测与静态检查全部成功。
