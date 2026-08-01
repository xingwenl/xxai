import asyncio

from app.modules.host_tool.models import HostToolPolicy
from app.modules.host_tool.repositories import HostToolRepository


class FakeSession:
    def __init__(self):
        self.committed = False
        self.refreshed = False

    async def commit(self):
        self.committed = True

    async def refresh(self, entity):
        self.refreshed = True


def test_updating_status_with_unchanged_schema_keeps_tool_enabled():
    policy = HostToolPolicy(
        platform_id=1,
        name="navigate_to_page",
        description="打开后台已有页面",
        input_schema={
            "type": "object",
            "properties": {"page_name": {"type": "string"}},
            "required": ["page_name"],
            "additionalProperties": False,
        },
        output_schema=None,
        schema_fingerprint="unchanged",
        side_effect="navigation",
        confirmation_policy="always",
        is_enabled=False,
    )
    session = FakeSession()

    asyncio.run(
        HostToolRepository(session).update_policy(
            policy,
            {
                "input_schema": policy.input_schema.copy(),
                "is_enabled": True,
            },
        )
    )

    assert policy.is_enabled is True
    assert session.committed is True
    assert session.refreshed is True
