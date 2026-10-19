"""REST/SSE 流式对话「工具执行独立 Session」的回归测试。

背景：模型循环跑在 `AgentRuntime.stream` 内部启动的独立 Task 中，工具调用与
消费方的会话/消息落库如果共用一个 `AsyncSession`，会触发 SQLAlchemy 并发
状态错误（`another operation is in progress` / `close()` 与 `commit()` 相撞）。

修复方式：请求级 Session 只服务消费方，工具执行改用独立 Session。这里锁定两个
关键点：
1. `_prepare` 生成的 `invoke` 闭包把工具仓库与 `session` 参数都绑定到工具 Session；
2. 工具 Session 能看到请求 Session 已提交的数据（跨连接可见性假设）。

注意：分派逻辑已抽到 `app.modules.conversation.tool_dispatch`（供无人值守任务
复用），因此这里 patch 的是分派模块里的执行器符号；断言仍然落在
「工具执行必须绑定独立 Session」这一保证上。
"""

import asyncio
from types import SimpleNamespace

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.modules.agent.models import Agent
from app.modules.conversation import router as conversation_router
from app.modules.conversation import tool_dispatch
from app.modules.conversation.models import Conversation, ConversationMessage
from app.modules.conversation.schemas import ChatRequest
from app.modules.embed.models import PlatformEndUser
from app.modules.platform.models import Platform
from app.shared.base_model import BaseModel


def _record_sessions(monkeypatch, name: str, calls: list):
    """把仓库类替换成记录 Session 的替身，返回构造出的替身列表。"""

    created: list = []

    def factory(session):
        stub = SimpleNamespace(session=session)
        created.append(stub)
        calls.append((name, session))
        return stub

    return factory, created


def test_prepare_binds_tool_execution_to_tool_session(monkeypatch):
    """`_prepare` 的工具分支必须使用独立 Session，而不是请求级 Session。"""

    async def scenario():
        request_session = object()
        tool_session = object()
        calls: list = []

        agent = SimpleNamespace(platform_id=7)
        context = SimpleNamespace(knowledge_bases=[], conversation_id=99)

        class AgentRepo:
            def __init__(self, session):
                self.session = session

            async def get_published_agent_for_user(self, agent_id, user_id):
                return agent

        builtin_factory, builtin_created = _record_sessions(
            monkeypatch, "builtin", calls
        )
        skill_factory, skill_created = _record_sessions(monkeypatch, "skill", calls)
        mcp_factory, mcp_created = _record_sessions(monkeypatch, "mcp", calls)

        monkeypatch.setattr(conversation_router, "AgentRepository", AgentRepo)
        monkeypatch.setattr(
            conversation_router,
            "KnowledgeRepository",
            lambda session: SimpleNamespace(session=session),
        )
        monkeypatch.setattr(conversation_router, "SkillRepository", skill_factory)
        monkeypatch.setattr(conversation_router, "McpRepository", mcp_factory)
        monkeypatch.setattr(
            conversation_router, "BuiltinToolRepository", builtin_factory
        )
        monkeypatch.setattr(
            conversation_router,
            "load_runtime_context",
            lambda *args, **kwargs: _async_result(context),
        )
        monkeypatch.setattr(
            conversation_router,
            "retrieve_citations",
            lambda *args, **kwargs: _async_result([]),
        )

        builtin_calls: list[dict] = []
        skill_calls: list[dict] = []
        mcp_calls: list[dict] = []

        async def fake_builtin(repo, asset_repo, *, session, **kwargs):
            builtin_calls.append({"repo": repo, "asset": asset_repo, "session": session})
            return {"ok": True}

        async def fake_skill_script(repo, client, **kwargs):
            skill_calls.append({"repo": repo})
            return {"ok": True}

        async def fake_skill_instruction(repo, *args, **kwargs):
            return SimpleNamespace(status="completed", content="指引")

        async def fake_mcp(repo, executor, **kwargs):
            mcp_calls.append({"repo": repo, "executor": executor})
            return {"ok": True}

        # 分派逻辑在 tool_dispatch 里，执行器符号也要 patch 到那边。
        monkeypatch.setattr(tool_dispatch, "invoke_builtin_tool", fake_builtin)
        monkeypatch.setattr(tool_dispatch, "execute_skill_script", fake_skill_script)
        monkeypatch.setattr(
            tool_dispatch, "load_bound_skill_instruction", fake_skill_instruction
        )
        monkeypatch.setattr(tool_dispatch, "invoke_tool", fake_mcp)
        # 本用例只关心工具 Session 绑定：对话主模型解析走真实实现会查库，
        # 这里固定返回 None（等于该 Agent 未绑定模型，回落 .env 默认值）。
        monkeypatch.setattr(
            conversation_router,
            "resolve_chat_model",
            lambda *args, **kwargs: _async_result(None),
        )
        monkeypatch.setattr(
            tool_dispatch, "AssetRepository",
            lambda session: SimpleNamespace(session=session),
        )

        current_user = SimpleNamespace(id=5)
        _, _, _, invoke, _ = await conversation_router._prepare(
            1,
            ChatRequest(message="你好"),
            current_user,
            request_session,
            tool_session=tool_session,
        )

        await invoke(
            tool=SimpleNamespace(kind="builtin", name="demo"),
            call={"id": "c1", "args": {}},
        )
        assert builtin_calls[0]["session"] is tool_session
        assert builtin_calls[0]["asset"].session is tool_session
        assert builtin_calls[0]["repo"] is builtin_created[-1]

        await invoke(
            tool=SimpleNamespace(kind="skill_script", name="skill"),
            call={"id": "c2", "args": {}},
        )
        assert skill_calls[0]["repo"] is skill_created[-1]

        await invoke(
            tool=SimpleNamespace(kind="skill_instruction", name="guide"),
            call={"id": "c3", "args": {"slug": "guide"}},
        )
        assert skill_created[-1].session is tool_session

        await invoke(
            tool=SimpleNamespace(server_id=3, name="mcp_tool"),
            call={"id": "c4", "args": {}},
        )
        assert mcp_calls[0]["repo"] is mcp_created[-1]
        assert mcp_created[-1].session is tool_session

        # 加载运行时上下文仍走请求级 Session（首个 BuiltinToolRepository），
        # 但进入 invoke 的工具仓库必须全部绑定工具 Session。
        assert builtin_created[0].session is request_session
        assert builtin_created[-1].session is tool_session
        assert skill_created[-1].session is tool_session
        assert mcp_created[-1].session is tool_session

    asyncio.run(scenario())


async def _async_result(value):
    return value


def test_tool_session_sees_only_committed_request_data(tmp_path):
    """工具 Session 是独立连接：已提交数据可见，未提交写入不可见。"""

    async def run():
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{tmp_path / 'tool-session.db'}"
        )
        async with engine.begin() as connection:
            await connection.run_sync(BaseModel.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with (
                factory() as request_session,
                factory() as tool_session,
            ):
                platform = Platform(name="Acme", code="acme")
                request_session.add(platform)
                await request_session.flush()
                agent = Agent(
                    platform_id=platform.id, name="Support", slug="support"
                )
                end_user = PlatformEndUser(
                    platform_id=platform.id, external_user_id="eu_1"
                )
                request_session.add_all([agent, end_user])
                await request_session.flush()
                conversation = Conversation(
                    platform_id=platform.id,
                    agent_id=agent.id,
                    platform_end_user_id=end_user.id,
                    title="你好",
                )
                request_session.add(conversation)
                await request_session.commit()

                # 已提交的会话对工具 Session 可见，工具执行才拿得到会话上下文。
                visible = await tool_session.get(Conversation, conversation.id)
                assert visible is not None
                assert visible.title == "你好"

                # 未提交的写入对工具 Session 不可见：工具只能依赖已提交数据，
                # 这也正是修复后必须保证"消费方先落库、再执行工具"的原因。
                pending = ConversationMessage(
                    conversation_id=conversation.id,
                    role="user",
                    content="未提交",
                )
                request_session.add(pending)
                await request_session.flush()
                assert (
                    await tool_session.get(ConversationMessage, pending.id) is None
                )
        finally:
            await engine.dispose()

    asyncio.run(run())
