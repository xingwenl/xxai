"""首轮工具组预取：入口用关键词规则猜「这条消息大概要用哪几组工具」。

为什么要有它
------------
工具按组按需加载后，一次加载会让 provider 的前缀缓存失效一次（``tools`` 数组
变了；目录文本已改为恒定，不再额外失效）。默认模型走 OpenAI 兼容端点，只有
自动前缀缓存、没有原生延迟加载，所以「加载发生在什么时候」直接决定代价：
历史越短，miss 掉的前缀越便宜。把第一次加载提前到第一轮之前，是这套机制里
性价比最高的一次优化。

为什么是规则而不是分类器
------------------------
分类器要多一次网络往返，压在首 token 之前，且中文能力与延迟都未验证。这里的
目标是「命中就赚、没命中也不亏」：没猜中就走原来的 ``load_tool_group``，猜中
就省掉一轮往返与一次缓存 miss。规则是纯函数、无 IO、可单测、可随时改词表。

行为契约
--------
- 只返回**当前工具清单里真实存在**的组（与 ``available`` 求交），不猜不存在的组。
- 命中即加载：达标（``MIN_PREFETCH_SCORE``）的组全部返回，不设数量上限。
- 只增不减：预取只是在首轮绑定前把组加进 ``active``，之后与历史重放合并，
  模型再调 ``load_tool_group`` 也不会撤销。
"""

from __future__ import annotations

from collections.abc import Iterable

# 组 → 关键词。词表按「业务域」而非「句式」组织：同一个词命中多个组时由分数
# 自然排序，不需要写优先级。中文按子串匹配，英文关键词按小写匹配。
PREFETCH_RULES: dict[str, tuple[str, ...]] = {
    "ops": (
        "店铺",
        "订单",
        "商品",
        "库存",
        "销量",
        "营业额",
        "sku",
        "会员",
        "客户",
        "退款",
        "发货",
        "价格",
        "活动",
        "营销",
        "带货",
    ),
    "memory": (
        "记住",
        "记忆",
        "忘记",
        "偏好",
        "我的习惯",
        "别名",
        "上次说",
    ),
    "task": (
        "定时",
        "每天",
        "每周",
        "稍后",
        "提醒",
        "委派",
        "子任务",
        "定时任务",
        "cron",
    ),
    "content": (
        "图片",
        "截图",
        "识别",
        "下载",
        "上传",
        "链接",
        "http",
        "附件",
        "pdf",
    ),
    "knowledge": (
        "知识库",
        "文档",
        "资料",
        "检索",
        "问答库",
    ),
    "skill": (
        "技能",
        "脚本",
        "自动化流程",
    ),
    "ui": (
        "卡片",
        "表格展示",
        "展示给用户",
        "可视化",
    ),
}

# 达标分数：命中该数量的**不同关键词**才预取。取 2 而不是 1，是因为单个词
# 误伤面太大（「订单」「图片」这类词在闲聊里也常见），而漏选的代价只是一次
# 额外的 load_tool_group 往返。
MIN_PREFETCH_SCORE = 2


def prefetch_tool_groups(message: str, available: Iterable[str]) -> set[str]:
    """按用户消息预取工具组，返回 ``available`` 的子集（可能为空）。"""

    text = (message or "").strip().lower()
    if not text:
        return set()
    allowed = set(available)
    scored: list[tuple[int, str]] = []
    for group, keywords in PREFETCH_RULES.items():
        if group not in allowed:
            continue
        hits = sum(1 for keyword in keywords if keyword.lower() in text)
        if hits >= MIN_PREFETCH_SCORE:
            # 分数降序、组名升序：同一消息在任何入口都得到同一份结果。
            scored.append((-hits, group))
    return {group for _, group in sorted(scored)}
