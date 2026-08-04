"""修正既有技能包的存储定位键。"""

from alembic import op

revision = "20260804_0016"
down_revision = "20260804_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0015 早期版本回填时遗漏了受控存储根目录下的 skill-packages 前缀。
    op.execute(
        "UPDATE skill_packages "
        "SET storage_key = 'skill-packages/' || storage_key "
        "WHERE storage_key NOT LIKE 'skill-packages/%'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE skill_packages "
        "SET storage_key = regexp_replace(storage_key, '^skill-packages/', '') "
        "WHERE storage_key LIKE 'skill-packages/%'"
    )
