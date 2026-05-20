"""Panel rendering primitives: borders, rows, wrapping, full panel layout.

``render_panel`` is the workhorse that wraps a title + body in Unicode box
borders, sized to the current terminal. ``wrap_panel_body_line`` does the
CJK-aware soft wrapping inside.
"""

from __future__ import annotations

from cc_code.tui.chrome._ansi import (
    ACCENT,
    BORDER,
    BORDER_DIM,
    ICON_CC_CODER,
    ICON_LOCK,
    ICON_MSG,
    ICON_PROMPT,
    ICON_TOOL,
    RESET,
    _ANSI_RE,
)
from cc_code.tui.chrome._terminal import _cached_terminal_size
from cc_code.tui.chrome._width import (
    char_display_width,
    pad_plain,
    string_display_width,
    truncate_plain,
)
from cc_code.tui.theme import theme


def color_badge(label: str, value: str, color: str, icon: str = "") -> str:
    """Render a styled badge: icon [label] value."""
    t = theme()
    icon_part = f"{color}{icon} " if icon else ""
    return f"{icon_part}{color}{t.dim}[{label}]{t.reset} {t.bold}{value}{t.reset}"


def border_line(kind: str, width: int, color: str = "") -> str:
    """Unicode box drawing: ╭─╮ or ╰─╯."""
    c = color or BORDER
    if kind == "top":
        return f"{c}╭{'─' * (width - 2)}╮{RESET}"
    elif kind == "bottom":
        return f"{c}╰{'─' * (width - 2)}╯{RESET}"
    else:
        return f"{c}├{'─' * (width - 2)}┤{RESET}"


def panel_row(left: str, width: int, right: str | None = None, border_color: str = "") -> str:
    """│ left ... right │"""
    bc = border_color or BORDER
    inner_width = width - 4
    if right:
        l_w = string_display_width(left)
        r_w = string_display_width(right)
        gap = inner_width - l_w - r_w
        if gap < 1:
            left = truncate_plain(left, inner_width - r_w - 1)
            gap = 1
        return f"{bc}│{RESET} {left}{' ' * gap}{right} {bc}│{RESET}"
    else:
        return f"{bc}│{RESET} {pad_plain(left, inner_width)} {bc}│{RESET}"


def empty_panel_row(width: int) -> str:
    return panel_row("", width)


def wrap_panel_body_line(line: str, width: int) -> list[str]:
    """Wrap long lines for panel, CJK aware."""
    inner_width = width - 4
    if string_display_width(line) <= inner_width:
        return [line]

    ansi_spans: list[tuple[int, int]] = []
    for m in _ANSI_RE.finditer(line):
        ansi_spans.append((m.start(), m.end()))

    lines: list[str] = []
    current_line = ""
    current_w = 0
    i = 0
    span_idx = 0

    while i < len(line):
        if span_idx < len(ansi_spans) and i == ansi_spans[span_idx][0]:
            end = ansi_spans[span_idx][1]
            current_line += line[i:end]
            i = end
            span_idx += 1
            continue

        char = line[i]
        cw = char_display_width(char)
        if current_w + cw > inner_width:
            lines.append(current_line)
            current_line = ""
            current_w = 0
            if char == " ":
                i += 1
                continue
        current_line += char
        current_w += cw
        i += 1
    if current_line:
        lines.append(current_line)
    return lines


_PANEL_ICONS: dict[str, str] = {
    "cc_code": ICON_CC_CODER,
    "session feed": ICON_MSG,
    "prompt": ICON_PROMPT,
    "activity": ICON_TOOL,
    "action required": ICON_LOCK,
}


def render_panel(
    title: str,
    body: str,
    right_title: str | None = None,
    min_body_lines: int = 0,
    border_color: str = "",
) -> str:
    """Full panel with Unicode borders.

    The border color defaults to the theme value for the given panel title
    (workspace → header, session → session, prompt → input, etc.).
    """
    t = theme()
    width, _ = _cached_terminal_size()
    if width < 40:
        width = 40

    # Pick border color from theme based on title
    if not border_color:
        title_lower = title.lower()
        if "workspace" in title_lower or "cc_code" in title_lower:
            border_color = t.header
        elif "session" in title_lower:
            border_color = t.session
        elif "prompt" in title_lower or "input" in title_lower:
            border_color = t.input
        elif "action" in title_lower or "approval" in title_lower:
            border_color = t.approval
        else:
            border_color = BORDER

    icon = _PANEL_ICONS.get(title.lower(), "")
    icon_str = f"{ACCENT}{icon} {RESET}" if icon else ""

    res = [border_line("top", width, border_color)]
    title_display = f"{icon_str}{t.bold}{title}{t.reset}"
    right_display = f"{t.subtle}{right_title}{t.reset}" if right_title else None
    res.append(panel_row(title_display, width, right_display, border_color))

    inner = width - 4
    divider_line = f"{BORDER_DIM}{'╌' * inner}{RESET}"
    res.append(panel_row(divider_line, width, border_color=border_color))

    body_lines = body.splitlines() if body else []
    wrapped_lines: list[str] = []
    for bl in body_lines:
        wrapped_lines.extend(wrap_panel_body_line(bl, width))

    while len(wrapped_lines) < min_body_lines:
        wrapped_lines.append("")

    for wl in wrapped_lines:
        res.append(panel_row(wl, width, border_color=border_color))
    res.append(border_line("bottom", width, border_color))
    return "\n".join(res)
