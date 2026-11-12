from __future__ import annotations

from pathlib import Path

import pytest

from app.config import PROJECT_ROOT, Settings
from app.harness.evals import EvalRunner
from app.harness.model_adapter import MockResearchModelAdapter
from app.harness.policy import ToolPolicy
from app.harness.runtime import AgentRuntime
from app.harness.tools import ToolRegistry
from app.persistence.database import Database


@pytest.fixture
def harness(tmp_path: Path):
    settings = Settings(
        database_path=tmp_path / "test.sqlite3",
        fixture_path=PROJECT_ROOT / "fixtures" / "mock_documents.json",
        cors_origins=("http://localhost:3001",),
        step_delay_seconds=0,
        model_mode="mock",
        content_ai_provider="mock",
        content_ai_base_url=None,
        content_ai_model="mock-research-model",
        content_ai_fallback_models=(),
        source_mode="fixture",
    )
    database = Database(settings.database_path)
    database.initialize()
    database.seed_subscriptions()
    registry = ToolRegistry(settings.fixture_path, database)
    runtime = AgentRuntime(
        database,
        registry,
        ToolPolicy(),
        MockResearchModelAdapter(),
        EvalRunner(),
        step_delay_seconds=0,
    )
    return settings, database, registry, runtime
