from app.modules.asset.models import ConversationAsset
from app.modules.builtin_tool.models import AgentBuiltinTool


def test_new_model_fields_have_chinese_comments() -> None:
    for model in (AgentBuiltinTool, ConversationAsset):
        missing = [
            column.name for column in model.__table__.columns if not column.comment
        ]
        assert missing == []


def test_asset_requires_exactly_one_conversation_principal() -> None:
    constraints = {
        constraint.name for constraint in ConversationAsset.__table__.constraints
    }
    assert (
        "ck_conversation_assets_ck_conversation_assets_exactly_one_principal"
        in constraints
    )
