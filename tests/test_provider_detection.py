from __future__ import annotations

from cc_code.model_registry import (
    Provider,
    build_provider_config,
    detect_provider,
    format_model_status,
)


def test_vendor_prefixed_model_with_openai_base_url_routes_to_custom(monkeypatch) -> None:
    """deepseek/* + openaiBaseUrl 应归类为 CUSTOM，且 base_url 不为空。"""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("CUSTOM_API_BASE_URL", raising=False)
    runtime = {
        "openaiBaseUrl": "https://my-endpoint.example.com/v1",
        "openaiApiKey": "sk-custom",
    }

    provider = detect_provider("deepseek/deepseek-r1", runtime)
    assert provider == Provider.CUSTOM

    pconfig = build_provider_config("deepseek/deepseek-r1", runtime)
    assert pconfig.provider == Provider.CUSTOM
    # 关键：base_url 从 openaiBaseUrl 回退取得，不为空
    assert pconfig.base_url == "https://my-endpoint.example.com/v1"
    assert pconfig.api_key == "sk-custom"


def test_model_status_provider_matches_base_url_source(monkeypatch) -> None:
    """状态展示的 Provider 必须与 Base URL 同源（不再 openrouter vs 空 base_url 矛盾）。"""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("CUSTOM_API_BASE_URL", raising=False)
    runtime = {"openaiBaseUrl": "https://my-endpoint.example.com/v1"}

    status = format_model_status("deepseek/deepseek-r1", runtime)
    assert "Provider: custom" in status
    assert "https://my-endpoint.example.com/v1" in status
    assert "Provider: openrouter" not in status
