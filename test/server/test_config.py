from __future__ import annotations

import pytest

from app.config import Settings


MODEL_ENV_NAMES = (
    "CONTENT_AI_PROVIDER",
    "CONTENT_AI_BASE_URL",
    "CONTENT_AI_API_KEY",
    "CONTENT_AI_MODEL",
    "CONTENT_AI_FALLBACK_MODELS",
    "INTEL_RADAR_MODEL_MODE",
    "INTEL_RADAR_SOURCE_MODE",
)


def isolate_model_environment(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv(
        "INTEL_RADAR_ENV_FILE",
        str(tmp_path / "missing.env"),
    )
    for name in MODEL_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_default_mode_requires_real_deepseek_api_key(
    monkeypatch,
    tmp_path,
):
    isolate_model_environment(monkeypatch, tmp_path)

    with pytest.raises(
        ValueError,
        match="Real model mode requires CONTENT_AI_API_KEY",
    ):
        Settings.from_env()


def test_default_mode_uses_real_deepseek_and_rss(
    monkeypatch,
    tmp_path,
):
    isolate_model_environment(monkeypatch, tmp_path)
    monkeypatch.setenv("CONTENT_AI_API_KEY", "test-key")

    settings = Settings.from_env()

    assert settings.model_mode == "real"
    assert settings.source_mode == "rss"
    assert settings.content_ai_provider == "deepseek"
    assert settings.content_ai_base_url == "https://api.deepseek.com"
    assert settings.content_ai_model == "deepseek-v4-pro"
    assert settings.content_ai_fallback_models == ("deepseek-v4-flash",)


def test_mock_mode_must_be_explicit(
    monkeypatch,
    tmp_path,
):
    isolate_model_environment(monkeypatch, tmp_path)
    monkeypatch.setenv("INTEL_RADAR_MODEL_MODE", "mock")
    monkeypatch.setenv("CONTENT_AI_API_KEY", "unused-real-key")
    monkeypatch.setenv("CONTENT_AI_MODEL", "deepseek-v4-pro")
    monkeypatch.setenv(
        "CONTENT_AI_FALLBACK_MODELS",
        "deepseek-v4-flash",
    )

    settings = Settings.from_env()

    assert settings.model_mode == "mock"
    assert settings.source_mode == "fixture"
    assert settings.content_ai_provider == "mock"
    assert settings.content_ai_model == "mock-research-model"
    assert settings.content_ai_fallback_models == ()
