"""Higher-level UI components: banner, status line, tool panel, footer, slash menu.

Compose the primitives from ``_panels`` + ``_width`` + theme into the
visible chrome of the TUI. Layout mirrors the Rust ``build_header_lines``.
"""

from __future__ import annotations

from typing import Any

from cc_code.tui.chrome._ansi import (
    ACCENT,
    BRIGHT_CYAN,
    BRIGHT_WHITE,
    ICON_ARROW,
    ICON_BG,
    ICON_DOT,
    ICON_ERROR,
    ICON_RUNNING,
    ICON_SKILL,
    ICON_SUCCESS,
    ICON_TOOL,
    RESET,
)
from cc_code.tui.chrome._panels import render_panel
from cc_code.tui.chrome._terminal import _cached_terminal_size
from cc_code.tui.chrome._width import (
    pad_plain,
    string_display_width,
    truncate_plain,
)
from cc_code.tui.theme import theme


def render_banner(
    runtime: dict | None,
    cwd: str,
    permission_summary: list[str],
    session: dict[str, int],
    compact: bool = False,
) -> str:
    """Render the workspace header panel.

    Layout matches Rust's build_header_lines:
      Line 1: project <cwd>   provider <host>   model <name>   auth <kind>
      Line 2: session messages=N events=N tools=N skills=N mcp=N

    When compact=True (small terminal), all info is compressed into one line.
    """
    t = theme()

    model = runtime.get("model", "(unconfigured)") if runtime else "(unconfigured)"

    # Provider hostname (strip scheme)
    provider = "offline"
    if runtime and runtime.get("baseUrl"):
        provider = (
            runtime["baseUrl"]
            .replace("https://", "")
            .replace("http://", "")
            .split("/")[0]
        )

    # Auth kind
    auth = "none"
    if runtime:
        if runtime.get("authToken"):
            auth = "auth_token"
        elif runtime.get("apiKey"):
            auth = "api_key"

    msg_count = session.get("messageCount", 0)
    evt_count = session.get("transcriptCount", 0)
    skill_count = session.get("skillCount", 0)
    mcp_count = session.get("mcpCount", 0)

    if compact:
        import os as _os
        cwd_short = _os.path.basename(cwd) or cwd
        body = (
            f"{t.header_label_info}{t.bold}project{t.reset} {cwd_short}"
            f"  {t.header_label_info}{t.bold}model{t.reset} {model}"
            f"  {t.header_label_session}{t.bold}msgs{t.reset} {msg_count}"
        )
        return render_panel("Workspace", body)

    line1 = (
        f"{t.header_label_info}{t.bold}project{t.reset} {cwd}"
        f"   {t.header_label_info}{t.bold}provider{t.reset} {provider}"
        f"   {t.header_label_info}{t.bold}model{t.reset} {model}"
        f"   {t.header_label_info}{t.bold}auth{t.reset} {auth}"
    )
    line2 = (
        f"{t.header_label_session}{t.bold}session{t.reset}"
        f" messages={msg_count}"
        f" events={evt_count}"
        f" skills={skill_count}"
        f" mcp={mcp_count}"
    )

    body = "\n".join([line1, line2])
    return render_panel("Workspace", body)


def render_status_line(status: str | None) -> str:
    """Render the status line."""
    t = theme()
    if status:
        return f"{t.tool}{t.bold}{ICON_RUNNING} {status}{t.reset}"
    return f"{t.assistant}{ICON_SUCCESS} Ready{t.reset}"


def render_tool_panel(
    active_tool: str | None,
    recent_tools: list[dict[str, str]],
    background_tasks: list[dict[str, Any]] | None = None,
) -> str:
    """Render current tool activity summary."""
    t = theme()
    if background_tasks is None:
        background_tasks = []
    parts: list[str] = []
    if active_tool:
        parts.append(f"{ICON_RUNNING} {t.tool}{t.bold}running{t.reset} {active_tool}")
    for task in background_tasks:
        if task.get("status") == "running":
            parts.append(f"{ICON_BG} {t.progress}bg{t.reset} {task.get('label', 'task')}")
    if not parts and not recent_tools:
        parts.append(f"{t.subtle}{ICON_DOT} idle{t.reset}")
    else:
        for tool in recent_tools[-3:]:
            if tool.get("status") == "success":
                parts.append(f"{t.assistant}{ICON_SUCCESS} {tool.get('name', 'tool')}{t.reset}")
            else:
                parts.append(f"{t.tool_error}{ICON_ERROR} {tool.get('name', 'tool')}{t.reset}")
    return f"{ICON_TOOL} {t.dim}tools{t.reset}  " + f"  {t.subtle}{ICON_DOT}{t.reset}  ".join(parts)


def render_footer_bar(
    status: str | None,
    tools_enabled: bool,
    skills_enabled: bool,
    background_tasks: list[dict[str, Any]] | None = None,
) -> str:
    """Single-line footer bar."""
    t = theme()
    if background_tasks is None:
        background_tasks = []
    width, _ = _cached_terminal_size()
    left = render_status_line(status)

    bg_info = ""
    if background_tasks:
        bg_info = f" {ICON_BG} {t.progress}{len(background_tasks)} bg{t.reset} {t.subtle}│{t.reset}"

    tools_indicator = f"{t.assistant}{ICON_SUCCESS}{t.reset}" if tools_enabled else f"{t.tool_error}{ICON_ERROR}{t.reset}"
    skills_indicator = f"{t.assistant}{ICON_SUCCESS}{t.reset}" if skills_enabled else f"{t.tool_error}{ICON_ERROR}{t.reset}"

    right = (
        f"{bg_info} {ICON_TOOL} {t.subtle}tools{t.reset} {tools_indicator}"
        f" {t.subtle}│{t.reset} {ICON_SKILL} {t.subtle}skills{t.reset} {skills_indicator}"
    )
    gap = max(1, width - string_display_width(left) - string_display_width(right))
    return f"{left}{' ' * gap}{right}"


def render_slash_menu(commands: list[Any], selected_index: int) -> str:
    """Render slash command menu with highlight."""
    t = theme()
    if not commands:
        return f"{t.subtle}no commands{t.reset}"
    width, _ = _cached_terminal_size()
    rows = [f"{ACCENT}{ICON_ARROW}{RESET} {t.dim}commands{t.reset}"]
    for i, cmd in enumerate(commands):
        usage = pad_plain(getattr(cmd, "usage", str(cmd)), 14)
        desc = getattr(cmd, "description", "")
        if i == selected_index:
            line = (
                f"  {t.command_highlight_bg}{BRIGHT_CYAN}{ICON_ARROW}{RESET}"
                f"{t.command_highlight_bg} {BRIGHT_WHITE}{t.bold}{usage}{RESET}"
                f"{t.command_highlight_bg} {desc} {RESET}"
            )
        else:
            line = f"   {t.subtle}{ICON_DOT}{t.reset} {usage} {t.subtle}{desc}{t.reset}"
        rows.append(truncate_plain(line, width))
    return "\n".join(rows)
