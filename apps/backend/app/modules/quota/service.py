"""基于 Redis 固定窗口的多租户运行时配额。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal, Protocol

from redis.asyncio import Redis

QuotaResource = Literal["token_issue", "connection", "message", "model_tokens"]


@dataclass(frozen=True)
class QuotaDimensions:
    platform_id: str | None = None
    client_id: str | None = None
    agent_id: str | None = None
    end_user_id: str | None = None


@dataclass(frozen=True)
class QuotaDecision:
    allowed: bool
    code: Literal["allowed", "quota_exceeded", "quota_unavailable"]
    current: int = 0
    limit: int = 0
    retry_after_seconds: int | None = None
    retryable: bool = False


class QuotaCounter(Protocol):
    async def check_and_increment(
        self, key: str, limit: int, amount: int, window_seconds: int
    ) -> tuple[bool, int, int]: ...


class RedisQuotaStore:
    """使用单次 Lua 执行保证检查与递增不会被并发请求打断。"""

    _SCRIPT = """
    local current = tonumber(redis.call('GET', KEYS[1]) or '0')
    local limit = tonumber(ARGV[1])
    local amount = tonumber(ARGV[2])
    local window = tonumber(ARGV[3])
    if current + amount > limit then
      return {0, current, window}
    end
    local updated = redis.call('INCRBY', KEYS[1], amount)
    if updated == amount then
      redis.call('EXPIRE', KEYS[1], window)
    end
    return {1, updated, window}
    """

    def __init__(self, redis: Redis) -> None:
        self.redis = redis
        self._script = redis.register_script(self._SCRIPT)

    async def check_and_increment(
        self, key: str, limit: int, amount: int, window_seconds: int
    ) -> tuple[bool, int, int]:
        result = await self._script(
            keys=[key], args=[limit, amount, window_seconds]
        )
        return bool(result[0]), int(result[1]), int(result[2])


class QuotaService:
    def __init__(
        self,
        counter: QuotaCounter,
        *,
        limits: dict[str, int],
        window_seconds: dict[str, int],
        clock: callable = time.time,
    ) -> None:
        self.counter = counter
        self.limits = limits
        self.window_seconds = window_seconds
        self.clock = clock

    @staticmethod
    def key(resource: QuotaResource, dimensions: QuotaDimensions, window: int) -> str:
        parts = [
            f"platform:{dimensions.platform_id or '*'}",
            f"client:{dimensions.client_id or '*'}",
            f"agent:{dimensions.agent_id or '*'}",
            f"user:{dimensions.end_user_id or '*'}",
        ]
        return f"agent:quota:{resource}:{window}:" + ":".join(parts)

    async def check(
        self,
        resource: QuotaResource,
        dimensions: QuotaDimensions,
        *,
        amount: int = 1,
    ) -> QuotaDecision:
        limit = self.limits.get(resource)
        window_seconds = self.window_seconds.get(resource)
        if limit is None or window_seconds is None or limit < 0 or amount <= 0:
            raise ValueError(f"quota configuration is invalid for {resource}")
        window = int(self.clock() // window_seconds)
        try:
            allowed, current, retry_after = await self.counter.check_and_increment(
                self.key(resource, dimensions, window),
                limit,
                amount,
                window_seconds,
            )
        except Exception:
            return QuotaDecision(
                allowed=False,
                code="quota_unavailable",
                limit=limit,
                retryable=True,
            )
        if not allowed:
            return QuotaDecision(
                allowed=False,
                code="quota_exceeded",
                current=current,
                limit=limit,
                retry_after_seconds=retry_after,
                retryable=True,
            )
        return QuotaDecision(
            allowed=True,
            code="allowed",
            current=current,
            limit=limit,
            retry_after_seconds=retry_after,
        )
