from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.base_model import BaseModel, TimeModel


class Agent(BaseModel, TimeModel):
    __tablename__ = "agents"
    __table_args__ = (UniqueConstraint("platform_id", "slug"),)

    id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True, comment="智能体主键"
    )
    platform_id: Mapped[int] = mapped_column(
        ForeignKey("platforms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属平台 ID",
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False, comment="智能体名称")
    slug: Mapped[str] = mapped_column(
        String(80), nullable=False, comment="智能体唯一标识"
    )
    description: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="智能体描述"
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="是否为平台默认智能体",
    )
    default_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_versions.id", ondelete="SET NULL", use_alter=True),
        nullable=True,
        comment="当前发布版本 ID",
    )
    orchestration_workflow_id: Mapped[int | None] = mapped_column(
        # ondelete=SET NULL：工作流被删掉时 Agent 退回普通单 Agent 对话，
        # 而不是让整个 Agent 变成不可用。绑定关系是「可选增强」，不是必备属性。
        # use_alter=True：workflows.agent_id 是指向 agents 的外键，加上这一条就
        # 构成了表间环，建表/删表时 SQLAlchemy 无法拓扑排序；标记成已知环后它
        # 会改用独立 DDL 落地（与上面的 default_version_id 同一处理）。
        ForeignKey(
            "workflows.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_agents_orchestration_workflow_id_workflows",
        ),
        nullable=True,
        comment="绑定的编排工作流 ID：非空时该 Agent 每轮消息由这条工作流接管编排",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        comment="智能体是否启用",
    )
    versions: Mapped[list[AgentVersion]] = relationship(
        back_populates="agent",
        foreign_keys="AgentVersion.agent_id",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    default_version: Mapped[AgentVersion | None] = relationship(
        foreign_keys=[default_version_id], uselist=False, viewonly=True
    )


class AgentVersion(BaseModel):
    __tablename__ = "agent_versions"
    __table_args__ = (UniqueConstraint("agent_id", "version"),)

    id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True, comment="智能体版本主键"
    )
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属智能体 ID",
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, comment="版本号")
    system_prompt: Mapped[str] = mapped_column(
        Text, nullable=False, comment="系统提示词"
    )
    temperature: Mapped[float] = mapped_column(
        nullable=False, default=0.2, server_default="0.2", comment="模型采样温度"
    )
    model_options: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, comment="模型额外配置"
    )
    context_window_tokens: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        default=None,
        comment=(
            "模型上下文窗口（token），用于对话上下文预算护栏；"
            "为空时按内置模型名映射推断，均未命中则不启用护栏"
        ),
    )
    capabilities: Mapped[dict[str, Any] | None] = mapped_column(
        JSON,
        nullable=True,
        default=None,
        comment=(
            "模型附件能力配置（image/native_file/text_retrieval），"
            "为空时按 OpenRouter input_modalities 探测并按模型名兜底"
        ),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="版本创建时间"
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="版本发布时间"
    )
    agent: Mapped[Agent] = relationship(
        back_populates="versions", foreign_keys=[agent_id]
    )


class SubagentBinding(BaseModel, TimeModel):
    """父智能体 → 可派子智能体的绑定关系。

    这张表只回答「主智能体能把任务派给谁」，不复制子 Agent 的任何配置：
    子 Agent 的工具、技能、模型仍由它自己的发布版本决定。``enabled`` 是运行期
    开关（停用后不进入候选清单但保留绑定与排序），与子 Agent 自身的
    ``is_active`` 及发布状态共同决定是否真的可派。
    """

    __tablename__ = "agent_subagents"
    __table_args__ = (
        UniqueConstraint(
            "parent_agent_id",
            "child_agent_id",
            name="uq_agent_subagents_parent_child",
        ),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True, comment="绑定关系主键"
    )
    parent_agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="父智能体 ID（下发委派的一方）",
    )
    child_agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="子智能体 ID（被委派执行的一方）",
    )
    sort_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="展示与提示清单的排序值，升序",
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        comment="是否允许被委派；停用后不进入候选清单但保留绑定与排序",
    )
