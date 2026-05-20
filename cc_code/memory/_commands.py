"""System-prompt injection and CLI formatting helpers."""

from __future__ import annotations

from cc_code.memory._manager import MemoryManager
from cc_code.memory._types import MemoryScope


def inject_memory_into_prompt(
    system_prompt: str,
    memory_manager: MemoryManager,
    max_tokens: int = 8000,
) -> str:
    """Inject memory context into system prompt."""
    memory_context = memory_manager.get_relevant_context(max_tokens=max_tokens)

    if not memory_context:
        return system_prompt

    return f"""{system_prompt}

## Project Memory & Context

The following information has been accumulated from previous sessions:

{memory_context}

Use this context to inform your decisions and follow established patterns."""


def format_memory_list(scope: MemoryScope | None = None, category: str | None = None) -> str:
    """Format memory entries for CLI display."""
    # Placeholder for CLI command formatting — call with a MemoryManager instance.
    return "Memory listing not available without MemoryManager instance."
