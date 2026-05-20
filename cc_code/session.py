"""Session persistence and resume module.

Sessions are stored as append-only JSONL files: one line per record (header,
message, transcript entry, history entry, meta_update). Resume = read the
file linewise and replay. No delta files, no consolidation, no MD5 change
hashes — append-only avoids all of that complexity.

Legacy sessions (``{id}.json`` + ``deltas/{id}/delta_*.json``) are still
loadable; new saves only ever write ``{id}.jsonl``.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cc_code.config import CC_CODE_DIR
from cc_code.io_atomic import atomic_write_text


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SESSIONS_DIR = CC_CODE_DIR / "sessions"
AUTOSAVE_INTERVAL_SECONDS = 30  # Minimum seconds between autosaves

# Legacy delta layout. Kept only for read-side migration.
DELTA_DIR_NAME = "deltas"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SessionMetadata:
    """Lightweight metadata for session listing."""
    session_id: str
    created_at: float  # Unix timestamp
    updated_at: float  # Unix timestamp
    first_message: str = ""  # Truncated first user message
    last_message: str = ""   # Truncated last message
    message_count: int = 0
    workspace: str = ""      # Working directory when session started


@dataclass
class SessionData:
    """Complete session state that can be persisted and restored."""
    session_id: str
    created_at: float
    updated_at: float
    workspace: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    transcript_entries: list[dict[str, Any]] = field(default_factory=list)
    history: list[str] = field(default_factory=list)
    permissions_summary: dict[str, Any] = field(default_factory=dict)
    skills: list[dict[str, Any]] = field(default_factory=list)
    mcp_servers: list[dict[str, Any]] = field(default_factory=list)
    metadata: SessionMetadata = field(default=None)

    # Append-only save tracking — how much has already been flushed to disk.
    _saved_msg_count: int = field(default=0, repr=False)
    _saved_transcript_count: int = field(default=0, repr=False)
    _saved_history_count: int = field(default=0, repr=False)
    _saved_meta_signature: tuple = field(default=(), repr=False)

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = SessionMetadata(
                session_id=self.session_id,
                created_at=self.created_at,
                updated_at=self.updated_at,
                message_count=len(self.messages),
                workspace=self.workspace,
            )

    def update_metadata(self) -> None:
        """Refresh metadata from current state."""
        self.updated_at = time.time()
        self.metadata.updated_at = self.updated_at
        self.metadata.message_count = len(self.messages)

        # First user message (truncated)
        for msg in self.messages:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                self.metadata.first_message = content[:100] if isinstance(content, str) else ""
                break

        # Last user/assistant message (truncated)
        for msg in reversed(self.messages):
            if msg.get("role") in ("user", "assistant"):
                content = msg.get("content", "")
                self.metadata.last_message = content[:100] if isinstance(content, str) else ""
                break

    @property
    def has_delta(self) -> bool:
        """Whether there are unsaved changes since the last save."""
        return (
            len(self.messages) != self._saved_msg_count
            or len(self.transcript_entries) != self._saved_transcript_count
            or len(self.history) != self._saved_history_count
            or self._current_meta_signature() != self._saved_meta_signature
        )

    def _current_meta_signature(self) -> tuple:
        # A hashable fingerprint of fields that can change mid-session and
        # are stored as meta_update records (not as append-only entries).
        return (
            json.dumps(self.permissions_summary, sort_keys=True),
            json.dumps(self.skills, sort_keys=True),
            json.dumps(self.mcp_servers, sort_keys=True),
        )


# ---------------------------------------------------------------------------
# File paths
# ---------------------------------------------------------------------------

def _session_file(session_id: str) -> Path:
    """New JSONL path for a session."""
    return SESSIONS_DIR / f"{session_id}.jsonl"


def _legacy_session_file(session_id: str) -> Path:
    """Legacy full-save JSON path. Read-only — never written by this module."""
    return SESSIONS_DIR / f"{session_id}.json"


def _legacy_delta_dir(session_id: str) -> Path:
    return SESSIONS_DIR / DELTA_DIR_NAME / session_id


def _session_index_file() -> Path:
    return CC_CODE_DIR / "sessions_index.json"


# ---------------------------------------------------------------------------
# Session index (lightweight metadata for fast listing)
# ---------------------------------------------------------------------------

def _load_session_index() -> dict[str, SessionMetadata]:
    index_path = _session_index_file()
    if not index_path.exists():
        return {}
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
        return {sid: SessionMetadata(**meta) for sid, meta in data.items()}
    except (json.JSONDecodeError, TypeError, KeyError):
        return {}


def _save_session_index(index: dict[str, SessionMetadata]) -> None:
    CC_CODE_DIR.mkdir(parents=True, exist_ok=True)
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    serializable = {
        sid: {
            "session_id": meta.session_id,
            "created_at": meta.created_at,
            "updated_at": meta.updated_at,
            "first_message": meta.first_message,
            "last_message": meta.last_message,
            "message_count": meta.message_count,
            "workspace": meta.workspace,
        }
        for sid, meta in index.items()
    }
    atomic_write_text(
        _session_index_file(),
        json.dumps(serializable, indent=2) + "\n",
    )


# ---------------------------------------------------------------------------
# JSONL save / load
# ---------------------------------------------------------------------------

def _write_jsonl_lines(path: Path, lines: list[dict[str, Any]], *, mode: str) -> None:
    """Write one JSON record per line. mode='a' for append, 'w' for rewrite.

    For append mode we flush + fsync so a crash mid-line doesn't leave a
    partial record. For rewrite mode we go through atomic_write_text.
    """
    if mode == "w":
        body = "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines)
        atomic_write_text(path, body)
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8", newline="") as f:
        for line in lines:
            f.write(json.dumps(line, ensure_ascii=False))
            f.write("\n")
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            pass


def _build_header_record(session: SessionData) -> dict[str, Any]:
    return {
        "type": "header",
        "session_id": session.session_id,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "workspace": session.workspace,
    }


def _build_meta_update_record(session: SessionData) -> dict[str, Any]:
    return {
        "type": "meta_update",
        "permissions_summary": session.permissions_summary,
        "skills": session.skills,
        "mcp_servers": session.mcp_servers,
    }


def save_session(session: SessionData, force_full: bool = False) -> None:
    """Persist session state to disk.

    Default behavior: append-only — only new messages / transcript entries /
    history entries (plus a meta_update record if skills / permissions /
    mcp_servers changed) are appended to ``{id}.jsonl``.

    ``force_full=True`` rewrites the whole file atomically. Use this on
    explicit "save" or at session finalize to ensure a single clean file.
    """
    session.update_metadata()
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    target = _session_file(session.session_id)

    # Fresh SessionData with the same id (no prior save tracked) → rewrite
    # rather than append, otherwise we'd duplicate every message that was
    # already on disk from a previous save.
    fresh_state = session._saved_msg_count == 0 and not session._saved_transcript_count
    if force_full or not target.exists() or fresh_state:
        # Rewrite mode: produce the full canonical record set.
        records: list[dict[str, Any]] = [_build_header_record(session)]
        for msg in session.messages:
            records.append({"type": "message", "data": msg})
        for entry in session.transcript_entries:
            records.append({"type": "transcript", "data": entry})
        for h in session.history:
            records.append({"type": "history", "data": h})
        if session.permissions_summary or session.skills or session.mcp_servers:
            records.append(_build_meta_update_record(session))
        _write_jsonl_lines(target, records, mode="w")

        session._saved_msg_count = len(session.messages)
        session._saved_transcript_count = len(session.transcript_entries)
        session._saved_history_count = len(session.history)
        session._saved_meta_signature = session._current_meta_signature()
    else:
        # Append mode: only the diff since last save.
        new_records: list[dict[str, Any]] = []
        for msg in session.messages[session._saved_msg_count:]:
            new_records.append({"type": "message", "data": msg})
        for entry in session.transcript_entries[session._saved_transcript_count:]:
            new_records.append({"type": "transcript", "data": entry})
        for h in session.history[session._saved_history_count:]:
            new_records.append({"type": "history", "data": h})

        current_meta = session._current_meta_signature()
        if current_meta != session._saved_meta_signature:
            new_records.append(_build_meta_update_record(session))

        if new_records:
            _write_jsonl_lines(target, new_records, mode="a")
            session._saved_msg_count = len(session.messages)
            session._saved_transcript_count = len(session.transcript_entries)
            session._saved_history_count = len(session.history)
            session._saved_meta_signature = current_meta

    # Update lightweight index (used by list_sessions)
    index = _load_session_index()
    index[session.session_id] = session.metadata
    _save_session_index(index)


def _load_jsonl_session(session_id: str) -> SessionData | None:
    target = _session_file(session_id)
    if not target.exists():
        return None
    try:
        session: SessionData | None = None
        messages: list[dict[str, Any]] = []
        transcripts: list[dict[str, Any]] = []
        history: list[str] = []
        permissions_summary: dict[str, Any] = {}
        skills: list[dict[str, Any]] = []
        mcp_servers: list[dict[str, Any]] = []

        with open(target, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    # Skip the corrupted line and keep going — append-only
                    # storage means later lines are still valid.
                    continue
                rtype = record.get("type")
                if rtype == "header":
                    session = SessionData(
                        session_id=record["session_id"],
                        created_at=record["created_at"],
                        updated_at=record["updated_at"],
                        workspace=record.get("workspace", ""),
                    )
                elif rtype == "message":
                    messages.append(record["data"])
                elif rtype == "transcript":
                    transcripts.append(record["data"])
                elif rtype == "history":
                    history.append(record["data"])
                elif rtype == "meta_update":
                    permissions_summary = record.get("permissions_summary", permissions_summary)
                    skills = record.get("skills", skills)
                    mcp_servers = record.get("mcp_servers", mcp_servers)
                # Unknown record types are ignored (forward-compatible).

        if session is None:
            return None

        session.messages = messages
        session.transcript_entries = transcripts
        session.history = history
        session.permissions_summary = permissions_summary
        session.skills = skills
        session.mcp_servers = mcp_servers
        session._saved_msg_count = len(messages)
        session._saved_transcript_count = len(transcripts)
        session._saved_history_count = len(history)
        session._saved_meta_signature = session._current_meta_signature()
        session.update_metadata()
        return session
    except OSError:
        return None


def _load_legacy_session(session_id: str) -> SessionData | None:
    """Read the old ``{id}.json`` + ``deltas/{id}/delta_*.json`` layout.

    Used only when no JSONL file exists for the id. After loading, callers
    can choose to resave; the next save will produce a ``.jsonl`` file.
    """
    legacy_path = _legacy_session_file(session_id)
    if not legacy_path.exists():
        return None
    try:
        data = json.loads(legacy_path.read_text(encoding="utf-8"))
        metadata = SessionMetadata(**data.get("metadata", {}))
        session = SessionData(
            session_id=data["session_id"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            workspace=data["workspace"],
            messages=data.get("messages", []),
            transcript_entries=data.get("transcript_entries", []),
            history=data.get("history", []),
            permissions_summary=data.get("permissions_summary", {}),
            skills=data.get("skills", []),
            mcp_servers=data.get("mcp_servers", []),
            metadata=metadata,
        )
    except (json.JSONDecodeError, KeyError, TypeError):
        return None

    # Apply legacy deltas if present.
    delta_dir = _legacy_delta_dir(session_id)
    if delta_dir.exists():
        for delta_path in sorted(delta_dir.glob("delta_*.json")):
            try:
                delta = json.loads(delta_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            new_msgs = delta.get("messages")
            if new_msgs:
                offset = delta.get("msg_offset", len(session.messages))
                if offset >= len(session.messages):
                    session.messages.extend(new_msgs)
                elif offset + len(new_msgs) > len(session.messages):
                    overlap = len(session.messages) - offset
                    session.messages.extend(new_msgs[overlap:])
            new_ts = delta.get("transcripts")
            if new_ts:
                offset = delta.get("transcript_offset", len(session.transcript_entries))
                if offset >= len(session.transcript_entries):
                    session.transcript_entries.extend(new_ts)
                elif offset + len(new_ts) > len(session.transcript_entries):
                    overlap = len(session.transcript_entries) - offset
                    session.transcript_entries.extend(new_ts[overlap:])

    session._saved_msg_count = len(session.messages)
    session._saved_transcript_count = len(session.transcript_entries)
    session._saved_history_count = len(session.history)
    session._saved_meta_signature = session._current_meta_signature()
    return session


def load_session(session_id: str) -> SessionData | None:
    """Load a session by id. Tries new JSONL format first, then legacy."""
    session = _load_jsonl_session(session_id)
    if session is not None:
        return session
    return _load_legacy_session(session_id)


def list_sessions() -> list[SessionMetadata]:
    """List all available sessions, newest first."""
    index = _load_session_index()
    sessions = list(index.values())
    sessions.sort(key=lambda s: s.updated_at, reverse=True)
    return sessions


def delete_session(session_id: str) -> bool:
    """Delete a session from disk (new + legacy paths). Returns True if anything was removed."""
    removed = False

    target = _session_file(session_id)
    if target.exists():
        try:
            target.unlink()
            removed = True
        except OSError:
            pass

    legacy = _legacy_session_file(session_id)
    if legacy.exists():
        try:
            legacy.unlink()
            removed = True
        except OSError:
            pass

    delta_dir = _legacy_delta_dir(session_id)
    if delta_dir.exists():
        for f in delta_dir.glob("delta_*.json"):
            try:
                f.unlink()
                removed = True
            except OSError:
                pass
        try:
            delta_dir.rmdir()
        except OSError:
            pass

    if removed:
        index = _load_session_index()
        if index.pop(session_id, None) is not None:
            _save_session_index(index)

    return removed


def cleanup_old_sessions(max_sessions: int = 50) -> int:
    """Remove oldest sessions beyond max_sessions limit. Returns count deleted."""
    sessions = list_sessions()
    if len(sessions) <= max_sessions:
        return 0

    to_delete = sessions[max_sessions:]
    deleted = 0
    for meta in to_delete:
        if delete_session(meta.session_id):
            deleted += 1
    return deleted


# ---------------------------------------------------------------------------
# Session creation helpers
# ---------------------------------------------------------------------------

def create_new_session(workspace: str) -> SessionData:
    """Create a new empty session."""
    now = time.time()
    session_id = uuid.uuid4().hex[:12]
    return SessionData(
        session_id=session_id,
        created_at=now,
        updated_at=now,
        workspace=workspace,
    )


def get_latest_session(workspace: str | None = None) -> SessionData | None:
    """Get the most recent session, optionally filtered by workspace."""
    sessions = list_sessions()
    for meta in sessions:
        if workspace is None or meta.workspace == workspace:
            return load_session(meta.session_id)
    return None


# ---------------------------------------------------------------------------
# Autosave manager
# ---------------------------------------------------------------------------

class AutosaveManager:
    """Periodic save with dirty tracking.

    Append-only storage means even the periodic save is cheap (it only writes
    what changed since last save). ``force_save`` does a full rewrite to
    consolidate any meta drift.
    """

    def __init__(self, session: SessionData, interval: int = AUTOSAVE_INTERVAL_SECONDS):
        self.session = session
        self.interval = interval
        self._last_save_time = time.time()
        self._dirty = False

    def mark_dirty(self) -> None:
        self._dirty = True

    def should_save(self) -> bool:
        if not self._dirty:
            return False
        return (time.time() - self._last_save_time) >= self.interval

    def save_if_needed(self) -> bool:
        if self.should_save():
            save_session(self.session, force_full=False)
            self._last_save_time = time.time()
            self._dirty = False
            return True
        return False

    def force_save(self) -> None:
        save_session(self.session, force_full=True)
        self._last_save_time = time.time()
        self._dirty = False


# ---------------------------------------------------------------------------
# Session formatting for display
# ---------------------------------------------------------------------------

def format_session_list(sessions: list[SessionMetadata]) -> str:
    """Format a list of sessions for terminal display."""
    if not sessions:
        return "No saved sessions found."

    lines = ["Saved sessions:", ""]
    for meta in sessions[:20]:  # show up to 20
        age_seconds = time.time() - meta.updated_at
        if age_seconds < 60:
            age = f"{int(age_seconds)}s ago"
        elif age_seconds < 3600:
            age = f"{int(age_seconds / 60)}m ago"
        elif age_seconds < 86400:
            age = f"{int(age_seconds / 3600)}h ago"
        else:
            age = f"{int(age_seconds / 86400)}d ago"
        first = meta.first_message[:60] + ("…" if len(meta.first_message) > 60 else "")
        lines.append(
            f"  [{meta.session_id[:8]}] {age:>10}  {meta.message_count:>3} msgs  {first}"
        )
    return "\n".join(lines)


def format_session_resume(session: SessionData) -> str:
    """Format session info shown when resuming."""
    lines = [
        f"Resuming session [{session.session_id[:8]}]",
        f"  workspace: {session.workspace}",
        f"  messages: {len(session.messages)}",
        f"  transcript entries: {len(session.transcript_entries)}",
    ]
    return "\n".join(lines)
