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


class FailingRedis:
    async def check_and_increment(
        self, key: str, limit: int, amount: int, window_seconds: int
    ) -> tuple[bool, int, int]:
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
