# Skill 脚本执行器调研

## 调研问题

- 已导入技能包内的 `scripts/` 如何在智能体运行时真正执行？
- 如何让 `allow_script_execution` 成为有效授权边界，同时限制脚本对宿主、网络、文件系统和资源的访问？
- 如何复用现有工具调用与审计能力，并兼顾同步对话需要的低延迟返回？

## 功能复杂度

- 级别：核心功能，架构级安全变更。
- 选择理由：需要执行上传代码，涉及独立运行时、数据模型、内部协议、公开审计 API 和权限行为。
- 最低调研要求：官方容器安全与资源限制文档、语言进程执行规范、命令注入防护基线，以及本项目现有审计/确认机制。

## 参考依据

### 来源 1

- 类型：官方文档
- 名称：Docker Engine security
- 链接：https://docs.docker.com/engine/security/
- 版本或发布日期：页面标注 2025-07-25 更新；调研日期 2026-08-04。
- 核心做法：容器与宿主的隔离依赖 namespaces、cgroups、capabilities 等边界；Docker daemon 本身拥有高权限，不应把 daemon 控制能力暴露给不可信代码。
- 对本项目的启发：执行器不能挂载 Docker Socket，也不能与 API 进程共享数据库密钥；应使用独立、最小权限容器。

### 来源 2

- 类型：官方文档
- 名称：Docker Resource constraints
- 链接：https://docs.docker.com/engine/containers/resource_constraints/
- 版本或发布日期：页面标注 2026-04-13 更新；调研日期 2026-08-04。
- 核心做法：容器默认没有 CPU 和内存上限，需要显式配置 memory、CPU 等运行时约束，防止单个工作负载耗尽宿主资源。
- 对本项目的启发：runner 必须设置内存、CPU、PID、超时和输出上限，不能只依赖应用层布尔权限。

### 来源 3

- 类型：官方文档
- 名称：Python `subprocess` 进程管理
- 链接：https://docs.python.org/3/library/subprocess.html
- 版本或发布日期：Python 3.14.6 在线文档；调研日期 2026-08-04。
- 核心做法：使用参数数组启动子进程、捕获 stdout/stderr、检查返回码并设置 timeout；是否启用 shell 会显著影响命令解释和注入风险。
- 对本项目的启发：runner 使用固定解释器和参数数组，禁止 `shell=True`，并在超时后终止整个进程组。

### 来源 4

- 类型：安全基线
- 名称：OWASP OS Command Injection Defense Cheat Sheet
- 链接：https://cheatsheetseries.owasp.org/cheatsheets/OS_Command_Injection_Defense_Cheat_Sheet.html
- 版本或发布日期：在线文档，MkDocs 1.6.1 / Material 9.7.7；调研日期 2026-08-04。
- 核心做法：首选避免直接调用操作系统命令；不可避免时采用命令白名单、参数校验和结构化参数传递，不能拼接 shell 命令字符串。
- 对本项目的启发：只允许数据库文件索引中标记为 `script` 的路径，扩展名映射到固定解释器，参数逐项限制长度和数量。

### 来源 5

- 类型：本项目成熟实践
- 名称：Host Tool / MCP 调用审计与状态机
- 链接：`apps/backend/app/modules/host_tool`、`apps/backend/app/modules/mcp`
- 版本或发布日期：仓库当前版本；调研日期 2026-08-04。
- 核心做法：工具调用使用结构化 schema、状态迁移、敏感参数脱敏、结果截断和审计记录。
- 对本项目的启发：脚本执行沿用 `requested -> running -> succeeded|failed` 的审计语义，并作为模型可调用的结构化工具接入对话 Graph。

## 方案比较

| 方案 | 优点 | 限制 | 与本项目的匹配度 |
|---|---|---|---|
| A. API 进程直接 `subprocess` | 实现最少、延迟低 | 脚本可接触 API 密钥、数据库网络和可写文件系统，故障会影响主服务 | 低，不采用 |
| B. 现有 Celery worker 直接执行 | 可异步、已有队列 | worker 同样持有数据库与存储权限；对话同步等待复杂；隔离不足 | 中低，不采用 |
| C. 独立受限 runner 容器，通过内部 HTTP 同步调用 | 与 API 密钥和数据库隔离；适合工具调用同步返回；可配置容器资源与网络限制 | 增加部署服务和内部协议，需要审计与健康检查 | 高，采用 |
| D. 每次调用动态创建临时容器 | 隔离最强、单次环境干净 | 需要 Docker daemon 控制权，冷启动高，运维复杂，暴露 Socket 风险 | 中，后续高隔离版本再考虑 |

## 最终决策

- 选择方案：C，常驻专用 runner 容器 + 每次调用独立子进程。
- 选择原因：在不暴露 Docker daemon 的前提下，将上传脚本与 API/数据库密钥隔离，并满足对话工具调用需要的同步响应。
- 运行约束：包目录只读、临时工作目录、默认禁网、非 root、`cap_drop: ALL`、`no-new-privileges`、只读根文件系统、CPU/内存/PID 限制、进程超时和输出上限。
- 调用约束：只允许已启用且绑定到当前智能体的技能包；包级 `allow_script_execution=true`；脚本必须存在于文件索引且角色为 `script`；解释器白名单首期支持 Python、Node.js 和 POSIX shell；禁止 shell 字符串拼接。
- 对后续 spec、plan 或人工确认的影响：新增 runner 服务、执行审计表、内部调用协议和公开审计查询 API，进入实现前必须人工确认。

## 剩余风险

- 常驻容器中的子进程仍共享容器内核与基础镜像，不等同于 microVM；高对抗场景应升级到 gVisor、Kata 或 Firecracker。
- 禁网会使依赖外部 API 的市场 Skill 无法运行；首期不开放任意出网，后续应采用域名/能力白名单。
- 市面 Skill 可能依赖未安装的第三方包；首期只提供固定基础运行时，不允许脚本动态安装依赖。
- Shell 脚本能力面更大，虽然位于受限 runner 内，仍需固定解释器、参数数组和严格资源限制。
