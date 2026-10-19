"""新增会话上下文压缩表 conversation_context_compactions

上下文超预算时此前的唯一动作是「整轮删掉最旧历史」，不可逆且用户无从得知。
本表承载新的首选动作——把较早历史交给同一个对话模型摘要成固定小节：

- 摘要正文与保留边界（``first_kept_message_id``）一起落库，模型此后可见的
  上下文 = 摘要（SystemMessage）+ 保留边界之后的消息；
- 原始消息永远保留在 ``conversation_messages``，本表只描述「发给模型的视图」；
- 行只增不改：最近一行即当前生效的摘要，再次压缩时新摘要并入旧摘要写成新行，
  旧行留作审计；``usage`` 记录摘要请求自身用量，便于核算压缩成本。

设计取舍见 docs/adr/0011-context-usage-and-compaction.md。

Revision ID: 20261019_0042
Revises: 20261019_0041
Create Date: 2026-10-19
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261019_0042"
down_revision: Union[str, None] = "20261019_0041"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversation_context_compactions",
        sa.Column(
            "id",
            sa.Integer(),
            autoincrement=True,
            nullable=False,
            comment="上下文压缩记录主键",
        ),
        sa.Column(
            "conversation_id",
            sa.Integer(),
            nullable=False,
            comment="所属会话 ID",
        ),
        sa.Column(
            "summary",
            sa.Text(),
            nullable=False,
            comment="压缩摘要正文，此后作为 SystemMessage 注入模型上下文",
        ),
        sa.Column(
            "first_kept_message_id",
            sa.Integer(),
            nullable=False,
            comment="保留边界：该消息及其之后的消息完整保留，之前的历史由摘要代替",
        ),
        sa.Column(
            "tokens_before",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
            comment="压缩前的上下文占用估算（token）",
        ),
        sa.Column(
            "tokens_after",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
            comment="压缩后重建上下文的占用估算（token）",
        ),
        sa.Column(
            "trigger",
            sa.String(length=20),
            server_default="auto",
            nullable=False,
            comment="触发方式：auto（超过阈值自动压缩）或 manual（用户手动压缩）",
        ),
        sa.Column(
            "instructions",
            sa.Text(),
            nullable=True,
            comment="手动压缩时用户附加的聚焦点，自动压缩为空",
        ),
        sa.Column(
            "model_name",
            sa.String(length=120),
            nullable=True,
            comment="执行摘要的模型名，用于审计压缩来源",
        ),
        sa.Column(
            "usage",
            sa.JSON(),
            nullable=True,
            comment="摘要请求自身的 token 用量，用于审计压缩成本",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="记录创建时间（UTC）",
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
            comment="记录最后更新时间（UTC）",
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            # 命名约定展开后超过 PG 的 63 字符标识符上限，SQLAlchemy 会截断并追加
            # 确定性后缀；这里必须写编译后的真实名字，否则 autogenerate 会反复尝试
            # 重建这个外键（同 20261019_0041 的处理）。
            name=op.f("fk_conversation_context_compactions_conversation_id_con_d153"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["first_kept_message_id"],
            ["conversation_messages.id"],
            name=op.f("fk_conversation_context_compactions_first_kept_message__151b"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "id", name=op.f("pk_conversation_context_compactions")
        ),
    )
    op.create_index(
        "ix_conversation_context_compactions_conversation_id",
        "conversation_context_compactions",
        ["conversation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversation_context_compactions_conversation_id",
        table_name="conversation_context_compactions",
    )
    op.drop_table("conversation_context_compactions")
