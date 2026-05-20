"""Stdio-based MCP client with lazy startup and request multiplexing.

Spawning the server is deferred until the first ``list_tools`` /
``call_tool`` / ``read_resource`` call — many configured servers never
get used in a given session, so we don't pay the startup cost up front.

JSON-RPC framing is auto-detected: the server can emit either
``Content-Length: N\\r\\n\\r\\n{...}`` LSP-style frames or single-line
JSON. Inbound messages run in a stdout-reader thread; the request/response
correlation is done with a per-id ``Queue``.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path
from queue import Empty, Queue
from typing import Any

from cc_code.config import sanitize_subprocess_env
from cc_code.mcp import _helpers as _helpers_module
from cc_code.mcp._helpers import (
    _format_prompt_result,
    _format_read_resource_result,
    _format_tool_call_result,
    _validate_mcp_args,
    _validate_mcp_command,
)
from cc_code.mcp._types import JsonRpcProtocol
from cc_code.tooling import ToolResult


class StdioMcpClient:
    """MCP client with lazy initialization.

    The server process is not started until the first request is made,
    reducing startup time and resource usage when MCP servers are configured
    but not immediately needed.
    """
    def __init__(self, server_name: str, config: dict[str, Any], cwd: str) -> None:
        self.server_name = server_name
        self.config = config
        self.cwd = cwd
        self.process: subprocess.Popen[bytes] | None = None
        self.protocol: JsonRpcProtocol | None = None
        self.next_id = 1
        self._pending: dict[int, Queue[Any]] = {}
        self._lock = threading.Lock()
        self.stderr_lines: list[str] = []
        self._stderr_thread: threading.Thread | None = None
        self._stdout_thread: threading.Thread | None = None
        # Lazy init state
        self._started = False
        self._start_error: str | None = None
        self._tools_cache: list[dict[str, Any]] | None = None
        self._resources_cache: list[dict[str, Any]] | None = None
        self._prompts_cache: list[dict[str, Any]] | None = None

    @property
    def is_started(self) -> bool:
        return self._started

    @property
    def start_error(self) -> str | None:
        return self._start_error

    def _protocol_candidates(self) -> list[JsonRpcProtocol]:
        configured = self.config.get("protocol")
        if configured == "content-length":
            return ["content-length"]
        if configured == "newline-json":
            return ["newline-json"]
        return ["content-length", "newline-json"]

    def start(self) -> None:
        """Start the MCP server process (idempotent).

        If already started, returns immediately.
        If previously failed, retries the connection.
        """
        if self._started:
            return

        if self._start_error is not None and self.process is None:
            self._start_error = None

        last_error: Exception | None = None
        for protocol in self._protocol_candidates():
            try:
                self._spawn_process()
                self.protocol = protocol
                self.request(
                    "initialize",
                    {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "cc-code", "version": "0.1.0"},
                    },
                    timeout_seconds=2.0,
                )
                self.notify("notifications/initialized", {})
                self._started = True
                self._start_error = None
                return
            except Exception as error:  # noqa: BLE001
                last_error = error
                self.close()

        self._start_error = str(last_error or f'Failed to connect MCP server "{self.server_name}".')
        raise RuntimeError(self._start_error)

    def _ensure_started(self) -> None:
        """Ensure the server is started before making a request."""
        if self._started and not self._is_process_alive():
            self.close()
        if not self._started:
            self.start()

    def _is_process_alive(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def _spawn_process(self) -> None:
        command = str(self.config.get("command", "")).strip()
        if not command:
            raise RuntimeError(f'MCP server "{self.server_name}" has no command configured.')

        _validate_mcp_command(command)
        _validate_mcp_args(list(self.config.get("args", []) or []))

        process_cwd = Path(self.cwd)
        if self.config.get("cwd"):
            process_cwd = (process_cwd / str(self.config["cwd"])).resolve()
        env = sanitize_subprocess_env()
        for key, value in dict(self.config.get("env", {}) or {}).items():
            env[str(key)] = str(value)

        popen_kwargs: dict = {}
        if os.name == "nt":
            # Suppress console window for the child on Windows
            CREATE_NO_WINDOW = 0x08000000
            popen_kwargs["creationflags"] = CREATE_NO_WINDOW
        try:
            self.process = subprocess.Popen(  # noqa: S603
                [command, *list(self.config.get("args", []) or [])],
                cwd=str(process_cwd),
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                **popen_kwargs,
            )
        except FileNotFoundError:
            raise RuntimeError(f"Command not found: {command}. Install it first and ensure it is available in PATH.") from None

        self.stderr_lines = []
        with self._lock:
            self._pending = {}
        self._stderr_thread = threading.Thread(target=self._consume_stderr, daemon=True)
        self._stderr_thread.start()

    def _consume_stderr(self) -> None:
        assert self.process is not None and self.process.stderr is not None
        for line in self.process.stderr:
            try:
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    self.stderr_lines.append(text)
                    self.stderr_lines = self.stderr_lines[-8:]
            except Exception:
                continue

    def _ensure_stdout_thread(self) -> None:
        if self._stdout_thread is not None:
            return
        self._stdout_thread = threading.Thread(target=self._consume_stdout, daemon=True)
        self._stdout_thread.start()

    def _consume_stdout(self) -> None:
        assert self.process is not None and self.process.stdout is not None
        try:
            while True:
                line_bytes = self.process.stdout.readline()
                if not line_bytes:
                    break

                try:
                    line = line_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    continue

                stripped = line.strip()
                if not stripped:
                    continue

                if len(line_bytes) > _helpers_module.MAX_MCP_PAYLOAD_BYTES:
                    self.stderr_lines.append(
                        f"MCP payload too large: {len(line_bytes)} bytes (limit {_helpers_module.MAX_MCP_PAYLOAD_BYTES})"
                    )
                    continue

                # Auto-detect protocol if not determined yet
                if self.protocol is None:
                    if line.lower().startswith("content-length:"):
                        self.protocol = "content-length"
                    else:
                        self.protocol = "newline-json"

                if self.protocol == "newline-json":
                    try:
                        self._handle_message(json.loads(stripped))
                    except json.JSONDecodeError:
                        continue
                else:
                    # Content-length protocol: 'line' is the first header line
                    header_lines = [line.rstrip("\r\n")]
                    while True:
                        next_line_bytes = self.process.stdout.readline()
                        if not next_line_bytes:
                            return
                        try:
                            next_line = next_line_bytes.decode("utf-8")
                        except UnicodeDecodeError:
                            return
                        h_stripped = next_line.rstrip("\r\n")
                        if h_stripped == "":
                            break
                        header_lines.append(h_stripped)

                    content_length = 0
                    for header in header_lines:
                        if header.lower().startswith("content-length:"):
                            try:
                                content_length = int(header.split(":", 1)[1].strip())
                            except ValueError:
                                pass
                            break

                    if content_length > _helpers_module.MAX_MCP_PAYLOAD_BYTES:
                        self.stderr_lines.append(
                            f"MCP payload too large: {content_length} bytes (limit {_helpers_module.MAX_MCP_PAYLOAD_BYTES})"
                        )
                        continue

                    if content_length > 0:
                        body_bytes = self.process.stdout.read(content_length)
                        if len(body_bytes) < content_length:
                            return
                        try:
                            self._handle_message(json.loads(body_bytes.decode("utf-8")))
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            pass
        finally:
            # Notify pending requests when process exits so callers don't hang.
            if self.process:
                exit_code = self.process.poll()
                error_msg = {"error": {"code": -1, "message": f"MCP server process exited (code={exit_code})"}}
                with self._lock:
                    for req_id, q in list(self._pending.items()):
                        q.put(error_msg)
                    self._pending.clear()

    def _handle_message(self, message: dict[str, Any]) -> None:
        message_id = message.get("id")
        if not isinstance(message_id, int):
            return
        with self._lock:
            queue = self._pending.pop(message_id, None)
            if queue is not None:
                queue.put(message)

    def send(self, message: dict[str, Any]) -> None:
        if self.process is None or self.process.stdin is None:
            raise RuntimeError(f'MCP server "{self.server_name}" is not running.')

        payload_bytes = json.dumps(message, ensure_ascii=False).encode("utf-8")

        if self.protocol == "newline-json":
            self.process.stdin.write(payload_bytes + b"\n")
            self.process.stdin.flush()
            self._ensure_stdout_thread()
            return

        header = f"Content-Length: {len(payload_bytes)}\r\n\r\n".encode("utf-8")
        self.process.stdin.write(header + payload_bytes)
        self.process.stdin.flush()
        self._ensure_stdout_thread()

    def notify(self, method: str, params: Any) -> None:
        self.send({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method: str, params: Any, timeout_seconds: float = 5.0) -> Any:
        message_id = self.next_id
        self.next_id += 1
        response_queue: Queue[Any] = Queue(maxsize=1)
        with self._lock:
            self._pending[message_id] = response_queue
        self.send({"jsonrpc": "2.0", "id": message_id, "method": method, "params": params})
        try:
            message = response_queue.get(timeout=timeout_seconds)
        except Empty as error:
            with self._lock:
                self._pending.pop(message_id, None)
            stderr = "\n".join(self.stderr_lines)
            raise RuntimeError(
                f"MCP {self.server_name}: request timed out for {method}" + (f"\n{stderr}" if stderr else "")
            ) from error
        if message.get("error"):
            details = message["error"].get("data")
            suffix = f"\n{json.dumps(details, indent=2, ensure_ascii=False)}" if details else ""
            raise RuntimeError(f"MCP {self.server_name}: {message['error']['message']}{suffix}")
        return message.get("result")

    def list_tools(self) -> list[dict[str, Any]]:
        """List tools with caching. Starts server lazily if not started."""
        if self._tools_cache is not None:
            return self._tools_cache
        self._ensure_started()
        result = self.request("tools/list", {})
        self._tools_cache = list(result.get("tools", []) if isinstance(result, dict) else [])
        return self._tools_cache

    def list_resources(self) -> list[dict[str, Any]]:
        """List resources with caching. Starts server lazily if not started."""
        if self._resources_cache is not None:
            return self._resources_cache
        self._ensure_started()
        result = self.request("resources/list", {}, timeout_seconds=3.0)
        self._resources_cache = list(result.get("resources", []) if isinstance(result, dict) else [])
        return self._resources_cache

    def read_resource(self, uri: str) -> ToolResult:
        self._ensure_started()
        return _format_read_resource_result(self.request("resources/read", {"uri": uri}, timeout_seconds=5.0))

    def list_prompts(self) -> list[dict[str, Any]]:
        """List prompts with caching. Starts server lazily if not started."""
        if self._prompts_cache is not None:
            return self._prompts_cache
        self._ensure_started()
        result = self.request("prompts/list", {}, timeout_seconds=3.0)
        self._prompts_cache = list(result.get("prompts", []) if isinstance(result, dict) else [])
        return self._prompts_cache

    def get_prompt(self, name: str, args: dict[str, str] | None = None) -> ToolResult:
        self._ensure_started()
        return _format_prompt_result(
            self.request("prompts/get", {"name": name, "arguments": args or {}}, timeout_seconds=5.0)
        )

    def call_tool(self, name: str, input_data: Any) -> ToolResult:
        self._ensure_started()
        return _format_tool_call_result(self.request("tools/call", {"name": name, "arguments": input_data or {}}))

    def close(self) -> None:
        with self._lock:
            pending = list(self._pending.values())
            self._pending.clear()
            for queue in pending:
                queue.put({"error": {"message": f'MCP server "{self.server_name}" closed before completing the request.'}})

        if self.process is not None:
            try:
                # Cross-platform process termination
                if os.name == "nt":
                    # Windows: use taskkill to terminate the process tree
                    try:
                        subprocess.run(
                            ["taskkill", "/T", "/F", "/PID", str(self.process.pid)],
                            capture_output=True,
                            timeout=5,
                        )
                    except subprocess.TimeoutExpired:
                        try:
                            self.process.kill()
                        except OSError:
                            pass
                    except Exception:
                        try:
                            self.process.kill()
                        except OSError:
                            pass
                else:
                    # Unix: SIGTERM first, escalate to SIGKILL on timeout
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        try:
                            self.process.kill()
                        except OSError:
                            pass

                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
            except OSError:
                pass  # Process may already be gone
            finally:
                self.process = None

        self.protocol = None
        self._stdout_thread = None
        self._stderr_thread = None
        # Reset lazy init state
        self._started = False
        self._tools_cache = None
        self._resources_cache = None
        self._prompts_cache = None
