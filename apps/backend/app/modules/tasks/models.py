"""任务模块数据模型：任务定义与任务运行两份表。

设计口径与 spec 对齐：
- 「任务」是一条按时间触发、到点自动跑一轮 Agent 对话的配置；
- 「任务运行」是它的一次执行记录，同一任务可以有多次互相独立的运行；
- 任务的「归属」（owner_user_id）、「创建者」（created_by_*）与
  「执行身份」（run_as_*）是三个不同概念，分别用于可见性、审计与权限。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.base_model import BaseModel, TimeModel

if TYPE_CHECKING:
    from app.modules.agent.models import Agent
    from app.modules.conversation.models import Conversation
    from app.modules.embed.models import PlatformEndUser
    from app.modules.platform.models import Platform
    from app.modules.user.models import User


class Task(BaseModel, TimeModel):
    """任务定义：一条 Agent + 指令 + 时间触发规则 + 落点的配置。"""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True, comment="任务主键"
    )
    platform_id: Mapped[int] = mapped_column(
        ForeignKey("platforms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="任务所属平台 ID",
    )
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="任务执行时使用的智能体 ID",
    )
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("sys_users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="任务归属用户 ID；为空表示平台级任务（仅平台管理员可管理）",
    )
    name: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="任务名称，用于列表展示"
    )
    prompt: Mapped[str] = mapped_column(
        Text, nullable=False, comment="到点后发给智能体的指令内容"
    )
    model_id: Mapped[int | None] = mapped_column(
        ForeignKey("platform_models.id", ondelete="SET NULL"),
        nullable=True,
        comment="可选：覆盖智能体默认模型；为空时沿用智能体自身配置",
    )
    trigger_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="cron",
        server_default="cron",
        comment="触发类型：cron 周期触发 / once 一次性触发",
    )
    cron_expression: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
        comment="五段式 cron 表达式（分 时 日 月 周）；trigger_type=cron 时必填",
    )
    run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="一次性执行时刻（UTC）；trigger_type=once 时必填",
    )
    timezone: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="Asia/Shanghai",
        server_default="Asia/Shanghai",
        comment="IANA 时区名，用于解释 cron 与 run_at（默认 Asia/Shanghai）",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        server_default="active",
        comment="任务状态：active 启用 / paused 暂停",
    )
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="下一次应触发的时刻（UTC），调度抢占依据；为空表示不再触发",
    )
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="最近一次实际触发的时刻（UTC）",
    )
    created_by_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="user",
        server_default="user",
        comment="创建者类型：user 用户 / agent 智能体 / integration 接入方",
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("sys_users.id", ondelete="SET NULL"),
        nullable=True,
        comment="创建者用户 ID（created_by_type=user 时记录）",
    )
    created_by_agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        comment="创建者智能体 ID（created_by_type=agent 时记录）",
    )
    run_as_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="user",
        server_default="user",
        comment="执行身份类型：user 后台用户 / end_user 终端用户 / platform 预留（v1 不支持）",
    )
    run_as_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("sys_users.id", ondelete="SET NULL"),
        nullable=True,
        comment="以哪个后台用户身份执行（run_as_type=user 时必填）",
    )
    run_as_end_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("platform_end_users.id", ondelete="SET NULL"),
        nullable=True,
        comment="以哪个终端用户身份执行（run_as_type=end_user 时必填，Embed 链路创建的任务用）",
    )
    auto_approve: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        comment="无人值守时是否自动批准需要确认的工具调用，默认开启",
    )
    strict_approval: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="严格模式：只自动批准 side_effect=navigation 的工具，默认关闭",
    )
    timeout_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=600,
        server_default="600",
        comment="单次执行超时秒数，默认 600",
    )

    platform: Mapped["Platform"] = relationship("Platform")
    # agents 与 sys_users 各有两条外键路径（执行用 / 创建者用），
    # 必须显式指定 foreign_keys，否则 SQLAlchemy 无法确定 join 条件。
    agent: Mapped["Agent"] = relationship("Agent", foreign_keys=[agent_id])
    owner_user: Mapped["User | None"] = relationship(
        "User", foreign_keys=[owner_user_id]
    )
    run_as_user: Mapped["User | None"] = relationship(
        "User", foreign_keys=[run_as_user_id]
    )
    run_as_end_user: Mapped["PlatformEndUser | None"] = relationship(
        "PlatformEndUser", foreign_keys=[run_as_end_user_id]
    )
    runs: Mapped[list["TaskRun"]] = relationship(
        "TaskRun", back_populates="task", cascade="all, delete-orphan"
    )


class TaskRun(BaseModel, TimeModel):
    """任务运行：任务的一次执行记录（含被跳过的触发点）。"""

    __tablename__ = "task_runs"
    __table_args__ = (
        # 「同一任务串行」由数据库兜底：一个任务最多只能有一条 running 记录。
        # 这样即使调度器多副本并发、或看门狗与抢占交错，也不会出现两条并行运行；
        # 重叠触发会被抢占逻辑改写成 skipped(overlapped) 记录。
        # 两种方言都要写 where：只给 postgresql_where 时，sqlite 会退化成
        # 「task_id 全表唯一」，反而让第二条 skipped 记录也插不进去。
        Index(
            "uq_task_runs_one_running_per_task",
            "task_id",
            unique=True,
            postgresql_where=text("status = 'running'"),
            sqlite_where=text("status = 'running'"),
        ),
        # 抢占与看门狗都按「状态 + 时间」筛选，走这条复合索引。
        Index("ix_task_runs_status_started_at", "status", "started_at"),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True, comment="任务运行主键"
    )
    task_id: Mapped[int] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属任务 ID",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="running",
        server_default="running",
        comment="执行状态：running 执行中 / completed 已完成 / failed 已失败 / skipped 已跳过",
    )
    trigger_kind: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="scheduled",
        server_default="scheduled",
        comment="触发方式：scheduled 到点触发 / manual 手动立即运行",
    )
    planned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="计划触发时刻（UTC），用于对齐这次运行对应哪个触发点",
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="实际开始时刻（UTC）"
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="实际结束时刻（UTC）"
    )
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="本轮自动创建的会话 ID；删除会话时置空以保留执行记录",
    )
    agent_loop_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_loop_runs.id", ondelete="SET NULL"),
        nullable=True,
        comment="对应的 Agent 运行记录 ID，便于从执行记录回溯到具体运行",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="失败原因（超时、模型错误等）"
    )
    skip_reason: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
        comment="跳过原因：overlapped 上一次未结束 / task_paused 任务已暂停 / deadline_missed 错过触发点",
    )
    auto_approved_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="本轮自动批准的工具调用次数，用于无人值守审批的可追溯性",
    )
    # 看门狗判定用：不依赖 started_at 做「是否超时」的计算基准，
    # 避免调度进程重启后因为 started_at 为空而漏掉悬挂记录。
    watchdog_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="看门狗最近一次检查该记录的时刻（UTC）",
    )

    task: Mapped["Task"] = relationship("Task", back_populates="runs")
    conversation: Mapped["Conversation | None"] = relationship("Conversation")
