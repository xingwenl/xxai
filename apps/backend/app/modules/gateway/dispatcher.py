"""网关模型循环内的运行时工具分发。"""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from jsonschema import ValidationError, validate

from app.core.logging import get_logger
from app.modules.asset.repositories import AssetRepository
from app.modules.builtin_tool.repositories import BuiltinToolRepository
from app.modules.builtin_tool.registry import get_builtin_tool
from app.modules.builtin_tool.services import invoke_builtin_tool
from app.modules.host_tool.repositories import HostToolRepository
from app.modules.host_tool.services import (
    canonical_fingerprint,
    redact_sensitive,
    wait_timeout_seconds,
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
from app.modules.agent_runtime.events import (
    confirmation_required,
    host_tool_call,
    question_required,
)
from app.modules.tool_approval.contracts import (
    CONFIRMATION_EXPIRED,
    CONFIRMATION_TTL_SECONDS,
    NAVIGATION_SIDE_EFFECT,
    REMEMBERED_APPROVAL,
    USER_REJECTED,
    ConfirmationDecision,
)
from app.modules.tool_approval.services import ToolApprovalService
from app.modules.tools.side_effects import coerce_side_effect

# 单次请求允许模型提问的次数上限，防止模型滥用提问替代正常回复。
MAX_QUESTIONS_PER_REQUEST = 3
# 问题等待用户回答的超时时间（秒），超时后注入结果让模型自行收尾。
QUESTION_TIMEOUT_SECONDS = 600.0
# 日志里工具参数/错误信息的最长字符数，避免一条日志被超长快照撑爆。
LOG_SUMMARY_LIMIT = 300

logger = get_logger(__name__)


def summarize_for_log(value: object, *, limit: int = LOG_SUMMARY_LIMIT) -> str:
    """把任意工具参数或结果压缩成有界字符串，供排障日志使用。"""

    try:
        encoded = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        encoded = str(value)
    return encoded if len(encoded) <= limit else f"{encoded[:limit]}…"


def host_tool_outcome_log_fields(result: object) -> tuple[int, str, str]:
    """提取宿主工具日志需要的字段：结果字节数、错误码、错误信息。

    页面回传的失败结果是 ``{"error", "code", "message"}`` 形状，直接看
    日志即可区分“页面没回结果（超时）”和“页面回了失败原因”。
    """

    try:
        size = len(json.dumps(result, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        size = -1
    if not isinstance(result, dict):
        return size, "", ""
    code = str(result.get("code") or ("host_tool_failed" if "error" in result else ""))
    message = str(result.get("message") or result.get("error") or "")
    return size, code, message[:LOG_SUMMARY_LIMIT]


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
                # 运行记录由 stream_embed_chat 创建后回填到 context；
                # 委派类工具据此把子运行挂到本次运行下。
                loop_run_id=getattr(self.context, "loop_run_id", None),
                # 有副作用的工具在执行前回到这里弹确认卡：闸口在
                # ``invoke_builtin_tool`` 内部，确认链路则复用本连接已有的等待通道。
                confirmation_decider=self._decide_builtin_confirmation,
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

    async def _decide_builtin_confirmation(self, tool, call) -> ConfirmationDecision:
        """内置工具的执行前裁决：先查会话内记忆，否则弹确认卡等页面回传。

        与 MCP 确认共用 ``pending_mcp_confirmations`` 这条连接级等待通道：连接层
        只按 ``callId`` 回传布尔结果、不关心工具来源，所以这里不必让连接层再多持有
        一份状态（字典名沿用历史命名）。落库、过期与「会话内记住同类工具」都由
        ``tool_approval`` 模块负责，本方法只做事件往返与裁决翻译。
        """

        tool_name = str(getattr(tool, "name", "") or "")
        # 以注册表定义为准，避免传入的 tool 对象带着过期的副作用声明。
        definition = get_builtin_tool(tool_name)
        side_effect = coerce_side_effect(
            getattr(definition or tool, "side_effect", "none")
        )
        arguments = dict(call.get("args") or {})
        call_id = str(call.get("id") or f"{self.request_id}_{tool_name}")
        conversation_id = getattr(self.context, "conversation_id", None)
        if side_effect == "navigation":
            # navigation 只影响宿主页面的路由、不落数据，交互式运行按已确认的
            # 策略直通（只有 write / external / financial 才弹卡）。无人值守侧
            # 仍由 UnattendedPolicy 裁决，因为内置工具闸口不区分副作用类型。
            return ConfirmationDecision(approved=True, reason=NAVIGATION_SIDE_EFFECT)
        approval = ToolApprovalService(self.session)
        if conversation_id is not None and await approval.remember_check(
            platform_id=self.platform_id,
            conversation_id=int(conversation_id),
            tool_name=tool_name,
            side_effect=side_effect,
        ):
            # 会话内刚刚批准过同类工具，直接复用那次批准，不再重复打扰用户。
            return ConfirmationDecision(
                approved=True,
                reason=REMEMBERED_APPROVAL,
                message="该工具在本会话中已被批准过，本次直接执行。",
            )
        confirmation = await approval.request(
            platform_id=self.platform_id,
            agent_id=self.agent_id,
            conversation_id=(
                int(conversation_id) if conversation_id is not None else None
            ),
            tool_name=tool_name,
            tool_type="builtin_tool",
            side_effect=side_effect,
            arguments=arguments,
            platform_end_user_id=self.end_user_id,
        )
        decision = asyncio.get_running_loop().create_future()
        self.pending_mcp_confirmations[call_id] = decision
        expires_at = getattr(confirmation, "expires_at", None)
        # 事件入队后等待连接层回传裁决；模型 Task 暂停期间连接主循环仍可接收
        # confirmation_resolve 并设置 Future，避免死锁。
        await self.event_queue.put(
            confirmation_required(
                conversation_id=None,
                request_id=self.request_id,
                call_id=call_id,
                name=tool_name,
                tool_type="builtin_tool",
                side_effect=side_effect,
                arguments=arguments,
                expires_at=expires_at.isoformat() if expires_at else None,
                confirmation_id=getattr(confirmation, "id", None),
            )
        )
        try:
            approved = await asyncio.wait_for(
                decision,
                timeout=wait_timeout_seconds(
                    expires_at, default=float(CONFIRMATION_TTL_SECONDS)
                ),
            )
        except asyncio.TimeoutError:
            await approval.expire(confirmation_id=confirmation.id)
            return ConfirmationDecision(
                approved=False,
                reason=CONFIRMATION_EXPIRED,
                message="工具确认已超时，工具未执行",
            )
        finally:
            self.pending_mcp_confirmations.pop(call_id, None)
        resolved = await approval.resolve(
            confirmation_id=confirmation.id,
            approved=bool(approved),
            actor="end_user",
        )
        if getattr(resolved, "status", None) == "approved":
            return ConfirmationDecision(approved=True)
        # 走到这里只剩「被拒绝」与「已过期」两种终态，回给模型的原因码要区分开：
        # 拒绝是明确表态，超时可能只是人不在。
        expired = getattr(resolved, "status", None) == "expired"
        return ConfirmationDecision(
            approved=False,
            reason=CONFIRMATION_EXPIRED if expired else USER_REJECTED,
            message=(
                "工具确认已超时，工具未执行"
                if expired
                else "用户拒绝执行该工具，请勿自动重试"
            ),
        )

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
            question_required(
                conversation_id=None,
                request_id=self.request_id,
                question_id=question_id,
                question=str(arguments["question"]),
                description=(
                    str(arguments["description"])
                    if arguments.get("description")
                    else None
                ),
                options=options,
                allow_free_text=bool(arguments.get("allowFreeText", True)),
                require_selection=bool(arguments.get("requireSelection", True)),
                expires_at=expires_at.isoformat(),
            )
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
        # 与宿主工具共用同一套时间归一化：MCP 确认过期时间同样来自数据库。
        timeout_seconds = wait_timeout_seconds(expires_at, default=600.0)
        await self.event_queue.put(
            confirmation_required(
                conversation_id=None,
                request_id=self.request_id,
                call_id=call_id,
                name=tool.name,
                tool_type="mcp_tool",
                side_effect=tool.side_effect,
                # 参数由事件构造器统一脱敏，这里传入原始参数。
                arguments=arguments,
                expires_at=(expires_at.isoformat() if expires_at else None),
            )
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
        started_at = datetime.now(UTC)
        existing = await self.host_tool_repo.get_call(
            call_id,
            platform_id=self.platform_id,
            agent_id=self.agent_id,
            end_user_id=self.end_user_id,
        )
        if existing is not None:
            # 终态调用直接复用历史结果，避免页面函数被重复执行。
            if existing.arguments_fingerprint != canonical_fingerprint(arguments):
                # 同一 callId 携带不同参数说明模型重试或页面重放，必须留痕，
                # 否则模型只会看到一句“工具执行失败”而无从定位。
                logger.error(
                    "Host tool call id reused with different arguments request_id=%s call_id=%s tool=%s audit_status=%s",
                    self.request_id,
                    call_id,
                    tool.name,
                    existing.status,
                )
                raise ValueError(
                    "host tool call id reused with different arguments"
                )
            if existing.status in {
                "succeeded",
                "failed",
                "rejected",
                "expired",
            }:
                logger.info(
                    "Host tool audit reused request_id=%s call_id=%s tool=%s audit_status=%s result=%s",
                    self.request_id,
                    call_id,
                    tool.name,
                    existing.status,
                    summarize_for_log(existing.result),
                )
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
                # 列类型是 TIMESTAMP WITH TIME ZONE：必须写入带时区的 UTC 值。
                # asyncpg 对 timestamptz 使用 ``obj.astimezone(utc)`` 编码，传入
                # naive 值会被当成**本地时间**，让过期时间整整差一个时区偏移。
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
            )
        future = self.pending_host_results.get(call_id)
        if future is None:
            future = asyncio.get_running_loop().create_future()
            self.pending_host_results[call_id] = future
            # 关键排障日志：注册时打印仍在等待的 callId 集合，便于和页面回传的
            # callId 对照，也能与下面的 released 日志拼出完整的 Future 生命周期。
            logger.info(
                "Host tool future registered request_id=%s call_id=%s tool=%s pending_keys=%s",
                self.request_id,
                call_id,
                tool.name,
                sorted(self.pending_host_results),
            )
        else:
            logger.warning(
                "Host tool reused pending future request_id=%s call_id=%s tool=%s",
                self.request_id,
                call_id,
                tool.name,
            )
        try:
            # 与 MCP 确认、ask_user 一样，host tool 等待必须有服务端上限，否则
            # 页面或用户确认永不响应时请求会无界挂起。等待时长直接沿用审计已
            # 写入的 expires_at（当前 10 分钟），不引入第二套超时配置；时间
            # 单位换算必须走 wait_timeout_seconds，避免 naive/aware 相减抛错。
            timeout_seconds = wait_timeout_seconds(
                getattr(existing, "expires_at", None), default=600.0
            )
            if timeout_seconds <= 0:
                # 审计行的过期时间已经在过去：等待会立即超时，页面结果必然被
                # 当成迟到结果丢弃。时间列写入口径（aware/naive）出错时就是这
                # 一行，因此把原始 expires_at 一起打出来。
                logger.warning(
                    "Host tool wait window already expired request_id=%s call_id=%s tool=%s audit_status=%s expires_at=%s now_utc=%s",
                    self.request_id,
                    call_id,
                    tool.name,
                    existing.status,
                    getattr(existing, "expires_at", None),
                    datetime.now(UTC),
                )
            # 关键排障日志：一行内同时给出 callId、工具名、是否需要确认、审计
            # 状态、等待上限和参数摘要；此后要么出现 Host tool completed/
            # failed，要么页面没回结果只能靠 Host tool wait timed out 定位。
            logger.info(
                "Host tool dispatched request_id=%s call_id=%s tool=%s side_effect=%s requires_confirmation=%s audit_status=%s wait_timeout_seconds=%.1f args=%s",
                self.request_id,
                call_id,
                tool.name,
                tool.side_effect,
                existing.status == "awaiting_confirmation",
                existing.status,
                timeout_seconds,
                summarize_for_log(redact_sensitive(arguments)),
            )
            await self.event_queue.put(
                host_tool_call(
                    conversation_id=None,
                    request_id=self.request_id,
                    call_id=call_id,
                    name=tool.name,
                    arguments=arguments,
                    side_effect=tool.side_effect,
                    requires_confirmation=existing.status
                    == "awaiting_confirmation",
                )
            )
            try:
                # 此处只暂停模型 Task；WebSocket 主循环仍可接收结果并唤醒
                # Future。wait_for 超时会取消底层 Future，模型 Task 取消也会
                # 经 finally 清理，避免 pending_host_results 残留。
                result = await asyncio.wait_for(future, timeout=timeout_seconds)
            except asyncio.TimeoutError:
                logger.warning(
                    "Host tool wait timed out request_id=%s call_id=%s tool=%s waited_seconds=%.1f",
                    self.request_id,
                    call_id,
                    tool.name,
                    timeout_seconds,
                )
                result = await self._expire_host_wait(call_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            # 工具执行链路的异常会被 AgentRuntime 归一成 failed 步骤，若不在这里
            # 记录堆栈，前端只会显示“执行失败”，无法区分是数据库、审计还是超时。
            logger.exception(
                "Host tool invocation failed request_id=%s call_id=%s tool=%s",
                self.request_id,
                call_id,
                tool.name,
            )
            raise
        finally:
            released = self.pending_host_results.pop(call_id, None) is not None
            if not future.done():
                future.cancel()
            # 关键排障日志：这一行说明 Future 何时、是否被回收；页面随后回传的
            # 结果若找不到 callId，就能在这里看到它已经被释放。
            logger.info(
                "Host tool future released request_id=%s call_id=%s tool=%s released=%s pending_keys=%s",
                self.request_id,
                call_id,
                tool.name,
                released,
                sorted(self.pending_host_results),
            )
        duration_ms = int((datetime.now(UTC) - started_at).total_seconds() * 1000)
        result_size, error_code, error_message = host_tool_outcome_log_fields(result)
        if error_code:
            logger.warning(
                "Host tool failed request_id=%s call_id=%s tool=%s error_code=%s error_message=%s result_bytes=%s duration_ms=%s",
                self.request_id,
                call_id,
                tool.name,
                error_code,
                error_message,
                result_size,
                duration_ms,
            )
        else:
            logger.info(
                "Host tool completed request_id=%s call_id=%s tool=%s result_bytes=%s duration_ms=%s",
                self.request_id,
                call_id,
                tool.name,
                result_size,
                duration_ms,
            )
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
            logger.info(
                "Host tool wait expired but page already succeeded request_id=%s call_id=%s",
                self.request_id,
                call_id,
            )
            return dict(getattr(fresh, "result", None) or {})
        if status in {"failed", "rejected", "expired"}:
            # 页面回调与超时竞争时，Future 可能已被 wait_for 取消，结果只能
            # 从审计终态恢复，不能凭空生成第二次成功结果。
            logger.warning(
                "Host tool wait expired with terminal audit request_id=%s call_id=%s audit_status=%s audit_error=%s",
                self.request_id,
                call_id,
                status,
                getattr(fresh, "error", None),
            )
            return {
                "error": "host_tool_failed",
                "code": "host_tool_execution_failed",
                "message": str(getattr(fresh, "error", None) or "宿主工具已结束"),
            }
        if status == "awaiting_confirmation":
            await self.host_tool_repo.transition_call(fresh, "expired")
            logger.warning(
                "Host tool confirmation expired request_id=%s call_id=%s audit_status=%s",
                self.request_id,
                call_id,
                status,
            )
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
        logger.warning(
            "Host tool execution timed out waiting for page result request_id=%s call_id=%s audit_status=%s",
            self.request_id,
            call_id,
            status,
        )
        return {
            "error": "host_tool_failed",
            "code": "host_tool_execution_timeout",
            "message": "宿主工具执行超时，未收到页面结果",
        }
