"""业务工具公共注册页：只负责收集注册，保持简洁。

统一入口聚合通用 business 工具与店铺运营项目（shop）分层工具，
对外 API（list_business_tools / get_business_tool）保持稳定。
"""

from app.modules.tools.basic.registry import get_basic_tool
from app.modules.tools.business import http_get  # noqa: F401  导入即注册
from app.modules.tools.business import http_post  # noqa: F401
from app.modules.tools.business import image_generate  # noqa: F401
from app.modules.tools.business import image_read  # noqa: F401
from app.modules.tools.business import attachment_search  # noqa: F401
from app.modules.tools.business import knowledge_search  # noqa: F401
from app.modules.tools.business import custom_component  # noqa: F401
from app.modules.tools.business import runtime_info  # noqa: F401
from app.modules.tools.business import create_task  # noqa: F401
from app.modules.tools.business import create_skill  # noqa: F401
from app.modules.tools.business import delegate_tasks  # noqa: F401
from app.modules.tools.shop import registry as _shop_registry  # noqa: F401
from app.modules.tools.business.framework import (
    BUSINESS_TOOL_REGISTRY,
    validate_business_tool_dependencies,
)

# 启动即校验依赖完整性与副作用声明一致性，有问题直接报错（快速失败）。
_problems = validate_business_tool_dependencies(get_basic_tool)
if _problems:
    raise RuntimeError(f"business tool declarations invalid: {'; '.join(_problems)}")


def list_business_tools():
    return list(BUSINESS_TOOL_REGISTRY.values())


def get_business_tool(name: str):
    return BUSINESS_TOOL_REGISTRY.get(name)
