from __future__ import annotations

import logging
import logging.config


def build_logging_config(level: str = "INFO") -> dict:
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
                "level": level,
            }
        },
        "root": {
            "handlers": ["console"],
            "level": level,
        },
    }


def setup_logging(level: str = "INFO") -> None:
    logging.config.dictConfig(build_logging_config(level=level))


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
