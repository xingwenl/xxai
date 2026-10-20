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
        self.last_search_kwargs = None

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
        self.last_search_kwargs = kwargs
        return self.search_results.get(kwargs["asset_id"], [])[: kwargs["limit"]]

    async def count_chunks(self, **kwargs):
        asset_id = kwargs["asset_id"]
        # 显式配置了 chunks_by_asset 时以它为准：向量检索用例会用
        # search_results=[] 模拟“低于阈值被过滤”，此时切块其实存在。
        if asset_id in self.chunks_by_asset:
            return len(self.chunks_by_asset[asset_id])
        return len(self.search_results.get(asset_id, []))


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


class FakeEmbeddingModel:
    """返回固定维度查询向量；fail=True 时模拟 embedding 服务不可用。"""

    def __init__(self, *, dim=2, fail=False):
        self.dim = dim
        self.fail = fail

    async def aget_query_embedding(self, query):
        if self.fail:
            raise RuntimeError("embedding service unavailable")
        return [0.1] * self.dim


async def _run(
    args,
    ctx,
    monkeypatch,
    *,
    embedding_enabled=False,
    embedding_fail=False,
    embedding_dim=2,
    min_score=0.5,
):
    async def _no_model(*_args, **_kwargs):
        return None

    monkeypatch.setattr(attachment_search, "resolve_agent_model", _no_model)
    monkeypatch.setattr(
        attachment_search,
        "attachment_embedding_enabled",
        lambda _model_config: embedding_enabled,
    )
    if embedding_enabled:
        monkeypatch.setattr(
            attachment_search,
            "build_attachment_embedding_model",
            lambda _model_config: FakeEmbeddingModel(
                dim=embedding_dim, fail=embedding_fail
            ),
        )
    monkeypatch.setattr(
        attachment_search,
        "get_settings",
        lambda: SimpleNamespace(
            attachment_embedding_dimension=2,
            attachment_retrieval_min_score=min_score,
        ),
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


def test_search_reports_no_text_extracted(monkeypatch):
    """解析标 ready 但没有切块（文件未抽出文本）时必须返回原因，而不是空数组。"""
    repo = FakeAssetRepo([_asset("doc-1")])
    processing = FakeProcessingRepo(ready_ids=["doc-1"], chunks_by_asset={})
    monkeypatch.setattr(
        attachment_search, "AssetProcessingRepository", lambda _s: processing
    )

    result = asyncio.run(_run({"query": "总成绩"}, _ctx(repo), monkeypatch))

    assert result["results"] == []
    assert result["reason"] == "asset_not_searchable"
    assert result["skipped"] == [
        {"filename": "doc-1.pdf", "reason": "no_text_extracted"}
    ]


def test_search_reports_no_document_asset(monkeypatch):
    """会话里只有图片时说明没有可检索文档，而不是报“没有匹配”。"""
    repo = FakeAssetRepo([_asset("img-1", content_type="image/png")])
    processing = FakeProcessingRepo(ready_ids=["img-1"])
    monkeypatch.setattr(
        attachment_search, "AssetProcessingRepository", lambda _s: processing
    )

    result = asyncio.run(_run({"query": "内容"}, _ctx(repo), monkeypatch))

    assert result["results"] == []
    assert result["reason"] == "no_document_asset"


def test_search_no_match_keeps_reason(monkeypatch):
    repo = FakeAssetRepo([_asset("doc-1")])
    processing = FakeProcessingRepo(
        ready_ids=["doc-1"],
        chunks_by_asset={"doc-1": [_chunk(0, "完全无关的内容", 1)]},
    )
    monkeypatch.setattr(
        attachment_search, "AssetProcessingRepository", lambda _s: processing
    )

    result = asyncio.run(_run({"query": "不存在的关键词"}, _ctx(repo), monkeypatch))

    assert result["reason"] == "no_match"
    assert result["skipped"] == [{"filename": "doc-1.pdf", "reason": "no_match"}]


def test_search_marks_truncated_long_chunk(monkeypatch):
    """单块超过上限时截断，并用 truncated 标记，避免误以为原文就这么长。"""
    long_text = "总成绩" + "x" * (attachment_search.SEARCH_CHUNK_MAX_CHARS + 100)
    repo = FakeAssetRepo([_asset("doc-1")])
    processing = FakeProcessingRepo(
        ready_ids=["doc-1"], chunks_by_asset={"doc-1": [_chunk(0, long_text, 1)]}
    )
    monkeypatch.setattr(
        attachment_search, "AssetProcessingRepository", lambda _s: processing
    )

    result = asyncio.run(_run({"query": "总成绩"}, _ctx(repo), monkeypatch))

    item = result["results"][0]
    assert item["truncated"] is True
    assert len(item["content"]) == attachment_search.SEARCH_CHUNK_MAX_CHARS


def test_search_default_limit_matches_schema(monkeypatch):
    """默认返回条数与 input_schema 上限一致，且不超过默认条数。"""
    repo = FakeAssetRepo([_asset("doc-1")])
    processing = FakeProcessingRepo(
        ready_ids=["doc-1"],
        chunks_by_asset={
            "doc-1": [_chunk(i, f"总成绩命中 {i}", 1) for i in range(20)]
        },
    )
    monkeypatch.setattr(
        attachment_search, "AssetProcessingRepository", lambda _s: processing
    )

    result = asyncio.run(_run({"query": "总成绩"}, _ctx(repo), monkeypatch))

    assert len(result["results"]) == attachment_search.DEFAULT_SEARCH_LIMIT
    schema = get_business_tool("attachment_search").input_schema
    assert schema["properties"]["limit"]["maximum"] == attachment_search.MAX_SEARCH_LIMIT
    assert (
        str(attachment_search.DEFAULT_SEARCH_LIMIT)
        in schema["properties"]["limit"]["description"]
    )


def test_search_passes_relevance_threshold_to_repository(monkeypatch):
    """向量检索必须把相关度下限传给仓储，否则低分片段会凑数返回。"""
    repo = FakeAssetRepo([_asset("doc-1")])
    processing = FakeProcessingRepo(ready_ids=["doc-1"])
    processing.search_results = {"doc-1": [(_chunk(0, "向量命中", 1), 0.8)]}
    monkeypatch.setattr(
        attachment_search, "AssetProcessingRepository", lambda _s: processing
    )

    result = asyncio.run(
        _run(
            {"query": "总成绩"},
            _ctx(repo),
            monkeypatch,
            embedding_enabled=True,
            min_score=0.42,
        )
    )

    assert processing.last_search_kwargs["min_score"] == 0.42
    assert result["results"][0]["match"] == "vector"


def test_search_falls_back_to_keyword_when_vector_filtered_out(monkeypatch):
    """向量结果被阈值过滤干净后，应退回词法检索而不是直接返回空。"""
    repo = FakeAssetRepo([_asset("doc-1")])
    processing = FakeProcessingRepo(
        ready_ids=["doc-1"],
        chunks_by_asset={"doc-1": [_chunk(0, "总成绩 72.86", 1)]},
    )
    # 向量链路模拟“全部低于阈值”：仓储返回空列表
    processing.search_results = {"doc-1": []}
    monkeypatch.setattr(
        attachment_search, "AssetProcessingRepository", lambda _s: processing
    )

    result = asyncio.run(
        _run({"query": "总成绩"}, _ctx(repo), monkeypatch, embedding_enabled=True)
    )

    assert len(result["results"]) == 1
    assert result["results"][0]["match"] == "keyword"


def test_search_falls_back_to_keyword_when_embedding_fails(monkeypatch):
    """embedding 服务不可用时检索不能整体失败，应退回词法检索。"""
    repo = FakeAssetRepo([_asset("doc-1")])
    processing = FakeProcessingRepo(
        ready_ids=["doc-1"],
        chunks_by_asset={"doc-1": [_chunk(0, "总成绩 72.86", 1)]},
    )
    monkeypatch.setattr(
        attachment_search, "AssetProcessingRepository", lambda _s: processing
    )

    result = asyncio.run(
        _run(
            {"query": "总成绩"},
            _ctx(repo),
            monkeypatch,
            embedding_enabled=True,
            embedding_fail=True,
        )
    )

    assert len(result["results"]) == 1
    assert result["results"][0]["match"] == "keyword"


def test_search_no_match_when_vector_and_keyword_both_empty(monkeypatch):
    """向量被阈值过滤且词法也不命中时，才报 no_match。"""
    repo = FakeAssetRepo([_asset("doc-1")])
    processing = FakeProcessingRepo(
        ready_ids=["doc-1"],
        chunks_by_asset={"doc-1": [_chunk(0, "完全无关的内容", 1)]},
    )
    processing.search_results = {"doc-1": []}
    monkeypatch.setattr(
        attachment_search, "AssetProcessingRepository", lambda _s: processing
    )

    result = asyncio.run(
        _run({"query": "股票行情"}, _ctx(repo), monkeypatch, embedding_enabled=True)
    )

    assert result["results"] == []
    assert result["reason"] == "no_match"
