from __future__ import annotations

import asyncio
import json

import pytest

from app.domain.models import (
    ApprovalDecision,
    EvalResult,
    IntelSourceTranslation,
    RunStatus,
    StructuredResultIntent,
)
from app.harness.evals import EvalRunner
from app.harness.model_adapter import (
    MockResearchModelAdapter,
    ModelDecision,
    ModelAdapterError,
)
from app.harness.policy import ToolPolicy
from app.harness.runtime import AgentRuntime, _eval_failure_message


def subscription_by_slug(database, slug: str):
    return next(
        subscription
        for subscription in database.list_subscriptions()
        if subscription.slug == slug
    )


def test_non_chinese_source_translation_is_attached_to_source_snapshot(harness):
    _, _, registry, _ = harness
    documents = [
        {
            "source_id": "source_en",
            "title": "Product update",
            "url": "https://example.com/product-update",
            "publisher": "Example",
            "source_type": "official",
            "published_at": "2026-07-26T00:00:00+00:00",
            "body": (
                "The release improves real-time rendering, multilingual "
                "lip sync, and production monitoring."
            ),
        },
        {
            "source_id": "source_zh",
            "title": "产品更新",
            "url": "https://example.com/product-update-zh",
            "publisher": "示例",
            "source_type": "official",
            "published_at": "2026-07-26T00:00:00+00:00",
            "body": "本次更新改善了实时渲染、多语言口型同步和生产监控能力。",
        },
    ]
    translations = [
        IntelSourceTranslation(
            source_id="source_en",
            content_zh="本次发布改善了实时渲染、多语言口型同步和生产监控能力。",
        ),
        IntelSourceTranslation(
            source_id="source_zh",
            content_zh="这条中文原文不应该被译文覆盖。",
        ),
    ]

    sources = registry.sources_from_documents(
        ["source_en", "source_zh"],
        documents,
        translations,
    )

    assert sources[0].translated_content == translations[0].content_zh
    assert sources[1].translated_content is None


def test_source_snapshot_keeps_low_confidence_attribution_clue(harness):
    _, _, registry, _ = harness
    sources = registry.sources_from_documents(
        ["source_cnmo"],
        [
            {
                "source_id": "source_cnmo",
                "title": (
                    "小鹏 IRON 人形机器人开启试生产"
                    " - CNMO 科技 - 手机新浪网"
                ),
                "url": "https://example.com/robot",
                "publisher": "手机新浪网",
                "source_type": "aggregator",
                "published_at": "2026-07-26T00:00:00+00:00",
                "body": "小鹏 IRON 人形机器人进入试生产阶段。",
                "reliability": 0.72,
            }
        ],
    )

    assert sources[0].attributed_publisher == "CNMO 科技"
    assert sources[0].attribution_evidence
    assert sources[0].reliability == 0.72


def test_translation_source_must_belong_to_current_event():
    item = {
        "title": "产品更新",
        "summary": "来源显示产品能力得到更新。",
        "category": "technology",
        "tags": ["数字人"],
        "event_time": "2026-07-26T00:00:00+00:00",
        "importance_score": 7.5,
        "importance_reason": "影响产品集成方式。",
        "confidence_level": "medium",
        "confidence_score": 0.75,
        "confidence_reason": "来自一个官方来源。",
        "verification_status": "partially_confirmed",
        "facts": [
            {
                "text": "产品发布了新版本。",
                "source_ids": ["source_allowed"],
            }
        ],
        "inferences": [],
        "source_ids": ["source_allowed"],
        "source_translations": [
            {
                "source_id": "source_other",
                "content_zh": "这是一段不属于当前事件来源的中文译文。",
            }
        ],
    }

    result, _ = EvalRunner().evaluate(
        [item],
        allowed_source_ids={"source_allowed", "source_other"},
        blocked_source_ids=set(),
    )

    assert result.passed is False
    consistency = next(
        check
        for check in result.checks
        if check["name"] == "citation_consistency"
    )
    assert consistency["detail"] == {
        "unlisted_source_ids": ["source_other"]
    }


def test_eval_failure_message_names_failed_hard_checks():
    result = EvalResult(
        passed=False,
        checks=[
            {
                "name": "fact_citation_coverage",
                "severity": "hard",
                "passed": False,
                "detail": {"unsupported_claims": ["事实一", "事实二"]},
            },
            {
                "name": "summary_faithfulness",
                "severity": "hard",
                "passed": False,
                "detail": {"items": [{"title": "摘要"}]},
            },
            {
                "name": "relevance_quality",
                "severity": "soft",
                "passed": False,
                "detail": {"items": ["软检查"]},
            },
        ],
        metrics={},
    )

    assert _eval_failure_message(result) == (
        "情报草稿未通过事实引用（2 条）、摘要数字回溯（1 条）检查"
    )


class FailingFinalModelAdapter:
    provider = "test"
    model = "failing-final-model"

    def __init__(self, error_code: str):
        self.mock = MockResearchModelAdapter()
        self.error_code = error_code

    @property
    def actor_id(self) -> str:
        return self.model

    async def close(self) -> None:
        return None

    async def decide(
        self,
        run,
        subscription,
        observations,
        tool_definitions,
    ):
        if not tool_definitions:
            raise ModelAdapterError(
                self.error_code,
                "simulated final timeout",
                retryable=True,
            )
        return await self.mock.decide(
            run,
            subscription,
            observations,
            tool_definitions,
        )


class PartiallyInvalidFinalModelAdapter:
    provider = "test"
    model = "partially-invalid-final-model"

    def __init__(self):
        self.mock = MockResearchModelAdapter()

    @property
    def actor_id(self) -> str:
        return self.model

    async def decide(
        self,
        run,
        subscription,
        observations,
        tool_definitions,
    ):
        decision = await self.mock.decide(
            run,
            subscription,
            observations,
            tool_definitions,
        )
        if not isinstance(decision.intent, StructuredResultIntent):
            return decision
        items = [dict(item) for item in decision.intent.items]
        invalid = dict(items[0])
        invalid["facts"] = [dict(fact) for fact in invalid["facts"]]
        invalid["facts"][0]["text"] = "来源中不存在的全新事实。"
        items[0] = invalid
        return ModelDecision(
            intent=StructuredResultIntent(
                items=items,
                research_summary=decision.intent.research_summary,
            ),
            provider=self.provider,
            model=self.model,
        )


class EmptyFinalModelAdapter:
    provider = "test"
    model = "empty-final-model"

    def __init__(self):
        self.mock = MockResearchModelAdapter()

    @property
    def actor_id(self) -> str:
        return self.model

    async def decide(
        self,
        run,
        subscription,
        observations,
        tool_definitions,
    ):
        decision = await self.mock.decide(
            run,
            subscription,
            observations,
            tool_definitions,
        )
        if not isinstance(decision.intent, StructuredResultIntent):
            return decision
        return ModelDecision(
            intent=StructuredResultIntent(
                items=[],
                research_summary=(
                    "检索到候选资料，但没有发现满足相关性与证据要求的可靠事件。"
                ),
            ),
            provider=self.provider,
            model=self.model,
        )


class ControlledConcurrentRuntime(AgentRuntime):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.started_run_ids: list[str] = []
        self.release_events: dict[str, asyncio.Event] = {}

    async def execute(self, run_id: str) -> None:
        run = self.database.update_run(
            run_id,
            status=RunStatus.RUNNING,
        )
        self.started_run_ids.append(run_id)
        self._event(
            run,
            "run.started",
            {"goal": run.goal, "trigger": run.trigger},
            actor={"type": "runtime", "id": "agent_runtime"},
        )
        await self.release_events.setdefault(run_id, asyncio.Event()).wait()
        run = self.database.update_run(
            run_id,
            status=RunStatus.COMPLETED,
            result={"item_count": 0},
        )
        self._event(
            run,
            "run.completed",
            {"item_count": 0},
            actor={"type": "runtime", "id": "agent_runtime"},
        )


async def wait_until(predicate, attempts: int = 100) -> None:
    for _ in range(attempts):
        if predicate():
            return
        await asyncio.sleep(0)
    raise AssertionError("condition was not reached")


def create_test_run(database, subscription, index: int):
    run = database.create_run(
        subscription_id=subscription.id,
        trigger="manual",
        goal=f"并发扫描 {index}",
        delivery_mode="web_inbox",
        idempotency_key=None,
    )
    database.append_event(
        run.id,
        "run.created",
        actor={"type": "test", "id": "pytest"},
        payload={},
    )
    return run


@pytest.mark.asyncio
async def test_runtime_limits_concurrency_and_promotes_queued_runs(harness):
    _, database, registry, _ = harness
    runtime = ControlledConcurrentRuntime(
        database,
        registry,
        ToolPolicy(),
        MockResearchModelAdapter(),
        EvalRunner(),
        step_delay_seconds=0,
        max_concurrent_runs=2,
    )
    subscriptions = database.list_subscriptions()[:3]
    runs = [
        create_test_run(database, subscription, index)
        for index, subscription in enumerate(subscriptions, start=1)
    ]

    for run in runs:
        runtime.start(run.id)
    await wait_until(
        lambda: len(runtime.started_run_ids) == 2
        and runtime.status()["queued_run_count"] == 1
    )

    assert runtime.status() == {
        "max_concurrent_runs": 2,
        "active_run_count": 2,
        "queued_run_count": 1,
    }
    assert database.get_run(runs[2].id).status == RunStatus.QUEUED
    queued_event = database.list_events(runs[2].id)[-1]
    assert queued_event.type == "run.queued"
    assert queued_event.payload == {
        "queue_position": 1,
        "max_concurrent_runs": 2,
    }

    runtime.release_events[runs[0].id].set()
    await wait_until(lambda: runs[2].id in runtime.started_run_ids)
    assert database.get_run(runs[2].id).status == RunStatus.RUNNING
    assert runtime.status()["active_run_count"] == 2

    runtime.release_events[runs[1].id].set()
    runtime.release_events[runs[2].id].set()
    await asyncio.gather(*runtime._tasks.values())
    assert runtime.status()["active_run_count"] == 0
    assert all(
        database.get_run(run.id).status == RunStatus.COMPLETED
        for run in runs
    )
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_queued_run_can_be_cancelled_before_execution(harness):
    _, database, registry, _ = harness
    runtime = ControlledConcurrentRuntime(
        database,
        registry,
        ToolPolicy(),
        MockResearchModelAdapter(),
        EvalRunner(),
        step_delay_seconds=0,
        max_concurrent_runs=1,
    )
    subscriptions = database.list_subscriptions()[:2]
    first = create_test_run(database, subscriptions[0], 1)
    queued = create_test_run(database, subscriptions[1], 2)

    runtime.start(first.id)
    runtime.start(queued.id)
    await wait_until(
        lambda: runtime.status()["active_run_count"] == 1
        and runtime.status()["queued_run_count"] == 1
    )

    cancelled = await runtime.cancel(queued.id)
    assert cancelled.status == RunStatus.CANCELLED
    assert queued.id not in runtime.started_run_ids
    assert [
        event.type for event in database.list_events(queued.id)
    ][-2:] == ["run.cancel_requested", "run.cancelled"]

    runtime.release_events[first.id].set()
    await asyncio.gather(*runtime._tasks.values(), return_exceptions=True)
    await runtime.shutdown()


@pytest.mark.asyncio
async def test_live2d_run_completes_with_trace_and_citations(harness):
    _, database, _, runtime = harness
    subscription = subscription_by_slug(database, "live2d")
    run = database.create_run(
        subscription_id=subscription.id,
        trigger="manual",
        goal="测试 Live2D 情报研究",
        delivery_mode="web_inbox",
        idempotency_key=None,
    )
    database.append_event(
        run.id,
        "run.created",
        actor={"type": "test", "id": "pytest"},
        payload={},
    )

    await runtime.execute(run.id)

    completed = database.get_run(run.id)
    assert completed is not None
    assert completed.status == RunStatus.COMPLETED
    assert completed.result is not None
    assert completed.result["item_count"] == 2
    assert completed.result["eval"]["passed"] is True
    assert completed.result["eval"]["metrics"]["citation_coverage"] == 1.0

    events = database.list_events(run.id)
    event_types = [event.type for event in events]
    assert event_types.count("tool.requested") == 3
    assert "eval.completed" in event_types
    assert event_types[-1] == "run.completed"

    intel_events = database.list_intel_events(subscription_id=subscription.id)
    assert len(intel_events) == 2
    assert {event.category for event in intel_events} == {"technology"}
    assert all(event.source_ids for event in intel_events)
    assert all(event.sources for event in intel_events)
    assert all(
        source.category == "technology"
        for event in intel_events
        for source in event.sources
    )
    assert all(
        source.url.startswith("https://")
        for event in intel_events
        for source in event.sources
    )
    source_documents = database.list_source_documents(
        subscription_id=subscription.id
    )
    run_documents = database.list_run_documents(run.id)
    assert len(source_documents) == len(run_documents) >= 2
    assert all(
        document.last_outcome in {"selected", "reviewed", "blocked"}
        for document in run_documents
    )
    assert all(len(document.content_excerpt) <= 1500 for document in run_documents)
    with database.connect() as connection:
        search_result = connection.execute(
            """
            SELECT result FROM tool_calls
            WHERE run_id = ? AND tool = 'search_sources'
            """,
            (run.id,),
        ).fetchone()
    stored_search_result = json.loads(search_result["result"])
    assert "documents" not in stored_search_result
    assert stored_search_result["documents_persisted"] == len(run_documents)
    assert stored_search_result["fetched_source_count"] == 0
    assert stored_search_result["search_query_count"] == 0
    assert stored_search_result["fulltext_count"] == 0

    repeat = database.create_run(
        subscription_id=subscription.id,
        trigger="manual",
        goal="再次扫描同一批 Live2D 来源",
        delivery_mode="web_inbox",
        idempotency_key=None,
    )
    await runtime.execute(repeat.id)
    refreshed_events = database.list_intel_events(
        subscription_id=subscription.id
    )
    assert len(refreshed_events) == 2
    assert all(event.run_id == repeat.id for event in refreshed_events)
    refreshed_documents = database.list_source_documents(
        subscription_id=subscription.id
    )
    assert len(refreshed_documents) == len(source_documents)
    assert all(document.seen_count == 2 for document in refreshed_documents)


@pytest.mark.asyncio
async def test_runtime_keeps_valid_items_when_one_draft_fails_eval(harness):
    _, database, registry, _ = harness
    runtime = AgentRuntime(
        database,
        registry,
        ToolPolicy(),
        PartiallyInvalidFinalModelAdapter(),
        EvalRunner(),
        step_delay_seconds=0,
    )
    subscription = subscription_by_slug(database, "live2d")
    run = database.create_run(
        subscription_id=subscription.id,
        trigger="manual",
        goal="测试逐条质量过滤",
        delivery_mode="web_inbox",
        idempotency_key=None,
    )

    await runtime.execute(run.id)

    completed = database.get_run(run.id)
    assert completed is not None
    assert completed.status == RunStatus.COMPLETED
    assert completed.result is not None
    assert completed.result["item_count"] == 1
    metrics = completed.result["eval"]["metrics"]
    assert metrics["input_item_count"] == 2
    assert metrics["accepted_item_count"] == 1
    assert metrics["rejected_item_count"] == 1
    eval_event = next(
        event
        for event in database.list_events(run.id)
        if event.type == "eval.completed"
    )
    item_filter = next(
        check
        for check in eval_event.payload["checks"]
        if check["name"] == "item_quality_filter"
    )
    assert item_filter["detail"]["rejected_item_count"] == 1
    assert len(
        database.list_intel_events(subscription_id=subscription.id)
    ) == 1


@pytest.mark.asyncio
async def test_runtime_completes_with_an_honest_empty_result(harness):
    _, database, registry, _ = harness
    runtime = AgentRuntime(
        database,
        registry,
        ToolPolicy(),
        EmptyFinalModelAdapter(),
        EvalRunner(),
        step_delay_seconds=0,
    )
    subscription = subscription_by_slug(database, "live2d")
    run = database.create_run(
        subscription_id=subscription.id,
        trigger="manual",
        goal="测试无合格结果的正常终态",
        delivery_mode="web_inbox",
        idempotency_key=None,
    )

    await runtime.execute(run.id)

    completed = database.get_run(run.id)
    assert completed is not None
    assert completed.status == RunStatus.COMPLETED
    assert completed.result is not None
    assert completed.result["item_count"] == 0
    assert completed.result["delivery"] == {
        "status": "not_needed",
        "reason": "no_qualifying_intel",
    }
    assert completed.result["empty_result"]["reason_code"] == (
        "NO_QUALIFYING_INTEL"
    )
    assert completed.result["eval"]["passed"] is True
    events = database.list_events(run.id)
    event_types = [event.type for event in events]
    assert event_types[-2:] == ["run.no_results", "run.completed"]
    assert "run.failed" not in event_types
    assert "delivery.completed" not in event_types
    assert database.list_intel_events(subscription_id=subscription.id) == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_code",
    [
        "MODEL_NETWORK_ERROR",
        "MODEL_INVALID_JSON",
        "MODEL_OUTPUT_TRUNCATED",
        "MODEL_INVALID_STRUCTURED_RESULT",
    ],
)
async def test_retryable_final_model_failure_uses_evidence_fallback(
    harness, error_code
):
    _, database, registry, _ = harness
    runtime = AgentRuntime(
        database,
        registry,
        ToolPolicy(),
        FailingFinalModelAdapter(error_code),
        EvalRunner(),
        step_delay_seconds=0,
    )
    subscription = subscription_by_slug(database, "live2d")
    run = database.create_run(
        subscription_id=subscription.id,
        trigger="manual",
        goal="测试最终生成降级",
        delivery_mode="web_inbox",
        idempotency_key=None,
    )

    await runtime.execute(run.id)

    completed = database.get_run(run.id)
    assert completed is not None
    assert completed.status == RunStatus.COMPLETED
    assert completed.result is not None
    assert completed.result["item_count"] == 2
    events = database.list_events(run.id)
    assert "model.failed" in [event.type for event in events]
    assert "model.degraded" in [event.type for event in events]
    responded = [
        event
        for event in events
        if event.type == "model.responded"
    ][-1]
    assert responded.payload["model"] == "deterministic-evidence-synthesizer"
    degraded = next(
        event for event in events if event.type == "model.degraded"
    )
    assert degraded.payload["reason_code"] == error_code


@pytest.mark.asyncio
async def test_prompt_injection_source_is_not_cited(harness):
    _, database, _, runtime = harness
    subscription = subscription_by_slug(database, "ai-agent")
    run = database.create_run(
        subscription_id=subscription.id,
        trigger="manual",
        goal="测试 AI Agent 安全研究",
        delivery_mode="web_inbox",
        idempotency_key=None,
    )

    await runtime.execute(run.id)

    completed = database.get_run(run.id)
    assert completed is not None
    assert completed.status == RunStatus.COMPLETED
    intel_events = database.list_intel_events(subscription_id=subscription.id)
    cited = {source_id for event in intel_events for source_id in event.source_ids}
    assert "src_agent_malicious_page" not in cited
    blocked_document = next(
        document
        for document in database.list_run_documents(run.id)
        if document.source_id == "src_agent_malicious_page"
    )
    assert blocked_document.last_outcome == "blocked"
    eval_event = next(
        event
        for event in database.list_events(run.id)
        if event.type == "eval.completed"
    )
    boundary_check = next(
        check
        for check in eval_event.payload["checks"]
        if check["name"] == "prompt_injection_boundary"
    )
    assert boundary_check["passed"] is True


@pytest.mark.asyncio
async def test_public_delivery_waits_for_approval(harness):
    _, database, _, runtime = harness
    subscription = subscription_by_slug(database, "game-dev")
    run = database.create_run(
        subscription_id=subscription.id,
        trigger="manual",
        goal="测试公开投递审批",
        delivery_mode="public_preview",
        idempotency_key=None,
    )

    await runtime.execute(run.id)

    waiting = database.get_run(run.id)
    assert waiting is not None
    assert waiting.status == RunStatus.WAITING_APPROVAL
    approval = database.get_pending_approval_for_run(run.id)
    assert approval is not None

    resolved_run = await runtime.resolve_approval(
        approval.id, ApprovalDecision(decision="approve", reason="测试允许一次")
    )
    assert resolved_run.status == RunStatus.COMPLETED
    assert resolved_run.result is not None
    assert resolved_run.result["delivery"]["channel"] == "public_preview"


@pytest.mark.asyncio
async def test_rejected_delivery_keeps_draft(harness):
    _, database, _, runtime = harness
    subscription = subscription_by_slug(database, "game-dev")
    run = database.create_run(
        subscription_id=subscription.id,
        trigger="manual",
        goal="测试拒绝公开投递",
        delivery_mode="public_preview",
        idempotency_key=None,
    )

    await runtime.execute(run.id)
    approval = database.get_pending_approval_for_run(run.id)
    assert approval is not None
    resolved_run = await runtime.resolve_approval(
        approval.id, ApprovalDecision(decision="reject", reason="仅保留草稿")
    )

    assert resolved_run.status == RunStatus.COMPLETED
    assert resolved_run.result is not None
    assert resolved_run.result["delivery"]["status"] == "draft_only"
