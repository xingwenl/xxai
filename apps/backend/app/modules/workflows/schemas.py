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
# conversation = 会话内接管触发（Agent 绑定编排后，每轮消息跑一次）。
# 它是唯一允许「同一工作流同时有多条 running」的触发来源，因此也参与
# uq_workflow_runs_one_running_per_workflow 的谓词。
WorkflowRunTriggerKind = Literal["manual", "scheduled", "conversation"]
WorkflowStepKind = Literal["agent", "tool", "condition"]
WorkflowStepStatus = Literal["running", "succeeded", "failed", "skipped", "waiting"]
WorkflowOnError = Literal["abort", "continue_with_default", "fail_branch"]


class CanvasPosition(BaseModel):
    """步骤在画布上的坐标，只影响前端布局，不参与任何执行语义。"""

    x: float
    y: float


class ConditionPredicate(BaseModel):
    """条件分支的谓词：对上游输出做**纯数据**判定，不调模型、无副作用。

    形状本身是递归的：``op`` 取 ``all`` / ``any`` / ``not`` 时读 ``children``，
    取 ``equals`` / ``contains`` / ``not_empty`` / ``matches`` 时读 ``left``
    （必须形如 ``{{step_id.output}}``）与 ``right``。这里只声明形状，取值合法性
    （算子在白名单内、引用的步骤确实是上游、正则能编译）由 ``validators`` 在
    保存期判定——那部分需要建图，放在 schema 里会让两层职责混在一起。
    """

    op: Literal["equals", "contains", "not_empty", "matches", "all", "any", "not"]
    # 比较算子的左操作数：``{{step_id.output}}``。组合算子不使用。
    left: str | None = None
    # 比较算子的右操作数（``not_empty`` 不使用）。
    right: str | None = None
    # 组合算子的子谓词。
    children: list[ConditionPredicate] | None = None


class ConditionBranch(BaseModel):
    """条件步骤的一个具名出口。

    ``when is None`` 表示无条件兜底分支：它必须存在且恰好一个，并排在最后，
    否则「所有条件都不成立」时这一步无路可走（保存期会拒绝）。
    """

    name: str = Field(min_length=1, max_length=64)
    when: ConditionPredicate | None = None


class WorkflowStepInput(BaseModel):
    """单个步骤的输入。

    执行顺序由 ``depends_on`` 决定，**不是** ``steps`` 数组顺序：``depends_on``
    缺省表示「依赖数组里的前一个步骤」（改造前保存的线性定义无需迁移），
    显式 ``[]`` 表示起点（并行分支的第二条靠它声明）。``step_id`` 是稳定字符串
    （会进入历史运行记录），不是自增行号。

    依赖条目可以带出口后缀 ``"<step_id>@<handle>"``，不带后缀等价于
    ``"<step_id>@default"``（成功出口）。``kind="condition"`` 的步骤没有
    ``default`` 出口，只能引用它声明的分支名；``on_error="fail_branch"`` 的
    步骤多一个 ``"<step_id>@failed"``。引用一个该步骤永远不会到达的出口会在
    保存期被拒绝。
    """

    step_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    kind: WorkflowStepKind
    # 依赖的 step_id 列表（可带 @出口）；None = 串行继任（依赖前一个），[] = 并行的起点。
    depends_on: list[str] | None = None
    # 画布坐标；后端只负责存取与校验形状，不解释含义。
    position: CanvasPosition | None = None
    agent_id: int | None = None
    prompt: str | None = None
    tool_name: str | None = None
    tool_arguments: dict[str, Any] = Field(default_factory=dict)
    # 数组选择器：{绑定名: [上游 step_id, 输出路径]}。用数组而不是字符串模板，
    # 是为了让「只能引用上游步骤」在保存时能做纯数据比对。
    input_bindings: dict[str, list[str]] = Field(default_factory=dict)
    on_error: WorkflowOnError = "abort"
    # 失败后额外重试几次（0 表示不重试）；重试拿的是同一份输入，用尽后 on_error 才生效。
    max_retries: int | None = Field(default=None, ge=0, le=5)
    default_output: str | None = None
    timeout_seconds: int | None = Field(default=None, ge=30, le=7200)
    # 仅条件步骤使用：具名分支出口 + 谓词。普通步骤声明它会保存期被拒。
    branches: list[ConditionBranch] | None = None


# 谓词是自引用的递归模型，前向注解在类体里还没绑定到名字，需显式重建。
ConditionPredicate.model_rebuild()


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
