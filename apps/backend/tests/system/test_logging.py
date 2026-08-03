from __future__ import annotations

import logging
from datetime import date

from app.core.logging import build_logging_config, setup_logging


def test_build_logging_config_includes_dated_file_handler(tmp_path) -> None:
    log_file = tmp_path / "logs" / "app.log"

    config = build_logging_config(
        level="DEBUG",
        log_file_path=str(log_file),
        log_file_backup_count=7,
    )

    assert config["root"]["handlers"] == ["console", "file"]
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
