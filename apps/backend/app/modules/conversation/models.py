from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base_model import BaseModel, TimeModel


class Conversation(BaseModel, TimeModel):
    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint(
            "(user_id IS NOT NULL AND platform_end_user_id IS NULL) OR "
            "(user_id IS NULL AND platform_end_user_id IS NOT NULL)",
            name="ck_conversations_exactly_one_principal",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    platform_id: Mapped[int] = mapped_column(
        ForeignKey("platforms.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("sys_users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    platform_end_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("platform_end_users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="active", server_default="active"
    )


class ConversationMessage(BaseModel, TimeModel):
    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[Literal["user", "assistant", "tool"]] = mapped_column(
        String(20), nullable=False, comment="消息角色：用户、助手或工具"
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="兼容旧客户端的纯文本内容或摘要")
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="completed", server_default="completed", comment="消息状态：sending、streaming、completed、failed、cancelled"
    )
    content_blocks: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]", comment="可渲染消息内容块数组"
    )
    citations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]", comment="知识库引用列表，兼容旧消息查询"
    )
    knowledge_grounded: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default="false", comment="是否使用了知识库内容"
    )
    tool_call_id: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="关联工具调用 ID")
    message_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}", comment="消息扩展元数据，不保存敏感原文"
    )


class AgentLoopRun(BaseModel, TimeModel):
    __tablename__ = "agent_loop_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, comment="AgentLoop 运行主键")
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True, comment="所属会话 ID"
    )
    user_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversation_messages.id", ondelete="SET NULL"), nullable=True, index=True, comment="触发本次运行的用户消息 ID"
    )
    assistant_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversation_messages.id", ondelete="SET NULL"), nullable=True, index=True, comment="最终助手消息 ID"
    )
    request_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True, comment="前后端请求 ID")
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="running", server_default="running", comment="运行状态：running、completed、failed、cancelled、waiting_confirmation"
    )
    summary: Mapped[str | None] = mapped_column(Text, nullable=True, comment="面向用户的安全过程摘要")
    parent_loop_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_loop_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="父运行 ID：非空表示这是一次被派生的子运行",
    )
    run_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}", comment="运行扩展元数据，不保存完整 Prompt 或敏感数据"
    )


class AgentLoopStep(BaseModel, TimeModel):
    __tablename__ = "agent_loop_steps"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True, comment="AgentLoop 步骤主键")
    loop_run_id: Mapped[int] = mapped_column(
        ForeignKey("agent_loop_runs.id", ondelete="CASCADE"), index=True, comment="所属 AgentLoop 运行 ID"
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, comment="运行内步骤顺序")
    step_type: Mapped[str] = mapped_column(String(40), nullable=False, comment="步骤类型：知识库、技能、工具、生成等")
    title: Mapped[str] = mapped_column(String(255), nullable=False, comment="面向用户展示的步骤标题")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="queued", server_default="queued", comment="步骤状态")
    input_summary: Mapped[str | None] = mapped_column(Text, nullable=True, comment="脱敏后的输入摘要")
    output_summary: Mapped[str | None] = mapped_column(Text, nullable=True, comment="脱敏后的输出摘要")
    thinking_text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="模型思考内容（reasoning/thinking），流式累计后落库，普通模型为 NULL")
    tool_name: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="工具名称")
    skill_name: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="技能名称")
    skill_version: Mapped[str | None] = mapped_column(String(80), nullable=True, comment="技能版本")
    tool_call_id: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="工具调用 ID")
    citation_refs: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list, server_default="[]", comment="关联知识库引用标识")
    error: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True, comment="错误码和脱敏错误摘要")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1", comment="步骤尝试次数")
    parent_step_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_loop_steps.id", ondelete="SET NULL"), nullable=True, index=True, comment="父步骤 ID，用于重试或派生步骤"
    )
    step_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default="{}", comment="步骤扩展元数据，不保存敏感原始输入输出"
    )


class ModelUsageRecord(BaseModel, TimeModel):
    __tablename__ = "model_usage_records"

    id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True, comment="模型用量明细主键"
    )
    platform_id: Mapped[int] = mapped_column(
        ForeignKey("platforms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属平台 ID",
    )
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="产生用量的智能体 ID",
    )
    agent_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="产生用量的智能体版本 ID",
    )
    client_id: Mapped[str | None] = mapped_column(
        String(80),
        nullable=True,
        index=True,
        comment="Embed Client 公开标识；后台会话为空",
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("sys_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="后台用户 ID；Embed 会话为空",
    )
    platform_end_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("platform_end_users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="平台最终用户 ID；后台会话为空",
    )
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联会话 ID",
    )
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversation_messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="关联助手消息 ID",
    )
    request_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True, comment="网关请求 ID"
    )
    model_name: Mapped[str | None] = mapped_column(
        String(120), nullable=True, comment="模型名称"
    )
    prompt_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="输入 token 数"
    )
    completion_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="输出 token 数"
    )
    total_tokens: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0", comment="总 token 数"
    )


class AgentLoopRunCheckpoint(BaseModel, TimeModel):
    """运行级确认检查点：把「等待确认那一刻」的模型上下文落成显式状态。

    一次运行遇到需要用户拍板的工具调用时会挂起：进程内的消息列表随请求结束而
    消失，而续跑必须让模型看到挂起前的完整上下文（system prompt 现算不入库、
    assistant 的 tool_calls 消息与工具结果从不落 ``conversation_messages``），
    所以上下文只能在这里显式存一份 JSON 快照。

    一个运行最多只有一个待确认检查点（``loop_run_id`` 唯一），续跑入口就是
    ``loop_run_id``；状态机为 pending → resolved → consumed，超时未处理则由
    解决请求惰性判定为 expired。
    """

    __tablename__ = "agent_loop_run_checkpoints"
    __table_args__ = (
        CheckConstraint(
            "(user_id IS NOT NULL AND platform_end_user_id IS NULL) OR "
            "(user_id IS NULL AND platform_end_user_id IS NOT NULL)",
            name="exactly_one_principal",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger, primary_key=True, autoincrement=True, comment="运行检查点主键"
    )
    loop_run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("agent_loop_runs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        comment="所属 AgentLoop 运行 ID；一个运行最多一个待确认检查点，故唯一",
    )
    conversation_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属会话 ID，用于归属校验",
    )
    platform_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("platforms.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属平台 ID",
    )
    agent_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="发起本次运行的智能体 ID",
    )
    user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("sys_users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="后台用户 ID，与 Embed 最终用户互斥",
    )
    platform_end_user_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("platform_end_users.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
        comment="Embed 最终用户 ID，与后台用户互斥",
    )
    confirmation_source: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        comment="确认记录来源表：tool_confirmations 或 mcp_tool_confirmations",
    )
    confirmation_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        comment="跨两张确认表的确认记录 ID，不建外键，按 confirmation_source 分派",
    )
    tool_call_id: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="等待确认的模型工具调用 ID，续跑时回填结果"
    )
    tool_name: Mapped[str] = mapped_column(
        String(120), nullable=False, comment="等待确认的工具名"
    )
    tool_type: Mapped[str | None] = mapped_column(
        String(40), nullable=True, comment="工具来源类型：builtin_tool / skill_script / mcp_tool"
    )
    side_effect: Mapped[str | None] = mapped_column(
        String(30), nullable=True, comment="工具副作用类型，用于 SSE 事件展示"
    )
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="pending",
        server_default="pending",
        comment="检查点状态：pending / resolved / expired / consumed",
    )
    context: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        nullable=False,
        comment="等待确认那一刻喂给模型的完整上下文，续跑后清空",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="检查点失效时间，超过后解决请求返回过期错误码",
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="确认被解决（批准或拒绝）的时间"
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="续跑消费检查点并清空上下文的时间"
    )
