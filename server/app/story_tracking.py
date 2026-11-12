from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domain.models import (
    Run,
    StoryTrackingOverview,
    StoryTrackingSignal,
    StoryWatch,
    StoryWeeklyRewind,
    utc_now,
)
from app.harness.runtime import AgentRuntime
from app.persistence.database import Database


DEEP_DIVE_FOCUS_GOALS = {
    "comprehensive": "补充背景、最新进展、官方来源、不同观点和待确认问题",
    "latest": "优先确认最新进展、后续动作、时间节点和实质变化",
    "official": "优先寻找官方声明、当事方回应、原始文件和一手资料",
    "perspectives": "优先梳理不同参与方观点、争议焦点、支持与冲突证据",
    "background": "优先回溯事件起因、关键节点、相关主体和历史背景",
}


class StoryWatchRunActive(RuntimeError):
    def __init__(self, run: Run):
        super().__init__("A story research run is already active")
        self.run = run


def build_story_research_goal(
    story_title: str,
    research_focus: str,
    research_question: str | None = None,
) -> str:
    goal = (
        f"围绕持续故事「{story_title}」进行深度研究，"
        f"{DEEP_DIVE_FOCUS_GOALS[research_focus]}"
    )
    if research_question:
        goal += f"；重点回答：{research_question.strip()}"
    return f"{goal}。"


def trigger_story_watch(
    database: Database,
    runtime: AgentRuntime,
    watch: StoryWatch,
    *,
    trigger: str,
    actor: dict[str, str],
    checked_at: datetime | None = None,
    idempotency_key: str | None = None,
) -> tuple[Run, bool]:
    active_run = database.get_active_story_run(watch.story_id)
    if active_run is not None:
        raise StoryWatchRunActive(active_run)
    story = database.get_story(watch.story_id)
    if story is None or story.subscription_id != watch.subscription_id:
        raise KeyError(watch.story_id)
    run = database.create_run(
        subscription_id=watch.subscription_id,
        trigger=trigger,
        goal=build_story_research_goal(
            story.canonical_title,
            watch.research_focus,
            watch.question,
        ),
        research_mode="deep_dive",
        story_id=watch.story_id,
        research_focus=watch.research_focus,
        research_question=watch.question,
        delivery_mode="web_inbox",
        idempotency_key=idempotency_key,
    )
    if database.list_events(run.id):
        return run, False
    database.append_event(
        run.id,
        "run.created",
        actor=actor,
        payload={
            "subscription_id": watch.subscription_id,
            "research_mode": "deep_dive",
            "story_id": watch.story_id,
            "research_focus": watch.research_focus,
            "research_question": watch.question,
            "story_watch_id": watch.id,
            "delivery_mode": "web_inbox",
        },
    )
    database.mark_story_watch_triggered(
        watch.id,
        run.id,
        checked_at=checked_at,
    )
    runtime.start(run.id)
    return run, True


def build_story_tracking_overview(
    database: Database,
    subscription_id: str,
    *,
    now: datetime | None = None,
) -> StoryTrackingOverview:
    generated_at = _aware_utc(now or utc_now())
    window_start = generated_at - timedelta(days=7)
    watches = {
        watch.story_id: watch
        for watch in database.list_story_watches(
            subscription_id=subscription_id,
            enabled=True,
        )
    }
    signals: list[
        tuple[StoryTrackingSignal, bool, bool, bool, bool]
    ] = []
    for story in database.list_stories(
        subscription_id=subscription_id,
        limit=200,
    ):
        event = database.get_intel_event(story.current_intel_event_id)
        if event is None:
            continue
        watch = watches.get(story.id)
        story_latest_at = _aware_utc(story.latest_event_at)
        story_first_at = _aware_utc(story.first_event_at)
        timeline = database.list_story_timeline(story.id)
        documents = database.list_story_documents(story.id)
        evidence_chain_count = len(
            {document.evidence_chain_id for document in documents}
        )
        official_source = next(
            (
                source.publisher
                for source in event.sources
                if "official" in source.source_type.casefold()
            ),
            None,
        )
        if official_source is None and any(
            document.relation_type == "official" for document in documents
        ):
            official_source = next(
                (
                    document.attributed_source
                    for document in documents
                    if document.relation_type == "official"
                    and document.attributed_source
                ),
                "已识别官方来源",
            )
        last_run = (
            database.get_run(watch.last_run_id)
            if watch and watch.last_run_id
            else None
        )
        active_run = (
            database.get_active_story_run(story.id) if watch else None
        )
        result = last_run.result if last_run and last_run.result else {}
        raw_item_count = result.get("item_count")
        last_run_item_count = (
            max(0, int(raw_item_count))
            if isinstance(raw_item_count, (int, float))
            else None
        )
        attention = (
            event.verification_status in {"unconfirmed", "conflicting"}
            or evidence_chain_count == 0
            or (last_run is not None and last_run.status.value == "failed")
        )
        new_progress = bool(
            watch
            and (
                last_run_item_count is not None
                and last_run_item_count > 0
                and last_run is not None
                and _aware_utc(last_run.updated_at) >= window_start
            )
        ) or bool(
            watch
            and len(timeline) > 1
            and story_latest_at >= window_start
        )
        new_story = story_first_at >= window_start
        no_change = bool(
            watch
            and last_run is not None
            and last_run.status.value == "completed"
            and last_run_item_count == 0
        )
        waiting = bool(watch and (active_run is not None or last_run is None))
        if active_run is not None:
            tracking_status = "checking"
        elif last_run is not None and last_run.status.value == "failed":
            tracking_status = "failed"
        elif new_progress:
            tracking_status = "new_progress"
        elif attention:
            tracking_status = "attention"
        elif no_change:
            tracking_status = "no_change"
        elif watch:
            tracking_status = "waiting"
        else:
            tracking_status = "untracked"
        question = watch.question if watch else _next_story_question(
            evidence_chain_count=evidence_chain_count,
            official_source=official_source,
            verification_status=event.verification_status,
        )
        signal = StoryTrackingSignal(
            story_id=story.id,
            subscription_id=subscription_id,
            watch_id=watch.id if watch else None,
            title=event.title,
            summary=event.summary,
            question=question,
            latest_event_at=story_latest_at,
            change_summary=event.change_summary,
            verification_status=event.verification_status,
            event_count=max(1, len(timeline)),
            fact_count=len(event.facts),
            evidence_chain_count=evidence_chain_count,
            has_official_source=official_source is not None,
            official_source=official_source,
            last_run_id=last_run.id if last_run else None,
            last_run_status=last_run.status.value if last_run else None,
            last_run_item_count=last_run_item_count,
            last_checked_at=watch.last_checked_at if watch else None,
            tracking_status=tracking_status,
        )
        signals.append((signal, new_progress, new_story, attention, no_change))

    def newest(items: list[StoryTrackingSignal]) -> list[StoryTrackingSignal]:
        return sorted(items, key=lambda item: item.latest_event_at, reverse=True)

    watched_signals = [item[0] for item in signals if item[0].watch_id]
    new_progress_items = newest([item[0] for item in signals if item[1]])
    new_story_items = newest([item[0] for item in signals if item[2]])
    attention_items = newest(
        [item[0] for item in signals if item[0].watch_id and item[3]]
    )
    waiting_items = newest(
        [
            item
            for item in watched_signals
            if item.tracking_status in {"checking", "waiting"}
        ]
    )
    no_change_items = newest(
        [item[0] for item in signals if item[0].watch_id and item[4]]
    )
    highlight_by_story: dict[str, StoryTrackingSignal] = {}
    for item in new_progress_items + new_story_items + attention_items:
        highlight_by_story.setdefault(item.story_id, item)
    checked_story_count = len(
        [
            watch
            for watch in watches.values()
            if watch.last_checked_at
            and _aware_utc(watch.last_checked_at) >= window_start
        ]
    )
    return StoryTrackingOverview(
        subscription_id=subscription_id,
        generated_at=generated_at,
        new_progress=new_progress_items,
        new_stories=new_story_items,
        attention_needed=attention_items,
        waiting_answers=waiting_items,
        no_change=no_change_items,
        weekly_rewind=StoryWeeklyRewind(
            window_start=window_start,
            tracked_story_count=len(watches),
            progressed_story_count=len(
                {item.story_id for item in new_progress_items}
            ),
            new_story_count=len({item.story_id for item in new_story_items}),
            attention_story_count=len(
                {item.story_id for item in attention_items}
            ),
            no_change_story_count=len(
                {item.story_id for item in no_change_items}
            ),
            checked_story_count=checked_story_count,
            highlights=list(highlight_by_story.values())[:5],
        ),
    )


def _next_story_question(
    *,
    evidence_chain_count: int,
    official_source: str | None,
    verification_status: str,
) -> str:
    if verification_status == "conflicting":
        return "冲突证据的关键分歧是什么，后续事实会支持哪一方？"
    if verification_status == "unconfirmed":
        return "当前说法还需要哪些直接证据确认？"
    if official_source is None:
        return "是否会出现官方、当事方或一手资料确认当前变化？"
    if evidence_chain_count < 2:
        return "能否找到第二条相互独立的证据链进行交叉验证？"
    return "下一次实质变化会发生在什么时间，由哪一方首先披露？"


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
