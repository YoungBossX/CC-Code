"""Save/load/clear `ContextManager` state on disk.

State file is JSON, written atomically. Keeps last 10 compaction-history
entries to bound size; preserves `_compaction_level` across restarts so a
session that has compacted aggressively doesn't reset its threshold.
"""

from __future__ import annotations

import json

from cc_code.config import CC_CODE_DIR
from cc_code.context_manager._manager import ContextManager
from cc_code.io_atomic import atomic_write_text


def _state_path():
    return CC_CODE_DIR / "context_state.json"


def save_context_state(manager: ContextManager) -> None:
    """Save context manager state to disk."""
    CC_CODE_DIR.mkdir(parents=True, exist_ok=True)
    state = {
        "model": manager.model,
        "context_window": manager.context_window,
        "messages": manager.messages,
        "compaction_history": manager.compaction_history[-10:],
        "_compaction_level": manager._compaction_level,
    }
    atomic_write_text(
        _state_path(),
        json.dumps(state, indent=2, ensure_ascii=False),
    )


def load_context_state() -> ContextManager | None:
    """Load context manager state from disk."""
    path = _state_path()
    if not path.exists():
        return None

    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        manager = ContextManager(
            model=state.get("model", "default"),
            context_window=state.get("context_window", 0),
            messages=state.get("messages", []),
            compaction_history=state.get("compaction_history", []),
        )
        if "_compaction_level" in state:
            manager._compaction_level = state["_compaction_level"]
        return manager
    except (json.JSONDecodeError, KeyError):
        return None


def clear_context_state() -> None:
    """Clear saved context state."""
    path = _state_path()
    if path.exists():
        path.unlink()
