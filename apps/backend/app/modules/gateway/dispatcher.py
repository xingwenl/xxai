"""网关模型循环内的运行时工具分发。"""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from jsonschema import ValidationError, validate

from app.modules.asset.repositories import AssetRepository
from app.modules.builtin_tool.repositories import BuiltinToolRepository
from app.modules.builtin_tool.registry import get_builtin_tool
from app.modules.builtin_tool.services import invoke_builtin_tool
from app.modules.host_tool.repositories import HostToolRepository
from app.modules.host_tool.services import (
    canonical_fingerprint,
    redact_sensitive,
    utc_naive_now,
)
from app.modules.mcp.repositories import McpRepository
from app.modules.mcp.runtime import RepositoryMcpExecutor
from app.modules.mcp.services import (
    expire_tool_confirmation,
    invoke_tool,
    resolve_tool_confirmation,
)
from app.modules.skill.repositories import SkillRepository
from app.modules.skill.services import load_bound_skill_instruction
from app.modules.skill_runner.client import SkillRunnerClient
from app.modules.skill_runner.services import execute_skill_script
from app.modules.agent_runtime.contracts import ToolCall

# 单次请求允许模型提问的次数上限，防止模型滥用提问替代正常回复。
MAX_QUESTIONS_PER_REQUEST = 3
# 问题等待用户回答的超时时间（秒），超时后注入结果让模型自行收尾。
QUESTION_TIMEOUT_SECONDS = 600.0


class RuntimeToolDispatcher:
    """按工具来源分发一次请求内的运行时工具调用。

    承载模型工具循环里的四类执行路径：MCP 工具（含确认）、内置工具、
    技能脚本/技能指令和宿主工具（含页面确认）。连接级容器（事件队列、
    待确认 Future、宿主工具审计仓库）由 WebSocket 连接层注入，
    分发器自身不持有连接级状态，因此不会绕过 token 和页面注册权限。
    """

    def __init__(
        self,
        *,
        session,
        context,
        request_id: str,
        agent_id: int,
        platform_id: int,
        end_user_id: int,
        event_queue: asyncio.Queue,
        pending_mcp_confirmations: dict[str, asyncio.Future],
        pending_host_results: dict[str, asyncio.Future],
        pending_questions: dict[str, asyncio.Future],
        host_tool_repo: HostToolRepository,
    ) -> None:
        self.session = session
        self.context = context
        self.request_id = request_id
        self.agent_id = agent_id
        self.platform_id = platform_id
        self.end_user_id = end_user_id
        self.event_queue = event_queue
        self.pending_mcp_confirmations = pending_mcp_confirmations
        self.pending_host_results = pending_host_results
        self.pending_questions = pending_questions
        self.host_tool_repo = host_tool_repo
        self.mcp_repo = McpRepository(session)
        self.skill_repo = SkillRepository(session)
        self.builtin_tool_repo = BuiltinToolRepository(session)
        self.mcp_tools_by_key = {
            (tool.server_id, tool.name): tool for tool in context.mcp_tools
        }
        self.loaded_skill_cache: dict[str, object] = {}
        self.mcp_call_sequence = 0
        self.question_sequence = 0

    async def invoke(
        self,
        *,
        tool=None,
        call=None,
        server_id=None,
        tool_name=None,
        arguments=None,
    ):
        """按工具来源分流，并在 MCP 确认后恢复同一模型循环。"""
        if isinstance(call, ToolCall):
            tool_name = tool_name or call.name
            server_id = server_id if server_id is not None else call.server_id
            call = {"id": call.id, "args": call.arguments}
        if tool is None and server_id is not None and tool_name is not None:
            tool = self.mcp_tools_by_key.get((server_id, tool_name))
            self.mcp_call_sequence += 1
            call = {
                "id": f"{self.request_id}_mcp_{self.mcp_call_sequence}",
                "args": arguments or {},
            }
        if tool is None or call is None:
            raise ValueError("runtime tool context is missing")
        if hasattr(tool, "server_id"):
            return await self._invoke_mcp_tool(tool, call)
        if tool.name == "ask_user":
            return await self._invoke_question_tool(tool, call)
        if getattr(tool, "kind", None) == "builtin":
            return await invoke_builtin_tool(
                self.builtin_tool_repo,
                AssetRepository(self.session),
                tool=tool,
                call=call,
                platform_id=self.platform_id,
                agent_id=self.agent_id,
                conversation_id=self.context.conversation_id,
                platform_end_user_id=self.end_user_id,
                session=self.session,
            )
        if getattr(tool, "kind", None) == "skill_script":
            return await execute_skill_script(
                self.skill_repo,
                SkillRunnerClient(),
                tool=tool,
                call=call,
                platform_id=self.platform_id,
                agent_id=self.agent_id,
                platform_end_user_id=self.end_user_id,
                request_id=self.request_id,
            )
        if getattr(tool, "kind", None) == "skill_instruction":
            slug = call.get("args", {}).get("slug")
            if isinstance(slug, str) and slug in self.loaded_skill_cache:
                return self.loaded_skill_cache[slug]
            outcome = await load_bound_skill_instruction(
                self.skill_repo,
                self.platform_id,
                self.agent_id,
                slug,
            )
            if isinstance(slug, str) and outcome.status == "completed":
                self.loaded_skill_cache[slug] = outcome
            return outcome
        return await self._invoke_host_tool(tool, call)

    def supports(self, tool: object) -> bool:
        """声明该执行器可处理网关注册的全部运行时工具。

        来源判断仍在 ``invoke`` 内部完成，因为 MCP 工具需要同时使用
        ``server_id``；对外暴露统一 supports 接口后，Agent runtime 可以把
        网关分发器作为单一 ToolExecutor 注册，而不复制权限和确认逻辑。
        """
        return tool is not None

    async def execute(self, tool, call: ToolCall):
        """实现 agent_runtime 的 ToolExecutor 形状。

        网关原有 ``invoke`` 仍保留给协议层；这个薄适配方法只负责把类型化
        ToolCall 送入同一套权限、确认、审计和页面 Future 流程，避免出现两套
        工具安全实现。
        """

        return await self.invoke(tool=tool, call=call)

    async def _invoke_question_tool(self, tool, call):
        """执行询问工具：发送 question_required 事件并等待用户选择后恢复。"""
        if self.question_sequence >= MAX_QUESTIONS_PER_REQUEST:
            return SimpleNamespace(
                status="completed",
                result={
                    "status": "unavailable",
                    "message": (
                        "已超出单次任务提问上限（3 次），"
                        "请基于现有信息继续，不要再次提问。"
                    ),
                },
            )
        call_id = str(
            call.get("id") or f"{self.request_id}_question_{self.question_sequence}"
        )
        arguments = call.get("args", {})
        definition = get_builtin_tool(tool.name)
        if definition is None:
            return SimpleNamespace(
                status="failed", result={"error": {"code": "tool_not_available"}}
            )
        try:
            validate(instance=arguments, schema=definition.input_schema)
        except ValidationError:
            return SimpleNamespace(
                status="failed", result={"error": {"code": "invalid_arguments"}}
            )

        self.question_sequence += 1
        question_id = call_id
        options = [
            {"id": str(item["id"]), "label": str(item["label"])}
            for item in arguments.get("options") or []
        ]
        expires_at = datetime.now(UTC) + timedelta(seconds=QUESTION_TIMEOUT_SECONDS)
        decision = asyncio.get_running_loop().create_future()
        self.pending_questions[question_id] = decision
        # 事件入队后等待 WebSocket 连接层回传用户答案；模型 Task 暂停期间
        # 连接主循环仍可接收 question_answer 并设置 Future，避免死锁。
        await self.event_queue.put(
            {
                "type": "question_required",
                "conversation_id": None,
                "request_id": self.request_id,
                "question_id": question_id,
                "question": str(arguments["question"]),
                "description": (
                    str(arguments["description"])
                    if arguments.get("description")
                    else None
                ),
                "options": options,
                "allow_free_text": bool(arguments.get("allowFreeText", True)),
                "require_selection": bool(
                    arguments.get("requireSelection", True)
                ),
                "expires_at": expires_at.isoformat(),
            }
        )
        try:
            answer = await asyncio.wait_for(
                decision, timeout=QUESTION_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            answer = {
                "status": "expired",
                "message": "问题等待超时，用户未在时限内回答。",
            }
        finally:
            self.pending_questions.pop(question_id, None)
        return SimpleNamespace(
            status="completed",
            result={"question": str(arguments["question"]), "answer": answer},
        )

    async def _invoke_mcp_tool(self, tool, call):
        """执行 MCP 工具；需要用户确认时先发确认事件并等待连接层结果。"""
        call_id = str(call.get("id") or f"{self.request_id}_{tool.name}")
        arguments = call.get("args", {})
        outcome = await invoke_tool(
            self.mcp_repo,
            RepositoryMcpExecutor(self.mcp_repo),
            platform_id=self.platform_id,
            agent_id=self.agent_id,
            platform_end_user_id=self.end_user_id,
            server_id=tool.server_id,
            tool_name=tool.name,
            arguments=arguments,
        )
        if outcome.status != "confirmation_required":
            return outcome

        decision = asyncio.get_running_loop().create_future()
        self.pending_mcp_confirmations[call_id] = decision
        expires_at = outcome.expires_at
        timeout_seconds = 600.0
        if expires_at is not None:
            timeout_seconds = max(
                0.0,
                (expires_at - datetime.now(UTC)).total_seconds(),
            )
        await self.event_queue.put(
            {
                "type": "confirmation_required",
                "conversation_id": None,
                "request_id": self.request_id,
                "call_id": call_id,
                "name": tool.name,
                "tool_type": "mcp_tool",
                "side_effect": tool.side_effect,
                "arguments": redact_sensitive(arguments),
                "expires_at": (
                    expires_at.isoformat() if expires_at else None
                ),
            }
        )
        try:
            approved = await asyncio.wait_for(
                decision, timeout=timeout_seconds
            )
            resolved = await resolve_tool_confirmation(
                self.mcp_repo,
                RepositoryMcpExecutor(self.mcp_repo),
                confirmation_id=outcome.confirmation_id,
                platform_id=self.platform_id,
                platform_end_user_id=self.end_user_id,
                approved=bool(approved),
            )
        except asyncio.TimeoutError:
            resolved = await expire_tool_confirmation(
                self.mcp_repo,
                confirmation_id=outcome.confirmation_id,
                platform_id=self.platform_id,
                platform_end_user_id=self.end_user_id,
            )
        finally:
            self.pending_mcp_confirmations.pop(call_id, None)

        if resolved.status in {"rejected", "expired"}:
            resolved.result = {
                "status": resolved.status,
                "message": (
                    "用户拒绝执行该工具，请勿自动重试"
                    if resolved.status == "rejected"
                    else "工具确认已超时，工具未执行"
                ),
            }
        return resolved

    async def _invoke_host_tool(self, tool, call):
        """执行宿主工具：先审计落库，再等待页面回传结果并唤醒模型循环。"""
        call_id = str(call.get("id") or f"{self.request_id}_{tool.name}")
        arguments = call.get("args", {})
        existing = await self.host_tool_repo.get_call(
            call_id,
            platform_id=self.platform_id,
            agent_id=self.agent_id,
            end_user_id=self.end_user_id,
        )
        if existing is not None:
            # 终态调用直接复用历史结果，避免页面函数被重复执行。
            if existing.arguments_fingerprint != canonical_fingerprint(arguments):
                raise ValueError(
                    "host tool call id reused with different arguments"
                )
            if existing.status in {
                "succeeded",
                "failed",
                "rejected",
                "expired",
            }:
                return SimpleNamespace(
                    status="completed", result=existing.result
                )
        else:
            # 有副作用且策略要求 always 时先进入确认态；无副作用工具
            # 可直接进入 running，由页面执行后回传结果。
            requires_confirmation = (
                tool.side_effect != "none"
                and tool.confirmation_policy == "always"
            )
            existing = await self.host_tool_repo.create_audit(
                call_id=call_id,
                platform_id=self.platform_id,
                agent_id=self.agent_id,
                platform_end_user_id=self.end_user_id,
                conversation_id=None,
                request_id=self.request_id,
                tool_name=tool.name,
                arguments=redact_sensitive(arguments),
                arguments_fingerprint=canonical_fingerprint(arguments),
                status=(
                    "awaiting_confirmation"
                    if requires_confirmation
                    else "running"
                ),
                expires_at=utc_naive_now() + timedelta(minutes=10),
            )
        future = self.pending_host_results.get(call_id)
        if future is None:
            future = asyncio.get_running_loop().create_future()
            self.pending_host_results[call_id] = future
        await self.event_queue.put(
            {
                "type": "host_tool_call",
                "conversation_id": None,
                "request_id": self.request_id,
                "call_id": call_id,
                "name": tool.name,
                "arguments": arguments,
                "side_effect": tool.side_effect,
                "requires_confirmation": existing.status
                == "awaiting_confirmation",
            }
        )
        # 与 MCP 确认、ask_user 一样，host tool 等待必须有服务端上限，否则
        # 页面或用户确认永不响应时请求会无界挂起。等待时长直接沿用审计已
        # 写入的 expires_at（当前 10 分钟），不引入第二套超时配置。
        timeout_seconds = 600.0
        if existing.expires_at is not None:
            timeout_seconds = max(
                0.0,
                (existing.expires_at - utc_naive_now()).total_seconds(),
            )
        try:
            try:
                # 此处只暂停模型 Task；WebSocket 主循环仍可接收结果并唤醒
                # Future。wait_for 超时会取消底层 Future，模型 Task 取消也会
                # 经 finally 清理，避免 pending_host_results 残留。
                result = await asyncio.wait_for(future, timeout=timeout_seconds)
            except asyncio.TimeoutError:
                result = await self._expire_host_wait(call_id)
        finally:
            self.pending_host_results.pop(call_id, None)
            if not future.done():
                future.cancel()
        if isinstance(result, dict) and "error" in result:
            return SimpleNamespace(status="completed", result=result)
        return SimpleNamespace(status="completed", result=result)

    async def _expire_host_wait(self, call_id: str) -> dict:
        """处理 host tool 等待超时：先重读审计避免覆盖并发终态，再落库。

        超时与页面回调可能在事件循环上交错：页面可能在同一时刻已把审计
        推进到 succeeded/failed。因此这里先重新读取审计；只有仍处于等待或
        运行状态时才执行转换，否则把页面已经写入的终态结果原样返回，避免
        ``transition_call`` 的条件更新行数为 0 而抛出二次解析错误。
        """

        fresh = await self.host_tool_repo.get_call(
            call_id,
            platform_id=self.platform_id,
            agent_id=self.agent_id,
            end_user_id=self.end_user_id,
        )
        status = getattr(fresh, "status", None)
        if status == "succeeded":
            return dict(getattr(fresh, "result", None) or {})
        if status in {"failed", "rejected", "expired"}:
            # 页面回调与超时竞争时，Future 可能已被 wait_for 取消，结果只能
            # 从审计终态恢复，不能凭空生成第二次成功结果。
            return {
                "error": "host_tool_failed",
                "code": "host_tool_execution_failed",
                "message": str(getattr(fresh, "error", None) or "宿主工具已结束"),
            }
        if status == "awaiting_confirmation":
            await self.host_tool_repo.transition_call(fresh, "expired")
            return {
                "error": "host_tool_expired",
                "code": "host_tool_expired",
                "message": "宿主工具确认已超时，工具未执行",
            }
        # running 是当前唯一剩余状态；状态机允许 running -> failed，超时按
        # 失败结果化回填模型，避免请求永久挂起在页面执行阶段。
        await self.host_tool_repo.transition_call(
            fresh, "failed", error="host_tool_execution_timeout"
        )
        return {
            "error": "host_tool_failed",
            "code": "host_tool_execution_timeout",
            "message": "宿主工具执行超时，未收到页面结果",
        }
