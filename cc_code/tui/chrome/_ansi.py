"""ANSI color constants, Unicode decoration characters, and ANSI stripping.

All ASCII/Unicode symbols and color escape sequences used by other chrome
submodules live here. ``RESET``/``BORDER``/``ACCENT``/``SUBTLE`` etc. are
re-exported through the package ``__init__`` because external code (notably
``tui/renderer.py``) imports them by name.
"""

from __future__ import annotations

import re


# Legacy ANSI constants (kept for backward compatibility with external imports)
RESET = "\x1b[0m"
DIM = "\x1b[2m"
CYAN = "\x1b[36m"
GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"
RED = "\x1b[31m"
BLUE = "\x1b[34m"
MAGENTA = "\x1b[35m"
BOLD = "\x1b[1m"
REVERSE = "\x1b[7m"
ITALIC = "\x1b[3m"
UNDERLINE = "\x1b[4m"
BRIGHT_GREEN = "\x1b[92m"
BRIGHT_RED = "\x1b[91m"
BRIGHT_CYAN = "\x1b[96m"
BRIGHT_YELLOW = "\x1b[93m"
BRIGHT_BLUE = "\x1b[94m"
BRIGHT_MAGENTA = "\x1b[95m"
BRIGHT_WHITE = "\x1b[97m"
# Extended 256-color palette
BORDER = "\x1b[38;5;39m"
BORDER_DIM = "\x1b[38;5;24m"
ACCENT = "\x1b[38;5;214m"
ACCENT2 = "\x1b[38;5;141m"
SUBTLE = "\x1b[38;5;243m"
HIGHLIGHT_BG = "\x1b[48;5;236m"


# Unicode decorative characters
ICON_CC_CODER = "✦"   # ✦
ICON_USER = "▶"       # ▶
ICON_ASSISTANT = "✴"  # ✴
ICON_TOOL = "⚙"       # ⚙
ICON_PROGRESS = "●"   # ●
ICON_SUCCESS = "✔"    # ✔
ICON_ERROR = "✘"      # ✘
ICON_RUNNING = "○"    # ○
ICON_FOLDER = "■"     # ■
ICON_MODEL = "◆"      # ◆
ICON_PROVIDER = "◈"   # ◈
ICON_PROMPT = "❯"     # ❯
ICON_SKILL = "★"      # ★
ICON_MSG = "▬"        # ▬
ICON_EVENT = "▪"      # ▪
ICON_MCP = "◉"        # ◉
ICON_BG = "◐"         # ◐
ICON_LOCK = "▣"       # ▣
ICON_DIVIDER = "─"    # ─
ICON_DOT = "·"        # ·
ICON_ARROW = "▸"      # ▸


# Pre-compiled regex for ANSI stripping (reused by width.py)
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    """Strip ANSI escape codes from text."""
    return _ANSI_RE.sub("", text)
