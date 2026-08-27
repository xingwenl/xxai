"""统一调用入口：只依赖两个公共注册页。"""

from app.modules.tools.business.framework import BusinessToolContext
from app.modules.tools.business.registry import get_business_tool


async def invoke_business_tool(
    tool_name: str,
    args: dict,
    ctx: BusinessToolContext,
) -> dict:
    tool = get_business_tool(tool_name)
    if tool is None:
        return {
            "status": "failed",
            "result": {"error": {"code": "tool_not_available"}},
        }
    try:
        return {"status": "completed", "result": await tool.handler(args, ctx)}
    except Exception as exc:  # 兜底：不向 LLM 泄漏未捕获异常
        code = exc.code if hasattr(exc, "code") else "tool_failed"
        return {"status": "failed", "result": {"error": {"code": code}}}
