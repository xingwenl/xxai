"""attachment_search 业务工具单测：权限隔离、检索路径与返回契约。"""

import asyncio
from types import SimpleNamespace

import pytest

from app.modules.tools.business.framework import (
    BusinessToolContext,
    BusinessToolError,
)
from app.modules.tools.business.registry import get_business_tool
from app.modules.tools.business import attachment_search


class FakeAssetRepo:
    """按 asset_id 索引的会话资源仓库，支持 Embed 与后台用户两种主体。"""

    def __init__(self, assets=None):
        self.assets = {a.asset_id: a for a in (assets or [])}

    async def get_for_embed_conversation(self, asset_id, **kwargs):
        return self.assets.get(asset_id)

    async def get_for_user_conversation(self, asset_id, user_id, conversation_id):
        return self.assets.get(asset_id)

    async def list_for_embed_conversation(self, **kwargs):
        return list(self.assets.values())

    async def list_for_user_conversation(self, user_id, conversation_id):
        return list(self.assets.values())


class FakeProcessingRepo:
    """只实现业务工具用到的三个方法。"""

    def __init__(self, ready_ids, chunks_by_asset=None, search_results=None):
        self.ready_ids = set(ready_ids)
        self.chunks_by_asset = chunks_by_asset or {}
        self.search_results = search_results or {}

    async def get_processing(self, asset_id, conversation_id):
        if asset_id in self.ready_ids:
            return SimpleNamespace(status="ready", id=asset_id)
        return None

    async def search_chunks_keyword(self, **kwargs):
        asset_id = kwargs["asset_id"]
        terms = kwargs["terms"]
        chunks = self.chunks_by_asset.get(asset_id, [])
        scored = []
        for chunk in chunks:
            score = sum(chunk.content.lower().count(t) for t in terms)
            if score > 0:
                scored.append((chunk, round(score / 1000.0, 4)))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[: kwargs["limit"]]

    async def search_chunks(self, **kwargs):
        return self.search_results.get(kwargs["asset_id"], [])[: kwargs["limit"]]


def _chunk(position, content, page_number=None):
    return SimpleNamespace(
        position=position,
        content=content,
        page_number=page_number,
    )


def _asset(asset_id, content_type="application/pdf"):
    return SimpleNamespace(
        id=asset_id,
        asset_id=asset_id,
        filename=f"{asset_id}.pdf",
        content_type=content_type,
        conversation_id=3,
        storage_key=f"{asset_id}.pdf",
        size_bytes=1024,
    )


def _ctx(repo, *, user_id=None, **kwargs) -> BusinessToolContext:
    values = dict(
        platform_id=1,
        agent_id=2,
        conversation_id=3,
        user_id=user_id,
        platform_end_user_id=None if user_id is not None else 7,
        session=SimpleNamespace(),
        asset_repo=repo,
    )
    values.update(kwargs)
    return BusinessToolContext(**values)


async def _run(args, ctx, monkeypatch, *, embedding_enabled=False):
    async def _no_model(*_args, **_kwargs):
        return None

    monkeypatch.setattr(attachment_search, "resolve_agent_model", _no_model)
    monkeypatch.setattr(
        attachment_search,
        "attachment_embedding_enabled",
        lambda _model_config: embedding_enabled,
    )
    if embedding_enabled:
        class FakeModel:
            async def aget_query_embedding(self, query):
                return [0.1, 0.2]

        monkeypatch.setattr(
            attachment_search,
            "build_attachment_embedding_model",
            lambda _model_config: FakeModel(),
        )
        monkeypatch.setattr(
            attachment_search,
            "get_settings",
            lambda: SimpleNamespace(attachment_embedding_dimension=2),
        )
    tool = get_business_tool("attachment_search")
    return await tool.handler(args, ctx)


def test_search_specific_asset_keyword_fallback(monkeypatch):
    asset = _asset("doc-1")
    repo = FakeAssetRepo([asset])
    processing = FakeProcessingRepo(
        ready_ids=["doc-1"],
        chunks_by_asset={
            "doc-1": [
                _chunk(0, "前言与公司介绍", 1),
                _chunk(1, "本季度营收增长 30%，利润率提升", 2),
                _chunk(2, "附录与免责声明", 5),
            ]
        },
    )
    monkeypatch.setattr(
        attachment_search, "AssetProcessingRepository", lambda _s: processing
    )

    result = asyncio.run(
        _run({"query": "营收 利润率"}, _ctx(repo), monkeypatch)
    )

    assert result["kind"] == "attachment_search"
    assert result["asset_count"] == 1
    assert len(result["results"]) == 1
    item = result["results"][0]
    assert item["asset_id"] == "doc-1"
    assert item["filename"] == "doc-1.pdf"
    assert item["position"] == 1
    assert item["page_number"] == 2
    assert "营收增长" in item["content"]
    assert 0 <= item["score"] <= 1


def test_search_all_ready_documents_aggregates(monkeypatch):
    repo = FakeAssetRepo([_asset("doc-1"), _asset("doc-2")])
    processing = FakeProcessingRepo(
        ready_ids=["doc-1"],  # doc-2 未 ready，应被跳过
        chunks_by_asset={
            "doc-1": [_chunk(0, "合同总金额 100 万元", 3)],
            "doc-2": [_chunk(0, "其他内容", 1)],
        },
    )
    monkeypatch.setattr(
        attachment_search, "AssetProcessingRepository", lambda _s: processing
    )

    result = asyncio.run(_run({"query": "合同"}, _ctx(repo), monkeypatch))

    assert result["asset_count"] == 2
    assert [r["asset_id"] for r in result["results"]] == ["doc-1"]


def test_search_uses_embedding_when_enabled(monkeypatch):
    asset = _asset("doc-1")
    repo = FakeAssetRepo([asset])
    processing = FakeProcessingRepo(ready_ids=["doc-1"])
    processing.search_results = {
        "doc-1": [(_chunk(4, "向量命中的片段", 6), 0.9)]
    }
    monkeypatch.setattr(
        attachment_search, "AssetProcessingRepository", lambda _s: processing
    )

    result = asyncio.run(
        _run({"query": "总金额"}, _ctx(repo), monkeypatch, embedding_enabled=True)
    )

    assert len(result["results"]) == 1
    assert result["results"][0]["position"] == 4
    assert result["results"][0]["page_number"] == 6
    assert result["results"][0]["score"] == 0.9


def test_search_rejects_cross_conversation_asset(monkeypatch):
    repo = FakeAssetRepo([])  # 模拟不属于当前会话/主体
    processing = FakeProcessingRepo(ready_ids=[])
    monkeypatch.setattr(
        attachment_search, "AssetProcessingRepository", lambda _s: processing
    )

    with pytest.raises(BusinessToolError) as exc:
        asyncio.run(_run({"query": "内容", "asset_id": "doc-1"}, _ctx(repo), monkeypatch))
    assert str(exc.value) == "asset_not_found"


def test_search_rejects_image_asset(monkeypatch):
    asset = _asset("img-1", content_type="image/png")
    repo = FakeAssetRepo([asset])
    processing = FakeProcessingRepo(ready_ids=["img-1"])
    monkeypatch.setattr(
        attachment_search, "AssetProcessingRepository", lambda _s: processing
    )

    with pytest.raises(BusinessToolError) as exc:
        asyncio.run(_run({"query": "内容", "asset_id": "img-1"}, _ctx(repo), monkeypatch))
    assert str(exc.value) == "asset_not_searchable"


def test_search_user_conversation_path(monkeypatch):
    asset = _asset("doc-1")
    repo = FakeAssetRepo([asset])
    processing = FakeProcessingRepo(
        ready_ids=["doc-1"],
        chunks_by_asset={"doc-1": [_chunk(0, "用户会话内容命中", 1)]},
    )
    monkeypatch.setattr(
        attachment_search, "AssetProcessingRepository", lambda _s: processing
    )

    result = asyncio.run(
        _run({"query": "命中"}, _ctx(repo, user_id=4), monkeypatch)
    )

    assert len(result["results"]) == 1
    assert result["results"][0]["filename"] == "doc-1.pdf"


def test_search_empty_results(monkeypatch):
    asset = _asset("doc-1")
    repo = FakeAssetRepo([asset])
    processing = FakeProcessingRepo(
        ready_ids=["doc-1"],
        chunks_by_asset={"doc-1": [_chunk(0, "完全无关的内容", 1)]},
    )
    monkeypatch.setattr(
        attachment_search, "AssetProcessingRepository", lambda _s: processing
    )

    result = asyncio.run(
        _run({"query": "不存在的关键词"}, _ctx(repo), monkeypatch)
    )

    assert result["results"] == []
    assert result["asset_count"] == 1


def test_search_empty_query_rejected(monkeypatch):
    repo = FakeAssetRepo([])
    processing = FakeProcessingRepo(ready_ids=[])
    monkeypatch.setattr(
        attachment_search, "AssetProcessingRepository", lambda _s: processing
    )

    with pytest.raises(BusinessToolError) as exc:
        asyncio.run(_run({"query": "   "}, _ctx(repo), monkeypatch))
    assert str(exc.value) == "invalid_arguments"
