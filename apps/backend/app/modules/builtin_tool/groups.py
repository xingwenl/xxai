"""内置工具的分组元数据（工具侧常量，与用户意图无关）。

分组只决定「一次请求里绑定哪些工具 schema」，不改变任何工具的语义、权限与
执行器：同一工具无论属于哪一组，被加载后的行为完全一致。分组的唯一判据是
工具本身的业务域，它由代码写死，不来自模型判断，也不来自用户消息。

新增业务工具必须在此登记分组：``registry`` 会在导入时校验，漏登记的工具有
静默不可用的风险（不在任何组里 → 永远不会被绑定），因此这里用启动期失败换
确定性。
"""

from __future__ import annotations

# 常驻组：无论是否加载其他组都始终绑定，用于平台级交互能力（ask_user）。
BASIC_GROUP = "basic"

# 立即绑定（不参与按需加载）的组名。默认只有宿主回落组（``agent_runtime`` 侧
# 的 ``host``）：它的成员没有声明过分组、无法被 ``load_tool_group`` 定向加载，
# 只能始终绑定。内置组默认「异步加载」——等模型自己调 ``load_tool_group`` 或
# 入口预取命中；需要让某个组常驻时，在 ``register_tool_group`` 里传 ``eager=True``。
EAGER_TOOL_GROUPS: set[str] = set()

# 分组展示信息：组名 → (中文标题, 一句话说明)。说明面向模型，回答“这组里大概
# 有什么能力”，不追求覆盖组内每个工具。
TOOL_GROUP_META: dict[str, tuple[str, str]] = {
    "ops": ("运营", "店铺、订单、商品与店铺卡片等电商运营数据"),
    "memory": ("记忆", "记住或忘记用户长期事实，以及检索已有记忆"),
    "task": ("任务", "定时任务、委派子任务、运行时环境信息"),
    "content": ("内容", "读取与生成图片、发起 HTTP 请求、检索附件"),
    "knowledge": ("知识", "在已绑定知识库中检索资料"),
    "skill": ("技能", "创建技能（脚本与指令由 load_skill 负责）"),
    "ui": ("界面", "向用户展示卡片式结果"),
}

# 业务工具名 → 分组。按域归类，不按调用频次或调用时序归类。
BUILTIN_TOOL_GROUPS: dict[str, str] = {
    # 运营 / 电商
    "show_shop_list": "ops",
    "order_query": "ops",
    "store_ops_query": "ops",
    "product_query": "ops",
    # 记忆
    "remember_user_memory": "memory",
    "forget_user_memory": "memory",
    "memory_search": "memory",
    # 任务 / 编排 / 运行时
    "create_task": "task",
    "delegate_tasks": "task",
    "get_runtime_info": "task",
    # 内容 / 媒体 / HTTP
    "image_read": "content",
    "image_generate": "content",
    "http_get": "content",
    "http_post": "content",
    "attachment_search": "content",
    # 知识
    "knowledge_search": "knowledge",
    # 技能
    "create_skill": "skill",
    # 数据库（只读查询本平台数据）
    "db_schema": "db",
    "db_query": "db",
    # 界面
    "show_user_card": "ui",
}


def register_tool_group(
    name: str,
    title: str,
    description: str,
    *,
    eager: bool = False,
) -> None:
    """注册一个工具组，供「按组按需加载」使用。

    这是「往组里加工具」的另一半：本函数只登记组的展示信息与加载时机，工具
    通过 ``@business_tool(group=...)`` 声明归属，两者在启动校验里对齐（见
    ``registry``：任一工具的分组必须已登记，否则导入即失败）。

    ``eager=True`` 表示该组不参与按需加载、每轮都绑定；默认 ``False``（异步
    加载：由模型调 ``load_tool_group`` 或入口预取触发）。
    """

    key = (name or "").strip()
    if not key:
        raise ValueError("工具组名不能为空")
    if key in TOOL_GROUP_META:
        raise RuntimeError(f"工具组 {key} 已注册，不能重复注册")
    if not title or not description:
        raise ValueError(f"工具组 {key} 缺少标题或说明")
    TOOL_GROUP_META[key] = (title, description)
    if eager:
        EAGER_TOOL_GROUPS.add(key)


# 「数据库」组：db_schema / db_query 两个只读查库工具。默认异步加载（不 eager），
# 与其它业务组一致：等模型调 load_tool_group 或入口预取命中时才绑定。
register_tool_group(
    "db",
    "数据库",
    "只读查询本平台数据：查看表结构与执行只读 SQL",
)
