"""Atomic file write helper.

Writes go to a sibling temp file, are fsync'd, then renamed over the
target with os.replace. On POSIX the rename is atomic. On Windows
os.replace is also atomic on NTFS for files on the same volume.

Use this for any file whose corruption would block recovery — session
state, settings, agent-driven file edits.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(path: str | Path, content: str, encoding: str = "utf-8") -> None:
    """Write content to path atomically.

    Guarantees: either path is fully replaced with the new content, or
    it is left unchanged. No partial writes survive a crash.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
            f.write(content)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                # fsync can fail on some filesystems (e.g. tmpfs on WSL); the
                # rename below still provides crash-consistency on most setups.
                pass
        os.replace(tmp_path, target)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
