"""
Structured logging via loguru.

Provides a pre-configured logger with console + rotating file output.
All modules should import `logger` from this module.
"""

import sys
from pathlib import Path

from loguru import logger

# Remove default loguru handler so we control everything
logger.remove()

_initialized = False


def setup_logger(level: str = "INFO", log_file: str = "./data/logs/outreach.log",
                 rotation_mb: int = 10, retention_count: int = 5) -> None:
    """
    Configure loguru with console + file sinks.

    Called once at startup from main.py / followup.py.
    """
    global _initialized
    if _initialized:
        return

    # Ensure log directory exists
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Console sink — colorized, human-readable
    logger.add(
        sys.stderr,
        level=level,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> — "
            "<level>{message}</level>"
        ),
        colorize=True,
    )

    # File sink — structured, rotating
    logger.add(
        str(log_path),
        level=level,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} — {message}",
        rotation=f"{rotation_mb} MB",
        retention=retention_count,
        encoding="utf-8",
        enqueue=True,  # Thread-safe
    )

    _initialized = True
    logger.info(f"Logger initialized — level={level}, file={log_file}")
