from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class StructuredFormatter(logging.Formatter):
    """JSON-structured log formatter for better parsing and analysis."""

    def format(self, record: logging.LogRecord) -> str:
        log_data: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        if hasattr(record, "extra_data"):
            log_data["extra"] = record.extra_data

        return json.dumps(log_data, ensure_ascii=False)


class HumanReadableFormatter(logging.Formatter):
    """Human-readable formatter with color support for terminal output."""

    COLORS = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        level = f"{color}{record.levelname:8s}{self.RESET}" if color else record.levelname
        return f"{timestamp} {level} {record.name:20s} {record.getMessage()}"


def configure_logging(log_dir: Path, *, structured: bool = False, level: str = "INFO") -> None:
    """Configure logging with optional structured output.

    Args:
        log_dir: Directory for log files
        structured: If True, use JSON structured logging
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
    """
    log_dir.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Clear existing handlers
    root_logger.handlers.clear()

    # Console handler with human-readable format
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(HumanReadableFormatter())
    root_logger.addHandler(console_handler)

    # File handler - use structured format for easier parsing
    file_handler = logging.FileHandler(log_dir / "iflowclaw.log", encoding="utf-8")
    if structured:
        file_handler.setFormatter(StructuredFormatter())
    else:
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
    root_logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the given name."""
    return logging.getLogger(name)


def log_with_extra(logger: logging.Logger, level: int, message: str, **extra: Any) -> None:
    """Log a message with extra structured data.

    Args:
        logger: Logger instance
        level: Log level
        message: Log message
        **extra: Extra key-value pairs to include in structured output
    """
    record = logger.makeRecord(
        logger.name, level, "", 0, message, (), None
    )
    record.extra_data = extra
    logger.handle(record)

