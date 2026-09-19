"""任务接口数据模型。

约定与仓库其他平台作用域模块一致：
- Create / Update / Read 分离，Update 字段全部可选以支持局部更新；
- 列表数据用 ``page_no / page_size / items / total / pages`` 分页字段；
- 时间字段由 ``TimeSchemas`` 统一格式化为 ``YYYY-MM-DD HH:MM:SS``。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.shared.base_schemas import TimeSchemas

TriggerType = Literal["cron", "once"]
TaskStatus = Literal["active", "paused"]
TaskRunStatus = Literal["running", "completed", "failed", "skipped"]
TaskRunTriggerKind = Literal["scheduled", "manual"]


class TaskCreate(BaseModel):
    """创建任务请求。

    ``owner_user_id`` 由服务层按调用者身份决定，不接受客户端传入，
    避免越权把任务挂到别人名下。
    """

    name: str = Field(min_length=1, max_length=200, description="任务名称")
    prompt: str = Field(min_length=1, description="到点后发给智能体的指令")
    agent_id: int = Field(description="执行任务的智能体 ID")
    trigger_type: TriggerType = Field(default="cron", description="触发类型")
    cron_expression: str | None = Field(
        default=None, description="五段式 cron 表达式（trigger_type=cron 时必填）"
    )
    run_at: datetime | None = Field(
        default=None, description="一次性执行时刻（trigger_type=once 时必填）"
    )
    timezone: str = Field(default="Asia/Shanghai", description="IANA 时区名")
    model_id: int | None = Field(default=None, description="可选：覆盖智能体默认模型")
    auto_approve: bool = Field(default=True, description="是否自动批准需要确认的工具")
    strict_approval: bool = Field(
        default=False, description="严格模式：只自动批准 navigation 类工具"
    )
    timeout_seconds: int = Field(default=600, ge=30, le=7200, description="单次执行超时秒数")


class TaskUpdate(BaseModel):
    """更新任务请求（字段可选，支持局部更新，含暂停/恢复）。"""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    prompt: str | None = Field(default=None, min_length=1)
    agent_id: int | None = Field(default=None)
    trigger_type: TriggerType | None = Field(default=None)
    cron_expression: str | None = Field(default=None)
    run_at: datetime | None = Field(default=None)
    timezone: str | None = Field(default=None)
    model_id: int | None = Field(default=None)
    status: TaskStatus | None = Field(
        default=None, description="任务状态：active 启用 / paused 暂停"
    )
    auto_approve: bool | None = Field(default=None)
    strict_approval: bool | None = Field(default=None)
    timeout_seconds: int | None = Field(default=None, ge=30, le=7200)


class TaskRead(TimeSchemas):
    """任务读取模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    platform_id: int
    agent_id: int
    owner_user_id: int | None
    name: str
    prompt: str
    model_id: int | None
    trigger_type: str
    cron_expression: str | None
    run_at: datetime | None
    timezone: str
    status: str
    next_run_at: datetime | None
    last_run_at: datetime | None
    created_by_type: str
    created_by_user_id: int | None
    created_by_agent_id: int | None
    run_as_type: str
    run_as_user_id: int | None
    run_as_end_user_id: int | None
    auto_approve: bool
    strict_approval: bool
    timeout_seconds: int


class TaskListData(BaseModel):
    """任务列表分页数据。"""

    page_no: int
    page_size: int
    items: list[TaskRead]
    total: int
    pages: int


class TaskRunRead(TimeSchemas):
    """任务运行读取模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    status: str
    trigger_kind: str
    planned_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    conversation_id: int | None
    agent_loop_run_id: int | None
    error_message: str | None
    skip_reason: str | None
    auto_approved_count: int


class TaskRunListData(BaseModel):
    """任务运行列表分页数据。"""

    page_no: int
    page_size: int
    items: list[TaskRunRead]
    total: int
    pages: int


class TaskRunAccepted(BaseModel):
    """「立即运行一次」的结果：返回新建的执行记录。"""

    run: TaskRunRead
    message: str = "已开始执行"


class TaskRunStepRead(BaseModel):
    """执行过程中的一步：模型思考、工具调用或知识检索。"""

    id: str
    sequence: int
    step_type: str
    title: str | None = None
    status: str | None = None
    output_summary: str | None = None
    thinking_text: str | None = None
    tool_name: str | None = None
    skill_name: str | None = None
    error: str | None = None


class TaskRunDetail(BaseModel):
    """单次运行的执行过程详情。

    让任务侧不跳会话也能看清一轮运行里发生了什么、卡在哪一步——
    排查「执行超时」这类问题时，先看步骤里最后停在哪个动作。
    """

    run: TaskRunRead
    loop_id: str | None = None
    loop_status: str | None = None
    loop_summary: str | None = None
    steps: list[TaskRunStepRead] = Field(default_factory=list)
