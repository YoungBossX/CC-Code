"""Pytest collection controls for repository-local legacy smoke scripts."""

from __future__ import annotations

import pytest


# These root-level scripts are manual smoke/integration utilities from earlier
# development rounds. Normal pytest coverage lives under tests/.
collect_ignore = [
    "test_chinese_input.py",
    "test_integration.py",
    "test_optim.py",
    "test_run.py",
    "visual_test.py",
]

collect_ignore_glob = [
    "benchmarks/*.py",
]


@pytest.fixture(autouse=True)
def isolate_cc_code_dirs(tmp_path, monkeypatch):
    """Redirect user-scoped runtime data into the test temp directory.

    ``CC_CODE_DIR`` is imported into many submodules with ``from cc_code.config
    import CC_CODE_DIR``; that copies the reference at import time, so patching
    only ``cc_code.config`` leaves the local bindings pointing at the user's
    real home. We patch every site that owns a local binding so user-scope
    memory, context state, and sessions all land in the sandbox.
    """
    sandbox = tmp_path / ".cc-code"
    sandbox.mkdir(parents=True, exist_ok=True)

    import cc_code.config
    import cc_code.context_manager  # package
    import cc_code.context_manager._persistence
    import cc_code.memory  # package
    import cc_code.memory._manager
    import cc_code.session

    monkeypatch.setattr(cc_code.config, "CC_CODE_DIR", sandbox, raising=False)
    monkeypatch.setattr(cc_code.context_manager, "CC_CODE_DIR", sandbox, raising=False)
    monkeypatch.setattr(cc_code.context_manager._persistence, "CC_CODE_DIR", sandbox, raising=False)
    monkeypatch.setattr(cc_code.memory, "CC_CODE_DIR", sandbox, raising=False)
    monkeypatch.setattr(cc_code.memory._manager, "CC_CODE_DIR", sandbox, raising=False)
    monkeypatch.setattr(cc_code.session, "CC_CODE_DIR", sandbox, raising=False)
    monkeypatch.setattr(cc_code.session, "SESSIONS_DIR", sandbox / "sessions", raising=False)

    return sandbox


@pytest.fixture
def memory_manager(tmp_path):
    """Create a MemoryManager with temporary paths."""
    from cc_code.memory import MemoryManager
    return MemoryManager(project_root=tmp_path)


@pytest.fixture
def memory_with_entries(memory_manager):
    """Create a MemoryManager pre-populated with test entries."""
    from cc_code.memory import MemoryScope
    entries = [
        ("project", "architecture", "Uses FastAPI for REST API backend", ["api", "fastapi"]),
        ("project", "code-pattern", "All functions use snake_case naming", ["convention", "naming"]),
        ("project", "testing", "Tests use pytest with fixtures", ["test", "pytest"]),
        ("user", "preference", "Always respond in Chinese", ["language", "chinese"]),
        ("local", "decision", "Use SQLite for development database", ["database", "sqlite"]),
    ]
    for scope, category, content, tags in entries:
        memory_manager.add_entry(MemoryScope(scope), category, content, tags)
    return memory_manager


@pytest.fixture
def mock_memory_search():
    """Mock search function for testing prompt injection."""
    def mock_search(query, scope=None, limit=20, min_relevance=0.1):
        from cc_code.memory import MemoryEntry, MemoryScope
        return [
            MemoryEntry(id="test-1", scope=MemoryScope.PROJECT, category="test", content=f"Mock result for: {query}"),
        ]
    return mock_search


@pytest.fixture
def temp_workspace(tmp_path):
    """Create a temporary workspace with basic structure."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "src").mkdir()
    (workspace / "tests").mkdir()
    (workspace / "src" / "main.py").write_text("# Main file\n")
    return str(workspace)
