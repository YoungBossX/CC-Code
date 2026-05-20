"""Security validators and result formatters for MCP messages.

`_validate_mcp_command` + `_validate_mcp_args` are the defense layer
against MCP server configs trying to launch shells or smuggle shell
metacharacters. The formatters turn MCP's varied response shapes (tool
result, resource read, prompt fetch) into a `ToolResult`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from cc_code.tooling import ToolResult


# Shell metacharacters that must not appear in MCP server argv. Rejecting
# these stops a config from smuggling `; rm -rf /` through args.
DANGEROUS_SHELL_CHARS = set('|&;`$(){}<>\n\r')

# Cap on a single JSON-RPC payload so a misbehaving server can't OOM us.
MAX_MCP_PAYLOAD_BYTES = 50 * 1024 * 1024  # 50 MB

# Allowlist of binary names that may launch MCP servers when given by
# bare name (no absolute path). Absolute paths must still land in a
# standard system dir or in this list — see `_validate_mcp_command`.
ALLOWED_COMMANDS = {
    'node', 'npm', 'npx', 'python', 'python3', 'pip', 'pip3',
    'uv', 'deno', 'bun', 'cargo', 'go', 'java', 'javac',
    'ruby', 'gem', 'dotnet', 'curl', 'wget',
}


def _sanitize_tool_segment(value: str) -> str:
    """Normalize a server or tool name into a safe tool-name segment."""
    normalized = "".join(
        char.lower() if char.isalnum() or char in {"_", "-"} else "_"
        for char in value
    )
    normalized = normalized.strip("_")
    return normalized or "tool"


def _validate_mcp_command(command: str) -> None:
    """Validate that an MCP server command is safe to launch.

    Rejects path-traversal characters, dangerous shells (cmd / powershell /
    command.com), and any non-allowlisted bare command. Absolute paths
    must live in a recognized system directory OR have a basename in the
    allowlist.
    """
    normalized = Path(command).resolve().as_posix()

    if '..' in normalized or '~' in normalized:
        raise RuntimeError("Invalid MCP command: contains path traversal characters")

    base_command = Path(command).name.lower()
    if base_command.endswith('.exe'):
        base_command = base_command[:-4]

    if Path(command).is_absolute():
        home_posix = str(Path.home().as_posix())
        allowed_system_dirs = [
            '/usr/bin', '/usr/local/bin', '/usr/local/sbin', '/usr/sbin', '/opt',
            # macOS Homebrew
            '/opt/homebrew/bin', '/opt/homebrew/sbin',
            '/usr/local/Cellar',
            # Linux extras
            '/snap/bin',
            '/home/linuxbrew/.linuxbrew/bin',
            # User-level tool directories
            f'{home_posix}/.local/bin',
            f'{home_posix}/.cargo/bin',
            f'{home_posix}/.nvm',
        ]
        if os.name == 'nt':
            allowed_system_dirs.extend([
                'C:\\Program Files',
                'C:\\Program Files (x86)',
                'C:\\Windows\\System32',
            ])

        is_in_allowed_dir = any(
            normalized.lower().startswith(d.lower()) for d in allowed_system_dirs
        )

        if not is_in_allowed_dir and base_command not in ALLOWED_COMMANDS:
            raise RuntimeError(
                f'MCP command "{command}" is not in the allowed list. '
                f"Use a whitelisted command or place the executable in a standard system directory."
            )

        dangerous_shells = ['cmd.exe', 'command.com', 'powershell.exe', 'pwsh.exe']
        if any(normalized.lower().endswith(d) for d in dangerous_shells):
            raise RuntimeError(
                f'MCP command "{command}" is a dangerous system shell. '
                f"Direct execution of shells is not allowed for security reasons."
            )
        return

    if base_command not in ALLOWED_COMMANDS:
        raise RuntimeError(
            f'MCP command "{command}" is not in the allowed list. '
            f"Allowed commands: {', '.join(sorted(ALLOWED_COMMANDS))}. "
            f"Use absolute paths for custom commands."
        )


def _validate_mcp_args(args: list[str]) -> None:
    """Reject MCP argv that contains shell metacharacters."""
    for arg in args:
        for char in arg:
            if char in DANGEROUS_SHELL_CHARS:
                raise RuntimeError(
                    f"Invalid MCP argument: contains dangerous shell character '{char}'. "
                    f"MCP server arguments cannot contain shell metacharacters for security reasons."
                )


def _normalize_input_schema(schema: dict[str, Any] | None) -> dict[str, Any]:
    """Return the schema as-is, or a permissive object schema if missing."""
    return schema if isinstance(schema, dict) else {"type": "object", "additionalProperties": True}


def _format_content_block(block: Any) -> str:
    """Format one MCP `content` block. Text blocks are passed through; others
    are JSON-dumped."""
    if not isinstance(block, dict):
        return json.dumps(block, indent=2, ensure_ascii=False)
    if block.get("type") == "text" and "text" in block:
        return str(block["text"])
    return json.dumps(block, indent=2, ensure_ascii=False)


def _format_tool_call_result(result: Any) -> ToolResult:
    """Convert an MCP `tools/call` response to a `ToolResult`."""
    if not isinstance(result, dict):
        return ToolResult(ok=True, output=json.dumps(result, indent=2, ensure_ascii=False))
    parts: list[str] = []
    content = result.get("content")
    if isinstance(content, list) and content:
        parts.append("\n\n".join(_format_content_block(block) for block in content))
    if "structuredContent" in result:
        parts.append("STRUCTURED_CONTENT:\n" + json.dumps(result["structuredContent"], indent=2, ensure_ascii=False))
    if not parts:
        parts.append(json.dumps(result, indent=2, ensure_ascii=False))
    return ToolResult(ok=not bool(result.get("isError")), output="\n\n".join(parts).strip())


def _format_read_resource_result(result: Any) -> ToolResult:
    """Convert an MCP `resources/read` response to a `ToolResult`."""
    if not isinstance(result, dict):
        return ToolResult(ok=False, output=json.dumps(result, indent=2, ensure_ascii=False))
    contents = result.get("contents", [])
    if not contents:
        return ToolResult(ok=True, output="No resource contents returned.")
    rendered = []
    for item in contents:
        header_lines = [f"URI: {item.get('uri', '(unknown)')}"]
        if item.get("mimeType"):
            header_lines.append(f"MIME: {item['mimeType']}")
        header = "\n".join(header_lines) + "\n\n"
        if isinstance(item.get("text"), str):
            rendered.append(header + item["text"])
        elif isinstance(item.get("blob"), str):
            rendered.append(header + "BLOB:\n" + item["blob"])
        else:
            rendered.append(header + json.dumps(item, indent=2, ensure_ascii=False))
    return ToolResult(ok=True, output="\n\n".join(rendered))


def _format_prompt_result(result: Any) -> ToolResult:
    """Convert an MCP `prompts/get` response to a `ToolResult`."""
    if not isinstance(result, dict):
        return ToolResult(ok=False, output=json.dumps(result, indent=2, ensure_ascii=False))
    header = f"DESCRIPTION: {result['description']}\n\n" if result.get("description") else ""
    body_parts = []
    for message in result.get("messages", []):
        role = message.get("role", "unknown")
        content = message.get("content")
        if isinstance(content, str):
            rendered = content
        elif isinstance(content, list):
            rendered = "\n".join(
                str(part["text"]) if isinstance(part, dict) and "text" in part else json.dumps(part, indent=2, ensure_ascii=False)
                for part in content
            )
        else:
            rendered = json.dumps(content, indent=2, ensure_ascii=False)
        body_parts.append(f"[{role}]\n{rendered}")
    output = (header + "\n\n".join(body_parts)).strip()
    return ToolResult(ok=True, output=output or json.dumps(result, indent=2, ensure_ascii=False))
