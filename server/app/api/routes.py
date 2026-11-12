from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.domain.focus import build_monitor_goal
from app.domain.focus_timeline import build_story_context_timeline
from app.domain.models import (
    AlertRuleCreate,
    ApprovalDecision,
    CustomSourceCreate,
    CustomSourcePreview,
    IntelFeedbackCreate,
    RunCreate,
    RunStatus,
    StoryContextTimeline,
    StoryWatchUpsert,
    SubscriptionCreate,
    SubscriptionPreferencesUpdate,
)
from app.story_tracking import (
    StoryWatchRunActive,
    build_story_tracking_overview,
    build_story_research_goal,
    trigger_story_watch,
)


router = APIRouter()

def _database(request: Request):
    return request.app.state.database


def _runtime(request: Request):
    return request.app.state.runtime


def _with_source_articles(request: Request, intel_events):
    registry = request.app.state.registry
    return [
        event
        if event.sources
        else event.model_copy(
            update={"sources": registry.sources_for_ids(event.source_ids)}
        )
        for event in intel_events
    ]


def _is_fixture_source(source) -> bool:
    return (
        source.content_origin == "fixture"
        or ".example.test" in source.url
        or "（演示）" in source.publisher
    )


def _visible_intel_events(request: Request, intel_events):
    events = _with_source_articles(request, intel_events)
    if request.app.state.settings.source_mode == "fixture":
        return events
    return [
        event
        for event in events
        if event.sources
        and not any(_is_fixture_source(source) for source in event.sources)
    ]


def _run_item_ids(run) -> set[str]:
    item_ids = (run.result or {}).get("item_ids", [])
    if not isinstance(item_ids, list):
        return set()
    return {item_id for item_id in item_ids if isinstance(item_id, str)}


def _system_status(request: Request) -> dict:
    settings = request.app.state.settings
    scheduler = request.app.state.scheduler
    registry = request.app.state.registry
    runtime = request.app.state.runtime
    return {
        "model": {
            "mode": settings.model_mode,
            "provider": settings.content_ai_provider,
            "model": settings.content_ai_model,
            "fallback_models": list(settings.content_ai_fallback_models),
        },
        "sources": {
            "mode": settings.source_mode,
            "configured_count": registry.source_count,
            "profile_count": registry.source_profile_count,
            "supply_expansion": {
                "enabled": settings.feed_supply_expansion_enabled,
                "discovery_limit": settings.feed_max_documents,
                "evidence_limit": settings.feed_evidence_documents,
                "fulltext_limit": settings.feed_fulltext_documents,
                "per_source_cap": settings.feed_per_source_cap,
                "per_publisher_cap": settings.feed_per_publisher_cap,
            },
        },
        "quality": {
            "observability_enabled": (
                settings.quality_observability_enabled
            ),
            "story_clustering_enabled": (
                settings.story_clustering_enabled
            ),
            "claim_eval_enabled": settings.claim_eval_enabled,
            "personalization_enabled": (
                settings.personalization_enabled
            ),
        },
        "runtime": runtime.status(),
        "scheduler": scheduler.status(),
    }


@router.get("/health")
async def health(request: Request) -> dict:
    return {
        "status": "ok",
        "service": "industry-intelligence-radar",
        "system": _system_status(request),
    }


@router.get("/api/system/status")
async def system_status(request: Request) -> dict:
    return _system_status(request)


@router.post("/api/scheduler/tick", status_code=202)
async def scheduler_tick(
    request: Request,
    force: bool = Query(default=False),
):
    return await request.app.state.scheduler.tick(force=force)


@router.get("/api/dashboard")
async def dashboard(request: Request) -> dict:
    database = _database(request)
    subscriptions = database.list_subscriptions()
    stored_intel_events = _with_source_articles(
        request, database.list_intel_events(limit=30)
    )
    feed_intel_events = _with_source_articles(
        request,
        database.list_intel_events(
            limit=30,
            include_stale_stories=False,
        ),
    )
    intel_events = _visible_intel_events(
        request,
        feed_intel_events,
    )
    visible_event_ids = {event.id for event in intel_events}
    hidden_event_ids = {
        event.id
        for event in stored_intel_events
        if event.id not in visible_event_ids
    }
    hidden_run_ids = {
        event.run_id
        for event in stored_intel_events
        if event.id not in visible_event_ids
    }
    persisted_runs = database.list_runs(limit=12)
    for run in persisted_runs:
        item_ids = _run_item_ids(run)
        if item_ids and item_ids.issubset(hidden_event_ids):
            hidden_run_ids.add(run.id)
    runs = [
        run
        for run in persisted_runs
        if run.id not in hidden_run_ids
    ]
    approvals = database.list_approvals(status="pending")
    completed = [run for run in runs if run.status == RunStatus.COMPLETED]
    article_count = sum(max(1, len(event.sources)) for event in intel_events)
    return {
        "subscriptions": subscriptions,
        "runs": runs,
        "intel_events": intel_events,
        "approvals": approvals,
        "story_watches": database.list_story_watches(),
        "system": _system_status(request),
        "stats": {
            "subscription_count": len(
                [subscription for subscription in subscriptions if subscription.enabled]
            ),
            "intel_event_count": article_count,
            "run_count": len(runs),
            "success_rate": round(len(completed) / len(runs), 3) if runs else 1.0,
            "pending_approval_count": len(approvals),
            "source_count": len(
                {
                    source_id
                    for event in intel_events
                    for source_id in event.source_ids
                }
            ),
        },
    }


@router.get("/api/subscriptions")
async def list_subscriptions(request: Request):
    return _database(request).list_subscriptions()


@router.post("/api/subscriptions", status_code=201)
async def create_subscription(payload: SubscriptionCreate, request: Request):
    try:
        return _database(request).create_subscription(payload)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/custom-sources")
async def list_custom_sources(
    request: Request,
    subscription_id: str | None = None,
):
    return _database(request).list_custom_sources(
        subscription_id=subscription_id
    )


@router.get("/api/source-documents")
async def list_source_documents(
    request: Request,
    subscription_id: str | None = None,
    outcome: str | None = Query(
        default=None,
        pattern=r"^(discovered|deferred|selected|reviewed|blocked)$",
    ),
    channel: str | None = None,
    retrieval_channel: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
):
    database = _database(request)
    if subscription_id and database.get_subscription(subscription_id) is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return database.list_source_documents(
        subscription_id=subscription_id,
        outcome=outcome,
        retrieval_channel=retrieval_channel or channel,
        limit=limit,
    )


@router.get("/api/runs/{run_id}/source-documents")
async def list_run_source_documents(run_id: str, request: Request):
    database = _database(request)
    if database.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return database.list_run_documents(run_id)


@router.get("/api/source-profiles")
async def list_source_profiles(request: Request):
    profiles_by_slug = {
        profile["slug"]: profile
        for profile in request.app.state.registry.list_source_profiles()
    }
    for subscription in _database(request).list_subscriptions():
        profiles_by_slug[subscription.slug] = (
            request.app.state.registry.source_profile_for_subscription(
                subscription
            )
        )
    return sorted(
        profiles_by_slug.values(),
        key=lambda profile: profile["name"],
    )


@router.get("/api/source-health")
async def list_source_health(
    request: Request,
    subscription_id: str,
):
    database = _database(request)
    if database.get_subscription(subscription_id) is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return database.list_source_runtime_states(
        subscription_id=subscription_id
    )


@router.get("/api/source-query-metrics")
async def list_source_query_metrics(
    request: Request,
    subscription_id: str,
):
    database = _database(request)
    if database.get_subscription(subscription_id) is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return database.list_source_query_metrics(
        subscription_id=subscription_id
    )


@router.post("/api/custom-sources", status_code=201)
async def create_custom_source(payload: CustomSourceCreate, request: Request):
    database = _database(request)
    if database.get_subscription(payload.subscription_id) is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    try:
        resolution = await request.app.state.registry.inspect_custom_source(payload)
        return database.create_custom_source(
            payload,
            resolved_url=resolution["resolved_url"],
            collection_mode=resolution["collection_mode"],
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/api/custom-sources/preview",
    response_model=CustomSourcePreview,
)
async def preview_custom_source(
    payload: CustomSourceCreate,
    request: Request,
):
    database = _database(request)
    if database.get_subscription(payload.subscription_id) is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    try:
        resolution = await request.app.state.registry.inspect_custom_source(
            payload
        )
        return CustomSourcePreview.model_validate(
            {"requested_url": payload.url, **resolution}
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/api/custom-sources/{source_id}", status_code=204)
async def delete_custom_source(source_id: str, request: Request):
    if not _database(request).delete_custom_source(source_id):
        raise HTTPException(status_code=404, detail="Custom source not found")


@router.get("/api/runs")
async def list_runs(request: Request, limit: int = Query(default=30, ge=1, le=100)):
    return _database(request).list_runs(limit=limit)


@router.post("/api/runs", status_code=202)
async def create_run(payload: RunCreate, request: Request):
    database = _database(request)
    subscription = database.get_subscription(payload.subscription_id)
    if subscription is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    story = None
    research_focus = None
    research_question = None
    if payload.research_mode == "deep_dive":
        if not payload.story_id:
            raise HTTPException(
                status_code=422,
                detail="Deep dive requires a story_id",
            )
        story = database.get_story(payload.story_id)
        if story is None:
            raise HTTPException(status_code=404, detail="Story not found")
        if story.subscription_id != subscription.id:
            raise HTTPException(
                status_code=409,
                detail="Story does not belong to this subscription",
            )
        research_focus = payload.research_focus or "comprehensive"
        research_question = (
            payload.research_question.strip()
            if payload.research_question
            else None
        )
    elif payload.story_id or payload.research_focus or payload.research_question:
        raise HTTPException(
            status_code=422,
            detail=(
                "story_id, research_focus and research_question are only "
                "supported for deep dives"
            ),
        )
    goal = payload.goal or (
        build_story_research_goal(
            story.canonical_title,
            research_focus,
            research_question,
        )
        if story
        else build_monitor_goal(
            name=subscription.name,
            topic=subscription.topic,
            keywords=subscription.include_keywords,
            slug=subscription.slug,
            lookback_hours=subscription.lookback_hours,
        )
    )
    run = database.create_run(
        subscription_id=subscription.id,
        trigger=payload.trigger,
        goal=goal,
        research_mode=payload.research_mode,
        story_id=payload.story_id,
        research_focus=research_focus,
        research_question=research_question,
        delivery_mode=payload.delivery_mode,
        idempotency_key=payload.idempotency_key,
    )
    if not database.list_events(run.id):
        database.append_event(
            run.id,
            "run.created",
            actor={"type": "user", "id": "local_user"},
            payload={
                "subscription_id": subscription.id,
                "subscription_name": subscription.name,
                "research_mode": payload.research_mode,
                "story_id": payload.story_id,
                "research_focus": research_focus,
                "research_question": research_question,
                "delivery_mode": payload.delivery_mode,
            },
        )
    _runtime(request).start(run.id)
    return database.get_run(run.id)


@router.get("/api/runs/{run_id}")
async def get_run(run_id: str, request: Request):
    run = _database(request).get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.post("/api/runs/{run_id}/cancel", status_code=202)
async def cancel_run(run_id: str, request: Request):
    try:
        return await _runtime(request).cancel(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc


@router.post("/api/runs/{run_id}/retry", status_code=202)
async def retry_run(run_id: str, request: Request):
    database = _database(request)
    previous = database.get_run(run_id)
    if previous is None:
        raise HTTPException(status_code=404, detail="Run not found")
    retry = database.create_run(
        subscription_id=previous.subscription_id,
        trigger="manual",
        goal=previous.goal,
        research_mode=previous.research_mode,
        story_id=previous.story_id,
        research_focus=previous.research_focus,
        research_question=previous.research_question,
        delivery_mode=previous.delivery_mode,
        idempotency_key=None,
    )
    database.append_event(
        retry.id,
        "run.created",
        actor={"type": "user", "id": "local_user"},
        payload={"retry_of": previous.id},
    )
    _runtime(request).start(retry.id)
    return retry


@router.get("/api/runs/{run_id}/events/history")
async def event_history(
    run_id: str,
    request: Request,
    after_seq: int = Query(default=0, ge=0),
):
    if _database(request).get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return _database(request).list_events(run_id, after_seq=after_seq)


@router.get("/api/runs/{run_id}/events")
async def stream_events(
    run_id: str,
    request: Request,
    after_seq: int = Query(default=0, ge=0),
):
    database = _database(request)
    if database.get_run(run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")

    last_event_id = request.headers.get("last-event-id")
    cursor = max(after_seq, int(last_event_id or 0))

    async def event_stream() -> AsyncIterator[str]:
        nonlocal cursor
        while True:
            if await request.is_disconnected():
                break
            events = database.list_events(run_id, after_seq=cursor)
            for event in events:
                cursor = event.seq
                data = json.dumps(
                    event.model_dump(mode="json"),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                yield f"id: {event.seq}\nevent: {event.type}\ndata: {data}\n\n"
            run = database.get_run(run_id)
            if (
                run is None
                or run.status
                in {
                    RunStatus.COMPLETED,
                    RunStatus.FAILED,
                    RunStatus.CANCELLED,
                    RunStatus.WAITING_APPROVAL,
                }
            ) and not events:
                break
            if not events:
                yield ": keep-alive\n\n"
            await asyncio.sleep(0.35)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/api/intel-events")
async def list_intel_events(
    request: Request,
    subscription_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    return _visible_intel_events(
        request,
        _database(request).list_intel_events(
            subscription_id=subscription_id,
            limit=limit,
            include_stale_stories=False,
        ),
    )


@router.get("/api/stories")
async def list_stories(
    request: Request,
    subscription_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
):
    database = _database(request)
    if (
        subscription_id
        and database.get_subscription(subscription_id) is None
    ):
        raise HTTPException(status_code=404, detail="Subscription not found")
    return database.list_stories(
        subscription_id=subscription_id,
        limit=limit,
    )


@router.get("/api/stories/{story_id}/context-timeline")
async def get_story_context_timeline(
    story_id: str,
    request: Request,
    days: int = Query(default=30, ge=7, le=90),
) -> StoryContextTimeline:
    database = _database(request)
    story = database.get_story(story_id)
    if story is None:
        raise HTTPException(status_code=404, detail="Story not found")
    subscription = database.get_subscription(story.subscription_id)
    if subscription is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    candidate_events = _visible_intel_events(
        request,
        database.list_intel_events(
            subscription_id=subscription.id,
            limit=200,
        ),
    )
    anchor_events = _visible_intel_events(
        request,
        database.list_story_timeline(story_id),
    )
    events = {
        event.id: event for event in [*candidate_events, *anchor_events]
    }
    return build_story_context_timeline(
        subscription,
        list(events.values()),
        current_story_id=story_id,
        story_relations=database.list_story_relations(story_id),
        window_days=days,
    )


@router.get("/api/stories/{story_id}")
async def get_story(story_id: str, request: Request):
    database = _database(request)
    story = database.get_story(story_id)
    if story is None:
        raise HTTPException(status_code=404, detail="Story not found")
    documents = database.list_story_documents(story_id)
    relations = database.list_story_relations(story_id)
    related_story_ids = {
        relation.to_story_id
        if relation.from_story_id == story_id
        else relation.from_story_id
        for relation in relations
    }
    return {
        "story": story,
        "relations": relations,
        "related_stories": [
            related_story
            for related_story_id in sorted(related_story_ids)
            if (related_story := database.get_story(related_story_id))
            is not None
        ],
        "documents": documents,
        "watch": database.get_story_watch(story_id),
        "evidence_chain_count": len(
            {document.evidence_chain_id for document in documents}
        ),
    }


@router.get("/api/story-watches")
async def list_story_watches(
    request: Request,
    subscription_id: str | None = None,
    enabled: bool | None = None,
):
    return _database(request).list_story_watches(
        subscription_id=subscription_id,
        enabled=enabled,
    )


@router.get("/api/story-watches/overview")
async def story_watch_overview(
    subscription_id: str,
    request: Request,
):
    database = _database(request)
    if database.get_subscription(subscription_id) is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return build_story_tracking_overview(database, subscription_id)


@router.put("/api/stories/{story_id}/watch")
async def upsert_story_watch(
    story_id: str,
    payload: StoryWatchUpsert,
    request: Request,
):
    try:
        return _database(request).upsert_story_watch(story_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Story not found") from exc


@router.post("/api/stories/{story_id}/watch/check", status_code=202)
async def check_story_watch(story_id: str, request: Request):
    database = _database(request)
    watch = database.get_story_watch(story_id)
    if watch is None:
        raise HTTPException(status_code=404, detail="Story watch not found")
    if not watch.enabled:
        raise HTTPException(status_code=409, detail="Story watch is paused")
    try:
        run, _ = trigger_story_watch(
            database,
            _runtime(request),
            watch,
            trigger="manual",
            actor={"type": "user", "id": "local_user"},
        )
    except StoryWatchRunActive as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Story research is already running",
                "run_id": exc.run.id,
            },
        ) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Story not found") from exc
    return run


@router.get("/api/stories/{story_id}/timeline")
async def get_story_timeline(story_id: str, request: Request):
    database = _database(request)
    if database.get_story(story_id) is None:
        raise HTTPException(status_code=404, detail="Story not found")
    return _visible_intel_events(
        request,
        database.list_story_timeline(story_id),
    )


@router.get("/api/intel-events/{intel_event_id}/feedback")
async def list_intel_feedback(intel_event_id: str, request: Request):
    database = _database(request)
    if database.get_intel_event(intel_event_id) is None:
        raise HTTPException(
            status_code=404, detail="Intel event not found"
        )
    return database.list_feedback(
        intel_event_id=intel_event_id
    )


@router.post(
    "/api/intel-events/{intel_event_id}/feedback",
    status_code=201,
)
async def create_intel_feedback(
    intel_event_id: str,
    payload: IntelFeedbackCreate,
    request: Request,
):
    try:
        return _database(request).create_feedback(
            intel_event_id, payload
        )
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail="Intel event not found"
        ) from exc


@router.delete(
    "/api/intel-events/{intel_event_id}/feedback/{feedback_type}",
    status_code=204,
)
async def delete_intel_feedback(
    intel_event_id: str,
    feedback_type: str,
    request: Request,
    target: str | None = None,
):
    if not _database(request).delete_feedback(
        intel_event_id,
        feedback_type,
        target=target,
    ):
        raise HTTPException(status_code=404, detail="Feedback not found")


@router.get("/api/subscriptions/{subscription_id}/preferences")
async def get_subscription_preferences(
    subscription_id: str,
    request: Request,
):
    database = _database(request)
    if database.get_subscription(subscription_id) is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return database.get_subscription_preferences(subscription_id)


@router.put("/api/subscriptions/{subscription_id}/preferences")
async def update_subscription_preferences(
    subscription_id: str,
    payload: SubscriptionPreferencesUpdate,
    request: Request,
):
    database = _database(request)
    if database.get_subscription(subscription_id) is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return database.update_subscription_preferences(
        subscription_id, payload
    )


@router.get("/api/alerts")
async def list_alert_rules(
    request: Request,
    subscription_id: str | None = None,
):
    return _database(request).list_alert_rules(
        subscription_id=subscription_id
    )


@router.post("/api/alerts", status_code=201)
async def create_alert_rule(payload: AlertRuleCreate, request: Request):
    database = _database(request)
    if database.get_subscription(payload.subscription_id) is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return database.create_alert_rule(payload)


@router.get("/api/alerts/matches")
async def list_alert_matches(
    request: Request,
    subscription_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=200),
):
    return _database(request).list_alert_matches(
        subscription_id=subscription_id,
        limit=limit,
    )


@router.put("/api/alerts/{alert_id}")
async def update_alert_rule(
    alert_id: str,
    payload: AlertRuleCreate,
    request: Request,
):
    database = _database(request)
    if database.get_subscription(payload.subscription_id) is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    alert = database.update_alert_rule(alert_id, payload)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert


@router.get("/api/digests")
async def list_digests(
    request: Request,
    subscription_id: str | None = None,
    limit: int = Query(default=30, ge=1, le=100),
):
    return _database(request).list_digests(
        subscription_id=subscription_id,
        limit=limit,
    )


@router.get("/api/approvals")
async def list_approvals(request: Request, status: str | None = None):
    return _database(request).list_approvals(status=status)


@router.post("/api/approvals/{approval_id}/decisions")
async def resolve_approval(
    approval_id: str, payload: ApprovalDecision, request: Request
):
    try:
        return await _runtime(request).resolve_approval(approval_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Approval not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
