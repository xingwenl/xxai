"""向量检索的相关度阈值：SQL 必须带相似度上界，否则低分切块会凑数返回。"""

import asyncio

import pytest
from sqlalchemy.sql.elements import BindParameter

from app.modules.asset_processing.repositories import AssetProcessingRepository


class _EmptyResult:
    """模拟空查询结果，只关心执行了哪条 SQL。"""

    def all(self):
        return []


class _RecordingSession:
    def __init__(self):
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _EmptyResult()


def _search_statement(min_score: float):
    session = _RecordingSession()
    repo = AssetProcessingRepository(session)

    async def _run():
        await repo.search_chunks(
            asset_id=1,
            conversation_id=2,
            processing_id=3,
            embedding=[0.1, 0.2, 0.3, 0.4],
            limit=5,
            min_score=min_score,
        )

    asyncio.run(_run())
    return session.statements[0]


def _where_clauses(statement) -> list:
    clause = statement.whereclause
    return list(getattr(clause, "clauses", [clause]))


def test_threshold_adds_similarity_upper_bound():
    """min_score=0.3 时应追加 distance <= 0.7 的条件。"""
    clauses = _where_clauses(_search_statement(0.3))

    bound = clauses[-1]
    assert isinstance(bound.right, BindParameter)
    assert float(bound.right.value) == pytest.approx(0.7)


def test_zero_threshold_keeps_plain_top_k():
    """不设阈值时不追加过滤条件，保持 Top-K 语义。"""
    filtered = _search_statement(0.3)
    plain = _search_statement(0.0)

    assert len(_where_clauses(filtered)) == len(_where_clauses(plain)) + 1
