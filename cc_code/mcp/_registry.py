"""Factory that turns the project's MCP server configs into agent tools.

For each configured server we create one ``StdioMcpClient`` (lazily
connected) plus one ``ToolDefinition`` per discovered MCP tool, named
``mcp__<server>__<tool>``. Resources and prompts get aggregated into
generic ``list_mcp_resources`` / ``read_mcp_resource`` /
``list_mcp_prompts`` / ``get_mcp_prompt`` tools so the model can browse
them by server name.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from cc_code.mcp._client import StdioMcpClient
from cc_code.mcp._helpers import _normalize_input_schema, _sanitize_tool_segment
from cc_code.mcp._types import McpServerSummary
from cc_code.tooling import ToolDefinition, ToolResult


def create_mcp_backed_tools(*, cwd: str, mcp_servers: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Build the MCP layer for one session.

    Returns ``{"tools": [...], "servers": [...summary dicts...], "dispose": fn}``.
    The dispose function closes every client process; call it at shutdown.

    Discovery happens at construction time but failures are non-fatal:
    a server that can't start now becomes "error"-status and will be
    retried the next time something calls a tool on it.
    """
    clients: list[StdioMcpClient] = []
    tools: list[ToolDefinition] = []
    servers: list[dict[str, Any]] = []
    resource_index: dict[str, dict[str, Any]] = {}
    prompt_index: dict[str, dict[str, Any]] = {}

    for server_name, config in mcp_servers.items():
        if config.get("enabled") is False:
            servers.append(asdict(McpServerSummary(
                name=server_name,
                command=config.get("command", ""),
                status="disabled",
                toolCount=0,
                protocol=config.get("protocol"),
            )))
            continue

        client = StdioMcpClient(server_name, config, cwd)
        clients.append(client)

        # Register server with "pending" status — will be connected lazily.
        servers.append(asdict(McpServerSummary(
            name=server_name,
            command=config.get("command", ""),
            status="pending",
            toolCount=0,
            protocol=config.get("protocol"),
        )))

        # Try eager discovery so the model sees tool descriptors immediately;
        # if it fails we leave the server in "error" status and retry on first
        # use via the lazy client.
        try:
            descriptors = client.list_tools()
            try:
                resources = client.list_resources()
            except Exception:  # noqa: BLE001
                resources = []
            try:
                prompts = client.list_prompts()
            except Exception:  # noqa: BLE001
                prompts = []

            for resource in resources:
                resource_index[f"{server_name}:{resource.get('uri')}"] = {
                    "serverName": server_name,
                    "resource": resource,
                }
            for prompt in prompts:
                prompt_index[f"{server_name}:{prompt.get('name')}"] = {
                    "serverName": server_name,
                    "prompt": prompt,
                }

            for descriptor in descriptors:
                wrapped_name = (
                    f"mcp__{_sanitize_tool_segment(server_name)}"
                    f"__{_sanitize_tool_segment(str(descriptor.get('name', 'tool')))}"
                )
                descriptor_name = str(descriptor.get("name", "tool"))
                input_schema = _normalize_input_schema(descriptor.get("inputSchema"))

                def _validator(value: Any) -> Any:
                    return value

                def _run(input_data: Any, _context, *, _client=client, _descriptor_name=descriptor_name):
                    return _client.call_tool(_descriptor_name, input_data)

                tools.append(ToolDefinition(
                    name=wrapped_name,
                    description=str(
                        descriptor.get("description")
                        or f"Call MCP tool {descriptor_name} from server {server_name}."
                    ),
                    input_schema=input_schema,
                    validator=_validator,
                    run=_run,
                ))

            # Update server status to connected
            for i, s in enumerate(servers):
                if s["name"] == server_name:
                    servers[i] = asdict(McpServerSummary(
                        name=server_name,
                        command=config.get("command", ""),
                        status="connected",
                        toolCount=len(descriptors),
                        protocol=client.protocol,
                        resourceCount=len(resources),
                        promptCount=len(prompts),
                    ))
                    break
        except Exception as error:  # noqa: BLE001
            # Lazy init: don't fail — server will be retried on first tool call.
            for i, s in enumerate(servers):
                if s["name"] == server_name:
                    servers[i] = asdict(McpServerSummary(
                        name=server_name,
                        command=config.get("command", ""),
                        status="error",
                        toolCount=0,
                        error=str(error)[:200],
                        protocol=config.get("protocol"),
                    ))
                    break

    if resource_index:
        tools.append(ToolDefinition(
            name="list_mcp_resources",
            description="List available MCP resources exposed by connected MCP servers.",
            input_schema={"type": "object", "properties": {"server": {"type": "string"}}},
            validator=lambda value: {"server": value.get("server")} if isinstance(value, dict) else {"server": None},
            run=lambda input_data, _context: ToolResult(
                ok=True,
                output="\n".join(
                    f"{entry['serverName']}: {entry['resource'].get('uri')}"
                    + (f" ({entry['resource'].get('name')})" if entry["resource"].get("name") else "")
                    + (f" - {entry['resource'].get('description')}" if entry["resource"].get("description") else "")
                    for entry in resource_index.values()
                    if not input_data.get("server") or entry["serverName"] == input_data["server"]
                )
                or "No MCP resources available.",
            ),
        ))

        def _read_resource(input_data: dict, _context) -> ToolResult:
            client = next((item for item in clients if item.server_name == input_data["server"]), None)
            if client is None:
                return ToolResult(ok=False, output=f"Unknown MCP server: {input_data['server']}")
            return client.read_resource(input_data["uri"])

        tools.append(ToolDefinition(
            name="read_mcp_resource",
            description="Read a specific MCP resource by server and URI.",
            input_schema={
                "type": "object",
                "properties": {"server": {"type": "string"}, "uri": {"type": "string"}},
                "required": ["server", "uri"],
            },
            validator=lambda value: value,
            run=_read_resource,
        ))

    if prompt_index:
        tools.append(ToolDefinition(
            name="list_mcp_prompts",
            description="List available MCP prompts exposed by connected MCP servers.",
            input_schema={"type": "object", "properties": {"server": {"type": "string"}}},
            validator=lambda value: {"server": value.get("server")} if isinstance(value, dict) else {"server": None},
            run=lambda input_data, _context: ToolResult(
                ok=True,
                output="\n".join(
                    f"{entry['serverName']}: {entry['prompt'].get('name')}"
                    + (
                        " args=["
                        + ", ".join(
                            f"{arg.get('name')}{'*' if arg.get('required') else ''}"
                            for arg in entry["prompt"].get("arguments", [])
                        )
                        + "]"
                        if entry["prompt"].get("arguments")
                        else ""
                    )
                    + (f" - {entry['prompt'].get('description')}" if entry["prompt"].get("description") else "")
                    for entry in prompt_index.values()
                    if not input_data.get("server") or entry["serverName"] == input_data["server"]
                )
                or "No MCP prompts available.",
            ),
        ))

        def _get_prompt(input_data: dict, _context) -> ToolResult:
            client = next((item for item in clients if item.server_name == input_data["server"]), None)
            if client is None:
                return ToolResult(ok=False, output=f"Unknown MCP server: {input_data['server']}")
            return client.get_prompt(input_data["name"], input_data.get("arguments"))

        tools.append(ToolDefinition(
            name="get_mcp_prompt",
            description="Fetch a rendered MCP prompt by server, prompt name, and optional arguments.",
            input_schema={
                "type": "object",
                "properties": {"server": {"type": "string"}, "name": {"type": "string"}, "arguments": {"type": "object"}},
                "required": ["server", "name"],
            },
            validator=lambda value: value,
            run=_get_prompt,
        ))

    return {
        "tools": tools,
        "servers": servers,
        "dispose": lambda: [client.close() for client in clients],
    }
