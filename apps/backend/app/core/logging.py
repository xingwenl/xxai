from __future__ import annotations

import logging
import logging.config
from datetime import date
from pathlib import Path


class DatedFileHandler(logging.FileHandler):
    """按自然日期写入 app-YYYY-MM-DD.log，避免当前日志永远停留在 app.log。

    同一目录只会被一个服务写入（Compose 中按服务区分 ``LOG_FILE_PATH``）：
    Python 标准库不支持多进程写同一个日志文件，共写会导致日志互相穿插、
    各自按自己的策略删除历史文件，因此清理范围严格限制在当前目录的
    ``<stem>-*<suffix>`` 文件内。
    """

    def __init__(
        self,
        filename: str,
        mode: str = "a",
        encoding: str | None = None,
        delay: bool = False,
        errors: str | None = None,
        backupCount: int = 14,
        cleanupOnInit: bool = True,
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
        # 只在跨天时清理会导致长期不重启的进程永不回收历史日志，
        # 因此进程启动时先清理一次过期文件。
        if cleanupOnInit:
            self._remove_expired_logs()

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
        # 只按文件名比较：baseFilename 是绝对路径，而配置的目录可能是相对路径，
        # 直接比较 Path 对象会因解析基准不同而误判当前文件。
        current_name = Path(self.baseFilename).name
        # 文件名内嵌 ISO 日期，按名称倒序即为由新到旧；只处理普通文件，
        # 避免把同名目录或软链接误删。
        log_files = sorted(
            (
                path
                for path in self.base_log_path.parent.glob(log_pattern)
                if path.is_file()
            ),
            key=lambda path: path.name,
            reverse=True,
        )
        for log_file in log_files[self.backup_count :]:
            # 时钟回拨或切换时区时，当前写入的文件可能不再是最新的，
            # 必须显式跳过，避免删掉正在写的日志。
            if log_file.name == current_name:
                continue
            # 清理失败不应影响正常写日志（例如文件被其他进程持有）。
            try:
                log_file.unlink()
            except OSError:
                continue


def build_logging_config(
    level: str = "INFO",
    log_file_path: str | None = None,
    log_file_backup_count: int = 14,
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
    log_file_backup_count: int = 14,
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
