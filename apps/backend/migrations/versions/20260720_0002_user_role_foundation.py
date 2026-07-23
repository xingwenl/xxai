"""add user role foundation

Revision ID: 20260720_0002
Revises: 20260719_0001
Create Date: 2026-07-20 18:30:00

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = "20260720_0002"
down_revision = "20260719_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    table_names = set(inspector.get_table_names())

    if "users" in table_names and "sys_users" not in table_names:
        user_indexes = {index["name"] for index in inspector.get_indexes("users")}
        if op.f("ix_users_email") in user_indexes:
            op.drop_index(op.f("ix_users_email"), table_name="users")
        op.rename_table("users", "sys_users")
        inspector = inspect(bind)
        table_names = set(inspector.get_table_names())

    sys_user_columns = {column["name"] for column in inspector.get_columns("sys_users")}
    sys_user_indexes = {index["name"] for index in inspector.get_indexes("sys_users")}

    if "account" not in sys_user_columns:
        op.add_column("sys_users", sa.Column("account", sa.String(length=40), nullable=True))
    if "password" not in sys_user_columns:
        op.add_column("sys_users", sa.Column("password", sa.String(length=60), nullable=True))

    op.execute("UPDATE sys_users SET account = email WHERE account IS NULL")
    op.execute("UPDATE sys_users SET password = 'temporary_password' WHERE password IS NULL")

    op.alter_column("sys_users", "account", existing_type=sa.String(length=100), type_=sa.String(length=40), nullable=False)
    op.alter_column("sys_users", "password", existing_type=sa.String(length=30), type_=sa.String(length=60), nullable=False)

    if op.f("ix_users_email") in sys_user_indexes:
        op.drop_index(op.f("ix_users_email"), table_name="sys_users")
    if op.f("ix_sys_users_email") not in sys_user_indexes:
        op.create_index(op.f("ix_sys_users_email"), "sys_users", ["email"], unique=True)
    if op.f("ix_sys_users_account") not in sys_user_indexes:
        op.create_index(op.f("ix_sys_users_account"), "sys_users", ["account"], unique=True)

    if "sys_roles" not in table_names:
        op.create_table(
            "sys_roles",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("code", sa.String(length=100), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("description", sa.String(length=255), nullable=True),
            sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_sys_roles")),
        )
        op.create_index(op.f("ix_sys_roles_code"), "sys_roles", ["code"], unique=True)

    if "sys_user_roles" not in table_names:
        op.create_table(
            "sys_user_roles",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("role_id", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["role_id"], ["sys_roles.id"], name=op.f("fk_sys_user_roles_role_id_sys_roles"), ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["user_id"], ["sys_users.id"], name=op.f("fk_sys_user_roles_user_id_sys_users"), ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id", name=op.f("pk_sys_user_roles")),
            sa.UniqueConstraint("user_id", "role_id", name="uq_sys_user_roles_user_id_role_id"),
        )
        op.create_index(op.f("ix_sys_user_roles_user_id"), "sys_user_roles", ["user_id"], unique=False)
        op.create_index(op.f("ix_sys_user_roles_role_id"), "sys_user_roles", ["role_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_sys_user_roles_role_id"), table_name="sys_user_roles")
    op.drop_index(op.f("ix_sys_user_roles_user_id"), table_name="sys_user_roles")
    op.drop_table("sys_user_roles")

    op.drop_index(op.f("ix_sys_roles_code"), table_name="sys_roles")
    op.drop_table("sys_roles")

    op.drop_index(op.f("ix_sys_users_account"), table_name="sys_users")
    op.drop_column("sys_users", "password")
    op.drop_column("sys_users", "account")
    op.drop_index(op.f("ix_sys_users_email"), table_name="sys_users")
    op.rename_table("sys_users", "users")
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
