# CC-Coder

CC-Coder is a standalone Python terminal coding assistant for local development workflows.

## What It Does

- terminal-first coding workflows
- tool calling and agent loop execution
- TUI-based interactive experience
- session persistence and recovery
- permission-gated local execution
- MCP integration

## Quick Start

```bash
pip install -e ".[dev]"
cc-coder --install
```

Run directly from source:

```bash
python -m cc_code.main
```

If you want a mock-only session for smoke testing:

```bash
set CC_CODE_MODEL_MODE=mock
python -m cc_code.main
```

## Configuration

Configure your model in `~/.cc-code/settings.json`:

```json
{
  "model": "claude-sonnet-4-20250514",
  "env": {
    "ANTHROPIC_BASE_URL": "https://api.anthropic.com",
    "ANTHROPIC_AUTH_TOKEN": "your-token-here"
  }
}
```

## Development

```bash
pip install -e ".[dev]"
pytest
```

## Notes

The Python package name remains `cc_code` internally, but the project branding and launchers are now CC-Coder.
