from __future__ import annotations

import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse
from typing import Any


CC_CODE_DIR = Path.home() / ".cc-code"
CC_CODE_SETTINGS_PATH = CC_CODE_DIR / "settings.json"
CC_CODE_HISTORY_PATH = CC_CODE_DIR / "history.json"
CC_CODE_PERMISSIONS_PATH = CC_CODE_DIR / "permissions.json"
CC_CODE_MCP_PATH = CC_CODE_DIR / "mcp.json"
CC_CODE_USER_PROFILE_PATH = CC_CODE_DIR / "USER.md"
CLAUDE_SETTINGS_PATH = Path.home() / ".claude" / "settings.json"

# 凭证类环境变量 — 不应传递给子进程
_CREDENTIAL_ENV_VARS: set[str] = {
    # LLM providers
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
    "OPENAI_API_KEY", "OPENROUTER_API_KEY", "CUSTOM_API_KEY",
    # Chat platform bots
    "TELEGRAM_BOT_TOKEN", "DISCORD_BOT_TOKEN",
    "SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_SIGNING_SECRET",
    # Cloud providers
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
    "AZURE_CLIENT_SECRET", "GOOGLE_APPLICATION_CREDENTIALS", "GCP_API_KEY",
    # VCS / CI / package registries
    "GITHUB_TOKEN", "GH_TOKEN", "GITHUB_PERSONAL_ACCESS_TOKEN",
    "GITLAB_TOKEN", "NPM_TOKEN", "PYPI_TOKEN", "HF_TOKEN",
    # Claude Code itself
    "CLAUDE_CODE_OAUTH_TOKEN",
    # CC-Coder gateway shared secret
    "CC_CODE_GATEWAY_TOKEN",
}

# 兜底：名字本身就表明是凭证的环境变量也一并清除。
# MCP 服务器若需要凭证，应在 mcp.json 的 env 中显式提供（_client.py 会叠加），
# 不依赖环境继承，因此此处可以放心激进清洗。
_CREDENTIAL_NAME_PATTERN = re.compile(
    r"(_API_KEY|_APIKEY|_TOKEN|_SECRET|_PASSWORD|_PASSWD|"
    r"_ACCESS_KEY|_PRIVATE_KEY|_CREDENTIALS)$",
    re.IGNORECASE,
)


def _is_credential_var(name: str) -> bool:
    return name in _CREDENTIAL_ENV_VARS or bool(_CREDENTIAL_NAME_PATTERN.search(name))


def sanitize_subprocess_env(env: dict[str, str] | None = None) -> dict[str, str]:
    """返回去除凭证变量后的环境变量副本，用于子进程。"""
    env = (env if env is not None else os.environ).copy()
    for key in [k for k in env if _is_credential_var(k)]:
        env.pop(key, None)
    return env


def project_user_profile_path(cwd: str | Path | None = None) -> Path:
    """Return the project-level USER.md path."""
    return Path(cwd or Path.cwd()) / ".cc-code" / "USER.md"

# 已知的合法模型名称（用于拼写检查提示）
KNOWN_MODELS = [
    "claude-sonnet-4-20250514",
    "claude-opus-4-20250514",
    "claude-haiku-3-20240307",
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4-turbo",
    "o1",
    "o1-mini",
    "o3-mini",
    # OpenRouter popular models
    "openrouter/auto",
    "anthropic/claude-sonnet-4",
    "anthropic/claude-opus-4",
    "openai/gpt-4o",
    "openai/gpt-4o-mini",
    "google/gemini-2.5-pro",
    "google/gemini-2.5-flash",
    "meta-llama/llama-4-maverick",
    "deepseek/deepseek-r1",
    "deepseek/deepseek-chat",
    "qwen/qwen3-235b-a22b",
    "minimax/minimax-m1",
]


def _suggest_model_name(typed: str) -> str:
    """根据输入建议最接近的合法模型名称"""
    if not typed:
        return ""
    
    # 简单的前缀匹配
    for model in KNOWN_MODELS:
        if model.startswith(typed.lower()):
            return model
    
    # 模糊匹配：包含输入字符的模型
    for model in KNOWN_MODELS:
        if typed.lower() in model:
            return model
    
    return ""


def project_mcp_path(cwd: str | Path | None = None) -> Path:
    return Path(cwd or Path.cwd()) / ".mcp.json"


def _read_json_file(file_path: Path) -> dict[str, Any]:
    if not file_path.exists():
        return {}
    return json.loads(file_path.read_text(encoding="utf-8"))


def read_settings_file(file_path: Path) -> dict[str, Any]:
    return _read_json_file(file_path)


def read_mcp_config_file(file_path: Path) -> dict[str, Any]:
    parsed = _read_json_file(file_path)
    if not isinstance(parsed, dict):
        return {}
    mcp_servers = parsed.get("mcpServers", {})
    return mcp_servers if isinstance(mcp_servers, dict) else {}


def merge_settings(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged_mcp = dict(base.get("mcpServers", {}))
    for name, server in override.get("mcpServers", {}).items():
        current = dict(merged_mcp.get(name, {}))
        next_server = dict(server)
        current.update(next_server)
        current["env"] = {
            **dict(merged_mcp.get(name, {}).get("env", {})),
            **dict(next_server.get("env", {})),
        }
        merged_mcp[name] = current

    return {
        **base,
        **override,
        "env": {
            **dict(base.get("env", {})),
            **dict(override.get("env", {})),
        },
        "mcpServers": merged_mcp,
    }


def load_effective_settings(cwd: str | Path | None = None) -> dict[str, Any]:
    claude_settings = read_settings_file(CLAUDE_SETTINGS_PATH)
    global_mcp = read_mcp_config_file(CC_CODE_MCP_PATH)
    project_mcp = read_mcp_config_file(project_mcp_path(cwd))
    cc_code_settings = read_settings_file(CC_CODE_SETTINGS_PATH)

    return merge_settings(
        merge_settings(
            merge_settings(claude_settings, {"mcpServers": global_mcp}),
            {"mcpServers": project_mcp},
        ),
        cc_code_settings,
    )


def save_cc_code_settings(updates: dict[str, Any]) -> None:
    CC_CODE_DIR.mkdir(parents=True, exist_ok=True)
    existing = read_settings_file(CC_CODE_SETTINGS_PATH)
    next_settings = merge_settings(existing, updates)
    CC_CODE_SETTINGS_PATH.write_text(
        json.dumps(next_settings, indent=2) + "\n",
        encoding="utf-8",
    )


def load_runtime_config(cwd: str | Path | None = None) -> dict[str, Any]:
    effective = load_effective_settings(cwd)
    env = {**dict(effective.get("env", {})), **os.environ}
    model = (
        os.environ.get("CC_CODE_MODEL")
        or effective.get("model")
        or str(env.get("ANTHROPIC_MODEL", "")).strip()
    )

    # --- Provider-specific base URLs ---
    # Anthropic
    base_url = str(env.get("ANTHROPIC_BASE_URL", "")).strip() or "https://api.anthropic.com"
    auth_token = str(env.get("ANTHROPIC_AUTH_TOKEN", "")).strip() or None
    api_key = str(env.get("ANTHROPIC_API_KEY", "")).strip() or None

    # OpenAI
    openai_base_url = (
        str(env.get("OPENAI_BASE_URL", "")).strip()
        or str(env.get("OPENAI_API_BASE", "")).strip()
        or effective.get("openaiBaseUrl", "")
        or "https://api.openai.com"
    )
    openai_api_key = str(env.get("OPENAI_API_KEY", "")).strip() or effective.get("openaiApiKey", "")

    # OpenRouter
    openrouter_base_url = (
        str(env.get("OPENROUTER_BASE_URL", "")).strip()
        or "https://openrouter.ai/api"
    )
    openrouter_api_key = str(env.get("OPENROUTER_API_KEY", "")).strip()

    # Custom endpoint
    custom_base_url = (
        str(env.get("CUSTOM_API_BASE_URL", "")).strip()
        or effective.get("customBaseUrl", "")
    )
    custom_api_key = (
        str(env.get("CUSTOM_API_KEY", "")).strip()
        or effective.get("customApiKey", "")
        or openai_api_key
    )

    raw_max_output_tokens = (
        os.environ.get("CC_CODE_MAX_OUTPUT_TOKENS")
        or effective.get("maxOutputTokens")
        or env.get("CC_CODE_MAX_OUTPUT_TOKENS")
    )
    max_output_tokens = None
    if raw_max_output_tokens is not None:
        try:
            parsed = int(raw_max_output_tokens)
            if parsed > 0:
                max_output_tokens = parsed
        except (TypeError, ValueError):
            max_output_tokens = None

    # Validate: at least one auth method must be available
    has_auth = any([
        auth_token, api_key, openai_api_key, openrouter_api_key, custom_api_key,
    ])
    if not model:
        raise RuntimeError("No model configured. Set ~/.cc-code/settings.json or ANTHROPIC_MODEL.")
    if not has_auth:
        raise RuntimeError(
            "No auth configured. Set one of: ANTHROPIC_API_KEY, OPENAI_API_KEY, "
            "OPENROUTER_API_KEY, or CUSTOM_API_KEY."
        )

    # --- User profile paths ---
    global_user_profile = CC_CODE_USER_PROFILE_PATH
    proj_user_profile = project_user_profile_path(cwd)

    # --- User preferences from settings (lightweight, not from USER.md) ---
    user_preferences = effective.get("userPreferences", {})
    response_language = (
        str(env.get("CC_CODE_LANGUAGE", "")).strip()
        or user_preferences.get("language", "")
    )
    response_verbosity = (
        str(env.get("CC_CODE_VERBOSITY", "")).strip()
        or user_preferences.get("verbosity", "")
    )

    return {
        "model": model,
        "baseUrl": base_url,
        "authToken": auth_token,
        "apiKey": api_key,
        "openaiBaseUrl": openai_base_url,
        "openaiApiKey": openai_api_key,
        "openrouterBaseUrl": openrouter_base_url,
        "openrouterApiKey": openrouter_api_key,
        "customBaseUrl": custom_base_url,
        "customApiKey": custom_api_key,
        "maxOutputTokens": max_output_tokens,
        "mcpServers": effective.get("mcpServers", {}),
        "globalUserProfilePath": str(global_user_profile),
        "projectUserProfilePath": str(proj_user_profile),
        "responseLanguage": response_language,
        "responseVerbosity": response_verbosity,
        "toolProfile": str(
            os.environ.get("CC_CODE_TOOL_PROFILE")
            or effective.get("toolProfile", "")
            or "core"
        ).strip().lower(),
        "sourceSummary": f"config: {CC_CODE_SETTINGS_PATH} > {CLAUDE_SETTINGS_PATH} > process.env",
    }


def _is_valid_http_url(value: str | None) -> bool:
    if not value:
        return False
    parsed = urlparse(str(value))
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def validate_provider_runtime(runtime: dict[str, Any]) -> list[str]:
    """Validate the auth/base-url required by the detected provider.

    A generic API key is not enough: if the selected model routes to OpenAI,
    OpenAI-compatible credentials must be present; likewise for Anthropic,
    OpenRouter, and custom endpoints.
    """
    from cc_code.model_registry import Provider, detect_provider

    model = str(runtime.get("model", "")).strip()
    provider = detect_provider(model, runtime)
    errors: list[str] = []

    if provider == Provider.OPENAI:
        if not runtime.get("openaiApiKey"):
            errors.append(
                "Provider is openai for this model, but OPENAI_API_KEY/openaiApiKey is not configured."
            )
        if not _is_valid_http_url(runtime.get("openaiBaseUrl")):
            errors.append("OpenAI base URL must be an http(s) URL.")
    elif provider == Provider.OPENROUTER:
        if not runtime.get("openrouterApiKey"):
            errors.append(
                "Provider is openrouter for this model, but OPENROUTER_API_KEY is not configured."
            )
        if not _is_valid_http_url(runtime.get("openrouterBaseUrl")):
            errors.append("OpenRouter base URL must be an http(s) URL.")
    elif provider == Provider.CUSTOM:
        if not runtime.get("customBaseUrl"):
            errors.append("Provider is custom, but CUSTOM_API_BASE_URL/customBaseUrl is not configured.")
        elif not _is_valid_http_url(runtime.get("customBaseUrl")):
            errors.append("Custom base URL must be an http(s) URL.")
        if not runtime.get("customApiKey"):
            errors.append("Provider is custom, but CUSTOM_API_KEY/customApiKey is not configured.")
    elif provider == Provider.ANTHROPIC:
        if not (runtime.get("apiKey") or runtime.get("authToken")):
            errors.append(
                "Provider is anthropic for this model, but ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN is not configured."
            )
        if not _is_valid_http_url(runtime.get("baseUrl")):
            errors.append("Anthropic base URL must be an http(s) URL.")

    return errors


def get_mcp_config_path(scope: str, cwd: str | Path | None = None) -> Path:
    return project_mcp_path(cwd) if scope == "project" else CC_CODE_MCP_PATH


def load_scoped_mcp_servers(scope: str, cwd: str | Path | None = None) -> dict[str, Any]:
    return read_mcp_config_file(get_mcp_config_path(scope, cwd))


def save_scoped_mcp_servers(scope: str, servers: dict[str, Any], cwd: str | Path | None = None) -> None:
    target = get_mcp_config_path(scope, cwd)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"mcpServers": servers}, indent=2) + "\n", encoding="utf-8")


def validate_config(cwd: str | Path | None = None) -> tuple[bool, list[str]]:
    """验证配置完整性，返回 (是否有效，错误列表)
    
    检查项：
    1. 模型名称是否配置
    2. API key 是否配置
    3. 模型名称拼写是否正确
    4. MCP 配置文件是否合法
    """
    errors: list[str] = []
    warnings: list[str] = []

    try:
        config = load_runtime_config(cwd)
        errors.extend(validate_provider_runtime(config))
        
        # 检查模型名称拼写
        model = config.get("model", "")
        if model and not any(model.lower() == km.lower() for km in KNOWN_MODELS):
            suggestion = _suggest_model_name(model)
            if suggestion:
                warnings.append(
                    f"Unknown model '{model}'. Did you mean '{suggestion}'?"
                )
            else:
                warnings.append(
                    f"Unknown model '{model}'. Known models: {', '.join(KNOWN_MODELS[:3])}..."
                )
        
        # 检查 MCP 配置
        mcp_servers = config.get("mcpServers", {})
        for name, server in mcp_servers.items():
            if not server.get("command"):
                errors.append(f"MCP server '{name}' has no command configured")
        
        return len(errors) == 0, errors + warnings
        
    except RuntimeError as e:
        error_msg = str(e)
        
        # 提供友好的错误消息
        if "No model configured" in error_msg:
            suggestion = _suggest_model_name(os.environ.get("CC_CODE_MODEL", ""))
            help_msg = (
                f"Error: {error_msg}\n\n"
                "How to fix:\n"
                "  1. Set model name: export ANTHROPIC_MODEL=claude-sonnet-4-20250514\n"
                "  2. Or edit ~/.cc-code/settings.json:\n"
                f'     {{"model": "claude-sonnet-4-20250514"}}\n'
            )
            if suggestion:
                help_msg += f"\n  Did you mean: {suggestion}?\n"
            help_msg += f"\n  Known models: {', '.join(KNOWN_MODELS[:3])}..."
            errors.append(help_msg)
            
        elif "No auth configured" in error_msg:
            help_msg = (
                f"Error: {error_msg}\n\n"
                "How to fix:\n"
                "  1. Anthropic:  export ANTHROPIC_API_KEY=sk-ant-...\n"
                "  2. OpenAI:     export OPENAI_API_KEY=sk-...\n"
                "  3. OpenRouter: export OPENROUTER_API_KEY=sk-or-...\n"
                "  4. Custom:     export CUSTOM_API_KEY=... + CUSTOM_API_BASE_URL=...\n"
                "  5. Or edit ~/.cc-code/settings.json:\n"
                '     {"env": {"ANTHROPIC_API_KEY": "sk-ant-..."}}\n'
            )
            errors.append(help_msg)
        else:
            errors.append(str(e))
        
        return False, errors
    except Exception as e:
        return False, [f"Unexpected error: {e}"]


def format_config_diagnostic(cwd: str | Path | None = None) -> str:
    """格式化配置诊断信息。

    始终尽量输出 `Tool Profile:` 一行，即便加载完整运行时配置失败。
    """
    is_valid, messages = validate_config(cwd)

    lines = ["Configuration Diagnostics", "=" * 40, ""]

    if is_valid:
        lines.append("Status: OK")
        if messages:
            lines.append("")
            lines.append("Warnings:")
            for msg in messages:
                lines.append(f"  [WARN] {msg}")
    else:
        lines.append("Status: ERRORS")
        lines.append("")
        lines.append("Errors:")
        for msg in messages:
            lines.append(f"  [ERROR] {msg}")

    # Determine fallback tool profile from environment or effective settings
    fallback_tool_profile = str(os.environ.get("CC_CODE_TOOL_PROFILE") or "core").strip()
    try:
        effective = load_effective_settings(cwd)
        tp = effective.get("toolProfile")
        if isinstance(tp, str) and tp.strip():
            fallback_tool_profile = tp.strip()
    except Exception:
        pass

    # Try to load full runtime config and show detailed info; otherwise show minimal info
    try:
        config = load_runtime_config(cwd)
        model_name = config.get("model", "not set")

        lines.append("")
        lines.append("Current Configuration")
        lines.append("-" * 40)
        lines.append(f"  Model: {model_name}")

        from cc_code.model_registry import detect_provider, Provider
        provider = detect_provider(model_name, config)
        lines.append(f"  Provider: {provider.value}")

        lines.append(f"  Base URL: {config.get('baseUrl', 'not set')}")
        if config.get('openaiBaseUrl') and provider in (Provider.OPENAI, Provider.OPENROUTER, Provider.CUSTOM):
            lines.append(f"  OpenAI Base URL: {config.get('openaiBaseUrl')}")
        if config.get('openrouterApiKey'):
            lines.append(f"  OpenRouter: configured")
        if config.get('customBaseUrl'):
            lines.append(f"  Custom Base URL: {config.get('customBaseUrl')}")

        auth_methods = []
        if config.get("authToken"):
            auth_methods.append("ANTHROPIC_AUTH_TOKEN")
        if config.get("apiKey"):
            auth_methods.append("ANTHROPIC_API_KEY")
        if config.get("openaiApiKey"):
            auth_methods.append("OPENAI_API_KEY")
        if config.get("openrouterApiKey"):
            auth_methods.append("OPENROUTER_API_KEY")
        if config.get("customApiKey"):
            auth_methods.append("CUSTOM_API_KEY")
        lines.append(f"  Auth: {', '.join(auth_methods) or 'none'}")
        lines.append(f"  MCP Servers: {len(config.get('mcpServers', {}))}")
        lines.append(f"  Tool Profile: {config.get('toolProfile', fallback_tool_profile)}")

        global_profile_path = config.get('globalUserProfilePath', '')
        project_profile_path = config.get('projectUserProfilePath', '')
        if global_profile_path:
            gp_exists = Path(global_profile_path).exists()
            lines.append(f"  Global Profile: {global_profile_path} ({'exists' if gp_exists else 'not found'})")
        if project_profile_path:
            pp_exists = Path(project_profile_path).exists()
            lines.append(f"  Project Profile: {project_profile_path} ({'exists' if pp_exists else 'not found'})")
        if config.get('responseLanguage'):
            lines.append(f"  Response Language: {config.get('responseLanguage')}")
        if config.get('responseVerbosity'):
            lines.append(f"  Response Verbosity: {config.get('responseVerbosity')}")

    except Exception:
        lines.append("")
        lines.append("Current Configuration")
        lines.append("-" * 40)
        lines.append(f"  Tool Profile: {fallback_tool_profile}")
        try:
            eff = load_effective_settings(cwd)
            model_name = eff.get("model", "not set")
        except Exception:
            model_name = "not set"
        lines.append(f"  Model: {model_name}")

    return "\n".join(lines)
