---
source: script
request: 2026-10-27-tool-groups-lazy-load
ranAt: "2026-10-27 14:43:30 CST"
exitCode: 0
---

## 已执行的命令与结果

### 1. 工具 schema 体积实测（/Users/lixingwen/xw/study/ai-base/apps/backend/.venv/bin/python 直接序列化 bind_tools 形状）
```
基线：全量绑定 19 个工具 = 18198 字符
PASS  WS 入口 初始绑定（常驻工具 + 目录工具）: 1514 字符（阈值 ≤1700）
       常驻工具：['ask_user']
       可加载组：['content', 'knowledge', 'memory', 'ops', 'skill', 'task', 'ui']
PASS  REST 入口 初始绑定（常驻工具 + 目录工具）: 487 字符（阈值 ≤800）
       常驻工具：（无）
       可加载组：['content', 'knowledge', 'memory', 'ops', 'skill', 'task', 'ui']
PASS  REST 加载 content 组之后: 4901 字符（阈值 ≤6500）
PASS  REST 加载 knowledge 组之后: 1797 字符（阈值 ≤6500）
PASS  REST 加载 memory 组之后: 3458 字符（阈值 ≤6500）
PASS  REST 加载 ops 组之后: 5842 字符（阈值 ≤6500）
PASS  REST 加载 skill 组之后: 2160 字符（阈值 ≤6500）
PASS  REST 加载 task 组之后: 3718 字符（阈值 ≤6500）
PASS  REST 加载 ui 组之后: 1813 字符（阈值 ≤6500）
PASS  重复加载同一组：返回空、版本不变
PASS  内置工具全部登记分组（19/19）

工具目录（进系统提示词，约 571 字符）：
工具目录（按组加载）：默认只绑定了部分工具，其他能力需要先调用 load_tool_group 加载对应分组，加载后下一轮即可调用。
- content（内容）：读取与生成图片、发起 HTTP 请求、检索附件。工具：attachment_search、http_get、http_post、image_generate、image_read
- knowledge（知识）：在已绑定知识库中检索资料。工具：knowledge_search
- memory（记忆）：记住或忘记用户长期事实，以及检索已有记忆。工具：forget_user_memory、memory_search、remember_user_memory
- ops（运营）：店铺、订单、商品与店铺卡片等电商运营数据。工具：order_query、product_query、show_shop_list、store_ops_query
- skill（技能）：创建技能（脚本与指令由 load_skill 负责）。工具：create_skill
- task（任务）：定时任务、委派子任务、运行时环境信息。工具：create_task、delegate_tasks、get_runtime_info
- ui（界面）：向用户展示卡片式结果。工具：show_user_card
```

### 2. REST 与 WS 对同一批工具产出一致的初始绑定与目录文本
```
PASS  工具顺序不同时，初始绑定与目录文本完全一致
PASS  目录文本不含 JSON schema（只常驻组名与工具名）
初始绑定：ask_user、load_tool_group
```

### 3. 跨轮重放加载态：第二轮开局即绑定上一轮加载过的组
```
PASS  加载结果携带 tool_group 元数据：{'tool_group': 'ops'}
PASS  第二轮开局即绑定 ops，version=0，目录只列未加载的组
PASS  未知组名被忽略
```

### 4. 分组/加载/兜底/重绑的单元与链路测试
```
..................                                                       [100%]
18 passed in 1.78s
..                                                                       [100%]
2 passed in 1.89s

--- 受影响包的回归（分批执行，规避测试模块同名收集冲突）
$ pytest tests/agent_runtime -q
.................................................................        [100%]
137 passed in 1.81s
$ pytest tests/conversation -q
...........................                                              [100%]
171 passed in 6.23s
$ pytest tests/gateway -q
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
123 passed, 1 skipped, 1 warning in 2.55s
$ pytest tests/builtin_tool -q
..................................................................       [100%]
66 passed in 2.48s
$ pytest tests/skill_runner -q
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
10 passed, 1 warning in 2.83s
$ pytest tests/workflows -q
..........................................                               [100%]
186 passed in 17.33s
```

### 5. 静态检查
```
All checks passed!
```

## 未执行项与原因

- 真实供应商调用下的工具选择准确率：需要可用的外部模型密钥与线上流量，本地无法复现。
- 前缀缓存命中率与首 token 延迟：需要供应商侧计费/缓存指标，仓库内无采集口径（见 ADR 0011）。
- 桌面宿主（ledger / note）真实页面注册链路：需要在桌面宿主进程内运行，本地只覆盖了同名形状的替身对象。
- 多轮对话中途加载组后的完整前端事件回放：已有消息落库口径未改，本轮未构造端到端回放用例。

## 验收结论

通过：体积断言、跨轮重放语义、幂等/兜底语义、REST/WS 目录一致性、受影响包单测与 ruff 全部成功。
