"""Logging configuration for the Pivot application.

This module provides a centralized logging configuration with:
- Console output with colored log levels for readability
- File output to server/logs/app.log (plain text, no ANSI codes)
"""

import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

# Log file path: server/logs/app.log
LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
LOG_FILE = LOG_DIR / "app.log"
LOG_FILE_BACKUP_COUNT = 30

# Log format (used by both handlers)
LOG_FORMAT = (
    "%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"
)
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# ANSI color codes for terminal output
COLORS = {
    "DEBUG": "\033[36m",  # Cyan
    "INFO": "\033[32m",  # Green
    "WARNING": "\033[33m",  # Yellow
    "ERROR": "\033[31m",  # Red
    "CRITICAL": "\033[35m",  # Magenta
    "RESET": "\033[0m",  # Reset
}


class ColoredFormatter(logging.Formatter):
    """Custom formatter that adds ANSI colors to log levels for terminal output."""

    def format(self, record: logging.LogRecord) -> str:
        # Get the original formatted message
        message = super().format(record)

        # Add color to the level name
        level_color = COLORS.get(record.levelname, COLORS["RESET"])
        colored_level = f"{level_color}{record.levelname}{COLORS['RESET']}"

        # Replace the plain level name with colored version
        return message.replace(f"- {record.levelname} -", f"- {colored_level} -")


# Create a logger for the core module
core_logger = logging.getLogger("core")
core_logger.setLevel(logging.DEBUG)
core_logger.propagate = False

_HANDLERS: list[logging.Handler] | None = None


def _ensure_log_dir() -> None:
    """Ensure the log directory exists."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def _create_console_handler() -> logging.Handler:
    """Create a console handler with colored output.

    Returns:
        Handler: A configured console handler for terminal output with colors.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    # Use colored formatter for terminal
    handler.setFormatter(ColoredFormatter(fmt=LOG_FORMAT, datefmt=DATE_FORMAT))
    return handler


def _create_file_handler() -> TimedRotatingFileHandler | None:
    """Create a daily rotating file handler with plain text output.

    Returns:
        TimedRotatingFileHandler: A configured rotating file handler for log output.
        None: If the log file cannot be opened due to permission issues.
    """
    try:
        _ensure_log_dir()

        handler = TimedRotatingFileHandler(
            filename=LOG_FILE,
            when="midnight",
            interval=1,
            backupCount=LOG_FILE_BACKUP_COUNT,
            encoding="utf-8",
            delay=True,
        )
        handler.suffix = "%Y-%m-%d"
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter(fmt=LOG_FORMAT, datefmt=DATE_FORMAT))
        return handler
    except OSError as exc:
        # In containerized dev environments, mounted workspace permissions may
        # block writing to /app/server/logs. Fall back to console-only logging
        # so the application can still boot.
        print(
            f"[logging] file handler disabled for {LOG_FILE}: {exc}",
            file=sys.stderr,
        )
        return None


def _get_handlers() -> list[logging.Handler]:
    """Get all logging handlers (console + file).

    Returns:
        List of configured logging handlers.
    """
    global _HANDLERS
    if _HANDLERS is None:
        handlers: list[logging.Handler] = [_create_console_handler()]
        file_handler = _create_file_handler()
        if file_handler is not None:
            handlers.append(file_handler)
        _HANDLERS = handlers
    return list(_HANDLERS)


def _attach_handlers(logger: logging.Logger) -> None:
    """Attach the shared logging handlers to the given logger once.

    Args:
        logger: Logger that should emit to the shared console/file handlers.
    """
    for handler in _get_handlers():
        if handler not in logger.handlers:
            logger.addHandler(handler)


_attach_handlers(core_logger)


def get_logger(name: str | None = None) -> logging.Logger:
    """Get a logger instance with the given name.

    If no name is provided, returns the core logger instance.
    All loggers output to both console (colored) and file (plain).

    Args:
        name: The name of the logger. If None, returns the core logger.

    Returns:
        logging.Logger: The logger instance with dual output.
    """
    if name:
        logger = logging.getLogger(f"core.{name}")
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        _attach_handlers(logger)
        return logger
    return core_logger


def setup_logging() -> None:
    """Set up the root logger with console and file output.

    This should be called once at application startup to configure
    the root logger with:
    - Console output (terminal) with colored log levels
    - File output (server/logs/app.log) with plain text
    """
    _ensure_log_dir()

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.handlers.clear()
    _attach_handlers(root_logger)

    # Suppress noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


# For backward compatibility: set up basic logging with both handlers
logging.basicConfig(
    level=logging.DEBUG,
    handlers=_get_handlers(),
)
