"""Context window management for LLM conversations.

Public surface (everything callers were importing pre-split):

- Token estimation: ``estimate_tokens``, ``estimate_message_tokens``,
  ``estimate_messages_tokens``
- Tracking: ``ContextStats``, ``ContextManager``
- Persistence: ``save_context_state``, ``load_context_state``,
  ``clear_context_state``
- Constants: ``DEFAULT_CONTEXT_WINDOWS``, ``AUTOCOMPACT_THRESHOLD``,
  ``MIN_MESSAGES_TO_KEEP``

Internal modules are prefixed with ``_`` (``_tokens``, ``_summary``,
``_manager``, ``_persistence``); reach for the package import surface,
not the submodules.
"""

from cc_code.context_manager._manager import ContextManager, ContextStats
from cc_code.context_manager._persistence import (
    clear_context_state,
    load_context_state,
    save_context_state,
)
from cc_code.context_manager._tokens import (
    AUTOCOMPACT_THRESHOLD,
    CHARS_PER_TOKEN,
    DEFAULT_CONTEXT_WINDOWS,
    MIN_MESSAGES_TO_KEEP,
    SYSTEM_PROMPT_RESERVED,
    estimate_message_tokens,
    estimate_messages_tokens,
    estimate_tokens,
)

__all__ = [
    # Token estimation
    "estimate_tokens",
    "estimate_message_tokens",
    "estimate_messages_tokens",
    # Tracking
    "ContextStats",
    "ContextManager",
    # Persistence
    "save_context_state",
    "load_context_state",
    "clear_context_state",
    # Constants
    "DEFAULT_CONTEXT_WINDOWS",
    "AUTOCOMPACT_THRESHOLD",
    "MIN_MESSAGES_TO_KEEP",
    "CHARS_PER_TOKEN",
    "SYSTEM_PROMPT_RESERVED",
]
