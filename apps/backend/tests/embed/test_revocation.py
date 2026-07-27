import asyncio

from app.modules.embed.security import EmbedTokenRevocationStore


class FakeRedis:
    def __init__(self):
        self.values = {}

    async def set(self, key, value, ex):
        self.values[key] = (value, ex)

    async def exists(self, key):
        return int(key in self.values)


def test_revocation_uses_jti_namespace_and_token_remaining_ttl():
    async def run():
        store = EmbedTokenRevocationStore(FakeRedis())
        await store.revoke("jti-1", expires_at=2_000_000_000)

        assert await store.is_revoked("jti-1") is True
        assert await store.is_revoked("other") is False
        assert store.redis.values["agent:embed:revoked:jti-1"][1] <= 900

    asyncio.run(run())
