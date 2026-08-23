"""微信助手绑定服务单元测试（mock iLink 网络调用）。"""

import asyncio

import pytest

from app.modules.wechat_bot import services
from app.modules.wechat_bot.models import WeChatBotBinding


class _FakeRepo:
    def __init__(self) -> None:
        self.created: dict | None = None
        self.updated: list[tuple[WeChatBotBinding, dict]] = []

    async def get_one_by(self, **filters):
        return None

    async def create(self, **kwargs):
        self.created = kwargs
        binding = WeChatBotBinding(**kwargs)
        binding.id = 1
        return binding

    async def update(self, binding, **kwargs):
        self.updated.append((binding, kwargs))
        for key, value in kwargs.items():
            setattr(binding, key, value)
        return binding


class _PendingRepo(_FakeRepo):
    def __init__(self, binding) -> None:
        super().__init__()
        self._existing = binding

    async def get_one_by(self, **filters):
        return self._existing

    async def update(self, binding, **kwargs):
        self.updated.append((binding, kwargs))
        for key, value in kwargs.items():
            setattr(binding, key, value)
        return binding


def test_hash_api_token_is_stable_sha256() -> None:
    assert services.hash_api_token("abc") == services.hash_api_token("abc")
    assert services.hash_api_token("abc") != services.hash_api_token("abd")
    assert len(services.hash_api_token("abc")) == 64


def test_create_binding_generates_qrcode_and_tokens(monkeypatch) -> None:
    class _FakeApi:
        async def get_qr_code(self, base_url, local_token_list=None):
            return {"qrcode_img_content": "https://qr", "qrcode": "qr-key"}

    monkeypatch.setattr(services, "ILinkApi", lambda: _FakeApi())
    repo = _FakeRepo()

    binding, api_token = asyncio.run(
        services.create_binding(
            repo, platform_id=1, user_id=2, agent_id=None
        )
    )
    assert repo.created["status"] == "pending"
    assert binding.qrcode == "https://qr"
    assert api_token
    assert repo.created["api_token_hash"] == services.hash_api_token(api_token)
    assert repo.created["api_token_encrypted"]


def test_create_binding_reuses_pending_record(monkeypatch) -> None:
    """pending 状态可再次生成二维码，不再报冲突。"""
    class _FakeApi:
        async def get_qr_code(self, base_url, local_token_list=None):
            return {"qrcode_img_content": "https://qr-2", "qrcode": "qr-key-2"}

    monkeypatch.setattr(services, "ILinkApi", lambda: _FakeApi())
    existing = WeChatBotBinding(
        platform_id=1,
        user_id=2,
        status="pending",
        qrcode="https://old",
        qrcode_key="old-key",
    )
    existing.id = 1
    repo = _PendingRepo(existing)

    binding, api_token = asyncio.run(
        services.create_binding(repo, platform_id=1, user_id=2, agent_id=None)
    )
    assert binding.id == 1
    assert binding.status == "pending"
    assert binding.qrcode == "https://qr-2"
    assert binding.qrcode_key == "qr-key-2"
    assert repo.created is None
    assert api_token
    assert binding.api_token_hash == services.hash_api_token(api_token)


def test_poll_binding_status_confirmed_activates(monkeypatch) -> None:
    class _FakeApi:
        async def poll_qr_status(self, base_url, qrcode, verify_code=None):
            return {
                "status": "confirmed",
                "bot_token": "bot-token-1",
                "ilink_bot_id": "bot-1",
                "ilink_user_id": "wx-1",
            }

    monkeypatch.setattr(services, "ILinkApi", lambda: _FakeApi())
    repo = _FakeRepo()
    binding = WeChatBotBinding(
        platform_id=1, user_id=2, status="pending", qrcode_key="qr-key"
    )
    binding.id = 1

    state = asyncio.run(services.poll_binding_status(repo, binding))
    assert state == "confirmed"
    assert binding.status == "active"
    assert binding.bot_token_encrypted
    assert binding.ilink_bot_id == "bot-1"


def test_poll_binding_status_binded_redirect_marks_expired(monkeypatch) -> None:
    class _FakeApi:
        async def poll_qr_status(self, base_url, qrcode, verify_code=None):
            return {"status": "binded_redirect"}

    monkeypatch.setattr(services, "ILinkApi", lambda: _FakeApi())
    repo = _FakeRepo()
    binding = WeChatBotBinding(
        platform_id=1, user_id=2, status="pending", qrcode_key="qr-key"
    )
    binding.id = 1

    state = asyncio.run(services.poll_binding_status(repo, binding))
    assert state == "binded_redirect"
    assert binding.status == "expired"


def test_poll_binding_status_need_verifycode(monkeypatch) -> None:
    class _FakeApi:
        async def poll_qr_status(self, base_url, qrcode, verify_code=None):
            assert verify_code is None
            return {"status": "need_verifycode"}

    monkeypatch.setattr(services, "ILinkApi", lambda: _FakeApi())
    repo = _FakeRepo()
    binding = WeChatBotBinding(
        platform_id=1, user_id=2, status="pending", qrcode_key="qr-key"
    )
    binding.id = 1

    state = asyncio.run(services.poll_binding_status(repo, binding))
    assert state == "need_verifycode"
    assert binding.status == "pending"


def test_poll_binding_status_confirm_with_verify_code(monkeypatch) -> None:
    class _FakeApi:
        async def poll_qr_status(self, base_url, qrcode, verify_code=None):
            assert verify_code == "123456"
            return {
                "status": "confirmed",
                "bot_token": "bot-token-2",
                "ilink_bot_id": "bot-2",
                "ilink_user_id": "wx-2",
            }

    monkeypatch.setattr(services, "ILinkApi", lambda: _FakeApi())
    repo = _FakeRepo()
    binding = WeChatBotBinding(
        platform_id=1,
        user_id=2,
        status="pending",
        qrcode_key="qr-key",
        pending_verify_code="123456",
    )
    binding.id = 1

    state = asyncio.run(services.poll_binding_status(repo, binding))
    assert state == "confirmed"
    assert binding.status == "active"
    assert binding.pending_verify_code is None


def test_poll_binding_status_redirect_updates_base_url(monkeypatch) -> None:
    class _FakeApi:
        async def poll_qr_status(self, base_url, qrcode, verify_code=None):
            return {"status": "scaned_but_redirect", "redirect_host": "ilink2.weixin.qq.com"}

    monkeypatch.setattr(services, "ILinkApi", lambda: _FakeApi())
    repo = _FakeRepo()
    binding = WeChatBotBinding(
        platform_id=1, user_id=2, status="pending", qrcode_key="qr-key"
    )
    binding.id = 1

    state = asyncio.run(services.poll_binding_status(repo, binding))
    assert state == "scaned"
    assert binding.qrcode_base_url == "https://ilink2.weixin.qq.com"


def test_poll_binding_status_timeout_returns_error(monkeypatch) -> None:
    class _SlowApi:
        async def poll_qr_status(self, base_url, qrcode, verify_code=None):
            await asyncio.sleep(30)
            return {"status": "wait"}

    monkeypatch.setattr(services, "ILinkApi", lambda: _SlowApi())
    repo = _FakeRepo()
    binding = WeChatBotBinding(
        platform_id=1, user_id=2, status="pending", qrcode_key="qr-key"
    )
    binding.id = 1

    with pytest.MonkeyPatch.context() as mp:
        async def _fast_wait_for(awaitable, timeout):
            raise asyncio.TimeoutError()

        mp.setattr(asyncio, "wait_for", _fast_wait_for)
        state = asyncio.run(services.poll_binding_status(repo, binding))

    assert state == "error"
    assert "超时" in binding.last_error


def test_deactivate_binding_clears_sensitive_fields() -> None:
    repo = _FakeRepo()
    binding = WeChatBotBinding(
        platform_id=1,
        user_id=2,
        status="active",
        bot_token_encrypted="enc",
        api_token_hash="h",
        api_token_encrypted="e",
    )
    asyncio.run(services.deactivate_binding(repo, binding))
    assert binding.status == "disabled"
    assert binding.is_active is False
    assert binding.bot_token_encrypted is None
    assert binding.api_token_hash is None
    assert binding.api_token_encrypted is None
