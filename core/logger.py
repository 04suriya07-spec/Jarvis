"""Structured logging for Javris using Rich."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler


_console = Console(stderr=True)
_configured = False


def get_logger(name: str = "javris") -> logging.Logger:
    global _configured
    if not _configured:
        _setup_root_logger()
        _configured = True
    return logging.getLogger(name)


def _setup_root_logger() -> None:
    from core.config import get_config

    cfg = get_config()
    level = getattr(logging, cfg.log_level, logging.INFO)

    # Rich console handler
    rich_handler = RichHandler(
        console=_console,
        show_time=True,
        show_path=False,
        markup=True,
        rich_tracebacks=True,
    )
    rich_handler.setLevel(level)

    # File handler
    log_path = cfg.logs_dir / "javris.log"
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
    )

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(rich_handler)
    root.addHandler(file_handler)
