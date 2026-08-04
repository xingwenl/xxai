"""add skill package storage metadata"""

from alembic import op
import sqlalchemy as sa

revision = "20260804_0014"
down_revision = "20260731_0013"
branch_labels = None
depends_on = None


def _timestamps():
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "skill_packages",
        sa.Column("id", sa.Integer(), primary_key=True, comment="技能包 ID"),
        sa.Column(
            "platform_id",
            sa.Integer(),
            sa.ForeignKey("platforms.id", ondelete="CASCADE"),
            nullable=False,
            comment="所属平台 ID",
        ),
        sa.Column("name", sa.String(120), nullable=False, comment="技能包名称"),
        sa.Column(
            "slug", sa.String(80), nullable=False, comment="平台内唯一技能包标识"
        ),
        sa.Column(
            "package_type",
            sa.String(40),
            nullable=False,
            comment="技能包类型，如 skill 或 codex_plugin",
        ),
        sa.Column(
            "source_filename",
            sa.String(255),
            nullable=False,
            comment="原始上传文件名",
        ),
        sa.Column(
            "storage_path",
            sa.String(1000),
            nullable=False,
            comment="技能包解压后的受控存储目录",
        ),
        sa.Column(
            "manifest",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
            comment="技能包 manifest 或解析元数据",
        ),
        sa.Column(
            "warnings",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
            comment="导入时产生的兼容性警告",
        ),
        sa.Column(
            "allow_script_execution",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
            comment="是否允许运行时执行包内脚本",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
            comment="技能包是否启用",
        ),
        *_timestamps(),
        sa.UniqueConstraint("platform_id", "slug"),
    )
    op.create_index("ix_skill_packages_platform_id", "skill_packages", ["platform_id"])

    op.create_table(
        "skill_package_files",
        sa.Column("id", sa.Integer(), primary_key=True, comment="技能包文件 ID"),
        sa.Column(
            "package_id",
            sa.Integer(),
            sa.ForeignKey("skill_packages.id", ondelete="CASCADE"),
            nullable=False,
            comment="所属技能包 ID",
        ),
        sa.Column(
            "relative_path",
            sa.String(500),
            nullable=False,
            comment="文件在技能包内的相对路径",
        ),
        sa.Column(
            "role",
            sa.String(40),
            nullable=False,
            comment="文件角色，如 skill、script、asset、reference",
        ),
        sa.Column(
            "size_bytes", sa.BigInteger(), nullable=False, comment="文件解压后字节数"
        ),
        sa.Column(
            "media_type",
            sa.String(120),
            nullable=True,
            comment="根据文件扩展名推断的媒体类型",
        ),
        *_timestamps(),
        sa.UniqueConstraint("package_id", "relative_path"),
    )
    op.create_index(
        "ix_skill_package_files_package_id", "skill_package_files", ["package_id"]
    )

    op.add_column(
        "skills",
        sa.Column(
            "package_id",
            sa.Integer(),
            sa.ForeignKey("skill_packages.id", ondelete="SET NULL"),
            nullable=True,
            comment="来源技能包 ID，手工创建技能为空",
        ),
    )
    op.add_column(
        "skills",
        sa.Column(
            "package_skill_path",
            sa.String(500),
            nullable=True,
            comment="技能包内 SKILL.md 相对路径，手工创建技能为空",
        ),
    )
    op.create_index("ix_skills_package_id", "skills", ["package_id"])


def downgrade() -> None:
    op.drop_index("ix_skills_package_id", table_name="skills")
    op.drop_column("skills", "package_skill_path")
    op.drop_column("skills", "package_id")
    op.drop_table("skill_package_files")
    op.drop_table("skill_packages")
