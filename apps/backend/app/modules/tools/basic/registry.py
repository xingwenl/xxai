"""基本工具公共注册页：只负责收集注册，保持简洁。

新增基本工具 = 新建一个文件（定义 + handler 同页）+ 在这里加一行 import。
"""

from app.modules.tools.basic import http_get  # noqa: F401  导入即注册
from app.modules.tools.basic import http_post  # noqa: F401
from app.modules.tools.basic import image_gen  # noqa: F401
from app.modules.tools.basic import vision  # noqa: F401
from app.modules.tools.basic.framework import BASIC_TOOL_REGISTRY


def list_basic_tools():
    return list(BASIC_TOOL_REGISTRY.values())


def get_basic_tool(name: str):
    return BASIC_TOOL_REGISTRY.get(name)
