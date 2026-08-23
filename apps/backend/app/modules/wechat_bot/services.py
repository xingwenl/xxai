"""微信助手绑定服务：二维码获取、状态轮询、服务 token 与敏感字段管理。"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
from datetime import UTC, datetime

from wechatbot.protocol import ILinkApi

from app.core.logging import get_logger
from app.modules.agent.services import decrypt_secret, encrypt_secret
from app.modules.wechat_bot.models import WeChatBotBinding
from app.modules.wechat_bot.repositories import WeChatBotBindingRepository
from app.shared.exceptions import ConflictException, NotFoundException

logger = get_logger(__name__)

FIXED_QR_BASE_URL = "https://ilinkai.weixin.qq.com"


def generate_api_token() -> str:
    """生成微信助手服务 token（创建绑定后仅返回一次明文）。"""
    return secrets.token_urlsafe(32)


def hash_api_token(token: str) -> str:
    """服务 token 以 sha256 哈希落库，禁止存明文。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def create_binding(
    repo: WeChatBotBindingRepository,
    *,
    platform_id: int,
    user_id: int,
    agent_id: int | None,
) -> tuple[WeChatBotBinding, str]:
    """创建绑定：生成二维码与服务 token，状态 pending。

    每个用户每平台仅 1 条记录：已存在未生效（pending/expired/disabled）的绑定
    时复用该记录重新生成二维码与 token，便于扫码失败后再次绑定；
    已生效（active）的绑定必须先解绑。
    """
    existing = await repo.get_one_by(platform_id=platform_id, user_id=user_id)
    if existing is not None and existing.status == "active":
        raise ConflictException("当前用户已存在微信助手绑定，请先解绑")

    api = ILinkApi()
    qr = await api.get_qr_code(FIXED_QR_BASE_URL)
    api_token = generate_api_token()
    values = dict(
        agent_id=agent_id,
        status="pending",
        qrcode=qr["qrcode_img_content"],
        qrcode_key=qr["qrcode"],
        qrcode_base_url=FIXED_QR_BASE_URL,
        pending_verify_code=None,
        api_token_hash=hash_api_token(api_token),
        api_token_encrypted=encrypt_secret(api_token),
        is_active=True,
        last_error=None,
    )
    if existing is not None:
        binding = await repo.update(existing, **values)
    else:
        binding = await repo.create(
            platform_id=platform_id, user_id=user_id, **values
        )
    logger.info("wechat binding created platform_id=%s user_id=%s", platform_id, user_id)
    return binding, api_token


async def poll_binding_status(
    repo: WeChatBotBindingRepository,
    binding: WeChatBotBinding,
    *,
    verify_code: str | None = None,
) -> str:
    """轮询扫码状态；confirmed 后加密保存 bot_token 并置 active。

    完整状态机：wait / scaned / confirmed / expired / binded_redirect /
    need_verifycode（需提交配对码）/ verify_code_blocked / scaned_but_redirect
    （IDC 重定向，更新轮询基址）。verify_code 参数优先于已存的配对码。
    """
    api = ILinkApi()
    base_url = binding.qrcode_base_url or FIXED_QR_BASE_URL
    code = verify_code if verify_code is not None else binding.pending_verify_code
    try:
        result = await asyncio.wait_for(
            api.poll_qr_status(base_url, binding.qrcode_key or "", code),
            timeout=10.0,
        )
    except asyncio.TimeoutError:
        logger.warning("wechat qr poll timeout binding_id=%s", binding.id)
        await repo.update(binding, last_error="二维码状态查询超时，请稍后重试")
        return "error"
    except Exception as exc:
        logger.warning("wechat qr poll failed binding_id=%s err=%s", binding.id, exc)
        await repo.update(
            binding, last_error=f"二维码状态查询失败：{type(exc).__name__}"
        )
        return "error"

    current = result.get("status", "")
    logger.info("wechat qr poll binding_id=%s status=%s", binding.id, current)
    if current == "confirmed":
        token = result.get("bot_token")
        bot_id = result.get("ilink_bot_id")
        user_id = result.get("ilink_user_id")
        if not token or not bot_id or not user_id:
            await repo.update(binding, last_error="扫码确认成功但缺少账号信息")
            return "error"
        await repo.update(
            binding,
            status="active",
            bot_token_encrypted=encrypt_secret(token),
            ilink_bot_id=bot_id,
            ilink_user_id=user_id,
            qrcode=None,
            qrcode_key=None,
            qrcode_base_url=None,
            pending_verify_code=None,
            last_error=None,
            last_login_at=datetime.now(UTC),
        )
        logger.info(
            "wechat binding activated binding_id=%s ilink_bot_id=%s",
            binding.id,
            bot_id,
        )
        return "confirmed"

    if current == "expired":
        await repo.update(
            binding,
            status="expired",
            last_error="二维码已过期，请重新创建绑定",
        )
        return "expired"

    if current == "binded_redirect":
        await repo.update(
            binding,
            status="expired",
            last_error="该微信号已绑定其他机器人，请先在微信 ClawBot 中解绑后重试",
        )
        return "binded_redirect"

    if current == "need_verifycode":
        await repo.update(
            binding,
            last_error="请在微信中查看配对码并提交（6 位数字）",
        )
        return "need_verifycode"

    if current == "verify_code_blocked":
        await repo.update(
            binding,
            status="expired",
            last_error="配对码错误次数过多，请重新生成二维码绑定",
        )
        return "verify_code_blocked"

    if current == "scaned_but_redirect":
        redirect_host = result.get("redirect_host")
        if redirect_host:
            await repo.update(
                binding, qrcode_base_url=f"https://{redirect_host}"
            )
        return "scaned"

    if current == "scaned":
        return "scaned"
    return "wait"


async def deactivate_binding(
    repo: WeChatBotBindingRepository, binding: WeChatBotBinding
) -> None:
    """解绑：清除敏感字段并停用（worker 刷新后停止对应实例）。"""
    await repo.update(
        binding,
        status="disabled",
        is_active=False,
        bot_token_encrypted=None,
        api_token_hash=None,
        api_token_encrypted=None,
        ilink_bot_id=None,
        ilink_user_id=None,
        qrcode=None,
        qrcode_key=None,
        qrcode_base_url=None,
        pending_verify_code=None,
        last_error=None,
    )
    logger.info("wechat binding disabled binding_id=%s", binding.id)


def get_binding_bot_token(binding: WeChatBotBinding) -> str:
    """解密绑定记录的 bot_token；未绑定/无凭证时抛 404。"""
    if not binding.bot_token_encrypted:
        raise NotFoundException("wechat bot token missing")
    return decrypt_secret(binding.bot_token_encrypted)


def get_binding_api_token(binding: WeChatBotBinding) -> str:
    """解密绑定记录的服务 token（worker 调 chat 接口用）。"""
    if not binding.api_token_encrypted:
        raise NotFoundException("wechat service token missing")
    return decrypt_secret(binding.api_token_encrypted)
