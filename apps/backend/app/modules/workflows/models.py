"""工作流模块数据模型：工作流定义、工作流运行、步骤运行三份表。

设计口径与 spec 对齐：
- 「工作流」是一串按固定顺序执行的步骤定义，每步跑一轮 Agent 或直接调用一个
  工具；它不包含触发器，定时触发由 ``tasks.workflow_id`` 这条可空外键接进来；
- 「工作流运行」是它的一次完整执行记录，同一定义可以有多次互相独立的运行；
- 「步骤运行」是运行中某一步骤的执行记录，两级记录不要互相代替。

定义以 JSON（``nodes[]`` + ``edges[]``，节点与边都带稳定字符串 id）存在
``workflows.definition`` 里，每次保存令 ``version`` 加一；每次运行把当次定义
**快照**写进 ``workflow_runs.definition_snapshot``，因此历史运行永远能解释自己。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.base_model import BaseModel, TimeModel

if TYPE_CHECKING:
    from app.modules.agent.models import Agent
    from app.modules.conversation.models import Conversation
    from app.modules.platform.models import Platform
    from app.modules.user.models import User


class Workflow(BaseModel, TimeModel):
    """工作流定义：一串有序步骤 + 工作流级默认 Agent 与审批策略。"""

    __tablename__ = "workflows"

    id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True, comment="工作流主键"
    )
    platform_id: Mapped[int] = mapped_column(
        ForeignKey("platforms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="工作流所属平台 ID",
    )
    name: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="工作流名称"
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="工作流说明，供后台识别用途"
    )
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="工作流级默认智能体 ID；步骤未覆盖 agent_id 时用它执行",
    )
    owner_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("sys_users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="工作流归属用户 ID；为空表示平台级工作流（仅平台管理员可管理）",
    )
    created_by_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="user",
        server_default="user",
        comment="创建者类型：user 用户 / agent 智能体 / integration 集成",
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("sys_users.id", ondelete="SET NULL"),
        nullable=True,
        comment="创建者用户 ID；创建者被删除时置空以保留定义",
    )
    created_by_agent_id: Mapped[int | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"),
        nullable=True,
        comment="创建者智能体 ID；由智能体创建时有值",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        server_default="active",
        comment="状态：active 启用 / paused 暂停（暂停期间到期触发会被跳过）",
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
        comment="定义版本号：每次保存定义加一，运行记录用它标记当时执行的是哪一版",
    )
    max_steps: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=50,
        server_default="50",
        comment="步骤数上限（默认 50，对齐成熟实现的单路径节点上限）",
    )
    definition: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
        comment="定义本体：nodes[] 步骤节点 + edges[] 顺序边，节点与边都带稳定字符串 id",
    )
    timeout_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=600,
        server_default="600",
        comment="整条工作流单次执行的超时秒数",
    )
    auto_approve: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
        comment="是否自动批准需要确认的工具调用（沿用任务模块的无人值守策略）",
    )
    strict_approval: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        comment="严格模式：只自动批准 navigation 类工具，其余仍需确认",
    )

    platform: Mapped["Platform"] = relationship("Platform")
    # agents 与 sys_users 各有两条外键路径（执行用 / 创建者用），必须显式指定
    # foreign_keys，否则 SQLAlchemy 无法确定 join 条件，映射配置阶段就会抛
    # AmbiguousForeignKeysError。
    agent: Mapped["Agent"] = relationship("Agent", foreign_keys=[agent_id])
    owner: Mapped["User | None"] = relationship("User", foreign_keys=[owner_user_id])
    runs: Mapped[list["WorkflowRun"]] = relationship(
        "WorkflowRun", back_populates="workflow", cascade="all, delete-orphan"
    )


class WorkflowRun(BaseModel, TimeModel):
    """工作流运行：工作流的一次完整执行记录（含被跳过的触发点）。"""

    __tablename__ = "workflow_runs"
    __table_args__ = (
        # 「同一工作流串行」由数据库兜底：一个工作流最多只能有一条 running 记录。
        # 这样即使调度器多副本并发、或看门狗与抢占交错，也不会出现两条并行运行；
        # 重叠触发会被抢占逻辑改写成 skipped(overlapped) 记录。
        # 两种方言都要写 where：只给 postgresql_where 时，sqlite 会退化成
        # 「workflow_id 全表唯一」，反而让第二条 skipped 记录也插不进去。
        Index(
            "uq_workflow_runs_one_running_per_workflow",
            "workflow_id",
            unique=True,
            postgresql_where=text("status = 'running'"),
            sqlite_where=text("status = 'running'"),
        ),
        # 抢占与看门狗都按「状态 + 时间」筛选，走这条复合索引。
        Index("ix_workflow_runs_status_started_at", "status", "started_at"),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True, comment="工作流运行主键"
    )
    workflow_id: Mapped[int] = mapped_column(
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属工作流 ID",
    )
    definition_version_id: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        comment="本次运行使用的定义版本号（对应 workflows.version，不建独立版本表）",
    )
    definition_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
        comment="本次运行冻结的定义快照；定义被修改后历史运行仍能解释自己",
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
        default="manual",
        server_default="manual",
        comment="触发方式：manual 手动运行 / scheduled 由任务定时触发",
    )
    run_as_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="user",
        server_default="user",
        comment="执行身份类型：user 平台用户 / end_user 终端用户 / platform 平台预留",
    )
    run_as_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("sys_users.id", ondelete="SET NULL"),
        nullable=True,
        comment="执行身份对应的平台用户 ID；身份由触发源决定，不在定义里存死",
    )
    run_as_end_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("platform_end_users.id", ondelete="SET NULL"),
        nullable=True,
        comment="执行身份对应的终端用户 ID；定时触发时可能由任务带入",
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
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="失败原因（超时、步骤失败、模型错误等）"
    )
    skip_reason: Mapped[str | None] = mapped_column(
        String(40),
        nullable=True,
        comment="跳过原因：overlapped 上一次未结束 / workflow_paused 工作流已暂停 / deadline_missed 错过触发点",
    )
    auto_approved_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="本轮各步骤自动批准的工具调用次数合计，用于无人值守审批的可追溯性",
    )
    total_steps: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="本次运行按快照应执行的步骤总数",
    )
    completed_steps: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="本次运行已成功完成的步骤数（含用兜底值继续的步骤）",
    )
    # 看门狗判定用：不依赖 started_at 做「是否超时」的计算基准，
    # 避免调度进程重启后因为 started_at 为空而漏掉悬挂记录。
    watchdog_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="看门狗最近一次检查该记录的时刻（UTC）",
    )

    workflow: Mapped["Workflow"] = relationship("Workflow", back_populates="runs")
    steps: Mapped[list["WorkflowStepRun"]] = relationship(
        "WorkflowStepRun", back_populates="run", cascade="all, delete-orphan"
    )


class WorkflowStepRun(BaseModel, TimeModel):
    """步骤运行：工作流运行中某一步骤的执行记录。"""

    __tablename__ = "workflow_step_runs"
    __table_args__ = (
        # 步骤明细一律按「某次运行 + 执行顺序」读取，走这条复合索引。
        Index("ix_workflow_step_runs_run_seq", "run_id", "seq"),
    )

    id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True, comment="步骤运行主键"
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey("workflow_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属工作流运行 ID",
    )
    step_id: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="步骤的稳定字符串标识（非自增行号），后续步骤用它引用本步输出",
    )
    seq: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="步骤在本次运行中的执行顺序，从 0 开始"
    )
    node_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="步骤类型：agent 跑一轮 Agent / tool 直接调用一个工具",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="running",
        server_default="running",
        comment="步骤状态：running 执行中 / succeeded 成功 / failed 失败 / skipped 已跳过 / waiting 等待人工（v1 预留未实现）",
    )
    model_visible_output: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="进下一步、对模型可见的输出；超过 50KB 会被截断并追加截断标记",
    )
    raw_output: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="完整未截断输出，仅供界面展示与审计"
    )
    retry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        comment="实际尝试次数：首跑成功记 1，重试过则按累计次数记（如 max_retries=2 且第 3 次成功记 3）",
    )
    on_error_applied: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
        comment="该步失败后是否改用了兜底值继续（on_error=continue_with_default 生效时为真）",
    )
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="该步自动创建的会话 ID（Agent 步骤）；删除会话时置空以保留步骤记录",
    )
    agent_loop_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_loop_runs.id", ondelete="SET NULL"),
        nullable=True,
        comment="该步对应的 Agent 运行记录 ID，用于回溯模型与工具调用",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="失败原因（工具错误、模型错误、超时等）"
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="该步实际开始时刻（UTC）"
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="该步实际结束时刻（UTC）"
    )

    run: Mapped["WorkflowRun"] = relationship("WorkflowRun", back_populates="steps")
    conversation: Mapped["Conversation | None"] = relationship("Conversation")
