"""add skill script execution audit"""

from alembic import op
import sqlalchemy as sa

revision = "20260804_0015"
down_revision = "20260804_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "skill_packages",
        sa.Column(
            "storage_key",
            sa.String(500),
            nullable=True,
            comment="技能包在受控存储根目录下的相对定位键",
        ),
    )
    op.execute(
        "UPDATE skill_packages SET storage_key = 'skill-packages/' || "
        "regexp_replace(storage_path, '^.*/skill-packages/', '')"
    )
    op.alter_column("skill_packages", "storage_key", nullable=False)
    op.create_table(
        "skill_script_executions",
        sa.Column("id", sa.Integer(), primary_key=True, comment="脚本执行审计 ID"),
        sa.Column(
            "platform_id",
            sa.Integer(),
            sa.ForeignKey("platforms.id", ondelete="CASCADE"),
            nullable=False,
            comment="所属平台 ID",
        ),
        sa.Column(
            "package_id",
            sa.Integer(),
            sa.ForeignKey("skill_packages.id", ondelete="CASCADE"),
            nullable=False,
            comment="执行来源技能包 ID",
        ),
        sa.Column(
            "skill_id",
            sa.Integer(),
            sa.ForeignKey("skills.id", ondelete="CASCADE"),
            nullable=False,
            comment="执行来源 Skill ID",
        ),
        sa.Column(
            "agent_id",
            sa.Integer(),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
            comment="调用所属智能体 ID",
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("sys_users.id", ondelete="SET NULL"),
            nullable=True,
            comment="后台用户调用者 ID，Embed 调用为空",
        ),
        sa.Column(
            "platform_end_user_id",
            sa.Integer(),
            sa.ForeignKey("platform_end_users.id", ondelete="SET NULL"),
            nullable=True,
            comment="Embed 终端用户调用者 ID，后台调用为空",
        ),
        sa.Column(
            "conversation_id",
            sa.Integer(),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
            comment="关联对话 ID",
        ),
        sa.Column("request_id", sa.String(128), nullable=True, comment="关联请求 ID"),
        sa.Column(
            "script_path",
            sa.String(500),
            nullable=False,
            comment="执行脚本在技能包内的相对路径",
        ),
        sa.Column(
            "arguments", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json"), comment="经过校验和脱敏的脚本参数"
        ),
        sa.Column("status", sa.String(30), nullable=False, comment="脚本执行状态"),
        sa.Column("exit_code", sa.Integer(), nullable=True, comment="脚本进程退出码"),
        sa.Column("stdout", sa.Text(), nullable=True, comment="截断后的标准输出"),
        sa.Column("stderr", sa.Text(), nullable=True, comment="截断后的标准错误输出"),
        sa.Column("error", sa.Text(), nullable=True, comment="执行器或授权错误信息"),
        sa.Column("duration_ms", sa.Integer(), nullable=True, comment="执行耗时毫秒数"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True, comment="进程启动时间"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True, comment="执行完成时间"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    for name, column in (
        ("platform_id", "platform_id"),
        ("package_id", "package_id"),
        ("skill_id", "skill_id"),
        ("agent_id", "agent_id"),
        ("user_id", "user_id"),
        ("platform_end_user_id", "platform_end_user_id"),
    ):
        op.create_index(f"ix_skill_script_executions_{name}", "skill_script_executions", [column])


def downgrade() -> None:
    for name in (
        "platform_id",
        "package_id",
        "skill_id",
        "agent_id",
        "user_id",
        "platform_end_user_id",
    ):
        op.drop_index(f"ix_skill_script_executions_{name}", table_name="skill_script_executions")
    op.drop_table("skill_script_executions")
    op.drop_column("skill_packages", "storage_key")
