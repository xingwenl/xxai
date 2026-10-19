"""对话主模型并入平台模型注册表

把 `agent_versions` 行内的模型三要素（model_name / model_base_url /
api_key_encrypted）提升为 `platform_models(model_type='chat')` 条目，并按 Agent
写入 `agent_model_bindings(role='chat')`，然后删除这三列。

设计取舍见 docs/adr/0008-model-registry-unification.md：
- 按 (platform_id, model_name) 去重，同一平台内同名模型只留一条（取 id 最大的
  那条版本的地址与密钥作为代表）；
- 绑定取 Agent 的 default_version_id，没有发布版本时退化为该 Agent 最新版本；
- 没有模型名的历史脏数据不建条目，也不建绑定，删除列后这些版本会回落到
  `.env` 默认模型；降级时把这一类版本补成 'unknown'，保证列可以恢复 NOT NULL。

Revision ID: 20261016_0039
Revises: 20261015_0038
Create Date: 2026-10-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261016_0039"
down_revision: Union[str, None] = "20261015_0038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1) 存量版本提升为平台级 chat 模型条目（同名去重，取最新一条的地址与密钥）。
    op.execute(
        """
        INSERT INTO platform_models (
            platform_id, name, model_type, model_name, base_url,
            api_key_encrypted, capabilities, options, is_active, created_at, updated_at
        )
        SELECT DISTINCT ON (a.platform_id, v.model_name)
            a.platform_id,
            v.model_name,
            'chat',
            v.model_name,
            v.model_base_url,
            v.api_key_encrypted,
            NULL,
            '{}'::json,
            true,
            now(),
            now()
        FROM agent_versions AS v
        JOIN agents AS a ON a.id = v.agent_id
        WHERE v.model_name IS NOT NULL AND btrim(v.model_name) <> ''
        ORDER BY a.platform_id, v.model_name, v.id DESC
        ON CONFLICT DO NOTHING
        """
    )
    # 2) 每个 Agent 绑定自己的对话模型（优先 default_version_id，其次最新版本）。
    op.execute(
        """
        INSERT INTO agent_model_bindings (
            agent_id, model_id, role, created_at, updated_at
        )
        SELECT a.id, pm.id, 'chat', now(), now()
        FROM agents AS a
        JOIN agent_versions AS v
          ON v.id = COALESCE(
              a.default_version_id,
              (SELECT max(id) FROM agent_versions WHERE agent_id = a.id)
          )
        JOIN platform_models AS pm
          ON pm.platform_id = a.platform_id
         AND pm.model_type = 'chat'
         AND pm.model_name = v.model_name
        WHERE v.model_name IS NOT NULL AND btrim(v.model_name) <> ''
        ON CONFLICT DO NOTHING
        """
    )
    # 3) 模型三要素归注册表所有，版本行只留提示词与采样参数。
    op.drop_column("agent_versions", "api_key_encrypted")
    op.drop_column("agent_versions", "model_base_url")
    op.drop_column("agent_versions", "model_name")


def downgrade() -> None:
    # 1) 先恢复可空列，再从绑定回填，最后补 NOT NULL。
    op.add_column(
        "agent_versions", sa.Column("model_name", sa.String(length=120), nullable=True)
    )
    op.add_column(
        "agent_versions",
        sa.Column("model_base_url", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "agent_versions", sa.Column("api_key_encrypted", sa.Text(), nullable=True)
    )
    op.execute(
        """
        UPDATE agent_versions AS v
        SET model_name = pm.model_name,
            model_base_url = pm.base_url,
            api_key_encrypted = pm.api_key_encrypted
        FROM agent_model_bindings AS b
        JOIN platform_models AS pm ON pm.id = b.model_id
        WHERE b.agent_id = v.agent_id
          AND b.role = 'chat'
        """
    )
    # 升级前没有模型名的版本在降级后也必须满足 NOT NULL：占位值只服务于
    # 「迁移可逆」，不做任何模型推断。
    op.execute(
        "UPDATE agent_versions SET model_name = 'unknown' WHERE model_name IS NULL"
    )
    op.alter_column("agent_versions", "model_name", nullable=False)
    # 2) 清掉本次提升出来的 chat 条目与绑定（chat 类型条目在升级前并不存在）。
    op.execute("DELETE FROM agent_model_bindings WHERE role = 'chat'")
    op.execute("DELETE FROM platform_models WHERE model_type = 'chat'")
