"""网关流式请求的 Session / 模型 Task 生命周期回归测试。

背景：模型循环跑在 `AgentRuntime.stream` 内部用 `asyncio.create_task` 启动的
独立 Task 中。当消费方提前结束事件流（流内 error 事件、结果为空、取消或断连）
时，内层生成器的 finally 不保证执行，模型 Task 会继续提交数据库；此时请求级
Session 若先 `close()`，就会抛出 SQLAlchemy 的 `IllegalStateChangeError`。

因此 `produce_embed_request` 必须在退出 `async with`（关闭 Session）之前，显式
join 由 `on_model_task_started` 登记的模型 Task。
"""

import asyncio
from types import SimpleNamespace

from app.modules.gateway import router as gateway_router


class RecordingSession:
    """记录 open/close 顺序的假 Session，用于断言释放时序。"""

    def __init__(self, name: str, timeline: list[str]) -> None:
        self.name = name
        self.timeline = timeline
        self.closed = False

    async def __aenter__(self):
        self.timeline.append(f"{self.name}:open")
        return self

    async def __aexit__(self, *exc_info):
        self.timeline.append(f"{self.name}:close")
        self.closed = True
        return False


def test_early_stream_end_joins_model_task_before_closing_sessions(monkeypatch):
    """流内提前结束后，必须先 join 模型 Task 再关闭 Session。"""

    async def scenario():
        timeline: list[str] = []
        created_sessions: list[RecordingSession] = []
        model_tasks: list[asyncio.Task] = []

        def session_factory():
            def create() -> RecordingSession:
                session = RecordingSession(
                    f"session-{len(created_sessions)}", timeline
                )
                created_sessions.append(session)
                return session

            return create

        monkeypatch.setattr(gateway_router, "get_session_factory", session_factory)

        context = SimpleNamespace(
            version=object(),
            agent=SimpleNamespace(id=1),
            knowledge_bases=[],
            builtin_tools=[],
            mcp_tools=[],
            skill_script_tools=[],
            skill_instruction_tool=None,
            conversation_id=None,
            host_tools=None,
        )

        async def fake_load_runtime_context(*args, **kwargs):
            return context

        async def fake_retrieve_citations(*args, **kwargs):
            return []

        monkeypatch.setattr(
            gateway_router, "load_runtime_context", fake_load_runtime_context
        )
        monkeypatch.setattr(
            gateway_router, "retrieve_citations", fake_retrieve_citations
        )
        monkeypatch.setattr(
            gateway_router, "build_chat_model", lambda *args, **kwargs: object()
        )

        # 对话主模型解析要查库；本用例只关心释放时序，固定返回 None（回落 .env 默认值）。
        async def fake_resolve_chat_model(*args, **kwargs):
            return None

        monkeypatch.setattr(
            gateway_router, "resolve_chat_model", fake_resolve_chat_model
        )
        monkeypatch.setattr(
            gateway_router,
            "RuntimeToolDispatcher",
            lambda **kwargs: SimpleNamespace(invoke=None),
        )

        task_started = asyncio.Event()

        async def model_task():
            try:
                task_started.set()
                await asyncio.sleep(60)
            finally:
                # 模型 Task 自己的清理（例如工具 Session 上的最后一次提交）必须先于
                # Session 关闭完成。
                timeline.append("model-task:cleanup")

        async def fake_stream_embed_chat(
            *args, on_model_task_started=None, **kwargs
        ):
            assert on_model_task_started is not None
            task = asyncio.create_task(model_task())
            on_model_task_started(task)
            model_tasks.append(task)
            # 等模型 Task 真正开始执行，才符合"消费方提前退出时内层仍在跑"的场景。
            await task_started.wait()
            # 只有 error 事件就提前 return：模拟 runtime 流在中途失败收尾。
            yield {"type": "error", "payload": {"code": "boom", "message": "失败"}}

        monkeypatch.setattr(
            gateway_router, "stream_embed_chat", fake_stream_embed_chat
        )

        event_queue: asyncio.Queue = asyncio.Queue()
        await gateway_router.produce_embed_request(
            request_id="req-1",
            message={"text": "你好"},
            agent_id=1,
            payload={"platform_id": 2, "client_id": "client", "sub": 3},
            event_queue=event_queue,
            pending_mcp_confirmations={},
            pending_host_results={},
            pending_questions={},
            registered_host_tools=set(),
            registered_host_policies={},
        )

        assert len(model_tasks) == 1
        assert model_tasks[0].done(), "请求收尾必须 join 内层模型 Task"
        assert len(created_sessions) == 2, "请求级 Session 与工具 Session 都应创建"
        assert all(session.closed for session in created_sessions)
        assert "model-task:cleanup" in timeline
        # 关键断言：模型 Task 清理完成早于任意一个 Session 关闭。
        first_close = timeline.index("session-1:close")
        assert timeline.index("model-task:cleanup") < first_close

    asyncio.run(scenario())
