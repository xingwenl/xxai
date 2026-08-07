from __future__ import annotations

import logging
import logging.config
from datetime import date
from pathlib import Path


class DatedFileHandler(logging.FileHandler):
    """按自然日期写入 app-YYYY-MM-DD.log，避免当前日志永远停留在 app.log。"""

    def __init__(
        self,
        filename: str,
        mode: str = "a",
        encoding: str | None = None,
        delay: bool = False,
        errors: str | None = None,
        backupCount: int = 5,
    ) -> None:
        self.base_log_path = Path(filename)
        self.backup_count = backupCount
        self.current_log_date = date.today()
        super().__init__(
            self._dated_log_path(self.current_log_date),
            mode=mode,
            encoding=encoding,
            delay=delay,
            errors=errors,
        )

    def emit(self, record: logging.LogRecord) -> None:
        today = date.today()
        if today != self.current_log_date:
            self._switch_to_date(today)
        super().emit(record)

    def _dated_log_path(self, log_date: date) -> str:
        dated_name = (
            f"{self.base_log_path.stem}-{log_date.isoformat()}"
            f"{self.base_log_path.suffix}"
        )
        return str(self.base_log_path.with_name(dated_name))

    def _switch_to_date(self, log_date: date) -> None:
        if self.stream:
            self.stream.close()
            self.stream = None
        self.baseFilename = self._dated_log_path(log_date)
        self.current_log_date = log_date
        if not self.delay:
            self.stream = self._open()
        self._remove_expired_logs()

    def _remove_expired_logs(self) -> None:
        if self.backup_count <= 0:
            return

        log_pattern = f"{self.base_log_path.stem}-*{self.base_log_path.suffix}"
        log_files = sorted(
            self.base_log_path.parent.glob(log_pattern),
            key=lambda path: path.name,
            reverse=True,
        )
        for log_file in log_files[self.backup_count :]:
            log_file.unlink(missing_ok=True)


def build_logging_config(
    level: str = "INFO",
    log_file_path: str | None = None,
    log_file_backup_count: int = 5,
) -> dict:
    handlers: dict[str, dict] = {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "level": level,
        },
    }

    if log_file_path:
        handlers["file"] = {
            "()": "app.core.logging.DatedFileHandler",
            "formatter": "default",
            "level": level,
            "filename": log_file_path,
            "backupCount": log_file_backup_count,
            "encoding": "utf-8",
        }

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            }
        },
        "handlers": handlers,
        "root": {
            "handlers": list(handlers),
            "level": level,
        },
        # HTTPX 的默认 INFO 日志会包含完整 URL（包括查询参数）。统一提升级别，
        # 避免模型提供的公开 URL 将令牌或业务参数写入应用日志。
        "loggers": {
            "httpx": {"level": "WARNING"},
            "httpcore": {"level": "WARNING"},
        },
    }


def setup_logging(
    level: str = "INFO",
    log_file_path: str | None = None,
    log_file_backup_count: int = 5,
) -> None:
    if log_file_path:
        Path(log_file_path).parent.mkdir(parents=True, exist_ok=True)

    logging.config.dictConfig(
        build_logging_config(
            level=level,
            log_file_path=log_file_path,
            log_file_backup_count=log_file_backup_count,
        )
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
