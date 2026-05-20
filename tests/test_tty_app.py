from cc_code.tty_app import (
    _ThrottledRenderer,
    _apply_tool_result_visual_state,
    _format_history,
    _mark_unfinished_tools,
    _save_transcript,
    summarize_tool_input,
    summarize_tool_output,
)
import cc_code.tui.input_handler as input_handler_module
from cc_code.context_manager import ContextManager
from cc_code.permissions import PermissionManager
from cc_code.tooling import ToolRegistry
from cc_code.tui.runtime_control import _ThrottledRenderer as RuntimeThrottledRenderer
from cc_code.tui.event_flow import _handle_event
from cc_code.tui.input_parser import KeyEvent
from cc_code.tui.state import ScreenState, TtyAppArgs
from cc_code.tui.renderer import _render_prompt_panel, _render_startup_panel
from cc_code.tui.transcript import format_transcript_text
from cc_code.tui.types import TranscriptEntry


def test_tty_app_uses_runtime_control_throttled_renderer() -> None:
    assert _ThrottledRenderer is RuntimeThrottledRenderer


def test_summarize_tool_output_prefers_first_meaningful_line() -> None:
    output = "\n\nFILE: README.md\nOFFSET: 0\nEND: 100"
    assert summarize_tool_output("read_file", output).startswith("FILE: README.md")


def test_summarize_tool_output_truncates_long_lines() -> None:
    output = "x" * 400
    summary = summarize_tool_output("run_command", output)
    assert len(summary) < 200
    assert summary.endswith("...")


def test_format_history_shows_recent_entries_with_numbers() -> None:
    rendered = _format_history(["/help", "build parser", "/cmd pytest -q"], limit=2)
    assert rendered == "2. build parser\n3. /cmd pytest -q"


def test_save_transcript_writes_plain_text(tmp_path) -> None:
    state_entries = [
        TranscriptEntry(id=1, kind="user", body="hello"),
        TranscriptEntry(id=2, kind="assistant", body="world"),
    ]
    permissions = PermissionManager(str(tmp_path), prompt=lambda request: {"decision": "allow_once"})

    path = _save_transcript(
        type("State", (), {"transcript": state_entries})(),
        str(tmp_path),
        permissions,
        "logs/session.txt",
    )

    assert path.endswith("logs\\session.txt") or path.endswith("logs/session.txt")
    assert (tmp_path / "logs" / "session.txt").read_text(encoding="utf-8") == "you\n  hello\n\n---\n\nassistant\n  world"


def test_format_transcript_text_uses_clean_separator() -> None:
    rendered = format_transcript_text(
        [
            TranscriptEntry(id=1, kind="user", body="one"),
            TranscriptEntry(id=2, kind="assistant", body="two"),
        ]
    )

    assert "\n\n---\n\n" in rendered


def test_summarize_tool_input_formats_patch_file() -> None:
    summary = summarize_tool_input(
        "patch_file",
        {"path": "demo.txt", "replacements": [{"search": "a", "replace": "b"}, {"search": "c", "replace": "d"}]},
    )

    assert summary == "patch_file path=demo.txt replacements=2"


def test_mark_unfinished_tools_marks_running_entries_as_errors() -> None:
    state = type(
        "State",
        (),
        {
            "transcript": [TranscriptEntry(id=1, kind="tool", body="running", toolName="run_command", status="running")],
            "recent_tools": [],
            "pending_tool_runs": {"run_command": [{"entry": "placeholder"}]},
            "active_tool": "run_command",
        },
    )()

    count = _mark_unfinished_tools(state)

    assert count == 1
    assert state.transcript[0].status == "error"
    assert "did not report a final result" in state.transcript[0].body
    assert state.recent_tools == [{"name": "run_command", "status": "error"}]
    assert state.pending_tool_runs == {}
    assert state.active_tool is None


def test_error_tool_entry_stays_expanded_for_visibility() -> None:
    entry = TranscriptEntry(id=1, kind="tool", body="boom", toolName="run_command", status="running")
    _apply_tool_result_visual_state(entry, "run_command", "boom", is_error=True)

    assert entry.status == "error"
    assert entry.collapsed is False
    assert entry.collapsedSummary is None


def test_success_tool_entry_collapses_to_summary() -> None:
    entry = TranscriptEntry(id=1, kind="tool", body="running", toolName="read_file", status="running")
    _apply_tool_result_visual_state(entry, "read_file", "FILE: README.md\nhello", is_error=False)

    assert entry.status == "success"
    assert entry.collapsed is True
    assert entry.collapsedSummary == "FILE: README.md"
    assert entry.collapsePhase == 3


def test_empty_tty_return_does_not_start_input_handler(tmp_path) -> None:
    calls = []
    state = ScreenState(input="   ", cursor_offset=3)
    args = TtyAppArgs(
        runtime=None,
        tools=None,
        model=None,
        messages=[],
        cwd=str(tmp_path),
        permissions=PermissionManager(str(tmp_path)),
    )

    def rerender() -> None:
        calls.append("rerender")

    def handle_input(*_args, **_kwargs):
        calls.append("handle_input")
        return False

    _handle_event(
        args,
        state,
        KeyEvent(name="return", ctrl=False, meta=False),
        rerender,
        __import__("threading").Event(),
        {},
        handle_input,
    )

    assert "handle_input" not in calls
    assert state.input == ""


def test_tty_return_submits_exact_history_command(tmp_path) -> None:
    submitted: list[str] = []
    state = ScreenState(input="/history", cursor_offset=8, selected_slash_index=0)
    args = TtyAppArgs(
        runtime=None,
        tools=ToolRegistry([]),
        model=object(),
        messages=[],
        cwd=str(tmp_path),
        permissions=PermissionManager(str(tmp_path)),
    )

    def handle_input(*callback_args, **_kwargs):
        submitted.append(callback_args[3])
        return False

    _handle_event(
        args,
        state,
        KeyEvent(name="return", ctrl=False, meta=False),
        lambda: None,
        __import__("threading").Event(),
        {},
        handle_input,
    )

    assert submitted == ["/history"]
    assert state.input == ""


def test_tty_enter_leaves_startup_mode(tmp_path) -> None:
    state = ScreenState(startup_mode=True)
    args = TtyAppArgs(
        runtime={"model": "demo"},
        tools=ToolRegistry([]),
        model=object(),
        messages=[],
        cwd=str(tmp_path),
        permissions=PermissionManager(str(tmp_path)),
    )

    _handle_event(
        args,
        state,
        KeyEvent(name="return", ctrl=False, meta=False),
        lambda: None,
        __import__("threading").Event(),
        {},
        lambda *_args, **_kwargs: False,
    )

    assert state.startup_mode is False


def test_startup_panel_shows_enter_message(tmp_path) -> None:
    state = ScreenState(startup_mode=True)
    args = TtyAppArgs(
        runtime={"model": "demo"},
        tools=ToolRegistry([]),
        model=object(),
        messages=[],
        cwd=str(tmp_path),
        permissions=PermissionManager(str(tmp_path)),
    )

    rendered = _render_startup_panel(args, state)

    assert "Press Enter to continue" in rendered
    assert "Welcome to CC-Code" in rendered


def test_tty_history_picker_number_executes_selected_entry(tmp_path, monkeypatch) -> None:
    state = ScreenState(
        input="1",
        cursor_offset=1,
        history_picker_entries=["/help", "/config"],
        history_picker_index=0,
    )
    args = TtyAppArgs(
        runtime=None,
        tools=ToolRegistry([]),
        model=object(),
        messages=[],
        cwd=str(tmp_path),
        permissions=PermissionManager(str(tmp_path)),
    )

    def fake_try_handle_local_command(user_input: str, tools=None, cwd: str | None = None):
        if user_input == "/help":
            return "history item handled"
        return None

    monkeypatch.setattr(input_handler_module, "try_handle_local_command", fake_try_handle_local_command)

    assert input_handler_module._handle_input(args, state, lambda: None) is False

    assert state.history_picker_entries == []
    assert state.transcript[-1].body == "history item handled"
    assert state.history[-1] == "/help"


def test_tty_history_direct_number_executes_selected_entry(tmp_path, monkeypatch) -> None:
    state = ScreenState(input="/history 1", cursor_offset=10)
    args = TtyAppArgs(
        runtime=None,
        tools=ToolRegistry([]),
        model=object(),
        messages=[],
        cwd=str(tmp_path),
        permissions=PermissionManager(str(tmp_path)),
    )

    monkeypatch.setattr(input_handler_module, "load_history_entries", lambda: ["/help", "/config"])
    executed: list[str] = []

    def fake_try_handle_local_command(user_input: str, tools=None, cwd: str | None = None):
        executed.append(user_input)
        if user_input == "/help":
            return "direct history handled"
        return None

    monkeypatch.setattr(input_handler_module, "try_handle_local_command", fake_try_handle_local_command)

    assert input_handler_module._handle_input(args, state, lambda: None) is False

    assert executed == ["/help"]
    assert state.transcript[-1].body == "direct history handled"


def test_history_picker_render_keeps_current_entry_visible() -> None:
    state = ScreenState(
        input="",
        cursor_offset=0,
        history_picker_entries=[f"/cmd {i}" for i in range(1, 11)],
        history_picker_index=8,
    )

    rendered = _render_prompt_panel(state)

    assert "9. /cmd 9" in rendered
    assert "> 9. /cmd 9" in rendered
    assert "..." in rendered


def test_tty_input_passes_and_persists_context_manager(tmp_path, monkeypatch) -> None:
    captured: dict = {}
    saved: list[ContextManager] = []
    context_manager = ContextManager(model="default", context_window=1000)

    def fake_run_agent_turn(**kwargs):
        captured.update(kwargs)
        manager = kwargs["context_manager"]
        manager.messages = list(kwargs["messages"])
        return [*kwargs["messages"], {"role": "assistant", "content": "done"}]

    monkeypatch.setattr(input_handler_module, "run_agent_turn", fake_run_agent_turn)
    monkeypatch.setattr(input_handler_module, "save_context_state", saved.append, raising=False)

    state = ScreenState(input="Please inspect context", cursor_offset=22)
    args = TtyAppArgs(
        runtime={"model": "default"},
        tools=ToolRegistry([]),
        model=object(),
        messages=[{"role": "system", "content": "sys"}],
        cwd=str(tmp_path),
        permissions=PermissionManager(str(tmp_path)),
        context_manager=context_manager,
    )

    assert input_handler_module._handle_input(args, state, lambda: None) is False
    state.agent_thread.join(timeout=5)

    assert captured["context_manager"] is context_manager
    assert saved == [context_manager]
    assert state.agent_result["messages"][-1] == {"role": "assistant", "content": "done"}
