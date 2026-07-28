import asyncio

import pytest

from app.modules.embed.services import get_embed_message_snapshot
from app.shared.exceptions import NotFoundException


class FakeSnapshotRepository:
    async def list_messages_for_principal(
        self, conversation_id, platform_id, *, end_user_id
    ):
        if (conversation_id, platform_id, end_user_id) == (10, 7, 22):
            return [{"id": 1, "content": "owned"}]
        return None


def test_message_snapshot_is_limited_to_token_subject_and_platform():
    async def run():
        result = await get_embed_message_snapshot(
            FakeSnapshotRepository(),
            conversation_id=10,
            claims={"platform_id": 7, "sub": "22"},
        )
        assert result[0]["content"] == "owned"

        with pytest.raises(NotFoundException):
            await get_embed_message_snapshot(
                FakeSnapshotRepository(),
                conversation_id=10,
                claims={"platform_id": 8, "sub": "22"},
            )

    asyncio.run(run())
