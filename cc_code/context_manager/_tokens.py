"""Token estimation and context-window constants.

Pure functions, no I/O. `estimate_tokens` is called once per message on
every turn — the LRU dict at module scope is the hot path.
"""

from __future__ import annotations

import json
import re
from typing import Any


# Default context window sizes (tokens)
DEFAULT_CONTEXT_WINDOWS = {
    # Anthropic
    "claude-sonnet-4-20250514": 200_000,
    "claude-opus-4-20250514": 200_000,
    "claude-haiku-3-20240307": 100_000,
    # OpenAI
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    "o1": 200_000,
    "o1-mini": 128_000,
    "o3-mini": 200_000,
    # OpenRouter popular models
    "openrouter/auto": 200_000,
    "anthropic/claude-sonnet-4": 200_000,
    "anthropic/claude-opus-4": 200_000,
    "openai/gpt-4o": 128_000,
    "openai/gpt-4o-mini": 128_000,
    "google/gemini-2.5-pro": 1_000_000,
    "google/gemini-2.5-flash": 1_000_000,
    "meta-llama/llama-4-maverick": 1_000_000,
    "deepseek/deepseek-r1": 128_000,
    "deepseek/deepseek-chat": 128_000,
    "qwen/qwen3-235b-a22b": 128_000,
    "minimax/minimax-m1": 1_000_000,
    "default": 128_000,  # Fallback
}

# Auto-compaction threshold (95% of context window)
AUTOCOMPACT_THRESHOLD = 0.95

# Estimated tokens per character (rough average for English/Code)
CHARS_PER_TOKEN = 4.0

# Minimum messages to keep after compaction
MIN_MESSAGES_TO_KEEP = 10

# System prompt is always kept (counts as 1 message)
SYSTEM_PROMPT_RESERVED = 1


# Precompiled regex for fast CJK detection (covers CJK Unified Ideographs,
# Hiragana, Katakana, and Hangul). Tokenizers count these denser than ASCII.
_CJK_PATTERN = re.compile(r'[一-鿿぀-ゟ゠-ヿ가-힯]')

# Module-level dict acting as a bounded cache: `estimate_tokens` gets called
# every turn for every message; deterministic same-text → same-count.
_token_cache: dict[Any, int] = {}
_TOKEN_CACHE_MAX = 1024


def estimate_tokens(text: str) -> int:
    """Rough token estimate that handles mixed Chinese/English.

    - Roman/code: ~4 chars/token
    - CJK: ~1.5 chars/token
    - Mixed: per-character classification then averaging

    Cached: same string returns the same count without re-scanning.
    Cache key is the string itself for short text, hash for long text.
    """
    if not text:
        return 0

    cache_key = text if len(text) < 256 else hash(text)
    if cache_key in _token_cache:
        return _token_cache[cache_key]

    cjk_count = len(_CJK_PATTERN.findall(text))
    ascii_chars = len(text) - cjk_count

    result = max(1, int(cjk_count / 1.5 + ascii_chars / 4.0))

    if len(_token_cache) < _TOKEN_CACHE_MAX:
        _token_cache[cache_key] = result

    return result


def estimate_message_tokens(message: dict[str, Any]) -> int:
    """Estimate tokens for a single message."""
    tokens = 0

    role = message.get("role", "")
    if role == "system":
        tokens += 3
    elif role == "user":
        tokens += 4
    elif role == "assistant":
        tokens += 3
    elif role == "assistant_tool_call":
        tokens += 7
    elif role == "tool_result":
        tokens += 6
    elif role == "assistant_progress":
        tokens += 3

    content = message.get("content", "")
    if isinstance(content, str):
        tokens += estimate_tokens(content)

    if "input" in message:
        input_str = (
            json.dumps(message["input"])
            if isinstance(message["input"], dict)
            else str(message["input"])
        )
        tokens += estimate_tokens(input_str)

    return tokens


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate total tokens for a list of messages."""
    return sum(estimate_message_tokens(msg) for msg in messages)
