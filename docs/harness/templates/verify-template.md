---
source: script
request: YYYY-MM-DD-topic
ranAt: "<由 tools/harness/verify.sh 写入>"
exitCode: 0
---

## 已执行的命令与结果

- 本文件由 `tools/harness/verify.sh <request-id>` 执行
  `tools/harness/verify/<request-id>.sh` 后自动写入，不要手写。
- 记录本次真实运行过的命令与真实输出。

## 未执行项与原因

- 写明无法在本机执行的项目及原因（缺环境、缺权限、需人工联调）。
- 若确实全部执行完毕，明确写"无未执行项"。
- 有意保留未执行项时，验证脚本以退出码 3 结束。

## 验收结论

- 三行以内：是否达到 `spec.md` 的验收标准；剩余风险；是否可归档。
