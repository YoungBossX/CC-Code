"""TUI chrome: ANSI primitives, width, panels, components, diff, permission prompt.

Public surface (everything callers were importing pre-split):

- ANSI constants: ``RESET``, ``DIM``, ``CYAN``, ``GREEN``, ``YELLOW``, ``RED``,
  ``BLUE``, ``MAGENTA``, ``BOLD``, ``REVERSE``, ``ITALIC``, ``UNDERLINE``,
  ``BRIGHT_*``, ``BORDER``, ``BORDER_DIM``, ``ACCENT``, ``ACCENT2``,
  ``SUBTLE``, ``HIGHLIGHT_BG``
- Icons: ``ICON_*``
- Helpers: ``strip_ansi``, ``_ANSI_RE``
- Terminal size: ``_cached_terminal_size``, ``invalidate_terminal_size_cache``
- Width: ``char_display_width``, ``_stripped_display_width``,
  ``string_display_width``, ``truncate_plain``, ``pad_plain``,
  ``truncate_path_middle``
- Panels: ``color_badge``, ``border_line``, ``panel_row``,
  ``empty_panel_row``, ``wrap_panel_body_line``, ``render_panel``
- Components: ``render_banner``, ``render_status_line``,
  ``render_tool_panel``, ``render_footer_bar``, ``render_slash_menu``
- Diff: ``classify_diff_line``, ``compute_changed_range``,
  ``apply_word_emphasis``, ``colorize_unified_diff_block``,
  ``colorize_edit_permission_details``
- Permission: ``get_permission_prompt_max_scroll_offset``,
  ``flatten_detail_lines``, ``slice_visible_details``,
  ``render_permission_prompt``

Internal modules are prefixed with ``_`` (``_ansi``, ``_terminal``,
``_width``, ``_panels``, ``_components``, ``_diff``, ``_permission``);
reach for the package import surface, not the submodules.
"""

from cc_code.tui.chrome._ansi import (
    ACCENT,
    ACCENT2,
    BLUE,
    BOLD,
    BORDER,
    BORDER_DIM,
    BRIGHT_BLUE,
    BRIGHT_CYAN,
    BRIGHT_GREEN,
    BRIGHT_MAGENTA,
    BRIGHT_RED,
    BRIGHT_WHITE,
    BRIGHT_YELLOW,
    CYAN,
    DIM,
    GREEN,
    HIGHLIGHT_BG,
    ICON_ARROW,
    ICON_ASSISTANT,
    ICON_BG,
    ICON_CC_CODER,
    ICON_DIVIDER,
    ICON_DOT,
    ICON_ERROR,
    ICON_EVENT,
    ICON_FOLDER,
    ICON_LOCK,
    ICON_MCP,
    ICON_MODEL,
    ICON_MSG,
    ICON_PROGRESS,
    ICON_PROMPT,
    ICON_PROVIDER,
    ICON_RUNNING,
    ICON_SKILL,
    ICON_SUCCESS,
    ICON_TOOL,
    ICON_USER,
    ITALIC,
    MAGENTA,
    RED,
    RESET,
    REVERSE,
    SUBTLE,
    UNDERLINE,
    YELLOW,
    _ANSI_RE,
    strip_ansi,
)
from cc_code.tui.chrome._components import (
    render_banner,
    render_footer_bar,
    render_slash_menu,
    render_status_line,
    render_tool_panel,
)
from cc_code.tui.chrome._diff import (
    apply_word_emphasis,
    classify_diff_line,
    colorize_edit_permission_details,
    colorize_unified_diff_block,
    compute_changed_range,
)
from cc_code.tui.chrome._panels import (
    border_line,
    color_badge,
    empty_panel_row,
    panel_row,
    render_panel,
    wrap_panel_body_line,
)
from cc_code.tui.chrome._permission import (
    flatten_detail_lines,
    get_permission_prompt_max_scroll_offset,
    render_permission_prompt,
    slice_visible_details,
)
from cc_code.tui.chrome._terminal import (
    _cached_terminal_size,
    invalidate_terminal_size_cache,
)
from cc_code.tui.chrome._width import (
    _stripped_display_width,
    char_display_width,
    pad_plain,
    string_display_width,
    truncate_path_middle,
    truncate_plain,
)
