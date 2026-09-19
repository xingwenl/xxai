"""tasks 新增终端用户执行身份列

Revision ID: 20260919_0035
Revises: 20260919_0034
Create Date: 2026-09-19
"""

import sqlalchemy as sa
from alembic import op

revision: str = "20260919_0035"
down_revision: str = "20260919_0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """为任务补充「以终端用户身份执行」的列。

    背景：Embed/AI SDK 链路的会话只有一个终端用户 principal，没有后台用户。
    原实现要求任务必须绑定后台用户，导致该链路无法创建任务。这里新增一列
    保存终端用户执行身份，与 run_as_user_id 互斥（由 run_as_type 决定用哪个）。
    """
    op.add_column(
        "tasks",
        sa.Column(
            "run_as_end_user_id",
            sa.Integer(),
            nullable=True,
            comment="以哪个终端用户身份执行（run_as_type=end_user 时必填，Embed 链路创建的任务用）",
        ),
    )
    op.create_foreign_key(
        op.f("fk_tasks_run_as_end_user_id_platform_end_users"),
        "tasks",
        "platform_end_users",
        ["run_as_end_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # run_as_type 的可取值集合扩大，注释同步更新，避免注释与实现口径不一致。
    op.alter_column(
        "tasks",
        "run_as_type",
        existing_type=sa.String(length=20),
        existing_nullable=False,
        existing_server_default="user",
        comment="执行身份类型：user 后台用户 / end_user 终端用户 / platform 预留（v1 不支持）",
    )
    op.alter_column(
        "tasks",
        "run_as_user_id",
        existing_type=sa.Integer(),
        existing_nullable=True,
        comment="以哪个后台用户身份执行（run_as_type=user 时必填）",
    )


def downgrade() -> None:
    """回滚删除终端用户执行身份列。

    注意：回滚后已创建的终端用户任务会失去执行身份，需要管理员手动暂停或删除。
    """
    op.alter_column(
        "tasks",
        "run_as_user_id",
        existing_type=sa.Integer(),
        existing_nullable=True,
        comment="以哪个用户身份执行（run_as_type=user 时必填）",
    )
    op.alter_column(
        "tasks",
        "run_as_type",
        existing_type=sa.String(length=20),
        existing_nullable=False,
        existing_server_default="user",
        comment="执行身份类型：user 以某个用户身份运行（v1 仅支持该取值）",
    )
    op.drop_constraint(
        op.f("fk_tasks_run_as_end_user_id_platform_end_users"),
        "tasks",
        type_="foreignkey",
    )
    op.drop_column("tasks", "run_as_end_user_id")
