from __future__ import annotations

import concurrent.futures
import inspect
from typing import Any, Callable

from cc_code.context_manager import ContextManager, estimate_message_tokens
from cc_code.logging_config import get_logger
from cc_code.permissions import PermissionManager
from cc_code.state import Store, AppState, increment_tool_calls, set_busy, set_idle
from cc_code.tooling import ToolContext, ToolRegistry, ToolResult
from cc_code.types import AgentStep, ChatMessage, ModelAdapter

# Hooks integration
from cc_code.hooks import HookEvent, fire_hook_sync

# Intelligence integration
from cc_code.agent_metrics import AgentMetricsCollector
from cc_code.agent_intelligence import ErrorClassifier, NudgeGenerator, ToolScheduler

logger = get_logger("agent_loop")

# 甯搁噺锛氶伩鍏嶉噸澶嶇殑鎻愮ず鏂囨湰
NUDGE_CONTINUE = (
    "Continue immediately from your <progress> update with concrete tool calls, "
    "code changes, or an explicit <final> answer only if the task is complete."
)

NUDGE_AFTER_TOOL_RESULT = (
    "Continue from your progress update. You have already used tools in this turn, "
    "so treat plain status text as progress, not a final answer. Respond with the "
    "next concrete tool call, code change, or an explicit <final> answer only if "
    "the task is truly complete."
)

NUDGE_AFTER_EMPTY_RESPONSE = (
    "Your last response was empty after recent tool results. Continue immediately "
    "by trying the next concrete step, adapting to any tool errors, or giving an "
    "explicit <final> answer only if the task is complete."
)

NUDGE_AFTER_EMPTY_NO_TOOLS = (
    "Your last response was empty. Continue immediately with concrete tool calls, "
    "code changes, or an explicit <final> answer only if the task is complete."
)

RESUME_AFTER_PAUSE = (
    "Resume from the previous pause and continue immediately with the next concrete "
    "tool call, code change, or an explicit <final> answer only if the task is complete."
)

RESUME_AFTER_MAX_TOKENS = (
    "Your previous response hit max_tokens during thinking before producing the next "
    "actionable step. Resume immediately and continue with the next concrete tool call, "
    "code change, or an explicit <final> answer only if the task is complete."
)


def _is_empty_assistant_response(content: str) -> bool:
    return len(content.strip()) == 0


def _execute_single_tool(
    call: dict,
    tools: ToolRegistry,
    cwd: str,
    permissions: Any | None,
    runtime: dict | None,
    store: Any | None,
    step: int,
    *,
    metrics_collector: AgentMetricsCollector | None = None,
    fire_ui_callbacks: bool = True,
    on_tool_start: Callable[[str, dict], None] | None = None,
    on_tool_result: Callable[[str, str, bool], None] | None = None,
) -> ToolResult:
    """Execute one tool call with the full lifecycle: pre-hook → metrics start
    → store-busy → execute → store-idle → metrics end → post-hook.

    Used uniformly by the serial and concurrent paths in run_agent_turn. The
    pre/post hooks, metrics, and store updates are thread-safe (Store has its
    own lock; AgentMetricsCollector.begin_tool/finish_tool are handle-based).

    UI callbacks (on_tool_start / on_tool_result) update transcript state that
    is NOT thread-safe — pass `fire_ui_callbacks=False` from worker threads
    and let the caller fire them on the agent thread once results arrive.

    Any unexpected crash in this pipeline is caught and converted to an error
    ToolResult so a single bad tool can't kill the whole turn.
    """
    tool_name = call["toolName"]
    tool_input = call["input"]
    metrics_record = None

    try:
        # Pre-tool hook (fires before any side effects; semantically a hook
        # that wants to deny could raise to abort — surfaces as error result).
        fire_hook_sync(
            HookEvent.PRE_TOOL_USE,
            tool_name=tool_name,
            tool_input=tool_input,
            step=step,
        )

        if fire_ui_callbacks and on_tool_start:
            on_tool_start(tool_name, tool_input)

        if store:
            store.set_state(set_busy(tool_name))

        if metrics_collector:
            metrics_record = metrics_collector.begin_tool(tool_name)

        # Execute the tool (ToolRegistry.execute already has its own safety net)
        result = tools.execute(
            tool_name,
            tool_input,
            ToolContext(cwd=cwd, permissions=permissions, _runtime=runtime),
        )

        if metrics_collector and metrics_record is not None:
            metrics_collector.finish_tool(
                metrics_record,
                success=result.ok,
                error="" if result.ok else result.output,
            )

        if store:
            store.set_state(increment_tool_calls())
            store.set_state(set_idle())

        # Post-tool hook always fires after execution.
        fire_hook_sync(
            HookEvent.POST_TOOL_USE,
            tool_name=tool_name,
            tool_output=result.output,
            is_error=not result.ok,
            step=step,
        )

        if fire_ui_callbacks and on_tool_result:
            on_tool_result(tool_name, result.output, not result.ok)

        return result

    except (KeyboardInterrupt, SystemExit):
        raise
    except Exception as exc:  # noqa: BLE001
        import traceback
        tb_excerpt = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)[-3:]).strip()
        error_type = type(exc).__name__
        logger.error("Tool execution pipeline crashed (%s): %s", error_type, exc)

        # Finalize metrics even on crash, so success rates stay accurate.
        if metrics_collector and metrics_record is not None:
            try:
                metrics_collector.finish_tool(
                    metrics_record, success=False, error=f"{error_type}: {exc}"
                )
            except Exception:
                pass

        if store:
            try:
                store.set_state(set_idle())
            except Exception:
                pass

        return ToolResult(
            ok=False,
            output=f"[{error_type}] Tool execution pipeline crashed: {exc}\n"
                   f"Traceback:\n{tb_excerpt}"
        )


def _format_diagnostics(stop_reason: str | None, block_types: list[str] | None, ignored_block_types: list[str] | None) -> str:
    parts: list[str] = []
    if stop_reason:
        parts.append(f"stop_reason={stop_reason}")
    if block_types:
        parts.append(f"blocks={','.join(block_types)}")
    if ignored_block_types:
        parts.append(f"ignored={','.join(ignored_block_types)}")
    return f" Diagnostics: {'; '.join(parts)}." if parts else ""


def _is_recoverable_thinking_stop(*, is_empty: bool, stop_reason: str | None, ignored_block_types: list[str] | None) -> bool:
    if not is_empty:
        return False
    if stop_reason not in {"pause_turn", "max_tokens"}:
        return False
    return "thinking" in (ignored_block_types or [])


def _should_treat_assistant_as_progress(*, kind: str | None, content: str, saw_tool_result: bool) -> bool:
    if kind == "progress":
        return True
    if kind == "final":
        return False
    if not saw_tool_result:
        return False
    return False


def _model_next(
    model: ModelAdapter,
    messages: list[ChatMessage],
    *,
    on_stream_chunk: Callable[[str], None] | None,
    store: Store[AppState] | None,
) -> AgentStep:
    """Call provider adapters with store support while preserving test doubles."""
    if store is None:
        return model.next(messages, on_stream_chunk=on_stream_chunk)

    try:
        signature = inspect.signature(model.next)
    except (TypeError, ValueError):
        return model.next(messages, on_stream_chunk=on_stream_chunk, store=store)

    supports_store = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD or parameter.name == "store"
        for parameter in signature.parameters.values()
    )
    if supports_store:
        return model.next(messages, on_stream_chunk=on_stream_chunk, store=store)
    return model.next(messages, on_stream_chunk=on_stream_chunk)


def run_agent_turn(
    *,
    model: ModelAdapter,
    tools: ToolRegistry,
    messages: list[ChatMessage],
    cwd: str,
    permissions: PermissionManager | None = None,
    store: Store[AppState] | None = None,
    max_steps: int = 50,
    on_tool_start: Callable[[str, dict], None] | None = None,
    on_tool_result: Callable[[str, str, bool], None] | None = None,
    on_assistant_message: Callable[[str], None] | None = None,
    on_progress_message: Callable[[str], None] | None = None,
    on_assistant_stream_chunk: Callable[[str], None] | None = None,
    context_manager: ContextManager | None = None,
    runtime: dict | None = None,
    metrics_collector: AgentMetricsCollector | None = None,
) -> list[ChatMessage]:
    current_messages = list(messages)
    saw_tool_result = False
    empty_response_retry_count = 0
    recoverable_thinking_retry_count = 0
    tool_error_count = 0
    step = 0

    tool_scheduler = ToolScheduler(metrics_collector=metrics_collector)

    def _finish_turn() -> None:
        if metrics_collector:
            total_tokens = sum(
                estimate_message_tokens(m) for m in current_messages
            ) if context_manager else 0
            metrics_collector.end_turn(total_tokens=total_tokens)

    # 妫€鏌ヤ笂涓嬫枃鐘舵€?
    if context_manager:
        context_manager.messages = current_messages
        stats = context_manager.get_stats()
        logger.info("Context: %d tokens (%.0f%%), %d messages", 
                   stats.total_tokens, stats.usage_percentage, stats.messages_count)
        
        # 濡傛灉闇€瑕佸帇缂╋紝鑷姩鎵ц
        if context_manager.should_auto_compact():
            logger.warning("Context near limit, auto-compacting...")
            current_messages = context_manager.compact_messages()
            if on_assistant_message:
                on_assistant_message(context_manager.get_context_summary())

    try:
        while max_steps is None or step < max_steps:
            step += 1

            # Hook: agent turn started
            fire_hook_sync(HookEvent.AGENT_START, step=step, cwd=cwd)

            if metrics_collector:
                metrics_collector.start_turn(step)

            next_step: AgentStep
            try:
                next_step = _model_next(
                    model,
                    current_messages,
                    on_stream_chunk=on_assistant_stream_chunk,
                    store=store,
                )
            except KeyboardInterrupt:
                raise  # Let Ctrl-C propagate
            except ConnectionError as error:
                fallback = f"Network error (connection failed or dropped): {error}"
                logger.error("Model API connection error: %s", error)
                if on_assistant_message:
                    on_assistant_message(fallback)
                current_messages.append({"role": "assistant", "content": fallback})
                _finish_turn()
                return current_messages
            except TimeoutError as error:
                fallback = f"Model API timeout: {error}"
                logger.error("Model API timeout: %s", error)
                if on_assistant_message:
                    on_assistant_message(fallback)
                current_messages.append({"role": "assistant", "content": fallback})
                _finish_turn()
                return current_messages
            except Exception as error:
                # Catch-all for unexpected errors (rate limit, auth, server 5xx, etc.)
                error_type = type(error).__name__
                fallback = f"Model API error ({error_type}): {error}"
                logger.error("Model API error (%s): %s", error_type, error)
                if on_assistant_message:
                    on_assistant_message(fallback)
                current_messages.append({"role": "assistant", "content": fallback})
                _finish_turn()
                return current_messages

            if next_step.type == "assistant":
                is_empty = _is_empty_assistant_response(next_step.content)
                if not is_empty and _should_treat_assistant_as_progress(
                    kind=getattr(next_step, 'kind', None),
                    content=next_step.content,
                    saw_tool_result=saw_tool_result,
                ):
                    if on_progress_message:
                        on_progress_message(next_step.content)
                    current_messages.append({"role": "assistant_progress", "content": next_step.content})
                    current_messages.append(
                        {
                            "role": "user",
                            "content": (
                                NUDGE_AFTER_TOOL_RESULT
                                if saw_tool_result and getattr(next_step, 'kind', None) != "progress"
                                else NUDGE_CONTINUE
                            ),
                        }
                    )
                    continue

                diagnostics = next_step.diagnostics

                if _is_recoverable_thinking_stop(
                    is_empty=is_empty,
                    stop_reason=diagnostics.stopReason if diagnostics else None,
                    ignored_block_types=diagnostics.ignoredBlockTypes if diagnostics else None,
                ) and recoverable_thinking_retry_count < 3:
                    recoverable_thinking_retry_count += 1
                    stop_reason = diagnostics.stopReason if diagnostics else None
                    progress_content = (
                        "Model hit max_tokens during thinking; requesting the next step."
                        if stop_reason == "max_tokens"
                        else "Model returned pause_turn; requesting the next step."
                    )
                    if on_progress_message:
                        on_progress_message(progress_content)
                    current_messages.append({"role": "assistant_progress", "content": progress_content})
                    current_messages.append(
                        {
                            "role": "user",
                            "content": (
                                RESUME_AFTER_PAUSE
                                if stop_reason == "pause_turn"
                                else RESUME_AFTER_MAX_TOKENS
                            ),
                        }
                    )
                    continue

                if is_empty and empty_response_retry_count < 2:
                    empty_response_retry_count += 1
                    current_messages.append(
                        {
                            "role": "user",
                            "content": (
                                NUDGE_AFTER_EMPTY_RESPONSE
                                if saw_tool_result
                                else NUDGE_AFTER_EMPTY_NO_TOOLS
                            ),
                        }
                    )
                    continue

                if is_empty:
                    diagnostics_suffix = _format_diagnostics(
                        diagnostics.stopReason if diagnostics else None,
                        diagnostics.blockTypes if diagnostics else None,
                        diagnostics.ignoredBlockTypes if diagnostics else None,
                    )
                    if saw_tool_result:
                        fallback = (
                            f"Model returned an empty response after tool execution and the turn was stopped. There were {tool_error_count} tool error(s); retry, adjust the command, or choose a different approach.{diagnostics_suffix}"
                            if tool_error_count > 0
                            else f"Model returned an empty response after tool execution and the turn was stopped. Retry or ask the model to continue the remaining steps.{diagnostics_suffix}"
                        )
                    else:
                        fallback = f"Model returned an empty response and the turn was stopped.{diagnostics_suffix}"
                    if on_assistant_message:
                        on_assistant_message(fallback)
                    current_messages.append({"role": "assistant", "content": fallback})
                    return current_messages

                if on_assistant_message:
                    on_assistant_message(next_step.content)
                current_messages.append({"role": "assistant", "content": next_step.content})
                _finish_turn()
                return current_messages

            if next_step.content:
                role = "assistant_progress" if next_step.contentKind == "progress" else "assistant"
                if role == "assistant_progress":
                    if on_progress_message:
                        on_progress_message(next_step.content)
                    current_messages.append({"role": role, "content": next_step.content})
                    current_messages.append(
                        {
                            "role": "user",
                            "content": NUDGE_CONTINUE,
                        }
                    )
                else:
                    if on_assistant_message:
                        on_assistant_message(next_step.content)
                    current_messages.append({"role": role, "content": next_step.content})

            if not next_step.calls and next_step.content and next_step.contentKind != "progress":
                _finish_turn()
                return current_messages

            # --- Tool execution ---
            # _execute_single_tool now owns the full lifecycle (pre-hook,
            # metrics, store, exec, store-idle, post-hook). Concurrent
            # workers skip UI callbacks (transcript state is not thread-safe);
            # the agent thread replays them after results return, in original
            # call order.
            calls = next_step.calls
            _results: list[tuple[dict, ToolResult]] = []

            if len(calls) <= 1:
                call = calls[0]
                result = _execute_single_tool(
                    call, tools, cwd, permissions, runtime, store, step,
                    metrics_collector=metrics_collector,
                    fire_ui_callbacks=True,
                    on_tool_start=on_tool_start,
                    on_tool_result=on_tool_result,
                )
                _results.append((call, result))
            else:
                concurrent_calls, serial_calls = tool_scheduler.schedule_calls(calls, tools)

                # Phase 1: concurrent-safe tools in parallel
                if concurrent_calls:
                    max_workers = tool_scheduler.get_recommended_max_workers(concurrent_calls)
                    with concurrent.futures.ThreadPoolExecutor(
                        max_workers=max_workers,
                        thread_name_prefix="mc-tool",
                    ) as pool:
                        future_to_call = {
                            pool.submit(
                                _execute_single_tool,
                                call, tools, cwd, permissions, runtime, store, step,
                                metrics_collector=metrics_collector,
                                fire_ui_callbacks=False,
                                on_tool_start=None,
                                on_tool_result=None,
                            ): call
                            for call in concurrent_calls
                        }
                        for future in concurrent.futures.as_completed(future_to_call):
                            call = future_to_call[future]
                            try:
                                result = future.result()
                            except Exception as exc:
                                result = ToolResult(ok=False, output=f"Concurrent execution error: {exc}")
                            _results.append((call, result))

                # Phase 2: serial tools in original order
                if serial_calls:
                    for call in serial_calls:
                        result = _execute_single_tool(
                            call, tools, cwd, permissions, runtime, store, step,
                            metrics_collector=metrics_collector,
                            fire_ui_callbacks=True,
                            on_tool_start=on_tool_start,
                            on_tool_result=on_tool_result,
                        )
                        _results.append((call, result))
                        if result.awaitUser:
                            break

            # Preserve original call order for message construction.
            call_order = {call["id"]: idx for idx, call in enumerate(calls)}
            _results.sort(key=lambda pair: call_order.get(pair[0]["id"], 999))

            for call, result in _results:
                # Replay UI callbacks for concurrent-executed tools on the
                # agent thread (transcript state is not thread-safe).
                tool_def = tools.find(call["toolName"])
                is_concurrent = tool_def and tool_def.is_concurrency_safe and len(calls) > 1

                if is_concurrent:
                    if on_tool_start:
                        on_tool_start(call["toolName"], call["input"])
                    if on_tool_result:
                        on_tool_result(call["toolName"], result.output, not result.ok)

                saw_tool_result = True
                if not result.ok:
                    tool_error_count += 1
                    # Use ErrorClassifier for intelligent error handling
                    classified = ErrorClassifier.classify(result.output, tool_name=call["toolName"])
                    nudge = NudgeGenerator.generate(classified, retry_count=tool_error_count)
                    # Append nudge to tool result content for model context
                    result_output = result.output + "\n\n[System note: " + nudge + "]"
                else:
                    result_output = result.output

                # Record conflicts between concurrent tools if both failed
                if not result.ok and len(calls) > 1:
                    for other_call, other_result in _results:
                        if other_call["id"] == call["id"]:
                            continue
                        if not other_result.ok:
                            tool_scheduler.record_conflict(call["toolName"], other_call["toolName"])

                current_messages.append(
                    {
                        "role": "assistant_tool_call",
                        "toolUseId": call["id"],
                        "toolName": call["toolName"],
                        "input": call["input"],
                    }
                )
                current_messages.append(
                    {
                        "role": "tool_result",
                        "toolUseId": call["id"],
                        "toolName": call["toolName"],
                        "content": result_output,
                        "isError": not result.ok,
                    }
                )
                if result.awaitUser:
                    if on_assistant_message:
                        on_assistant_message(result_output)
                    current_messages.append({"role": "assistant", "content": result_output})
                    if metrics_collector:
                        metrics_collector.end_turn(total_tokens=0)
                    return current_messages

            # Tool execution completed for this step; ask the model for the next turn
            # instead of falling through to the max-step fallback.
            if metrics_collector:
                total_tokens = sum(
                    estimate_message_tokens(m) for m in current_messages
                ) if context_manager else 0
                metrics_collector.end_turn(total_tokens=total_tokens)
            continue

        fallback = "Reached the maximum tool step limit for this turn."
        if on_assistant_message:
            on_assistant_message(fallback)
        current_messages.append({"role": "assistant", "content": fallback})
        return current_messages
    finally:
        # Hook: agent turn stopped (always fires, even on exceptions)
        fire_hook_sync(HookEvent.AGENT_STOP, step=step, tool_errors=tool_error_count)
