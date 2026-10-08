"""Centralised logging setup with optional ANSI color.

Used by ``compile.py`` (main entry) and helper scripts so the build's
output looks the same regardless of which process emitted a line.

Color is ANSI escape codes only — no third-party deps.  Detection
follows the GNU coreutils convention: enabled when stderr is a TTY and
``NO_COLOR`` is not set, disabled otherwise (so logs piped to a file
or grepped stay clean).
"""

from __future__ import annotations

import logging
import os
import sys

# ANSI codes.  Kept short so log lines stay readable in raw form.
_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"
_RED = "\033[31m"
_YELLOW = "\033[33m"
_GREEN = "\033[32m"
_CYAN = "\033[36m"
_GREY = "\033[90m"

_LEVEL_STYLE: dict[int, str] = {
    logging.DEBUG: _GREY,
    logging.INFO: _CYAN,
    logging.WARNING: _YELLOW,
    logging.ERROR: _RED + _BOLD,
    logging.CRITICAL: _RED + _BOLD,
}

# Short level names — easier to scan than INFO/WARNING/ERROR.
_LEVEL_NAME: dict[int, str] = {
    logging.DEBUG: "dbg",
    logging.INFO: "info",
    logging.WARNING: "warn",
    logging.ERROR: "ERR ",
    logging.CRITICAL: "CRIT",
}


def _color_enabled() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return sys.stderr.isatty()


class _ColorFormatter(logging.Formatter):
    """Colors the level prefix; leaves the message untouched."""

    def __init__(self, *, use_color: bool) -> None:
        super().__init__()
        self.use_color = use_color

    def format(self, record: logging.LogRecord) -> str:
        level_name = _LEVEL_NAME.get(record.levelno, record.levelname.lower())
        message = record.getMessage()
        if self.use_color:
            style = _LEVEL_STYLE.get(record.levelno, "")
            level_part = f"{style}{level_name}{_RESET}"
            # Dim the leading bracket so the level pops more.
            return f"{_DIM}[{_RESET}{level_part}{_DIM}]{_RESET} {message}"
        return f"[{level_name}] {message}"


def setup_logging(level: str | int = "INFO") -> None:
    """Install the colored formatter on the root logger.

    Idempotent — replaces any existing root handlers so calling this
    twice (or from a subprocess that already had basicConfig set) leaves
    a single clean handler.
    """
    if isinstance(level, str):
        level = getattr(logging, level.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_ColorFormatter(use_color=_color_enabled()))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
