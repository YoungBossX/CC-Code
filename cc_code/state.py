"""Zustand-style state management for CC-Coder Python.

Provides a simple, predictable state container with:
- Immutable updates via updater functions
- Subscriber notifications on state changes
- Type-safe generic store
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Generic, TypeVar

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class Store(Generic[T]):
    """Zustand-style state management.
    
    Provides predictable state updates with subscriber notifications.
    Inspired by Claude Code's Zustand store implementation.
    """
    
    def __init__(
        self,
        initial_state: T,
        on_change: Callable[[T, T], None] | None = None,
    ):
        """Initialize store with initial state.
        
        Args:
            initial_state: Initial state value
            on_change: Optional callback invoked on state changes
        """
        self._state = initial_state
        self._listeners: list[Callable[[], None]] = []
        self._on_change = on_change
        self._update_count = 0
        self._lock = threading.Lock()

    def get_state(self) -> T:
        """Get current state."""
        return self._state

    def set_state(self, updater: Callable[[T], T]) -> None:
        """Update state using an updater function.

        The updater MUST return a new state object (e.g. via
        dataclasses.replace) — in-place mutation defeats the `is prev`
        change detection below and silently skips all subscribers.

        Args:
            updater: Function that takes current state and returns new state
        """
        with self._lock:
            prev = self._state
            next_state = updater(prev)

            if next_state is prev:
                return

            self._state = next_state
            self._update_count += 1
            listeners_snapshot = list(self._listeners)
            on_change = self._on_change

        if on_change:
            try:
                on_change(next_state, prev)
            except Exception:
                pass

        for listener in listeners_snapshot:
            try:
                listener()
            except Exception:
                pass
    
    def subscribe(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Subscribe to state changes.

        Args:
            listener: Callback invoked on state changes

        Returns:
            Unsubscribe function
        """
        with self._lock:
            self._listeners.append(listener)

        def unsubscribe():
            with self._lock:
                if listener in self._listeners:
                    self._listeners.remove(listener)

        return unsubscribe
    
    @property
    def update_count(self) -> int:
        """Number of state updates."""
        return self._update_count
    
    @property
    def subscriber_count(self) -> int:
        """Number of active subscribers."""
        return len(self._listeners)


# ---------------------------------------------------------------------------
# AppState
# ---------------------------------------------------------------------------

@dataclass
class AppState:
    """Global application state.
    
    Inspired by Claude Code's AppState type.
    """
    # Session info
    session_id: str = ""
    workspace: str = ""
    model: str = "unknown"
    
    # Context tracking
    message_count: int = 0
    tool_call_count: int = 0
    token_usage: int = 0
    context_window_size: int = 128_000
    context_usage_percentage: float = 0.0
    
    # Cost tracking
    total_cost_usd: float = 0.0
    api_calls: int = 0
    api_errors: int = 0
    
    # Task tracking
    active_tasks: int = 0
    completed_tasks: int = 0
    
    # UI state
    is_busy: bool = False
    active_tool: str | None = None
    status_message: str = ""
    
    # Feature flags
    verbose: bool = False
    skills_enabled: bool = True
    mcp_enabled: bool = True
    
    # Timestamps
    created_at: float = field(default_factory=time.time)
    last_updated: float = field(default_factory=time.time)
    
    # Custom metadata
    metadata: dict[str, Any] = field(default_factory=dict)
    
    def update_timestamp(self) -> None:
        """Update the last_updated timestamp."""
        self.last_updated = time.time()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def create_app_store(
    initial: dict[str, Any] | None = None,
    on_change: Callable[[AppState, AppState], None] | None = None,
) -> Store[AppState]:
    """Create a new AppState store.
    
    Args:
        initial: Optional initial state overrides
        on_change: Optional change callback
    
    Returns:
        Store[AppState] instance
    """
    state = AppState()
    if initial:
        for key, value in initial.items():
            if hasattr(state, key):
                setattr(state, key, value)
    
    return Store(state, on_change)


def format_app_state_summary(state: AppState) -> str:
    """Format app state as a human-readable summary.
    
    Args:
        state: Current AppState
    
    Returns:
        Formatted summary string
    """
    lines = [
        "Application State",
        "=" * 50,
        "",
        "Session:",
        f"  ID: {state.session_id[:8] if state.session_id else 'new'}",
        f"  Model: {state.model}",
        f"  Workspace: {state.workspace}",
        "",
        "Context:",
        f"  Messages: {state.message_count}",
        f"  Tool calls: {state.tool_call_count}",
        f"  Tokens: {state.token_usage:,} / {state.context_window_size:,} "
        f"({state.context_usage_percentage:.1f}%)",
        "",
        "Cost:",
        f"  Total: ${state.total_cost_usd:.4f}",
        f"  API calls: {state.api_calls}",
        f"  API errors: {state.api_errors}",
        "",
        "Tasks:",
        f"  Active: {state.active_tasks}",
        f"  Completed: {state.completed_tasks}",
        "",
        "Status:",
        f"  Busy: {'Yes' if state.is_busy else 'No'}",
        f"  Active tool: {state.active_tool or 'none'}",
        f"  Message: {state.status_message or 'ready'}",
    ]
    
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# State updaters (helper functions)
# ---------------------------------------------------------------------------

# Updaters return a NEW AppState (via dataclasses.replace) so that
# Store.set_state can detect the change via `next_state is prev` and
# fire subscribers. In-place mutation breaks that contract.

def update_message_count(count: int) -> Callable[[AppState], AppState]:
    def updater(state: AppState) -> AppState:
        return replace(state, message_count=count, last_updated=time.time())
    return updater


def increment_tool_calls() -> Callable[[AppState], AppState]:
    def updater(state: AppState) -> AppState:
        return replace(
            state,
            tool_call_count=state.tool_call_count + 1,
            last_updated=time.time(),
        )
    return updater


def update_context_usage(
    tokens: int,
    window_size: int | None = None,
) -> Callable[[AppState], AppState]:
    def updater(state: AppState) -> AppState:
        next_window = window_size if window_size is not None else state.context_window_size
        percentage = (tokens / next_window * 100) if next_window > 0 else 0.0
        return replace(
            state,
            token_usage=tokens,
            context_window_size=next_window,
            context_usage_percentage=percentage,
            last_updated=time.time(),
        )
    return updater


def add_cost(cost_usd: float) -> Callable[[AppState], AppState]:
    def updater(state: AppState) -> AppState:
        return replace(
            state,
            total_cost_usd=state.total_cost_usd + cost_usd,
            api_calls=state.api_calls + 1,
            last_updated=time.time(),
        )
    return updater


def record_api_error() -> Callable[[AppState], AppState]:
    def updater(state: AppState) -> AppState:
        return replace(
            state,
            api_errors=state.api_errors + 1,
            api_calls=state.api_calls + 1,
            last_updated=time.time(),
        )
    return updater


def set_busy(tool_name: str | None = None) -> Callable[[AppState], AppState]:
    def updater(state: AppState) -> AppState:
        return replace(
            state,
            is_busy=True,
            active_tool=tool_name,
            status_message=f"Running {tool_name}..." if tool_name else "Working...",
            last_updated=time.time(),
        )
    return updater


def set_idle() -> Callable[[AppState], AppState]:
    def updater(state: AppState) -> AppState:
        return replace(
            state,
            is_busy=False,
            active_tool=None,
            status_message="Ready",
            last_updated=time.time(),
        )
    return updater


# ---------------------------------------------------------------------------
# Global store singleton (merged from state_integration.py)
# ---------------------------------------------------------------------------

_global_store: Store[AppState] | None = None


def get_global_store() -> Store[AppState]:
    """Get or create the global store instance."""
    global _global_store
    if _global_store is None:
        _global_store = create_app_store()
    return _global_store


def set_global_store(store: Store[AppState]) -> None:
    """Set the global store instance."""
    global _global_store
    _global_store = store


def handle_state_command() -> str:
    """Handle /state slash command."""
    return format_app_state_summary(get_global_store().get_state())
