# 技能：order-query（订单查询）

## 用途

把 `apps/backend/app/modules/tools/shop/data/order_query.py` 的能力以**技能（指令层）**形式提供给 Agent：

- 取数：内置工具 `order_query`（真实调用 hua8 订单接口，按登录用户会话鉴权，白名单剔除手机号等隐私字段）；
- 技能：定义触发时机、参数口径、输出与错误规范。

不把查询逻辑写成技能脚本的原因：`skill_runner` 脚本只接收字符串参数，无法注入当前登录用户的 `shop_token`；按用户鉴权的数据获取必须走内置工具链路。

## 使用步骤（管理后台）

1. 创建技能：
   - 方式 A（技能包导入）：把本目录打成 zip（内含 `SKILL.md`），在「技能管理 → 导入技能包」上传；或
   - 方式 B（手工创建）：名称 `order-query`，slug `order-query`，把 `SKILL.md` 中 frontmatter 之后的正文填入「指令模板」。
2. 绑定技能：在目标 Agent 的「技能绑定」中启用 `order-query`。
3. 启用工具：同一 Agent 需在「内置工具绑定」中启用 `order_query`（技能只负责教模型怎么用，取数必须靠工具）。

## 验证

对已绑定 Agent 提问「查一下我今天的订单」，期望输出：一句汇总 + 订单摘要列表，隐私字段不出现，token 过期时提示重新登录。

## 相关代码

- 工具实现：`apps/backend/app/modules/tools/shop/data/order_query.py`
- 数据访问与白名单：`apps/backend/app/modules/tools/shop/data/client.py`（`fetch_orders` / `ORDER_FIELDS`）
- 注册：`apps/backend/app/modules/tools/shop/registry.py`
