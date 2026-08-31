"""knowledge_search 业务工具单测：注册契约、权限隔离、检索路径与返回契约。"""

import asyncio
from types import SimpleNamespace

import pytest

from app.modules.tools.business.framework import (
    BusinessToolContext,
    BusinessToolError,
)
from app.modules.tools.business.registry import get_business_tool
from app.modules.tools.business import knowledge_search
from app.shared.exceptions import BadRequestException


class FakeKnowledgeRepo:
    """只实现业务工具用到的两个方法：启用列表与向量检索。"""

    def __init__(self, bases=None, search_results=None):
        self.bases = bases or []
        self.search_results = search_results or {}

    async def list_enabled_for_agent(self, agent_id, platform_id):
        return self.bases

    async def search(self, base, embedding, limit=None):
        results = self.search_results.get(base.id, [])
        return results if limit is None else results[:limit]


def _base(base_id, name="产品手册", dimension=3, threshold=0.5):
    return SimpleNamespace(
        id=base_id,
        name=name,
        embedding_dimension=dimension,
        retrieval_top_k=5,
        retrieval_threshold=threshold,
    )


def _chunk(document_id, content, position=1, title="安装指南", source_url=None):
    return SimpleNamespace(
        document_id=document_id,
        content=content,
        position=position,
        source_metadata={"title": title, "source_url": source_url},
    )


def _ctx(repo, **kwargs) -> BusinessToolContext:
    values = dict(
        platform_id=1,
        agent_id=2,
        conversation_id=3,
        session=SimpleNamespace(),
    )
    values.update(kwargs)
    return BusinessToolContext(**values)


def _run(args, repo, ctx, monkeypatch, *, embedding=None):
    if embedding is None:
        embedding = [0.1, 0.2, 0.3]

    class FakeModel:
        async def aget_query_embedding(self, query):
            return embedding

    monkeypatch.setattr(
        knowledge_search, "build_embedding_model", lambda _base: FakeModel()
    )
    monkeypatch.setattr(knowledge_search, "KnowledgeRepository", lambda _session: repo)
    tool = get_business_tool("knowledge_search")
    return tool.handler(args, ctx)


def test_registered_and_contract_disambiguated():
    tool = get_business_tool("knowledge_search")
    assert tool is not None
    assert tool.name == "knowledge_search"
    assert "知识库" in tool.description
    assert "attachment_search" in tool.description
    assert tool.input_schema["required"] == ["query"]
    assert tool.input_schema["properties"]["query"]["maxLength"] == 500

    attachment = get_business_tool("attachment_search")
    assert "knowledge_search" in attachment.description


def test_search_missing_query_rejected(monkeypatch):
    repo = FakeKnowledgeRepo([_base(1)])
    with pytest.raises(BusinessToolError) as exc:
        asyncio.run(_run({"query": "   "}, repo, _ctx(repo), monkeypatch))
    assert str(exc.value) == "invalid_arguments"


def test_search_no_knowledge_base(monkeypatch):
    repo = FakeKnowledgeRepo([])
    with pytest.raises(BusinessToolError) as exc:
        asyncio.run(_run({"query": "条款"}, repo, _ctx(repo), monkeypatch))
    assert str(exc.value) == "no_knowledge_base"


def test_search_base_not_available(monkeypatch):
    repo = FakeKnowledgeRepo([_base(1)])
    with pytest.raises(BusinessToolError) as exc:
        asyncio.run(
            _run(
                {"query": "条款", "knowledge_base_id": 9},
                repo,
                _ctx(repo),
                monkeypatch,
            )
        )
    assert str(exc.value) == "knowledge_base_not_available"


def test_search_base_id_limits_to_one_base(monkeypatch):
    repo = FakeKnowledgeRepo(
        bases=[_base(1), _base(2, name="合规手册")],
        search_results={
            1: [(_chunk(10, "产品手册片段", 2), 0.8)],
            2: [(_chunk(20, "合规手册片段", 1), 0.9)],
        },
    )

    result = asyncio.run(
        _run(
            {"query": "条款", "knowledge_base_id": 2},
            repo,
            _ctx(repo),
            monkeypatch,
        )
    )

    assert result["base_count"] == 1
    assert len(result["results"]) == 1
    assert result["results"][0]["knowledge_base_name"] == "合规手册"
    assert result["results"][0]["document_id"] == 20


def test_search_aggregates_sorted_dedup_and_contract(monkeypatch):
    repo = FakeKnowledgeRepo(
        bases=[_base(1), _base(2)],
        search_results={
            1: [
                (_chunk(10, "低相关片段", 1), 0.55),
                (
                    _chunk(11, "高相关片段", 2, title="FAQ", source_url="https://x"),
                    0.92,
                ),
            ],
            2: [(_chunk(11, "高相关片段", 2, title="FAQ"), 0.9)],
        },
    )

    result = asyncio.run(
        _run(
            {"query": "相关", "limit": 2},
            repo,
            _ctx(repo),
            monkeypatch,
        )
    )

    assert result["kind"] == "knowledge_search"
    assert result["query"] == "相关"
    assert result["base_count"] == 2
    assert len(result["results"]) == 2
    assert result["results"][0]["score"] == 0.92
    assert result["results"][1]["score"] == 0.55
    # 同一文档同一内容跨库去重，只保留一次
    titles = [item["title"] for item in result["results"]]
    assert titles.count("FAQ") == 1
    item = result["results"][0]
    assert item["knowledge_base_id"] == 1
    assert item["knowledge_base_name"] == "产品手册"
    assert item["document_id"] == 11
    assert item["source_url"] == "https://x"
    assert item["position"] == 2
    assert item["content"] == "高相关片段"


def test_search_threshold_filtering(monkeypatch):
    repo = FakeKnowledgeRepo(
        bases=[_base(1, threshold=0.6)],
        search_results={
            1: [
                (_chunk(10, "低于阈值", 1), 0.4),
                (_chunk(11, "高于阈值", 2), 0.75),
            ]
        },
    )

    result = asyncio.run(_run({"query": "条款"}, repo, _ctx(repo), monkeypatch))

    assert len(result["results"]) == 1
    assert result["results"][0]["content"] == "高于阈值"


def test_search_embedding_dimension_mismatch_propagates(monkeypatch):
    repo = FakeKnowledgeRepo([_base(1, dimension=2)])

    with pytest.raises(BadRequestException):
        asyncio.run(_run({"query": "条款"}, repo, _ctx(repo), monkeypatch))
