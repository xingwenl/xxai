import pytest

from app.modules.skill.services import render_skill_instruction
from app.shared.exceptions import BadRequestException


def test_render_skill_instruction_uses_declared_parameters() -> None:
    result = render_skill_instruction(
        "请为 {{ customer }} 查询订单 {{ order_id }}",
        {"customer": "Alice", "order_id": "A-100"},
    )

    assert result == "请为 Alice 查询订单 A-100"


def test_render_skill_instruction_rejects_missing_parameter() -> None:
    with pytest.raises(BadRequestException, match="skill parameter is missing"):
        render_skill_instruction("查询 {{ order_id }}", {})
