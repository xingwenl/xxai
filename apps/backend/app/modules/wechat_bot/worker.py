"""微信 ClawBot 多实例 worker 入口

按数据库 wechat_bot_bindings 中 active 的绑定记录，为每个绑定启动一个独立
WeChatBot 实例（单账号单实例长轮询）；收到消息后以绑定用户的服务 token
调用后台 /api/v1/agents/{agent_id}/chat 接口获取回复。

运行方式（在 apps/backend 目录）：
    python -m app.modules.wechat_bot.worker
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

try:
    from wechatbot import WeChatBot
    from wechatbot.types import Credentials
except ImportError:  # 未安装 SDK 时延迟到 main() 报错退出
    WeChatBot = None  # type: ignore[assignment,misc]
    Credentials = None  # type: ignore[assignment,misc]

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.core.logging import get_logger, setup_logging
from app.modules.agent.repositories import AgentRepository
from app.modules.wechat_bot.chat_client import (
    ConversationNotFoundError,
    WeChatChatClient,
)
from app.modules.wechat_bot.repositories import WeChatBotBindingRepository
from app.modules.wechat_bot.services import (
    get_binding_api_token,
    get_binding_bot_token,
)
from app.modules.wechat_bot.session import (
    WeChatBotSession,
    install_cursor_persistence,
)

logger = get_logger(__name__)

REFRESH_INTERVAL_SECONDS = 60


async def _resolve_agent_id(binding, session_factory) -> int | None:
    """解析绑定使用的智能体 ID：绑定指定优先，否则用平台默认智能体。"""
    if binding.agent_id is not None:
        return binding.agent_id
    async with session_factory() as session:
        agent = await AgentRepository(session).get_default_agent(binding.platform_id)
        return agent.id if agent is not None else None


async def _run_binding(
    binding,
    settings,
    session_factory,
    stop_event: asyncio.Event,
) -> None:
    """运行单个绑定的长轮询实例；stop_event 置位时退出。"""
    try:
        bot_token = get_binding_bot_token(binding)
        api_token = get_binding_api_token(binding)
    except Exception as exc:
        logger.error("binding %s 缺少凭证，跳过：%s", binding.id, exc)
        return

    chat_client = WeChatChatClient(settings.wechat_bot_api_base_url)
    bot = WeChatBot()
    bot._credentials = Credentials(
        token=bot_token,
        base_url="https://ilinkai.weixin.qq.com",
        account_id=binding.ilink_bot_id or "",
        user_id=binding.ilink_user_id or "",
        saved_at=None,
    )

    # 恢复长轮询游标并持久化新游标，避免重启后重复拉取已消费消息
    state_dir = Path(settings.wechat_bot_state_dir) / str(binding.id)
    session = WeChatBotSession(state_dir)
    bot._cursor = session.cursor
    install_cursor_persistence(bot, session)

    @bot.on_message
    async def handle(msg):
        user_text = getattr(msg, "text", "") or ""
        user_id = getattr(msg, "user_id", None) or ""
        is_group = str(user_id).endswith("@chatroom")
        logger.info(
            "收到微信消息 binding_id=%s user_id=%s chars=%s kind=%s",
            binding.id,
            user_id,
            len(user_text),
            "group" if is_group else "private",
        )
        if not user_text.strip():
            await bot.reply(msg, "请发送文字内容，我再帮你处理。")
            return
        agent_id = await _resolve_agent_id(binding, session_factory)
        if agent_id is None:
            await bot.reply(msg, "未找到可用的智能体，请先在后台绑定智能体。")
            return

        # 同一微信用户（私聊联系人 / 群聊房间）复用同一后台会话，延续上下文；
        # 会话失效（404）时清除映射并用新会话重试一次。
        conversation_id = session.get_conversation_id(user_id)
        reply = None
        try:
            try:
                reply = await chat_client.send_chat(
                    api_token=api_token,
                    agent_id=agent_id,
                    message=user_text,
                    conversation_id=conversation_id,
                )
            except ConversationNotFoundError:
                logger.warning(
                    "微信会话 %s 已失效，重置后重试 binding_id=%s",
                    conversation_id,
                    binding.id,
                )
                await session.clear_conversation_id(user_id)
                reply = await chat_client.send_chat(
                    api_token=api_token,
                    agent_id=agent_id,
                    message=user_text,
                )
        except Exception:
            logger.exception("微信消息转发失败 binding_id=%s", binding.id)
        if reply is not None and reply.conversation_id is not None:
            await session.save_conversation_id(user_id, reply.conversation_id)
        await bot.reply(
            msg, reply.content if reply is not None else "模型服务暂时连接不上，请稍后再试。"
        )

    logger.info(
        "wechat bot instance start binding_id=%s agent_id=%s",
        binding.id,
        binding.agent_id,
    )
    monitor = asyncio.create_task(_wait_stop(bot, stop_event))
    try:
        await bot.start()
    finally:
        monitor.cancel()
        logger.info("wechat bot instance stopped binding_id=%s", binding.id)


async def _wait_stop(bot, stop_event: asyncio.Event) -> None:
    """stop_event 置位后停止 SDK 长轮询循环。"""
    try:
        await stop_event.wait()
    except asyncio.CancelledError:
        return
    bot.stop()


def _heartbeat_log_level(
    previous: tuple[int, int] | None, current: tuple[int, int]
) -> int:
    """心跳日志级别：实例数/绑定数变化时才用 INFO，未变化降到 DEBUG。

    心跳原本每分钟一条 INFO，在多服务共用的日志文件里会淹没真实业务日志；
    降级后仍保留 DEBUG 供排查，同时避免稳态运行时的无效噪音。
    """
    return logging.INFO if current != previous else logging.DEBUG


async def _supervise(settings, session_factory) -> None:
    """周期加载 active 绑定：新增实例拉起、移除/停用实例停止，上限 WECHAT_BOT_MAX_INSTANCES。"""
    tasks: dict[int, tuple[asyncio.Task, asyncio.Event]] = {}
    last_heartbeat: tuple[int, int] | None = None
    try:
        while True:
            async with session_factory() as session:
                bindings = await WeChatBotBindingRepository(session).list_active(
                    limit=settings.wechat_bot_max_instances
                )
            active_ids = {item.id for item in bindings}

            for binding_id, (task, stop_event) in list(tasks.items()):
                if binding_id not in active_ids:
                    logger.info("binding %s 已移除/停用，停止实例", binding_id)
                    stop_event.set()
                    task.cancel()
                    tasks.pop(binding_id, None)

            for binding in bindings:
                if binding.id in tasks or len(tasks) >= settings.wechat_bot_max_instances:
                    continue
                stop_event = asyncio.Event()
                task = asyncio.create_task(
                    _run_binding(binding, settings, session_factory, stop_event)
                )
                tasks[binding.id] = (task, stop_event)

            heartbeat = (len(tasks), len(bindings))
            level = _heartbeat_log_level(last_heartbeat, heartbeat)
            last_heartbeat = heartbeat
            logger.log(
                level,
                "wechat bot supervise running=%s active_bindings=%s",
                heartbeat[0],
                heartbeat[1],
            )
            await asyncio.sleep(REFRESH_INTERVAL_SECONDS)
    except asyncio.CancelledError:
        for _task, stop_event in tasks.values():
            stop_event.set()
            _task.cancel()
        logger.info("wechat bot supervise stopped")


def main() -> None:
    settings = get_settings()
    setup_logging(
        settings.log_level,
        log_file_path=settings.log_file_path,
        log_file_backup_count=settings.log_file_backup_count,
    )
    if not settings.wechat_bot_enabled:
        logger.info("WECHAT_BOT_ENABLED=false，微信机器人 worker 退出")
        return

    if WeChatBot is None:
        logger.error("未安装 wechatbot-sdk，请先执行 pip install wechatbot-sdk")
        sys.exit(1)

    session_factory = get_session_factory()
    logger.info(
        "微信机器人 worker 启动（api=%s max_instances=%s state_dir=%s）",
        settings.wechat_bot_api_base_url,
        settings.wechat_bot_max_instances,
        settings.wechat_bot_state_dir,
    )
    try:
        asyncio.run(_supervise(settings, session_factory))
    except KeyboardInterrupt:
        logger.info("微信机器人 worker 退出")


if __name__ == "__main__":
    main()
