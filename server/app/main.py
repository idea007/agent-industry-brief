from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import Settings
from app.harness.evals import EvalRunner
from app.harness.model_adapter import (
    MockResearchModelAdapter,
    OpenAICompatibleResearchModelAdapter,
)
from app.harness.policy import ToolPolicy
from app.harness.runtime import AgentRuntime
from app.harness.tools import ToolRegistry
from app.persistence.database import Database
from app.scheduler import RunScheduler


def create_app(settings: Settings | None = None) -> FastAPI:
    configured = settings or Settings.from_env()
    database = Database(configured.database_path)
    registry = ToolRegistry(
        configured.fixture_path,
        database,
        source_mode=configured.source_mode,
        feed_config_path=configured.feed_config_path,
        feed_timeout_seconds=configured.feed_timeout_seconds,
        feed_max_bytes=configured.feed_max_bytes,
        feed_max_documents=configured.feed_max_documents,
        feed_evidence_documents=configured.feed_evidence_documents,
        feed_fulltext_documents=configured.feed_fulltext_documents,
        feed_per_source_cap=configured.feed_per_source_cap,
        feed_per_publisher_cap=configured.feed_per_publisher_cap,
        feed_supply_expansion_enabled=configured.feed_supply_expansion_enabled,
    )
    if configured.model_mode == "real":
        if not configured.content_ai_base_url or not configured.content_ai_api_key:
            raise ValueError("Real model mode is missing API configuration")
        model = OpenAICompatibleResearchModelAdapter(
            provider=configured.content_ai_provider,
            base_url=configured.content_ai_base_url,
            api_key=configured.content_ai_api_key,
            model=configured.content_ai_model,
            fallback_models=configured.content_ai_fallback_models,
            reasoning_effort=configured.content_ai_reasoning_effort,
            timeout_seconds=configured.model_timeout_seconds,
            max_retries=configured.model_max_retries,
        )
    else:
        model = MockResearchModelAdapter()
    runtime = AgentRuntime(
        database,
        registry,
        ToolPolicy(),
        model,
        EvalRunner(),
        step_delay_seconds=configured.step_delay_seconds,
        quality_observability_enabled=(
            configured.quality_observability_enabled
        ),
        story_clustering_enabled=configured.story_clustering_enabled,
        claim_eval_enabled=configured.claim_eval_enabled,
        personalization_enabled=configured.personalization_enabled,
        max_concurrent_runs=configured.max_concurrent_runs,
    )
    scheduler = RunScheduler(
        database,
        runtime,
        enabled=configured.scheduler_enabled,
        poll_seconds=configured.scheduler_poll_seconds,
        catch_up_hours=configured.scheduler_catch_up_hours,
        timezone_name=configured.scheduler_timezone,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database.initialize()
        database.reconcile_interrupted_runs()
        database.seed_subscriptions()
        app.state.database = database
        app.state.registry = registry
        app.state.runtime = runtime
        app.state.scheduler = scheduler
        app.state.settings = configured
        scheduler.start()
        try:
            yield
        finally:
            await scheduler.stop()
            await runtime.shutdown()

    app = FastAPI(
        title="行业新闻简报",
        version="0.3.0",
        description=(
            "Industry news discovery and AI assessment service with RSS tools, "
            "source validation, scheduler, approvals, and durable scan events."
        ),
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(configured.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


app = create_app()
