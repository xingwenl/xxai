"""Embed Client 增加「允许终端用户切换智能体」开关

需求（`docs/harness/requests/2026-10-21-ai-sdk-agent-switching/`）：ai-sdk 聊天窗
允许终端用户在「后台已配置的智能体」之间切换，并且这个能力要能开能关。

开关放在 ``platform_embed_clients`` 而不是 SDK 配置里：同一接入 client 可能被多个
宿主页面嵌入，只有平台侧配置才能统一关闭。列默认 ``false``，存量 client 升级后
保持关闭——新增功能不改变现有接入方的行为。

开关的运行时下发通道是网关 ``session_ready`` 的 client 快照，不是 token claim；
原因（token 300-900s 生命周期 + 客户端缓存复用会留下旧策略窗口）与候选列表为什么
由宿主提供，见 docs/adr/0014-host-provided-agent-switching.md。

Revision ID: 20261021_0044
Revises: 20261020_0043
Create Date: 2026-10-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261021_0044"
down_revision: Union[str, None] = "20261020_0043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "platform_embed_clients",
        sa.Column(
            "allow_agent_switching",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment=(
                "是否允许该 Embed Client 接入的 SDK 由终端用户切换智能体；"
                "关闭时 SDK 不展示切换入口，程序化切换也会被拒绝"
            ),
        ),
    )


def downgrade() -> None:
    op.drop_column("platform_embed_clients", "allow_agent_switching")
