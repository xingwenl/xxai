import asyncio
from dataclasses import dataclass

from app.modules.quota.service import (
    QuotaDimensions,
    QuotaResource,
    QuotaService,
)


@dataclass
class FakeRedis:
    values: dict[str, int]

    async def check_and_increment(
        self, key: str, limit: int, amount: int, window_seconds: int
    ) -> tuple[bool, int, int]:
        current = self.values.get(key, 0)
        if current + amount > limit:
            return False, current, window_seconds
        self.values[key] = current + amount
        return True, current + amount, window_seconds

    async def check_and_increment_capped(
        self, key: str, limit: int, amount: int, window_seconds: int
    ) -> tuple[int, int, int]:
        current = self.values.get(key, 0)
        updated = min(limit, current + amount)
        self.values[key] = updated
        exceeded = 1 if current + amount > limit else 0
        return updated, window_seconds, exceeded

    async def peek(self, key: str) -> int:
        return self.values.get(key, 0)


class FailingRedis:
    async def check_and_increment(
        self, key: str, limit: int, amount: int, window_seconds: int
    ) -> tuple[bool, int, int]:
        raise RuntimeError("redis unavailable")

    async def check_and_increment_capped(
        self, key: str, limit: int, amount: int, window_seconds: int
    ) -> tuple[int, int, int]:
        raise RuntimeError("redis unavailable")

    async def peek(self, key: str) -> int:
        raise RuntimeError("redis unavailable")


def dimensions(**overrides: str) -> QuotaDimensions:
    values = {
        "platform_id": "platform-1",
        "client_id": "client-1",
        "agent_id": "agent-1",
        "end_user_id": "user-1",
    }
    values.update(overrides)
    return QuotaDimensions(**values)


def test_quota_isolated_by_all_principal_dimensions():
    async def scenario():
        service = QuotaService(
            FakeRedis({}),
            limits={"message": 1},
            window_seconds={"message": 60},
        )

        first = await service.check("message", dimensions())
        same_principal = await service.check("message", dimensions())
        other_user = await service.check(
            "message", dimensions(end_user_id="user-2")
        )

        assert first.allowed is True
        assert same_principal.code == "quota_exceeded"
        assert same_principal.allowed is False
        assert other_user.allowed is True

    asyncio.run(scenario())


def test_each_resource_has_an_independent_window():
    async def scenario():
        service = QuotaService(
            FakeRedis({}),
            limits={"message": 1, "connection": 1},
            window_seconds={"message": 60, "connection": 60},
        )

        await service.check("message", dimensions())
        connection = await service.check("connection", dimensions())

        assert connection.allowed is True

    asyncio.run(scenario())


def test_redis_failure_fails_closed_with_stable_code():
    async def scenario():
        service = QuotaService(
            FailingRedis(),
            limits={"message": 1},
            window_seconds={"message": 60},
        )

        decision = await service.check("message", dimensions())

        assert decision.allowed is False
        assert decision.code == "quota_unavailable"
        assert decision.retryable is True

    asyncio.run(scenario())


def test_quota_resource_is_restricted_to_supported_values():
    assert set(QuotaResource.__args__) == {
        "token_issue",
        "connection",
        "message",
        "model_tokens",
    }


def test_model_tokens_capped_consume_saturates_and_peek_blocks():
    async def scenario():
        service = QuotaService(
            FakeRedis({}),
            limits={"model_tokens": 10},
            window_seconds={"model_tokens": 60},
        )

        first = await service.consume_capped(
            "model_tokens", dimensions(), amount=8
        )
        assert first.exceeded is False
        assert first.current == 8

        over = await service.consume_capped(
            "model_tokens", dimensions(), amount=8
        )
        assert over.exceeded is True
        assert over.current == 10

        peek = await service.peek("model_tokens", dimensions())
        assert peek.allowed is False
        assert peek.code == "quota_exceeded"
        assert peek.retryable is True
        assert peek.current == 10
        assert peek.limit == 10
        assert peek.retry_after_seconds is not None

    asyncio.run(scenario())


def test_model_tokens_peek_allows_below_limit():
    async def scenario():
        service = QuotaService(
            FakeRedis({}),
            limits={"model_tokens": 10},
            window_seconds={"model_tokens": 60},
        )

        await service.consume_capped("model_tokens", dimensions(), amount=3)
        peek = await service.peek("model_tokens", dimensions())

        assert peek.allowed is True
        assert peek.code == "allowed"
        assert peek.current == 3

    asyncio.run(scenario())


def test_capped_consume_redis_failure_never_blocks_answer():
    async def scenario():
        service = QuotaService(
            FailingRedis(),
            limits={"model_tokens": 10},
            window_seconds={"model_tokens": 60},
        )

        result = await service.consume_capped(
            "model_tokens", dimensions(), amount=5
        )

        assert result.available is False
        assert result.exceeded is False
        assert result.current == 0

    asyncio.run(scenario())


def test_model_tokens_peek_redis_failure_fails_closed():
    async def scenario():
        service = QuotaService(
            FailingRedis(),
            limits={"model_tokens": 10},
            window_seconds={"model_tokens": 60},
        )

        decision = await service.peek("model_tokens", dimensions())

        assert decision.allowed is False
        assert decision.code == "quota_unavailable"
        assert decision.retryable is True

    asyncio.run(scenario())
