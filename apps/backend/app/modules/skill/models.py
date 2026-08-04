from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    BigInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.base_model import BaseModel, TimeModel


class Skill(BaseModel, TimeModel):
    __tablename__ = "skills"
    __table_args__ = (UniqueConstraint("platform_id", "slug"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    platform_id: Mapped[int] = mapped_column(
        ForeignKey("platforms.id", ondelete="CASCADE"),
        index=True,
        comment="所属平台 ID",
    )
    package_id: Mapped[int | None] = mapped_column(
        ForeignKey("skill_packages.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
        comment="来源技能包 ID，手工创建技能为空",
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    instruction_template: Mapped[str] = mapped_column(Text, nullable=False)
    parameter_schema: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    lifecycle_hooks: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict
    )
    package_skill_path: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="技能包内 SKILL.md 相对路径，手工创建技能为空",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    package: Mapped["SkillPackage | None"] = relationship(
        back_populates="skills", lazy="selectin"
    )


class SkillPackage(BaseModel, TimeModel):
    __tablename__ = "skill_packages"
    __table_args__ = (UniqueConstraint("platform_id", "slug"),)

    id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True, comment="技能包 ID"
    )
    platform_id: Mapped[int] = mapped_column(
        ForeignKey("platforms.id", ondelete="CASCADE"),
        index=True,
        comment="所属平台 ID",
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False, comment="技能包名称")
    slug: Mapped[str] = mapped_column(
        String(80), nullable=False, comment="平台内唯一技能包标识"
    )
    package_type: Mapped[str] = mapped_column(
        String(40), nullable=False, comment="技能包类型，如 skill 或 codex_plugin"
    )
    source_filename: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="原始上传文件名"
    )
    storage_key: Mapped[str] = mapped_column(
        String(500), nullable=False, comment="技能包在受控存储根目录下的相对定位键"
    )
    storage_path: Mapped[str] = mapped_column(
        String(1000), nullable=False, comment="技能包解压后的受控存储目录"
    )
    manifest: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, comment="技能包 manifest 或解析元数据"
    )
    warnings: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, comment="导入时产生的兼容性警告"
    )
    allow_script_execution: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
        comment="是否允许运行时执行包内脚本",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
        comment="技能包是否启用",
    )
    files: Mapped[list["SkillPackageFile"]] = relationship(
        back_populates="package", cascade="all, delete-orphan", lazy="selectin"
    )
    skills: Mapped[list[Skill]] = relationship(
        back_populates="package", lazy="selectin"
    )


class SkillPackageFile(BaseModel, TimeModel):
    __tablename__ = "skill_package_files"
    __table_args__ = (UniqueConstraint("package_id", "relative_path"),)

    id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True, comment="技能包文件 ID"
    )
    package_id: Mapped[int] = mapped_column(
        ForeignKey("skill_packages.id", ondelete="CASCADE"),
        index=True,
        comment="所属技能包 ID",
    )
    relative_path: Mapped[str] = mapped_column(
        String(500), nullable=False, comment="文件在技能包内的相对路径"
    )
    role: Mapped[str] = mapped_column(
        String(40), nullable=False, comment="文件角色，如 skill、script、asset、reference"
    )
    size_bytes: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="文件解压后字节数"
    )
    media_type: Mapped[str | None] = mapped_column(
        String(120), nullable=True, comment="根据文件扩展名推断的媒体类型"
    )
    package: Mapped[SkillPackage] = relationship(back_populates="files")


class SkillScriptExecution(BaseModel, TimeModel):
    __tablename__ = "skill_script_executions"

    id: Mapped[int] = mapped_column(
        primary_key=True, autoincrement=True, comment="脚本执行审计 ID"
    )
    platform_id: Mapped[int] = mapped_column(
        ForeignKey("platforms.id", ondelete="CASCADE"),
        index=True,
        comment="所属平台 ID",
    )
    package_id: Mapped[int] = mapped_column(
        ForeignKey("skill_packages.id", ondelete="CASCADE"),
        index=True,
        comment="执行来源技能包 ID",
    )
    skill_id: Mapped[int] = mapped_column(
        ForeignKey("skills.id", ondelete="CASCADE"),
        index=True,
        comment="执行来源 Skill ID",
    )
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"),
        index=True,
        comment="调用所属智能体 ID",
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("sys_users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
        comment="后台用户调用者 ID，Embed 调用为空",
    )
    platform_end_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("platform_end_users.id", ondelete="SET NULL"),
        index=True,
        nullable=True,
        comment="Embed 终端用户调用者 ID，后台调用为空",
    )
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"),
        nullable=True,
        comment="关联对话 ID",
    )
    request_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="关联请求 ID"
    )
    script_path: Mapped[str] = mapped_column(
        String(500), nullable=False, comment="执行脚本在技能包内的相对路径"
    )
    arguments: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, comment="经过校验和脱敏的脚本参数"
    )
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, comment="执行状态，如 requested、running、succeeded、failed"
    )
    exit_code: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="脚本进程退出码"
    )
    stdout: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="截断后的标准输出"
    )
    stderr: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="截断后的标准错误输出"
    )
    error: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="执行器或授权错误信息"
    )
    duration_ms: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="执行耗时毫秒数"
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="进程启动时间"
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="执行完成时间"
    )


class AgentSkill(BaseModel, TimeModel):
    __tablename__ = "agent_skills"
    __table_args__ = (UniqueConstraint("agent_id", "skill_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    agent_id: Mapped[int] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), index=True
    )
    skill_id: Mapped[int] = mapped_column(
        ForeignKey("skills.id", ondelete="CASCADE"), index=True
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    skill: Mapped[Skill] = relationship(lazy="joined")
