"""Logging configuration for the Pivot application.

This module provides a centralized logging configuration with:
- Console output with colored log levels for readability
- File output to server/logs/app.log (plain text, no ANSI codes)
"""

import logging
import sys
from pathlib import Path

# Log file path: server/logs/app.log
LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
LOG_FILE = LOG_DIR / "app.log"

# Log format (used by both handlers)
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# ANSI color codes for terminal output
COLORS = {
    "DEBUG": "\033[36m",     # Cyan
    "INFO": "\033[32m",      # Green
    "WARNING": "\033[33m",   # Yellow
    "ERROR": "\033[31m",     # Red
    "CRITICAL": "\033[35m",  # Magenta
    "RESET": "\033[0m",      # Reset
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


def _ensure_log_dir() -> None:
    """Ensure the log directory exists."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def _create_console_handler() -> logging.Handler:
    """Create a console handler with colored output.

    Returns:
        Handler: A configured console handler for terminal output with colors.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    # Use colored formatter for terminal
    handler.setFormatter(ColoredFormatter(fmt=LOG_FORMAT, datefmt=DATE_FORMAT))
    return handler


def _create_file_handler() -> logging.FileHandler:
    """Create a file handler with plain text output (no ANSI codes).

    Returns:
        FileHandler: A configured file handler for log file output.
    """
    _ensure_log_dir()

    handler = logging.FileHandler(
        filename=LOG_FILE,
        mode="a",
        encoding="utf-8",
    )
    handler.setLevel(logging.DEBUG)
    # Use standard formatter for file (no colors)
    handler.setFormatter(logging.Formatter(fmt=LOG_FORMAT, datefmt=DATE_FORMAT))
    return handler


def _get_handlers() -> list[logging.Handler]:
    """Get all logging handlers (console + file).

    Returns:
        List of configured logging handlers.
    """
    return [_create_console_handler(), _create_file_handler()]


# Add both handlers to the core logger
for handler in _get_handlers():
    core_logger.addHandler(handler)


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

        # Add both handlers to child logger if it doesn't have any
        if not logger.handlers:
            for h in _get_handlers():
                logger.addHandler(h)

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

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Remove any existing handlers
    root_logger.handlers.clear()

    # Add both handlers
    for h in _get_handlers():
        root_logger.addHandler(h)

    # Suppress noisy third-party loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


# For backward compatibility: set up basic logging with both handlers
logging.basicConfig(
    level=logging.INFO,
    handlers=_get_handlers(),
)
