"""新增用户记忆表 user_memories

「把个人信息放进知识库」在检索上是错的：短事实与长文档的命中概率没有保证，
改一条事实还要重建索引。本表承载另一套机制——短条目、按 key 覆盖、问到才查：

- ``kind`` 区分事实（会变，覆盖时关闭旧行保留时间线）与经历（只追加）；
- 「同用户同 key 只有一条有效事实」由部分唯一索引
  ``uq_user_memories_active_fact`` 在数据库层保证，应用层先查再写在并发下会失效；
- 记忆内容**不进系统提示**（用户明确要求），只注入一行不含内容的条数索引，
  模型被问到时用 ``memory_search`` 取。

设计取舍见 docs/adr/0013-user-memory.md。

Revision ID: 20261020_0043
Revises: 20261019_0042
Create Date: 2026-10-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261020_0043"
down_revision: Union[str, None] = "20261019_0042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_memories",
        sa.Column(
            "id",
            sa.Integer(),
            autoincrement=True,
            nullable=False,
            comment="用户记忆主键",
        ),
        sa.Column(
            "platform_id", sa.Integer(), nullable=False, comment="所属平台 ID；记忆按平台隔离，不跨平台共享"
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            nullable=False,
            comment="记忆所属的后台用户 ID，即会话主体；只有本人能读",
        ),
        sa.Column(
            "kind",
            sa.String(length=10),
            nullable=False,
            comment="记忆类别：fact=事实（可按 key 覆盖），event=经历（只追加）",
        ),
        sa.Column(
            "key",
            sa.String(length=80),
            nullable=True,
            comment="事实的稳定标识（姓名/城市等）；经历为空，事实必填",
        ),
        sa.Column(
            "content", sa.Text(), nullable=False, comment="记忆正文，由本人或模型写入"
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="事实的生效起点或经历的发生时间；事实为空表示未记录起点",
        ),
        sa.Column(
            "valid_until",
            sa.DateTime(timezone=True),
            nullable=True,
            comment="事实失效时间；为空表示当前有效。被新值覆盖时写入当前时间，旧行留作时间线",
        ),
        sa.Column(
            "source",
            sa.String(length=10),
            server_default="explicit",
            nullable=False,
            comment="写入来源：explicit=用户明确要求，inferred=模型自动判定",
        ),
        sa.Column(
            "source_conversation_id",
            sa.Integer(),
            nullable=True,
            comment="写入来源会话 ID，便于回溯「这话是哪次聊出来的」；会话被删则置空",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="记录创建时间（UTC）",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="记录最后更新时间（UTC）",
        ),
        sa.ForeignKeyConstraint(
            ["platform_id"], ["platforms.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["sys_users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_conversation_id"], ["conversations.id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "kind IN ('fact', 'event')", name="ck_user_memories_kind"
        ),
        sa.CheckConstraint(
            "source IN ('explicit', 'inferred')", name="ck_user_memories_source"
        ),
        sa.CheckConstraint(
            "kind = 'event' OR key IS NOT NULL", name="ck_user_memories_fact_key"
        ),
        sa.CheckConstraint(
            "kind = 'fact' OR valid_until IS NULL",
            name="ck_user_memories_event_valid_until",
        ),
        sa.CheckConstraint(
            "kind = 'fact' OR occurred_at IS NOT NULL",
            name="ck_user_memories_event_occurred_at",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_user_memories_platform_id_user_id",
        "user_memories",
        ["platform_id", "user_id"],
        unique=False,
    )
    # 部分唯一索引：只约束「有效事实」这一子集，被关闭的旧行不参与唯一性，
    # 因此覆盖历史可以保留多条同 key 的行。
    op.create_index(
        "uq_user_memories_active_fact",
        "user_memories",
        ["platform_id", "user_id", "key"],
        unique=True,
        postgresql_where=sa.text("kind = 'fact' AND valid_until IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_user_memories_active_fact",
        table_name="user_memories",
        postgresql_where=sa.text("kind = 'fact' AND valid_until IS NULL"),
    )
    op.drop_index("ix_user_memories_platform_id_user_id", table_name="user_memories")
    op.drop_table("user_memories")
