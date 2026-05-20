"""ContextManager: tracks token usage and runs auto-compaction.

Owns `messages` and the compaction state machine. Multi-level compaction
escalates progressively: first hit targets 70% of the window, second hit
50%, third hit 30%. Each level tries phases in order — drop progress
messages, truncate large tool results, compress tool call/result pairs into
inline summaries, then priority-based removal of the oldest low-priority
messages.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from cc_code.context_manager._summary import (
    _COMMAND_TOOLS,
    _EDIT_TOOLS,
    _READ_TOOLS,
    _SEARCH_TOOLS,
    _summarize_removed_messages,
)
from cc_code.context_manager._tokens import (
    AUTOCOMPACT_THRESHOLD,
    DEFAULT_CONTEXT_WINDOWS,
    MIN_MESSAGES_TO_KEEP,
    estimate_message_tokens,
    estimate_messages_tokens,
)


@dataclass
class ContextStats:
    """Current context window statistics."""
    total_tokens: int = 0
    context_window: int = 0
    usage_percentage: float = 0.0
    messages_count: int = 0
    system_tokens: int = 0
    conversation_tokens: int = 0
    tool_calls_count: int = 0
    is_near_limit: bool = False
    should_compact: bool = False


@dataclass(init=False)
class ContextManager:
    """Manages context window tracking and auto-compaction."""
    model: str = "default"
    context_window: int = 0
    messages: list[dict[str, Any]] = field(default_factory=list)
    compaction_history: list[dict[str, Any]] = field(default_factory=list)
    _token_cache: dict[int, int] = field(default_factory=dict, repr=False)  # id(msg) -> tokens

    # Multi-level compaction support
    _compaction_level: int = field(default_factory=lambda: 0)  # 0=none, 1=light, 2=medium, 3=deep

    # Multi-level compaction targets (relative to context window)
    _COMPACTION_LEVELS = [0.70, 0.50, 0.30]  # light / medium / deep

    def __init__(
        self,
        model: str = "default",
        context_window: int = 0,
        messages: list[dict[str, Any]] | None = None,
        compaction_history: list[dict[str, Any]] | None = None,
        _token_cache: dict[int, int] | None = None,
        _compaction_level: int = 0,
        **kwargs: Any,
    ):
        model_name = kwargs.pop("model_name", None)
        if kwargs:
            unexpected = ", ".join(sorted(kwargs))
            raise TypeError(f"Unexpected keyword arguments: {unexpected}")

        self.model = model_name or model
        self.context_window = context_window
        self.messages = list(messages) if messages is not None else []
        self.compaction_history = list(compaction_history) if compaction_history is not None else []
        self._token_cache = dict(_token_cache) if _token_cache is not None else {}
        self._compaction_level = _compaction_level

        if self.context_window == 0:
            self.context_window = DEFAULT_CONTEXT_WINDOWS.get(
                self.model, DEFAULT_CONTEXT_WINDOWS["default"]
            )

    def update_model(self, model: str) -> None:
        """Update model and adjust context window."""
        self.model = model
        self.context_window = DEFAULT_CONTEXT_WINDOWS.get(
            model, DEFAULT_CONTEXT_WINDOWS["default"]
        )

    def add_message(self, message: dict[str, Any]) -> None:
        """Add a message and update tracking."""
        self.messages.append(message)
        self._token_cache[id(message)] = estimate_message_tokens(message)

    def get_stats(self) -> ContextStats:
        """Calculate current context statistics."""
        if not self.messages:
            return ContextStats(context_window=self.context_window)

        system_tokens = 0
        conversation_tokens = 0
        tool_calls = 0

        for msg in self.messages:
            msg_tokens = self._token_cache.get(id(msg))
            if msg_tokens is None:
                msg_tokens = estimate_message_tokens(msg)
                self._token_cache[id(msg)] = msg_tokens
            if msg.get("role") == "system":
                system_tokens += msg_tokens
            else:
                conversation_tokens += msg_tokens

            if msg.get("role") == "assistant_tool_call":
                tool_calls += 1

        total_tokens = system_tokens + conversation_tokens
        usage_pct = (total_tokens / self.context_window * 100) if self.context_window > 0 else 0

        is_near_limit = usage_pct >= 80
        should_compact = usage_pct >= (AUTOCOMPACT_THRESHOLD * 100)

        return ContextStats(
            total_tokens=total_tokens,
            context_window=self.context_window,
            usage_percentage=usage_pct,
            messages_count=len(self.messages),
            system_tokens=system_tokens,
            conversation_tokens=conversation_tokens,
            tool_calls_count=tool_calls,
            is_near_limit=is_near_limit,
            should_compact=should_compact,
        )

    def should_auto_compact(self) -> bool:
        """Check if auto-compaction should trigger.

        Higher compaction level = more aggressive (lower threshold).
        """
        stats = self.get_stats()
        threshold = AUTOCOMPACT_THRESHOLD - (self._compaction_level * 0.10)
        threshold = max(0.60, threshold)
        return stats.usage_percentage >= (threshold * 100)

    def compact_messages(self) -> list[dict[str, Any]]:
        """Compact messages to fit within context window.

        Phases:
          1. Drop assistant_progress messages
          2. Truncate large tool_result content (tool-type aware)
          3. Compress tool_call+result pairs into inline summaries
          4. Priority-based removal (oldest, lowest-priority first)
        """
        if not self.should_auto_compact():
            return self.messages

        stats = self.get_stats()

        target_pct = self._COMPACTION_LEVELS[min(self._compaction_level, 2)]
        target_tokens = int(self.context_window * target_pct)

        system_messages = [m for m in self.messages if m.get("role") == "system"]
        other_messages = [m for m in self.messages if m.get("role") != "system"]

        # Phase 1: Remove progress messages
        filtered = [m for m in other_messages if m.get("role") != "assistant_progress"]

        current_tokens = estimate_messages_tokens(filtered)
        if current_tokens <= target_tokens:
            return self._finalize_compaction(
                system_messages, other_messages, filtered, stats, target_tokens
            )

        # Phase 2: Truncate large tool results (adaptive thresholds)
        _READ_TOOL_TRUNCATE = 1500
        _EDIT_TOOL_TRUNCATE = 3000
        _ERROR_TRUNCATE = 4000
        _DEFAULT_TRUNCATE = 2000

        for i, m in enumerate(filtered):
            if m.get("role") != "tool_result":
                continue
            content = m.get("content", "")
            if not content or len(content) <= _DEFAULT_TRUNCATE:
                continue

            tool_name = m.get("toolName", "")
            is_error = m.get("isError", False)

            if is_error:
                threshold = _ERROR_TRUNCATE
            elif tool_name in _EDIT_TOOLS:
                threshold = _EDIT_TOOL_TRUNCATE
            elif tool_name in _READ_TOOLS:
                threshold = _READ_TOOL_TRUNCATE
            else:
                threshold = _DEFAULT_TRUNCATE

            if len(content) <= threshold:
                continue

            content_lines = content.split("\n")
            keep_chars = threshold
            head_lines: list[str] = []
            tail_lines: list[str] = []
            head_chars = 0

            for line in content_lines:
                if head_chars + len(line) + 1 > keep_chars * 0.7:
                    break
                head_lines.append(line)
                head_chars += len(line) + 1

            tail_chars = 0
            for line in reversed(content_lines):
                if tail_chars + len(line) + 1 > keep_chars * 0.3:
                    break
                tail_lines.insert(0, line)
                tail_chars += len(line) + 1

            omitted = len(content_lines) - len(head_lines) - len(tail_lines)
            truncated_content = "\n".join(head_lines)
            if omitted > 0:
                truncated_content += f"\n... [{omitted} lines truncated for compaction] ...\n"
            truncated_content += "\n".join(tail_lines)

            filtered[i] = {**m, "content": truncated_content}

        current_tokens = estimate_messages_tokens(filtered)
        if current_tokens <= target_tokens:
            return self._finalize_compaction(
                system_messages, other_messages, filtered, stats, target_tokens
            )

        # Phase 3: Compress tool_call + result pairs into inline summaries
        compressed: list[dict[str, Any]] = []
        i = 0
        while i < len(filtered):
            msg = filtered[i]
            if (
                msg.get("role") == "assistant_tool_call"
                and i + 1 < len(filtered)
                and filtered[i + 1].get("role") == "tool_result"
            ):
                call_msg = msg
                result_msg = filtered[i + 1]
                summary = self._compress_tool_pair(call_msg, result_msg)
                compressed.append({"role": "assistant", "content": summary})
                i += 2
            else:
                compressed.append(msg)
                i += 1

        current_tokens = estimate_messages_tokens(compressed)
        if current_tokens <= target_tokens:
            return self._finalize_compaction(
                system_messages, other_messages, compressed, stats, target_tokens
            )

        # Phase 4: Priority-based removal (oldest, lowest priority first)
        PRIORITY = {
            "user": 0,
            "assistant": 1,
            "assistant_tool_call": 2,
            "tool_result": 3,
        }
        PROTECTED_RECENT = 6

        while estimate_messages_tokens(compressed) > target_tokens and len(compressed) > MIN_MESSAGES_TO_KEEP:
            removable_end = max(MIN_MESSAGES_TO_KEEP, len(compressed) - PROTECTED_RECENT)
            best_idx = None
            best_priority = -1

            for idx in range(removable_end):
                role = compressed[idx].get("role", "")
                priority = PRIORITY.get(role, 1)
                if priority > best_priority:
                    best_priority = priority
                    best_idx = idx

            if best_idx is None:
                break

            del compressed[best_idx]

        return self._finalize_compaction(
            system_messages, other_messages, compressed, stats, target_tokens
        )

    @staticmethod
    def _compress_tool_pair(call_msg: dict[str, Any], result_msg: dict[str, Any]) -> str:
        """Compress a tool_call + tool_result pair into a compact inline summary."""
        tool_name = call_msg.get("toolName", "unknown")
        inp = call_msg.get("input", {})
        result_content = result_msg.get("content", "")
        is_error = result_msg.get("isError", False)

        if is_error:
            error_text = result_content.strip()[:200].replace("\n", " ")
            return f"[Tool {tool_name} ERROR: {error_text}]"

        if tool_name in _EDIT_TOOLS:
            path = inp.get("path") or inp.get("filePath", "unknown")
            if tool_name == "multi_edit":
                edits = inp.get("edits", [])
                return f"[Edited {path}: {len(edits)} changes applied]"
            return f"[Edited {path}: ok]"

        if tool_name in _READ_TOOLS:
            path = inp.get("path") or inp.get("filePath", "")
            if path:
                line_count = result_content.count("\n") + 1
                return f"[Read {path}: {line_count} lines]"
            return f"[{tool_name}: completed]"

        if tool_name in _SEARCH_TOOLS:
            pattern = inp.get("pattern") or inp.get("query", "")
            match_lines = [l for l in result_content.split("\n") if l.strip() and not l.startswith("#")]
            return f"[Searched '{pattern[:50]}': {len(match_lines)} results]"

        if tool_name in _COMMAND_TOOLS:
            cmd = inp.get("command", "")
            cmd_name = cmd.split()[0] if cmd.split() else "command"
            exit_info = ""
            if "exit code" in result_content.lower():
                for line in result_content.split("\n"):
                    if "exit code" in line.lower():
                        exit_info = f" ({line.strip()[:50]})"
                        break
            return f"[Ran {cmd_name}{exit_info}]"

        brief = result_content.strip()[:100].replace("\n", " ")
        if brief:
            return f"[{tool_name}: {brief}]"
        return f"[{tool_name}: completed]"

    def _finalize_compaction(
        self,
        system_messages: list[dict[str, Any]],
        original_other: list[dict[str, Any]],
        filtered: list[dict[str, Any]],
        stats: ContextStats,
        target_tokens: int,
    ) -> list[dict[str, Any]]:
        """Build the final compacted message list with summary marker."""
        # Identify removed messages by value (some phases create new dicts).
        removed_messages = [m for m in original_other if m not in filtered]
        summary_text = _summarize_removed_messages(removed_messages)

        removed_count = len(original_other) - len(filtered)
        after_pct = estimate_messages_tokens(filtered) / self.context_window * 100 if self.context_window > 0 else 0

        compaction_marker = {
            "role": "system",
            "content": (
                f"[Context compacted at {time.strftime('%H:%M:%S')}. "
                f"{removed_count} messages removed. "
                f"Token usage: {stats.usage_percentage:.0f}% → {after_pct:.0f}%]\n"
                + (f"\nSummary of removed conversation:\n{summary_text}" if summary_text else "")
            ),
        }

        compacted = system_messages + [compaction_marker] + filtered

        # Record but do NOT mutate self.messages — callers compare pre/post.
        self.compaction_history.append({
            "timestamp": time.time(),
            "before_tokens": stats.total_tokens,
            "after_tokens": estimate_messages_tokens(compacted),
            "messages_removed": len(self.messages) - len(compacted),
            "compaction_level": self._compaction_level,
        })

        self._compaction_level = min(self._compaction_level + 1, 3)
        return compacted

    def get_context_summary(self) -> str:
        """Get a human-readable context usage summary."""
        stats = self.get_stats()

        if stats.messages_count == 0:
            return "Context: empty"

        status = "✓"
        if stats.is_near_limit:
            status = "⚠"
        if stats.should_compact:
            status = "🔴"

        return (
            f"Context: {status} {stats.usage_percentage:.0f}% "
            f"({stats.total_tokens:,}/{stats.context_window:,} tokens, "
            f"{stats.messages_count} msgs, {stats.tool_calls_count} tools)"
        )

    def format_context_details(self) -> str:
        """Get detailed context information for /context command."""
        stats = self.get_stats()

        lines = [
            "Context Window Usage",
            "=" * 50,
            f"Model: {self.model}",
            f"Context window: {stats.context_window:,} tokens",
            "",
            f"Total tokens: {stats.total_tokens:,}",
            f"Usage: {stats.usage_percentage:.1f}%",
            f"Messages: {stats.messages_count}",
            f"Tool calls: {stats.tool_calls_count}",
            "",
        ]

        if stats.should_compact:
            lines.append("⚠️  WARNING: Context is near capacity!")
            lines.append("Auto-compaction will trigger soon.")
            lines.append("")

        if self.compaction_history:
            lines.append("Compaction History:")
            for comp in self.compaction_history[-3:]:
                ts = time.strftime("%H:%M:%S", time.localtime(comp["timestamp"]))
                lines.append(
                    f"  {ts}: {comp['messages_removed']} messages removed, "
                    f"{comp['before_tokens']:,} → {comp['after_tokens']:,} tokens"
                )

        return "\n".join(lines)
