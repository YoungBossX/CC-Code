"""Interactive permission prompt rendering.

Renders the "Action Required" panel with optional collapsed/expanded
detail view, scrolling, and a feedback-mode text input for rejection
reasons. Diff details get colorized through ``_diff``.
"""

from __future__ import annotations

from typing import Any

from cc_code.tui.chrome._ansi import (
    BRIGHT_CYAN,
    BRIGHT_WHITE,
    ICON_ARROW,
    ICON_DIVIDER,
    ICON_DOT,
    ICON_PROMPT,
    RESET,
)
from cc_code.tui.chrome._diff import colorize_edit_permission_details
from cc_code.tui.chrome._panels import render_panel
from cc_code.tui.chrome._terminal import _cached_terminal_size
from cc_code.tui.theme import theme


def get_permission_prompt_max_scroll_offset(
    request: dict[str, Any], expanded: bool = False
) -> int:
    if not expanded:
        return 0
    flat = flatten_detail_lines(request.get("details", []))
    _, rows = _cached_terminal_size()
    max_visible = max(4, rows - 20)
    return max(0, len(flat) - max_visible)


def flatten_detail_lines(details: list[str]) -> list[str]:
    result: list[str] = []
    for detail in details:
        result.extend(detail.split("\n"))
    return result


def slice_visible_details(
    flat_lines: list[str], scroll_offset: int, max_visible: int | None = None
) -> tuple[list[str], int]:
    if max_visible is None:
        _, rows = _cached_terminal_size()
        max_visible = max(4, rows - 20)
    total = len(flat_lines)
    offset = max(0, min(scroll_offset, max(0, total - max_visible)))
    return flat_lines[offset:offset + max_visible], total


def render_permission_prompt(
    request: dict[str, Any],
    expanded: bool = False,
    scroll_offset: int = 0,
    selected_choice_index: int = 0,
    feedback_mode: bool = False,
    feedback_input: str = "",
) -> str:
    """Interactive permission prompt with Morandi theme."""
    t = theme()
    lines: list[str] = []
    if feedback_mode:
        lines.extend([
            f"{t.progress}{t.bold}{ICON_PROMPT} Provide reason for rejection:{t.reset}",
            f"  {t.assistant}{ICON_PROMPT}{t.reset} {feedback_input}_",
            "",
            f"{t.subtle}  Press Enter to send, Esc to cancel.{t.reset}",
        ])
    else:
        lines.extend([request.get("summary", "Permission Request"), ""])
        details = request.get("details", [])
        if details:
            flat = flatten_detail_lines(details)
            if not expanded:
                lines.append(
                    f"{t.subtle}  {ICON_ARROW} {len(flat)} lines hidden "
                    f"{t.subtle}│{t.reset} {t.dim}press 'v' to expand │ Ctrl+O toggle{t.reset}"
                )
            else:
                colorized = colorize_edit_permission_details(flat)
                visible, total = slice_visible_details(colorized, scroll_offset)
                lines.extend(visible)
                if total > len(visible):
                    lines.append(
                        f"{t.subtle}  {ICON_DIVIDER * 3} scroll "
                        f"{scroll_offset + 1}/{total} (Wheel/PgUp/PgDn) "
                        f"{ICON_DIVIDER * 3}{t.reset}"
                    )
            lines.append("")
        for i, choice in enumerate(request.get("choices", [])):
            label = choice.get("label", "")
            key = choice.get("key", "")
            if i == selected_choice_index:
                lines.append(
                    f"  {t.command_highlight_bg}{BRIGHT_CYAN}{ICON_ARROW}{RESET}"
                    f"{t.command_highlight_bg} {BRIGHT_WHITE}{t.bold}{label}{RESET}"
                    f"{t.command_highlight_bg} {t.subtle}({key}){RESET}"
                )
            else:
                lines.append(f"    {t.subtle}{ICON_DOT}{t.reset} {label} {t.subtle}({key}){t.reset}")
    return render_panel("Action Required", "\n".join(lines), right_title="Permission")
