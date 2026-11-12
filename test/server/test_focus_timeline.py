from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.domain.focus_timeline import build_story_context_timeline
from app.domain.models import (
    IntelEvent,
    IntelEventDraft,
    IntelFact,
    IntelSource,
    Subscription,
)
from app.main import create_app


NOW = datetime(2026, 8, 3, 10, 0, tzinfo=timezone.utc)


def _subscription(
    name: str,
    *,
    focus_type: str,
) -> Subscription:
    return Subscription(
        id=f"sub-{focus_type}",
        name=name,
        slug=f"focus-{focus_type}",
        topic=f"持续关注{name}的公开动态",
        include_keywords=[name],
        exclude_keywords=[],
        languages=["zh-CN"],
        lookback_hours=720,
        max_items=20,
        minimum_importance=6.0,
        schedule_label="每天 09:00",
        accent="#6366f1",
        focus_type=focus_type,
        enabled=True,
        created_at=NOW,
        updated_at=NOW,
    )


def _event(
    title: str,
    *,
    story_id: str,
    days_ago: int,
    tags: list[str],
    category: str = "news",
) -> IntelEvent:
    event_time = NOW - timedelta(days=days_ago)
    return IntelEvent(
        id=f"intel-{story_id}-{days_ago}",
        story_id=story_id,
        run_id="run-timeline",
        subscription_id="sub-person",
        title=title,
        summary=f"{title}的公开报道摘要。",
        category=category,
        tags=tags,
        event_time=event_time,
        importance_score=7.0,
        importance_reason="与关注主体直接相关。",
        confidence_level="medium",
        confidence_score=0.8,
        confidence_reason="存在公开来源。",
        verification_status="partially_confirmed",
        facts=[IntelFact(text=title, source_ids=[f"source-{story_id}"])],
        source_ids=[f"source-{story_id}"],
        first_seen_at=event_time,
        created_at=event_time,
    )


def test_person_timeline_centers_the_current_story_topic():
    subscription = _subscription("林舟", focus_type="person")
    events = [
        _event(
            "林舟确认复出时间，开始恢复合练",
            story_id="return",
            days_ago=3,
            tags=["林舟", "复出", "海港俱乐部"],
        ),
        _event(
            "海港队战平对手，林舟替补登场",
            story_id="match",
            days_ago=1,
            tags=["林舟", "比赛", "海港俱乐部"],
        ),
        _event(
            "前队友评价林舟是球队榜样",
            story_id="comment",
            days_ago=2,
            tags=["林舟", "评价"],
        ),
        _event(
            "协会举办活动致敬林舟",
            story_id="tribute",
            days_ago=4,
            tags=["林舟", "致敬"],
            category="event",
        ),
        _event(
            "俱乐部商业收入增长，林舟效应受到关注",
            story_id="effect",
            days_ago=5,
            tags=["林舟", "俱乐部", "商业"],
        ),
        _event(
            "林舟参加赛季首场比赛",
            story_id="old",
            days_ago=31,
            tags=["林舟", "比赛"],
        ),
    ]

    timeline = build_story_context_timeline(
        subscription,
        events,
        current_story_id="match",
        window_days=30,
        now=NOW,
    )

    assert timeline.current_story_id == "match"
    assert timeline.subject == "林舟"
    assert timeline.topic == "海港俱乐部 · 比赛"
    assert timeline.counts.model_dump() == {
        "core": 1,
        "related": 1,
        "context": 3,
    }
    assert {item.story_id for item in timeline.items} == {
        "return",
        "match",
        "comment",
        "tribute",
        "effect",
    }
    by_story = {item.story_id: item for item in timeline.items}
    assert by_story["return"].tier == "related"
    assert by_story["match"].tier == "core"
    assert by_story["match"].reason == "current_story_anchor"
    assert by_story["comment"].tier == "context"
    assert by_story["tribute"].tier == "context"
    assert by_story["effect"].tier == "context"


def test_late_forecast_is_shown_below_the_fact_that_already_resolved_it():
    subscription = _subscription("林舟", focus_type="person")
    stale_forecast = _event(
        "林舟复出时间曝光，新队友称赞其表现",
        story_id="return-forecast",
        days_ago=0,
        tags=["林舟", "复出", "海港俱乐部"],
    ).model_copy(
        update={
            "confidence_score": 0.55,
            "confidence_level": "low",
            "verification_status": "unconfirmed",
            "sources": [
                IntelSource(
                    source_id="source-return-forecast",
                    title="林舟复出时间曝光",
                    url="https://example.com/return-forecast",
                    publisher="聚合来源",
                    source_type="aggregator",
                    published_at=NOW,
                    content="林舟复出时间曝光",
                    content_origin="feed",
                    word_count=12,
                )
            ],
        }
    )
    realized = _event(
        "海港队战平对手，林舟替补登场",
        story_id="match-result",
        days_ago=2,
        tags=["林舟", "比赛", "海港俱乐部"],
    ).model_copy(
        update={
            "confidence_score": 0.9,
            "confidence_level": "high",
            "verification_status": "confirmed",
        }
    )

    timeline = build_story_context_timeline(
        subscription,
        [stale_forecast, realized],
        current_story_id=stale_forecast.story_id,
        now=NOW,
    )

    assert [item.story_id for item in timeline.items] == [
        realized.story_id,
        stale_forecast.story_id,
    ]
    by_story = {item.story_id: item for item in timeline.items}
    assert by_story[realized.story_id].tier == "core"
    assert by_story[realized.story_id].temporal_status == "resolution"
    assert by_story[stale_forecast.story_id].tier == "related"
    assert by_story[stale_forecast.story_id].relation == "resolved_by"
    assert by_story[stale_forecast.story_id].temporal_status == "superseded"
    assert (
        by_story[stale_forecast.story_id].resolved_by_story_id
        == realized.story_id
    )


def test_industry_timeline_uses_current_topic_and_omits_unrelated_items():
    subscription = _subscription("机器人", focus_type="industry")
    subscription.include_keywords = ["机器人", "人形机器人", "具身智能"]
    events = [
        _event(
            "中国具身智能融资潮持续，资本聚焦头部赛道",
            story_id="funding",
            days_ago=0,
            tags=["机器人", "具身智能", "融资", "资本"],
            category="funding",
        ),
        _event(
            "智元创新启动上市辅导，人形机器人资本竞速",
            story_id="listing",
            days_ago=1,
            tags=["机器人", "人形机器人", "智元创新", "上市"],
            category="funding",
        ),
        _event(
            "人形机器人进入量产元年，减速器企业接受考验",
            story_id="production",
            days_ago=2,
            tags=["机器人", "人形机器人", "量产", "供应链"],
        ),
        _event(
            "Google DeepMind 发布具身智能模型",
            story_id="model",
            days_ago=3,
            tags=["机器人", "具身智能", "Google DeepMind", "模型"],
            category="technology",
        ),
        _event(
            "仓储自动化系统完成全国升级",
            story_id="warehouse",
            days_ago=4,
            tags=["机器人", "仓储自动化", "物流", "系统"],
            category="technology",
        ),
    ]

    timeline = build_story_context_timeline(
        subscription,
        events,
        current_story_id="funding",
        now=NOW,
    )
    by_story = {item.story_id: item for item in timeline.items}

    assert timeline.subject == "机器人"
    assert timeline.topic == "具身智能 · 融资"
    assert by_story["funding"].tier == "core"
    assert by_story["listing"].tier == "core"
    assert by_story["production"].tier == "related"
    assert by_story["model"].tier == "context"
    assert "warehouse" not in by_story


def test_company_timeline_keeps_subscription_only_as_candidate_scope():
    subscription = _subscription("星河科技", focus_type="company")
    events = [
        _event(
            "星河科技发布新一代推理平台",
            story_id="launch",
            days_ago=1,
            tags=["星河科技", "发布"],
            category="technology",
        ),
        _event(
            "分析师评价星河科技的新平台战略",
            story_id="analysis",
            days_ago=2,
            tags=["星河科技", "评价"],
        ),
        _event(
            "供应商订单增加，星河科技效应向产业链扩散",
            story_id="supply-chain",
            days_ago=3,
            tags=["星河科技", "供应商"],
        ),
    ]
    for event in events:
        event.subscription_id = subscription.id

    timeline = build_story_context_timeline(
        subscription,
        events,
        current_story_id="launch",
        now=NOW,
    )
    by_story = {item.story_id: item for item in timeline.items}

    assert by_story["launch"].tier == "core"
    assert timeline.topic == "技术"
    assert by_story["analysis"].tier == "context"
    assert by_story["supply-chain"].tier == "context"


def test_multi_event_story_remains_a_follow_up_inside_story_context_timeline():
    subscription = _subscription("林舟", focus_type="person")
    events = [
        _event(
            "林舟宣布复出时间",
            story_id="return",
            days_ago=3,
            tags=["林舟", "复出"],
        ),
        _event(
            "林舟复出后首次首发",
            story_id="return",
            days_ago=1,
            tags=["林舟", "复出", "首发"],
        ),
    ]

    timeline = build_story_context_timeline(
        subscription,
        events,
        current_story_id="return",
        now=NOW,
    )

    assert len(timeline.items) == 1
    assert timeline.items[0].event_count == 2
    assert timeline.items[0].relation == "follow_up"


@pytest.mark.asyncio
async def test_story_context_timeline_api_validates_story_and_window(harness):
    settings, database, _, _ = harness
    subscription = next(
        item
        for item in database.list_subscriptions()
        if item.slug == "ai-agent"
    )
    run = database.create_run(
        subscription_id=subscription.id,
        trigger="manual",
        goal="保存当前新闻故事脉络事件",
        delivery_mode="web_inbox",
        idempotency_key=None,
    )
    saved_event = database.save_intel_events(
        run.id,
        subscription.id,
        [
            IntelEventDraft(
                title="AI Agent 平台发布新的任务编排能力",
                summary="AI Agent 平台增加任务编排能力。",
                category="technology",
                tags=["AI Agent", "任务编排"],
                event_time=datetime.now(timezone.utc),
                importance_score=7.2,
                importance_reason="影响 Agent 工程实践。",
                confidence_level="medium",
                confidence_score=0.8,
                confidence_reason="存在公开来源。",
                verification_status="partially_confirmed",
                facts=[
                    IntelFact(
                        text="平台发布任务编排能力。",
                        source_ids=["source-timeline-api"],
                    )
                ],
                source_ids=["source-timeline-api"],
            )
        ],
    )[0]

    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            response = await client.get(
                f"/api/stories/{saved_event.story_id}/context-timeline",
                params={"days": 30},
            )
            assert response.status_code == 200
            payload = response.json()
            assert payload["subscription_id"] == subscription.id
            assert payload["current_story_id"] == saved_event.story_id
            assert payload["topic"] == "任务编排 · 技术"
            assert payload["window_days"] == 30
            assert payload["counts"]["core"] == 1
            assert payload["items"][0]["tier"] == "core"

            missing = await client.get(
                "/api/stories/missing/context-timeline"
            )
            assert missing.status_code == 404

            invalid_window = await client.get(
                f"/api/stories/{saved_event.story_id}/context-timeline",
                params={"days": 120},
            )
            assert invalid_window.status_code == 422
