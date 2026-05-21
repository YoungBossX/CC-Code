from cc_code.tui import render_banner, render_panel, render_permission_prompt, render_transcript
from cc_code.tui.types import TranscriptEntry


def test_render_panel_contains_title() -> None:
    rendered = render_panel("Demo", "body")
    assert "Demo" in rendered
    assert "body" in rendered


def test_render_banner_includes_model() -> None:
    rendered = render_banner(
        {"model": "claude-test", "baseUrl": "https://api.anthropic.com"},
        "/tmp/demo",
        ["cwd: /tmp/demo"],
        {"transcriptCount": 1, "messageCount": 2, "skillCount": 3, "mcpCount": 4},
    )
    assert "claude-test" in rendered
    assert "api.anthropic.com" in rendered


def test_render_transcript_shows_tool_entry() -> None:
    transcript = [
        TranscriptEntry(id=1, kind="user", body="hi"),
        TranscriptEntry(id=2, kind="tool", body="done", toolName="read_file", status="success"),
    ]
    rendered = render_transcript(transcript, scroll_offset=0)
    assert "read_file" in rendered
    assert "ok" in rendered


def test_render_transcript_shows_intermediate_collapse_phase() -> None:
    transcript = [
        TranscriptEntry(
            id=1,
            kind="tool",
            body="full output here",
            toolName="run_command",
            status="success",
            collapsePhase=1,
        ),
    ]

    rendered = render_transcript(transcript, scroll_offset=0)

    assert "run_command" in rendered
    assert "collapsing" in rendered


def test_render_transcript_shows_collapsed_summary_when_fully_collapsed() -> None:
    transcript = [
        TranscriptEntry(
            id=1,
            kind="tool",
            body="full output here",
            toolName="run_command",
            status="success",
            collapsed=True,
            collapsedSummary="short summary",
            collapsePhase=3,
        ),
    ]

    rendered = render_transcript(transcript, scroll_offset=0)

    assert "run_command" in rendered
    assert "short summary" in rendered
    assert "full output here" not in rendered


def test_render_transcript_shows_above_fold_indicator_when_content_overflows() -> None:
    # Body with many lines forces total_lines > window_size.
    long_body = "\n".join(f"line {i}" for i in range(60))
    transcript = [TranscriptEntry(id=1, kind="assistant", body=long_body)]

    rendered = render_transcript(transcript, scroll_offset=0, window_size=10)

    # Top indicator must appear so the user knows there's content above.
    assert "上方还有" in rendered
    assert "PgUp" in rendered
    # Tail of the body should still be the last visible line.
    assert "line 59" in rendered
    # Beginning of the body must be hidden (proves the window is clipping).
    assert "line 0" not in rendered


def test_render_transcript_no_indicator_when_content_fits() -> None:
    transcript = [TranscriptEntry(id=1, kind="user", body="hi")]
    rendered = render_transcript(transcript, scroll_offset=0, window_size=10)
    assert "上方还有" not in rendered
    assert "hi" in rendered


def test_render_permission_prompt_lists_choices() -> None:
    rendered = render_permission_prompt(
        {
            "summary": "Need approval",
            "details": ["target: demo.txt"],
            "choices": [{"key": "1", "label": "allow once"}],
        }
    )
    assert "Need approval" in rendered
    assert "allow once" in rendered
