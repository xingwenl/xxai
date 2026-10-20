"""本地开发用 ai-agent.v1 最小服务端（mock agent）。

用途：在没有 AI Base 后端的情况下打通「全局助手 → 宿主工具桥 → 记账子应用」全链路，
让 DESKTOP_DEV_AGENT=1 的桌面端可以端到端联调与自动化验收。

刻意只用规则式意图解析、不接 LLM：它验证的是 WebSocket 契约与工具调用链，
而不是模型能力；生产环境不会挂载本模块。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from desktop_app.app_config import APP_VERSION

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = 1
# 与 apps/ai-sdk/src/core/websocket.ts 中客户端请求的子协议保持一致
PROTOCOL_SUBPROTOCOL = "ai-agent.v1"

# 本地开发固定会话参数：宿主前端通过 /api/desktop/agent-config 读取后交给 ai-sdk
DEV_TOKEN = "dev-local-token"
DEV_AGENT_ID = "local"
DEV_PLATFORM_ID = "desktop"
DEV_AGENT_DISPLAY_NAME = "记账助手（本地开发）"
WS_PATH = "/api/v1/ws/agents/{agent_id}"

AUTH_TIMEOUT_SECONDS = 5.0
TOOL_TIMEOUT_SECONDS = 15.0

# 金额解析：优先带「元/块/钱」的写法，其次任意数字（最多两位小数）
_AMOUNT_WITH_UNIT = re.compile(r"(\d+(?:\.\d{1,2})?)\s*(?:元|块|钱|rmb|RMB)")
_AMOUNT_ANY = re.compile(r"(\d+(?:\.\d{1,2})?)")
_MONTH = re.compile(r"(\d{4})-(\d{1,2})")

_INCOME_KEYWORDS = ("收入", "工资", "奖金", "收到", "进账", "报销", "赚了")
_SUMMARY_KEYWORDS = ("汇总", "花了多少", "支出多少", "总支出", "总收入", "结余", "余额", "统计", "花了")
_LIST_KEYWORDS = ("明细", "列表", "账单", "最近", "查一下", "记录")
_ADD_KEYWORDS = ("记", "花", "买了", "支出", "收入", "收到")

# 分类关键词命中表：命中即用，未命中归入「其他」/「其他收入」
_CATEGORY_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("餐饮", ("午饭", "晚饭", "早饭", "午餐", "晚餐", "早餐", "吃饭", "咖啡", "奶茶", "外卖", "餐", "火锅", "零食")),
    ("交通", ("打车", "地铁", "公交", "加油", "停车", "高铁", "机票", "共享单车")),
    ("购物", ("购物", "买", "衣服", "鞋", "超市", "快递")),
    ("居住", ("房租", "水费", "电费", "物业", "燃气")),
    ("娱乐", ("电影", "游戏", "唱歌", "演出", "旅游")),
    ("医疗", ("医院", "药", "体检", "挂号")),
    ("学习", ("书", "课程", "学费", "培训")),
    ("工资", ("工资", "薪水")),
    ("奖金", ("奖金", "红包", "补贴")),
    ("理财", ("理财", "利息", "基金", "股票")),
)


def _now_iso() -> str:
    """生成与后端一致的 ISO-8601 UTC 时间字符串。"""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def is_enabled_by_env(environ: dict[str, str] | None = None) -> bool:
    """读取 DESKTOP_DEV_AGENT 环境变量，判定是否启用本地 mock 网关。"""
    source = environ if environ is not None else os.environ
    return source.get("DESKTOP_DEV_AGENT", "").strip().lower() in {"1", "true", "yes", "on"}


class DevToolError(Exception):
    """宿主工具执行失败（对应 host_tool_error 帧）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _to_number(value: Any) -> float:
    """把工具返回值中的数字安全转为 float（容忍字符串与缺失值）。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _fmt_money(value: Any) -> str:
    """按「¥123.45」格式展示金额。"""
    return f"¥{_to_number(value):.2f}"


def _guess_category(text: str, income: bool) -> str:
    """从自然语言里猜一个分类；猜不到用「其他」或「其他收入」。"""
    for category, keywords in _CATEGORY_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return category
    return "其他收入" if income else "其他"


def _parse_month(text: str) -> str | None:
    """解析形如 2026-10 的月份；「上个月」返回上月，未提及返回 None。"""
    match = _MONTH.search(text)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        if 1 <= month <= 12:
            return f"{year:04d}-{month:02d}"
    if "上个月" in text or "上月" in text:
        today = datetime.now()
        year, month = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
        return f"{year:04d}-{month:02d}"
    return None


class DevAgentConnection:
    """单条 WebSocket 连接的协议状态与事件发送。"""

    def __init__(self, websocket: WebSocket) -> None:
        self._ws = websocket
        self._sequence = 0
        self._conversation_id: str | None = None
        self.tools: dict[str, dict[str, Any]] = {}
        self._pending: dict[str, asyncio.Future[Any]] = {}
        self._turn: asyncio.Task[None] | None = None
        self._closed = False

    async def send(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        request_id: str | None = None,
        conversation_id: str | None = None,
    ) -> None:
        """按 ai-agent.v1 信封发送一条服务端事件（sequence 严格递增）。"""
        if self._closed:
            return
        self._sequence += 1
        envelope: dict[str, Any] = {
            "id": uuid.uuid4().hex,
            "type": event_type,
            "protocolVersion": PROTOCOL_VERSION,
            "sequence": self._sequence,
            "timestamp": _now_iso(),
            "payload": payload,
        }
        if request_id:
            envelope["requestId"] = request_id
        cid = conversation_id or self._conversation_id
        if cid:
            envelope["conversationId"] = cid
        await self._ws.send_json(envelope)

    async def close(self, code: int, reason: str) -> None:
        """关闭连接并释放挂起的工具调用。"""
        self._closed = True
        self._cancel_turn()
        for future in self._pending.values():
            if not future.done():
                future.cancel()
        self._pending.clear()
        try:
            await self._ws.close(code=code, reason=reason)
        except RuntimeError:
            # 连接已由对端关闭，忽略重复关闭
            pass

    def _cancel_turn(self) -> None:
        if self._turn and not self._turn.done():
            self._turn.cancel()

    # ---------- 消息循环 ----------

    async def serve(self) -> None:
        """接收并分发客户端帧，直到连接关闭。"""
        try:
            while True:
                raw = await self._ws.receive_text()
                try:
                    frame = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("mock agent 收到非法 JSON 帧，已忽略")
                    continue
                await self._handle_frame(frame)
        except WebSocketDisconnect:
            pass
        finally:
            self._closed = True
            self._cancel_turn()
            for future in self._pending.values():
                if not future.done():
                    future.cancel()
            self._pending.clear()

    async def _handle_frame(self, frame: dict[str, Any]) -> None:
        frame_type = frame.get("type")
        payload = frame.get("payload") if isinstance(frame.get("payload"), dict) else {}
        if frame_type == "host_tools_register":
            tools = payload.get("tools")
            if isinstance(tools, list):
                self.tools = {
                    str(item["name"]): item
                    for item in tools
                    if isinstance(item, dict) and isinstance(item.get("name"), str)
                }
                logger.info("mock agent 收到宿主工具注册: %s", sorted(self.tools))
            return
        if frame_type in {"host_tool_result", "host_tool_error"}:
            call_id = str(payload.get("callId") or "")
            future = self._pending.pop(call_id, None)
            if future is None or future.done():
                return
            if frame_type == "host_tool_result":
                future.set_result(payload.get("result"))
            else:
                future.set_exception(
                    DevToolError(
                        str(payload.get("code") or "host_tool_execution_failed"),
                        str(payload.get("message") or "工具执行失败"),
                    )
                )
            return
        if frame_type == "message_send":
            request_id = str(frame.get("requestId") or uuid.uuid4().hex)
            text = payload.get("text")
            text = text if isinstance(text, str) else ""
            # 同一会话只保留一轮进行中的回答，新消息打断旧轮次（与后端取消语义一致）
            self._cancel_turn()
            self._turn = asyncio.create_task(self._run_turn(request_id, text))
            return
        if frame_type == "message_cancel":
            self._cancel_turn()
            return
        if frame_type in {"confirmation_resolve", "question_answer", "ping"}:
            # 本地网关不产生确认/提问；ping 由客户端主动发起时回 pong 便于排查
            if frame_type == "ping":
                await self.send("pong", {})
            return
        logger.info("mock agent 忽略未知帧: %s", frame_type)

    # ---------- 一轮对话 ----------

    async def _run_turn(self, request_id: str, text: str) -> None:
        try:
            await self.send("message_started", {}, request_id=request_id)
            reply = await self._compose_reply(text)
            await self._stream_reply(request_id, reply)
        except asyncio.CancelledError:
            raise
        except Exception:  # 兜底：任何异常都转成一条可读回复，避免 UI 一直转圈
            logger.exception("mock agent 处理对话失败")
            await self._stream_reply(request_id, "本地助手处理出错了，请查看桌面端日志。")

    async def _stream_reply(self, request_id: str, reply: str) -> None:
        """把回复切成若干片段流式下发，最后补一条 message_completed。"""
        chunk_size = 24
        for index in range(0, len(reply), chunk_size):
            await self.send("message_delta", {"content": reply[index : index + chunk_size]}, request_id=request_id)
            await asyncio.sleep(0.01)
        await self.send("message_completed", {"content": reply}, request_id=request_id)

    async def _compose_reply(self, text: str) -> str:
        """按关键词选择工具并生成回复；工具未注册时给出可执行引导。"""
        amount = self._parse_amount(text)
        income = any(keyword in text for keyword in _INCOME_KEYWORDS)
        month = _parse_month(text)

        if amount is not None and any(keyword in text for keyword in _ADD_KEYWORDS):
            return await self._add_entry(text, amount, income)
        if any(keyword in text for keyword in _LIST_KEYWORDS):
            return await self._list_entries(month, income)
        if any(keyword in text for keyword in _SUMMARY_KEYWORDS):
            return await self._month_summary(month)
        return await self._help()

    @staticmethod
    def _parse_amount(text: str) -> float | None:
        match = _AMOUNT_WITH_UNIT.search(text) or _AMOUNT_ANY.search(text)
        if not match:
            return None
        value = float(match.group(1))
        return value if value > 0 else None

    def _pick_tool(self, *keywords: str) -> str | None:
        """按名称关键词挑一个已注册的宿主工具。"""
        for name in sorted(self.tools):
            if all(keyword in name for keyword in keywords):
                return name
        return None

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """向宿主发起工具调用并等待结果。"""
        call_id = uuid.uuid4().hex
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self._pending[call_id] = future
        await self.send(
            "host_tool_call",
            {
                "callId": call_id,
                "name": name,
                "arguments": arguments,
                "requiresConfirmation": False,
            },
        )
        try:
            return await asyncio.wait_for(future, timeout=TOOL_TIMEOUT_SECONDS)
        except asyncio.TimeoutError as exc:
            self._pending.pop(call_id, None)
            raise DevToolError("host_tool_timeout", "工具调用超时，请确认记账子应用已打开") from exc

    async def _add_entry(self, text: str, amount: float, income: bool) -> str:
        tool = self._pick_tool("add", "entry")
        if tool is None:
            return self._missing_tool_reply("记账")
        category = _guess_category(text, income)
        note = re.sub(r"\s+", " ", text).strip()
        try:
            result = await self._call_tool(
                tool,
                {
                    "type": "income" if income else "expense",
                    "amount": amount,
                    "category": category,
                    "note": note[:100],
                },
            )
        except DevToolError as exc:
            return self._tool_error_reply(tool, exc)
        entry = result.get("entry") if isinstance(result, dict) else None
        if not isinstance(entry, dict):
            return f"已执行 {tool}，但返回结果格式异常。"
        type_label = "收入" if entry.get("type") == "income" else "支出"
        occurred_on = str(entry.get("occurred_on") or "")
        month_summary = result.get("month_summary") if isinstance(result, dict) else None
        month_summary = month_summary if isinstance(month_summary, dict) else None
        reply = (
            f"已记账：{occurred_on} {entry.get('category', category)} {_fmt_money(entry.get('amount_yuan', amount))}"
            f"（{type_label}）。"
        )
        if month_summary:
            reply += (
                f"\n本月支出 {_fmt_money(month_summary.get('expense_yuan'))}，"
                f"收入 {_fmt_money(month_summary.get('income_yuan'))}，"
                f"结余 {_fmt_money(month_summary.get('balance_yuan'))}。"
            )
        return reply

    async def _list_entries(self, month: str | None, income: bool) -> str:
        tool = self._pick_tool("list", "entr")
        if tool is None:
            return self._missing_tool_reply("记账")
        arguments: dict[str, Any] = {"limit": 10}
        if month:
            arguments["month"] = month
        if income:
            arguments["type"] = "income"
        try:
            result = await self._call_tool(tool, arguments)
        except DevToolError as exc:
            return self._tool_error_reply(tool, exc)
        items = result.get("items") if isinstance(result, dict) else None
        items = items if isinstance(items, list) else []
        total = result.get("total") if isinstance(result, dict) else len(items)
        if not items:
            return "这段时间还没有记账记录。"
        lines = ["最近的记录："]
        for item in items[:10]:
            if not isinstance(item, dict):
                continue
            label = "收入" if item.get("type") == "income" else "支出"
            lines.append(
                f"· {item.get('occurred_on', '')} {item.get('category', '')} "
                f"{label} {_fmt_money(item.get('amount_yuan'))} {item.get('note', '')}".rstrip()
            )
        lines.append(f"共 {total} 条（最多显示 10 条）。")
        return "\n".join(lines)

    async def _month_summary(self, month: str | None) -> str:
        tool = self._pick_tool("summary")
        if tool is None:
            return self._missing_tool_reply("记账")
        arguments: dict[str, Any] = {}
        if month:
            arguments["month"] = month
        try:
            result = await self._call_tool(tool, arguments)
        except DevToolError as exc:
            return self._tool_error_reply(tool, exc)
        if not isinstance(result, dict):
            return f"已执行 {tool}，但返回结果格式异常。"
        reply = (
            f"{result.get('month', month or '本月')} 支出 {_fmt_money(result.get('expense_yuan'))}，"
            f"收入 {_fmt_money(result.get('income_yuan'))}，"
            f"结余 {_fmt_money(result.get('balance_yuan'))}。"
        )
        by_category = result.get("by_category")
        if isinstance(by_category, list) and by_category:
            top = [item for item in by_category if isinstance(item, dict) and _to_number(item.get("expense_yuan")) > 0][:3]
            if top:
                detail = "、".join(f"{item.get('category', '')} {_fmt_money(item.get('expense_yuan'))}" for item in top)
                reply += f"\n支出前三：{detail}。"
        return reply

    async def _help(self) -> str:
        if not self.tools:
            return (
                "我还没有拿到记账子应用提供的方法。请先在桌面端打开「记账」应用，再回来问我；"
                "打开后可以直接说：今天午饭花了 35 块 / 本月支出汇总 / 最近的记账明细。"
            )
        return (
            "我是记账助手（本地开发模式，规则式回复）。可以这样说：\n"
            "· 今天午饭花了 35 块\n"
            "· 本月支出汇总\n"
            "· 最近的记账明细"
        )

    @staticmethod
    def _missing_tool_reply(app_name: str) -> str:
        return f"还没有拿到{app_name}子应用提供的方法，请先在桌面端打开「记账」应用后再试。"

    @staticmethod
    def _tool_error_reply(tool: str, error: DevToolError) -> str:
        return f"调用 {tool} 失败（{error.code}）：{error.message}"


def session_payload() -> dict[str, Any]:
    """返回本地网关的连接参数（宿主前端与 dev-agent/session 接口共用）。"""
    return {
        "enabled": True,
        "mode": "dev",
        "endpoint": f"/api/v1/ws/agents/{DEV_AGENT_ID}",
        "platformId": DEV_PLATFORM_ID,
        "agentId": DEV_AGENT_ID,
        "token": DEV_TOKEN,
        "displayName": DEV_AGENT_DISPLAY_NAME,
        "version": APP_VERSION,
    }


def register_dev_agent(app: FastAPI) -> None:
    """把本地 mock 网关注册到 FastAPI 应用（仅 DESKTOP_DEV_AGENT 开启时调用）。"""

    @app.get("/api/desktop/dev-agent/session")
    def dev_agent_session() -> dict[str, Any]:
        """返回本地网关连接参数，供宿主前端组装 ai-sdk 客户端。"""
        return session_payload()

    @app.websocket("/api/v1/ws/agents/{agent_id}")
    async def dev_agent_socket(websocket: WebSocket, agent_id: str) -> None:
        """实现 ai-agent.v1 的最小握手、工具调用与流式回复。"""
        await websocket.accept(subprotocol=PROTOCOL_SUBPROTOCOL)
        connection = DevAgentConnection(websocket)
        try:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=AUTH_TIMEOUT_SECONDS)
            auth = json.loads(raw)
            payload = auth.get("payload") if isinstance(auth.get("payload"), dict) else {}
            if auth.get("type") != "auth":
                await connection.close(4401, "expected auth frame")
                return
            if payload.get("protocolVersion") != PROTOCOL_VERSION:
                await connection.send(
                    "error",
                    {
                        "code": "unsupported_protocol_version",
                        "message": f"本地网关仅支持协议版本 {PROTOCOL_VERSION}",
                        "details": {"supported": PROTOCOL_VERSION},
                    },
                )
                await connection.close(4406, "unsupported protocol version")
                return
            token = payload.get("token")
            if not isinstance(token, str) or not token:
                await connection.close(4401, "missing token")
                return
            session_id = f"dev-{uuid.uuid4().hex[:12]}"
            connection._conversation_id = session_id
            await connection.send(
                "session_ready",
                {
                    "sessionId": session_id,
                    "client": {"id": "desktop-dev", "name": "桌面助手（本地开发）"},
                    "agent": {"id": 1, "name": DEV_AGENT_DISPLAY_NAME},
                },
            )
            logger.info("mock agent 会话就绪: agent_id=%s session=%s", agent_id, session_id)
            await connection.serve()
        except asyncio.TimeoutError:
            await connection.close(4408, "auth timeout")
        except (WebSocketDisconnect, json.JSONDecodeError):
            pass
        except Exception:  # 兜底，避免异常帧打断整个网关
            logger.exception("mock agent 连接异常")
            await connection.close(1011, "internal error")
