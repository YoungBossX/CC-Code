"""MCP (Model Context Protocol) integration.

Public surface (everything callers were importing pre-split):

- ``StdioMcpClient`` — the lazy stdio JSON-RPC client
- ``create_mcp_backed_tools`` — factory turning configs into agent tools
- ``McpServerSummary`` — status snapshot for a configured server

Internal modules are prefixed with ``_`` (``_helpers``, ``_client``,
``_registry``, ``_types``); reach for the package import surface, not
the submodules.
"""

from cc_code.mcp._client import StdioMcpClient
from cc_code.mcp._registry import create_mcp_backed_tools
from cc_code.mcp._types import JsonRpcProtocol, McpServerSummary

__all__ = [
    "StdioMcpClient",
    "create_mcp_backed_tools",
    "McpServerSummary",
    "JsonRpcProtocol",
]
