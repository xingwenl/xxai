"""店铺运营项目（shop）工具注册页：按层收集，导入即注册。

- data 层：查询/操作店铺运营平台数据的工具；
- ui 层：把数据渲染成前端组件的展示工具。
"""

from app.modules.tools.shop.data import order_query  # noqa: F401  导入即注册
from app.modules.tools.shop.data import product_query  # noqa: F401  导入即注册
from app.modules.tools.shop.data import store_ops_query  # noqa: F401  导入即注册
from app.modules.tools.shop.ui import show_shop_list  # noqa: F401  导入即注册
