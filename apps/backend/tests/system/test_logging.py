from __future__ import annotations

import asyncio
import contextlib
import logging
from functools import wraps
from types import SimpleNamespace
from datetime import date

from app.core import config as core_config
from app.core.logging import DatedFileHandler, build_logging_config, setup_logging
from app.modules.knowledge.tasks import configure_worker_logging
from app.modules.wechat_bot import worker as wechat_worker


def async_test(function):
    """项目内既有约定：用 asyncio.run 包装异步用例，不引入 pytest-asyncio。"""

    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return run


def test_build_logging_config_includes_dated_file_handler(tmp_path) -> None:
    log_file = tmp_path / "logs" / "app.log"

    config = build_logging_config(
        level="DEBUG",
        log_file_path=str(log_file),
        log_file_backup_count=7,
    )

    assert config["root"]["handlers"] == ["console", "file"]
    assert config["loggers"]["httpx"]["level"] == "WARNING"
    assert config["loggers"]["httpcore"]["level"] == "WARNING"
    assert config["handlers"]["file"] == {
        "()": "app.core.logging.DatedFileHandler",
        "formatter": "default",
        "level": "DEBUG",
        "filename": str(log_file),
        "backupCount": 7,
        "encoding": "utf-8",
    }


def test_setup_logging_creates_directory_and_writes_log_file(tmp_path) -> None:
    log_file = tmp_path / "nested" / "app.log"

    setup_logging(
        level="INFO",
        log_file_path=str(log_file),
        log_file_backup_count=1,
    )

    logger = logging.getLogger("tests.system.file_logging")
    logger.info("hello local file logging")
    logging.shutdown()

    dated_log_file = log_file.with_name(f"app-{date.today().isoformat()}.log")

    assert dated_log_file.exists()
    assert "hello local file logging" in dated_log_file.read_text(encoding="utf-8")


def test_configure_worker_logging_uses_shared_file_handler(tmp_path, monkeypatch) -> None:
    log_file = tmp_path / "worker" / "app.log"

    monkeypatch.setattr(
        "app.modules.knowledge.tasks.get_settings",
        lambda: SimpleNamespace(
            log_level="INFO",
            log_file_path=str(log_file),
            log_file_backup_count=1,
        ),
    )

    configure_worker_logging(sender=None)

    logger = logging.getLogger("tests.system.worker_file_logging")
    logger.info("hello worker logging")
    logging.shutdown()

    dated_log_file = log_file.with_name(f"app-{date.today().isoformat()}.log")

    assert dated_log_file.exists()
    assert "hello worker logging" in dated_log_file.read_text(encoding="utf-8")


def test_resolve_log_file_path_defaults_under_base_dir(monkeypatch) -> None:
    monkeypatch.delenv("LOG_FILE_PATH", raising=False)

    assert core_config._resolve_log_file_path() == str(
        core_config.BASE_DIR / "logs" / "app.log"
    )


def test_resolve_log_file_path_resolves_relative_against_base_dir(monkeypatch) -> None:
    monkeypatch.setenv("LOG_FILE_PATH", "logs/app.log")

    assert core_config._resolve_log_file_path() == str(
        core_config.BASE_DIR / "logs" / "app.log"
    )


def test_resolve_log_file_path_keeps_absolute_path(monkeypatch, tmp_path) -> None:
    absolute = tmp_path / "api" / "app.log"
    monkeypatch.setenv("LOG_FILE_PATH", str(absolute))

    assert core_config._resolve_log_file_path() == str(absolute)


def test_settings_default_log_file_backup_count_is_14(monkeypatch) -> None:
    monkeypatch.delenv("LOG_FILE_BACKUP_COUNT", raising=False)
    core_config.get_settings.cache_clear()
    try:
        assert core_config.get_settings().log_file_backup_count == 14
    finally:
        core_config.get_settings.cache_clear()


def test_dated_file_handler_prunes_expired_logs_on_init(tmp_path) -> None:
    log_dir = tmp_path / "api"
    log_dir.mkdir()
    for day in range(1, 6):
        (log_dir / f"app-2026-08-0{day}.log").write_text("old", encoding="utf-8")

    handler = DatedFileHandler(str(log_dir / "app.log"), backupCount=3)
    try:
        remaining = sorted(path.name for path in log_dir.glob("app-*.log"))
    finally:
        handler.close()

    # 当前日期文件必须保留，历史文件按名称（ISO 日期）只保留最新的 3 个
    assert f"app-{date.today().isoformat()}.log" in remaining
    assert len(remaining) == 3
    assert "app-2026-08-05.log" in remaining
    assert "app-2026-08-01.log" not in remaining


def test_dated_file_handler_keeps_other_prefixes_and_dirs(tmp_path) -> None:
    service_dir = tmp_path / "api"
    other_service_dir = tmp_path / "worker"
    service_dir.mkdir()
    other_service_dir.mkdir()
    for day in range(1, 5):
        (service_dir / f"app-2026-08-0{day}.log").write_text("old", encoding="utf-8")
    (service_dir / "other.log").write_text("keep", encoding="utf-8")
    (other_service_dir / "app-2026-08-01.log").write_text("keep", encoding="utf-8")

    handler = DatedFileHandler(str(service_dir / "app.log"), backupCount=1)
    try:
        remaining = sorted(path.name for path in service_dir.glob("app-*.log"))
    finally:
        handler.close()

    # 清理范围必须限定在本服务的 app-*.log，不能跨服务目录或前缀误删
    assert len(remaining) == 1
    assert (service_dir / "other.log").exists()
    assert (other_service_dir / "app-2026-08-01.log").exists()


def test_heartbeat_log_level_reports_info_only_on_change() -> None:
    assert wechat_worker._heartbeat_log_level(None, (1, 1)) == logging.INFO
    assert wechat_worker._heartbeat_log_level((1, 1), (1, 2)) == logging.INFO
    assert wechat_worker._heartbeat_log_level((1, 1), (1, 1)) == logging.DEBUG


class _FakeSession:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *_exc):
        return False


class _FakeBindingRepository:
    calls = 0
    bindings: list = []

    def __init__(self, session) -> None:
        self.session = session

    async def list_active(self, limit: int) -> list:
        type(self).calls += 1
        return list(type(self).bindings)


@async_test
async def test_supervise_heartbeat_degrades_to_debug_when_unchanged(
    monkeypatch, caplog
) -> None:
    monkeypatch.setattr(wechat_worker, "REFRESH_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(
        wechat_worker, "WeChatBotBindingRepository", _FakeBindingRepository
    )
    _FakeBindingRepository.calls = 0
    _FakeBindingRepository.bindings = []
    settings = SimpleNamespace(wechat_bot_max_instances=3)

    with caplog.at_level(logging.DEBUG, logger="app.modules.wechat_bot.worker"):
        task = asyncio.create_task(
            wechat_worker._supervise(settings, lambda: _FakeSession())
        )
        for _ in range(1000):
            if _FakeBindingRepository.calls >= 3:
                break
            await asyncio.sleep(0)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    heartbeats = [
        record
        for record in caplog.records
        if "supervise running=" in record.getMessage()
    ]
    assert len([r for r in heartbeats if r.levelno == logging.INFO]) == 1
    assert [r for r in heartbeats if r.levelno == logging.DEBUG], (
        "状态未变化的心跳应降级为 DEBUG"
    )
