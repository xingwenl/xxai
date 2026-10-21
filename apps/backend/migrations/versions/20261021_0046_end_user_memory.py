"""user_memories 支持嵌入终端用户主体

记忆原先只认后台用户（``user_id`` 非空）。嵌入通道的第三方访客没有后台账号，
若不改表，他们要么写不了记忆，要么被塞进同一个后台用户下串号。本迁移把记忆
主体扩成两种，**恰好一种**：

- 后台用户：``user_id`` 非空（控制台、REST 对话、受信任入口的浮动助手）；
- 嵌入终端用户：``client_id`` + ``end_user_id`` 同时非空（公开入口的访客）。

为什么不能只加 ``client_id``：同一 Client 下不同访客会共享记忆，等于把所有访客
当成一个人。为什么不用多态 ``principal_id``：类型化列才能建外键，删用户/删 Client
时由数据库级联清理，不留孤儿记忆。完整取舍见 docs/adr/0016-end-user-memory.md。

存量数据全部是后台用户记忆，只加列、不重写；``user_id`` 由非空改为可空。
「同一主体同 key 只有一条有效事实」仍由部分唯一索引保证，现在拆成两条：
后台用户一条、终端用户一条。

不可逆点：``downgrade`` 会**删除所有终端用户记忆**（旧表结构无法表达它们），
后台用户记忆不受影响。

Revision ID: 20261021_0046
Revises: 20261021_0045
Create Date: 2026-10-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261021_0046"
down_revision: Union[str, None] = "20261021_0045"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_FACT_WHERE = sa.text("kind = 'fact' AND valid_until IS NULL")
NEW_FACT_WHERE = sa.text(
    "kind = 'fact' AND valid_until IS NULL AND user_id IS NOT NULL"
)
END_USER_FACT_WHERE = sa.text(
    "kind = 'fact' AND valid_until IS NULL AND end_user_id IS NOT NULL"
)


def upgrade() -> None:
    # 旧索引只约束 user_id 一列，先拆掉再按两种主体分别重建。
    op.drop_index(
        "uq_user_memories_active_fact",
        table_name="user_memories",
        postgresql_where=OLD_FACT_WHERE,
    )
    op.alter_column(
        "user_memories",
        "user_id",
        existing_type=sa.Integer(),
        nullable=True,
        comment=(
            "记忆所属的后台用户 ID（sys_users.id）；与 client_id/end_user_id 恰好一种，"
            "后台用户主体只有本人能读"
        ),
    )
    op.add_column(
        "user_memories",
        sa.Column(
            "client_id",
            sa.String(length=80),
            nullable=True,
            comment=(
                "嵌入终端用户主体所属的 Embed Client ID；与 end_user_id 成对出现，"
                "用于隔离不同接入方带来的访客记忆"
            ),
        ),
    )
    op.add_column(
        "user_memories",
        sa.Column(
            "end_user_id",
            sa.Integer(),
            nullable=True,
            comment="嵌入终端用户 ID（platform_end_users.id）；与 client_id 成对出现",
        ),
    )
    op.create_foreign_key(
        "fk_user_memories_client_id_platform_embed_clients",
        "user_memories",
        "platform_embed_clients",
        ["client_id"],
        ["client_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_user_memories_end_user_id_platform_end_users",
        "user_memories",
        "platform_end_users",
        ["end_user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    # 主体恰好一种：两列都填会让归属含糊，都不填则记忆成了无主数据。
    op.create_check_constraint(
        "ck_user_memories_exactly_one_principal",
        "user_memories",
        "(user_id IS NOT NULL AND client_id IS NULL AND end_user_id IS NULL) "
        "OR (user_id IS NULL AND client_id IS NOT NULL AND end_user_id IS NOT NULL)",
    )
    op.create_index(
        "ix_user_memories_platform_id_client_id_end_user_id",
        "user_memories",
        ["platform_id", "client_id", "end_user_id"],
        unique=False,
    )
    # 部分唯一索引只约束「有效事实」这一子集，被关闭的旧行不参与唯一性，
    # 因此覆盖历史可以保留多条同 key 的行。
    op.create_index(
        "uq_user_memories_active_fact",
        "user_memories",
        ["platform_id", "user_id", "key"],
        unique=True,
        postgresql_where=NEW_FACT_WHERE,
    )
    op.create_index(
        "uq_user_memories_active_end_user_fact",
        "user_memories",
        ["platform_id", "client_id", "end_user_id", "key"],
        unique=True,
        postgresql_where=END_USER_FACT_WHERE,
    )


def downgrade() -> None:
    # 旧结构无法表达终端用户记忆，只能丢弃（已在 docstring 声明为不可逆点）。
    op.execute("DELETE FROM user_memories WHERE user_id IS NULL")
    op.drop_index(
        "uq_user_memories_active_end_user_fact",
        table_name="user_memories",
        postgresql_where=END_USER_FACT_WHERE,
    )
    op.drop_index(
        "uq_user_memories_active_fact",
        table_name="user_memories",
        postgresql_where=NEW_FACT_WHERE,
    )
    op.drop_index(
        "ix_user_memories_platform_id_client_id_end_user_id",
        table_name="user_memories",
    )
    op.drop_constraint(
        "ck_user_memories_exactly_one_principal",
        "user_memories",
        type_="check",
    )
    op.drop_constraint(
        "fk_user_memories_end_user_id_platform_end_users",
        "user_memories",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_user_memories_client_id_platform_embed_clients",
        "user_memories",
        type_="foreignkey",
    )
    op.drop_column("user_memories", "end_user_id")
    op.drop_column("user_memories", "client_id")
    op.alter_column(
        "user_memories",
        "user_id",
        existing_type=sa.Integer(),
        nullable=False,
        comment="记忆所属的后台用户 ID，即会话主体；只有本人能读",
    )
    op.create_index(
        "uq_user_memories_active_fact",
        "user_memories",
        ["platform_id", "user_id", "key"],
        unique=True,
        postgresql_where=OLD_FACT_WHERE,
    )
