from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _discover_env_file() -> Path | None:
    configured = os.getenv("INTEL_RADAR_ENV_FILE")
    if configured:
        candidate = Path(configured).expanduser()
        return candidate if candidate.exists() else None
    for parent in (Path(__file__).resolve().parent, *Path(__file__).resolve().parents):
        candidate = parent / ".env"
        if candidate.exists():
            return candidate
    return None


def _load_env_file() -> Path | None:
    """Load simple KEY=VALUE entries without overriding process environment."""
    env_file = _discover_env_file()
    if env_file is None:
        return None
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.removeprefix("export ").strip()
        if not key or not key.replace("_", "").isalnum():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        os.environ.setdefault(key, value)
    return env_file


def _as_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_path: Path
    fixture_path: Path
    cors_origins: tuple[str, ...]
    step_delay_seconds: float = 0.18
    model_mode: str = "real"
    content_ai_provider: str = "deepseek"
    content_ai_base_url: str | None = "https://api.deepseek.com"
    content_ai_api_key: str | None = None
    content_ai_model: str = "deepseek-v4-pro"
    content_ai_fallback_models: tuple[str, ...] = ("deepseek-v4-flash",)
    content_ai_reasoning_effort: str | None = None
    model_timeout_seconds: float = 45
    model_max_retries: int = 1
    source_mode: str = "rss"
    feed_config_path: Path = PROJECT_ROOT / "feeds.json"
    feed_timeout_seconds: float = 15
    feed_max_bytes: int = 1_500_000
    feed_max_documents: int = 96
    feed_evidence_documents: int = 30
    feed_fulltext_documents: int = 36
    feed_per_source_cap: int = 4
    feed_per_publisher_cap: int = 6
    feed_supply_expansion_enabled: bool = True
    quality_observability_enabled: bool = True
    story_clustering_enabled: bool = True
    claim_eval_enabled: bool = True
    personalization_enabled: bool = True
    max_concurrent_runs: int = 2
    scheduler_enabled: bool = False
    scheduler_poll_seconds: float = 30
    scheduler_catch_up_hours: float = 6
    scheduler_timezone: str = "Asia/Shanghai"

    @classmethod
    def from_env(cls) -> "Settings":
        _load_env_file()
        database_path = Path(
            os.getenv(
                "INTEL_RADAR_DATABASE",
                PROJECT_ROOT / "data" / "intelligence-radar.sqlite3",
            )
        )
        fixture_path = Path(
            os.getenv(
                "INTEL_RADAR_FIXTURES",
                PROJECT_ROOT / "fixtures" / "mock_documents.json",
            )
        )
        cors_origins = tuple(
            origin.strip()
            for origin in os.getenv(
                "INTEL_RADAR_CORS_ORIGINS",
                "http://localhost:3000,http://localhost:3001,http://127.0.0.1:3000,http://127.0.0.1:3001",
            ).split(",")
            if origin.strip()
        )
        provider = os.getenv(
            "CONTENT_AI_PROVIDER", "deepseek"
        ).strip().casefold()
        api_key = os.getenv("CONTENT_AI_API_KEY", "").strip() or None
        base_url = (
            os.getenv("CONTENT_AI_BASE_URL", "https://api.deepseek.com")
            .strip()
            or None
        )
        model_mode = os.getenv(
            "INTEL_RADAR_MODEL_MODE", "real"
        ).strip().casefold()
        if model_mode not in {"mock", "real"}:
            raise ValueError("INTEL_RADAR_MODEL_MODE must be mock or real")
        if model_mode == "real" and (not api_key or not base_url):
            raise ValueError(
                "Real model mode requires CONTENT_AI_API_KEY and CONTENT_AI_BASE_URL"
            )
        default_model = (
            "mock-research-model"
            if model_mode == "mock"
            else (
                "deepseek-v4-pro"
                if provider == "deepseek"
                else "research-model"
            )
        )
        default_fallback_models = (
            "deepseek-v4-flash"
            if model_mode == "real" and provider == "deepseek"
            else ""
        )
        fallback_models = (
            ()
            if model_mode == "mock"
            else tuple(
                model.strip()
                for model in os.getenv(
                    "CONTENT_AI_FALLBACK_MODELS",
                    default_fallback_models,
                ).split(",")
                if model.strip()
            )
        )
        source_mode = os.getenv(
            "INTEL_RADAR_SOURCE_MODE",
            "rss" if model_mode == "real" else "fixture",
        ).strip().casefold()
        if source_mode not in {"fixture", "rss", "hybrid"}:
            raise ValueError(
                "INTEL_RADAR_SOURCE_MODE must be fixture, rss or hybrid"
            )
        return cls(
            database_path=database_path,
            fixture_path=fixture_path,
            cors_origins=cors_origins,
            step_delay_seconds=float(
                os.getenv("INTEL_RADAR_STEP_DELAY_SECONDS", "0.18")
            ),
            model_mode=model_mode,
            content_ai_provider=(
                "mock"
                if model_mode == "mock"
                else (provider or "openai-compatible")
            ),
            content_ai_base_url=base_url,
            content_ai_api_key=api_key,
            content_ai_model=(
                "mock-research-model"
                if model_mode == "mock"
                else os.getenv("CONTENT_AI_MODEL", default_model).strip()
            ),
            content_ai_fallback_models=fallback_models,
            content_ai_reasoning_effort=(
                os.getenv("CONTENT_AI_REASONING_EFFORT", "").strip() or None
            ),
            model_timeout_seconds=float(
                os.getenv("INTEL_RADAR_MODEL_TIMEOUT_SECONDS", "45")
            ),
            model_max_retries=int(
                os.getenv("INTEL_RADAR_MODEL_MAX_RETRIES", "1")
            ),
            source_mode=source_mode,
            feed_config_path=Path(
                os.getenv(
                    "INTEL_RADAR_FEED_CONFIG",
                    PROJECT_ROOT / "feeds.json",
                )
            ),
            feed_timeout_seconds=float(
                os.getenv("INTEL_RADAR_FEED_TIMEOUT_SECONDS", "15")
            ),
            feed_max_bytes=int(
                os.getenv("INTEL_RADAR_FEED_MAX_BYTES", "1500000")
            ),
            feed_max_documents=int(
                os.getenv(
                    "INTEL_RADAR_FEED_DISCOVERY_MAX_DOCUMENTS",
                    os.getenv(
                        "INTEL_RADAR_FEED_DISCOVERY_DOCUMENTS",
                        os.getenv("INTEL_RADAR_FEED_MAX_DOCUMENTS", "96"),
                    ),
                )
            ),
            feed_evidence_documents=int(
                os.getenv(
                    "INTEL_RADAR_FEED_EVIDENCE_MAX_DOCUMENTS",
                    os.getenv("INTEL_RADAR_FEED_EVIDENCE_DOCUMENTS", "30"),
                )
            ),
            feed_fulltext_documents=int(
                os.getenv(
                    "INTEL_RADAR_FEED_FULLTEXT_MAX_DOCUMENTS",
                    os.getenv("INTEL_RADAR_FEED_FULLTEXT_DOCUMENTS", "36"),
                )
            ),
            feed_per_source_cap=int(
                os.getenv("INTEL_RADAR_FEED_PER_SOURCE_CAP", "4")
            ),
            feed_per_publisher_cap=int(
                os.getenv("INTEL_RADAR_FEED_PER_PUBLISHER_CAP", "6")
            ),
            feed_supply_expansion_enabled=_as_bool(
                "INTEL_RADAR_FEED_SUPPLY_EXPANSION_ENABLED", True
            ),
            quality_observability_enabled=_as_bool(
                "INTEL_RADAR_QUALITY_OBSERVABILITY_ENABLED", True
            ),
            story_clustering_enabled=_as_bool(
                "INTEL_RADAR_STORY_CLUSTERING_ENABLED", True
            ),
            claim_eval_enabled=_as_bool(
                "INTEL_RADAR_CLAIM_EVAL_ENABLED", True
            ),
            personalization_enabled=_as_bool(
                "INTEL_RADAR_PERSONALIZATION_ENABLED", True
            ),
            max_concurrent_runs=max(
                1,
                int(os.getenv("INTEL_RADAR_MAX_CONCURRENT_RUNS", "2")),
            ),
            scheduler_enabled=_as_bool(
                "INTEL_RADAR_SCHEDULER_ENABLED", False
            ),
            scheduler_poll_seconds=float(
                os.getenv("INTEL_RADAR_SCHEDULER_POLL_SECONDS", "30")
            ),
            scheduler_catch_up_hours=float(
                os.getenv("INTEL_RADAR_SCHEDULER_CATCH_UP_HOURS", "6")
            ),
            scheduler_timezone=os.getenv(
                "INTEL_RADAR_SCHEDULER_TIMEZONE", "Asia/Shanghai"
            ).strip(),
        )
