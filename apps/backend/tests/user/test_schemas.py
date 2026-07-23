from pydantic import ValidationError

from app.modules.user.schemas import UserCreate, UserUpdate


def test_user_create_schema_accepts_valid_payload() -> None:
    payload = UserCreate(
        name="Alice",
        email="alice@example.com",
        account="alice",
        password="secret123",
    )

    assert payload.name == "Alice"
    assert payload.email == "alice@example.com"
    assert payload.account == "alice"


def test_user_create_schema_rejects_empty_name() -> None:
    try:
        UserCreate(name="", email="alice@example.com", account="alice", password="secret123")
    except ValidationError:
        return

    raise AssertionError("UserCreate should reject an empty name")


def test_user_update_schema_accepts_partial_payload() -> None:
    payload = UserUpdate(name="Bob")

    assert payload.name == "Bob"
    assert payload.email is None
    assert payload.account is None
    assert payload.is_active is None
