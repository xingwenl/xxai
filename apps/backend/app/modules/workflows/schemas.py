"""工作流模块的接口层 schema。

分三块：定义（Create/Update/Read）、运行（RunRead/明细）、步骤（StepRunRead）。
与任务模块保持同一口径：

- Update 的字段全部可选，支持局部更新；
- 列表统一用 ``page_no / page_size / items / total / pages``；
- 时间字段由 ``TimeSchemas`` 统一序列化；
- ``owner_user_id`` / ``platform_id`` **不接受客户端传入**，一律由服务层按调用者
  身份决定，避免把工作流挂到别人名下或跨平台创建。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.modules.workflows import validators
from app.shared.base_schemas import TimeSchemas

WorkflowStatus = Literal["active", "paused"]
WorkflowRunStatus = Literal["running", "completed", "failed", "skipped"]
WorkflowRunTriggerKind = Literal["manual", "scheduled"]
WorkflowStepKind = Literal["agent", "tool"]
WorkflowStepStatus = Literal["running", "succeeded", "failed", "skipped", "waiting"]
WorkflowOnError = Literal["abort", "continue_with_default", "fail_branch"]


class WorkflowStepInput(BaseModel):
    """单个步骤的输入。

    步骤顺序即 ``steps`` 数组顺序，因此没有显式的顺序字段；``step_id`` 是稳定
    字符串（会进入历史运行记录），不是自增行号。
    """

    step_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    kind: WorkflowStepKind
    agent_id: int | None = None
    prompt: str | None = None
    tool_name: str | None = None
    tool_arguments: dict[str, Any] = Field(default_factory=dict)
    # 数组选择器：{绑定名: [前序 step_id, 输出路径]}。用数组而不是字符串模板，
    # 是为了让「只能引用排在前面的步骤」在保存时能做纯数据比对。
    input_bindings: dict[str, list[str]] = Field(default_factory=dict)
    on_error: WorkflowOnError = "abort"
    # 失败后额外重试几次（0 表示不重试）；重试拿的是同一份输入，用尽后 on_error 才生效。
    max_retries: int | None = Field(default=None, ge=0, le=5)
    default_output: str | None = None
    timeout_seconds: int | None = Field(default=None, ge=30, le=7200)


class WorkflowCreate(BaseModel):
    """创建工作流。"""

    name: str = Field(min_length=1, max_length=200)
    agent_id: int
    description: str | None = None
    steps: list[WorkflowStepInput] = Field(min_length=1)
    max_steps: int = Field(default=50, ge=1, le=50)
    timeout_seconds: int = Field(default=600, ge=30, le=7200)
    auto_approve: bool = True
    strict_approval: bool = False


class WorkflowUpdate(BaseModel):
    """局部更新工作流；传 ``steps`` 会整体替换定义并把 ``version`` 加一。"""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    agent_id: int | None = None
    steps: list[WorkflowStepInput] | None = None
    timeout_seconds: int | None = Field(default=None, ge=30, le=7200)
    auto_approve: bool | None = None
    strict_approval: bool | None = None
    status: WorkflowStatus | None = None


class WorkflowRead(TimeSchemas):
    """工作流定义读取模型，``definition`` 为编译后的 nodes/edges。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    platform_id: int
    agent_id: int
    owner_user_id: int | None = None
    name: str
    description: str | None = None
    status: WorkflowStatus
    version: int
    max_steps: int
    definition: dict[str, Any]
    timeout_seconds: int
    auto_approve: bool
    strict_approval: bool
    created_by_type: str
    created_by_user_id: int | None = None
    created_by_agent_id: int | None = None


class WorkflowListData(BaseModel):
    """工作流列表分页数据。"""

    page_no: int
    page_size: int
    items: list[WorkflowRead]
    total: int
    pages: int


class WorkflowRunRead(TimeSchemas):
    """工作流运行记录读取模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    workflow_id: int
    definition_version_id: int
    status: WorkflowRunStatus
    trigger_kind: WorkflowRunTriggerKind
    run_as_type: str
    run_as_user_id: int | None = None
    run_as_end_user_id: int | None = None
    planned_at: Any | None = None
    started_at: Any | None = None
    finished_at: Any | None = None
    error_message: str | None = None
    skip_reason: str | None = None
    auto_approved_count: int
    total_steps: int
    completed_steps: int
    watchdog_checked_at: Any | None = None


class WorkflowStepRunRead(TimeSchemas):
    """步骤运行记录读取模型（不含完整输出，用于列表）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    step_id: str
    seq: int
    node_type: WorkflowStepKind
    status: WorkflowStepStatus
    model_visible_output: str | None = None
    retry_count: int
    on_error_applied: bool
    conversation_id: int | None = None
    agent_loop_run_id: int | None = None
    error_message: str | None = None
    started_at: Any | None = None
    finished_at: Any | None = None


class WorkflowStepRunDetail(WorkflowStepRunRead):
    """步骤运行明细，额外带上完整未截断输出。

    ``raw_output_size`` 与 ``output_truncated`` 是**算出来的**字段（不落库）：
    界面要显示「多少字节、有没有被截断」，而这两件事都能由 ``raw_output``
    与 ``model_visible_output`` 直接推出来，另存两列只会多一份可能不一致的真相。
    """

    raw_output: str | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def raw_output_size(self) -> int:
        """完整输出的字节数（按 UTF-8 计），用于界面提示截断了多少内容。"""

        return len((self.raw_output or "").encode("utf-8"))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def output_truncated(self) -> bool:
        """模型可见输出是否被截断过；判定口径与写入端共用 validators.is_truncated。"""

        return validators.is_truncated(self.model_visible_output)


class WorkflowRunDetail(BaseModel):
    """一次运行的完整视图：运行概览 + 当次定义快照 + 各步结果。

    ``definition_snapshot`` 一并返回，是为了让「定义被改过之后旧运行为什么是
    这个结果」当场可解释，而不必去翻历史版本。
    """

    run: WorkflowRunRead
    definition_snapshot: dict[str, Any]
    steps: list[WorkflowStepRunDetail] = Field(default_factory=list)


class WorkflowRunListData(BaseModel):
    """工作流运行列表分页数据。"""

    page_no: int
    page_size: int
    items: list[WorkflowRunRead]
    total: int
    pages: int


class WorkflowRunAccepted(BaseModel):
    """手动运行接口的响应：只表示已排队，不表示已跑完。"""

    run: WorkflowRunRead
    message: str = "已开始执行"
