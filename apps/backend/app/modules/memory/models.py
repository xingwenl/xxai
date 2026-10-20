from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel, TimeModel


class UserMemory(BaseModel, TimeModel):
    """用户记忆：会话主体关于自身的短条目，跨会话、跨 Agent 持久保存。

    一张表用 ``kind`` 区分两类语义，差别只在**写入**：``fact`` 会按 key 关闭旧行
    （保留时间线），``event`` 只追加。读取、权限、删除、页面完全共用一条路径——
    拆成两张表会让「查我的记忆」变成两个工具调用，模型少调一个就漏掉一半。
    """

    __tablename__ = "user_memories"
    __table_args__ = (
        # 「同一用户同一 key 同时只有一条有效事实」由数据库保证：应用层先查再写
        # 在并发下会写出两条有效事实，而记忆的正确性正是这套系统的全部价值。
        Index(
            "uq_user_memories_active_fact",
            "platform_id",
            "user_id",
            "key",
            unique=True,
            postgresql_where=text("kind = 'fact' AND valid_until IS NULL"),
        ),
        Index("ix_user_memories_platform_id_user_id", "platform_id", "user_id"),
        CheckConstraint(
            "kind IN ('fact', 'event')", name="ck_user_memories_kind"
        ),
        CheckConstraint(
            "source IN ('explicit', 'inferred')",
            name="ck_user_memories_source",
        ),
        # 事实靠 key 表达覆盖关系，没有 key 的事实无法被新值关闭。
        CheckConstraint(
            "kind = 'event' OR key IS NOT NULL", name="ck_user_memories_fact_key"
        ),
        # 经历没有「失效」概念，只有发生时间。
        CheckConstraint(
            "kind = 'fact' OR valid_until IS NULL",
            name="ck_user_memories_event_valid_until",
        ),
        CheckConstraint(
            "kind = 'fact' OR occurred_at IS NOT NULL",
            name="ck_user_memories_event_occurred_at",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True, comment="用户记忆主键"
    )
    platform_id: Mapped[int] = mapped_column(
        ForeignKey("platforms.id", ondelete="CASCADE"),
        nullable=False,
        comment="所属平台 ID；记忆按平台隔离，不跨平台共享",
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("sys_users.id", ondelete="CASCADE"),
        nullable=False,
        comment="记忆所属的后台用户 ID，即会话主体；只有本人能读",
    )
    kind: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="记忆类别：fact=事实（可按 key 覆盖），event=经历（只追加）",
    )
    key: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
        comment="事实的稳定标识（姓名/城市等）；经历为空，事实必填",
    )
    content: Mapped[str] = mapped_column(
        Text, nullable=False, comment="记忆正文，由本人或模型写入"
    )
    occurred_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="事实的生效起点或经历的发生时间；事实为空表示未记录起点",
    )
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="事实失效时间；为空表示当前有效。被新值覆盖时写入当前时间，旧行留作时间线",
    )
    source: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default="explicit",
        server_default="explicit",
        comment="写入来源：explicit=用户明确要求，inferred=模型自动判定",
    )
    source_conversation_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        comment="写入来源会话 ID，便于回溯「这话是哪次聊出来的」；会话被删则置空",
    )
