"""Public data types and protocol aliases for the MCP client."""

from __future__ import annotations

from dataclasses import dataclass


# JSON-RPC framing flavor: either "content-length" headers (LSP-style)
# or one-JSON-per-line. The MCP client tries both, in that order, and
# auto-detects from the first frame the server emits.
JsonRpcProtocol = str


@dataclass(slots=True)
class McpServerSummary:
    """Status snapshot for one configured MCP server."""
    name: str
    command: str
    status: str
    toolCount: int
    error: str | None = None
    protocol: str | None = None
    resourceCount: int | None = None
    promptCount: int | None = None
