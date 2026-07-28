import json

MAX_MESSAGE_BYTES = 64 * 1024
MAX_TEXT_BYTES = 16 * 1024


def validate_incoming_message(raw: str) -> dict:
    if len(raw.encode("utf-8")) > MAX_MESSAGE_BYTES:
        raise ValueError("message_too_large")
    try:
        message = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid_json") from exc
    if not isinstance(message, dict):
        raise ValueError("invalid_message")
    if message.get("type") in {
        "host_tools_register",
        "host_tool_result",
        "host_tool_error",
        "confirmation_resolve",
    } and not isinstance(message.get("payload"), dict):
        raise ValueError("invalid_host_tool_payload")
    if message.get("type") == "message_send":
        text = message.get("payload", {}).get("text")
        if isinstance(text, str) and len(text.encode("utf-8")) > MAX_TEXT_BYTES:
            raise ValueError("text_too_large")
    return message


class RequestLimiter:
    def __init__(self) -> None:
        self.active = False

    def begin(self) -> bool:
        if self.active:
            return False
        self.active = True
        return True

    def end(self) -> None:
        self.active = False
