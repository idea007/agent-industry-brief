from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from app.domain.focus import infer_focus_domain, infer_focus_type
from app.domain.models import (
    IntelEventDraft,
    IntelFact,
    IntelSource,
    SubscriptionCreate,
    utc_now,
)
from app.persistence.database import Database


def subscription_by_slug(database, slug: str):
    return next(
        subscription
        for subscription in database.list_subscriptions()
        if subscription.slug == slug
    )


def legacy_document(source_id: str, url: str) -> dict:
    return {
        "source_id": source_id,
        "title": "同一篇候选新闻",
        "url": url,
        "publisher": "Example News",
        "source_type": "industry",
        "published_at": "2026-07-26T00:00:00+00:00",
        "body": "用于验证历史扫描候选新闻迁移和 URL 去重。",
        "content_origin": "feed",
        "word_count": 24,
        "reliability": 0.8,
        "safety_flags": [],
    }


def test_initialize_migrates_legacy_custom_focus_types(tmp_path: Path):
    database_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE subscriptions (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                slug TEXT NOT NULL UNIQUE,
                topic TEXT NOT NULL,
                include_keywords TEXT NOT NULL,
                exclude_keywords TEXT NOT NULL,
                languages TEXT NOT NULL,
                lookback_hours INTEGER NOT NULL,
                max_items INTEGER NOT NULL,
                minimum_importance REAL NOT NULL,
                schedule_label TEXT NOT NULL,
                accent TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        now = utc_now().isoformat()
        rows = [
            (
                "sub_football",
                "足球",
                "custom-football",
                "持续追踪足球",
                '["梅西", "世界杯"]',
            ),
            (
                "sub_research",
                "前沿观察",
                "custom-research",
                "持续追踪前沿观察",
                '["新进展"]',
            ),
            (
                "sub_jokes",
                "段子",
                "custom-jokes",
                "持续追踪段子",
                '["搞笑", "抖机灵"]',
            ),
            (
                "sub_xiaomi_su7",
                "小米 SU7",
                "custom-xiaomi-su7",
                "持续追踪小米 SU7",
                '["小米汽车", "汽车"]',
            ),
        ]
        connection.executemany(
            """
            INSERT INTO subscriptions (
                id, name, slug, topic, include_keywords, exclude_keywords,
                languages, lookback_hours, max_items, minimum_importance,
                schedule_label, accent, enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, '[]', '["zh-CN", "en"]', 72, 12,
                      6, '每天 09:00', '#6366f1', 1, ?, ?)
            """,
            [(*row, now, now) for row in rows],
        )

    database = Database(database_path)
    database.initialize()
    database.initialize()

    subscriptions = {
        subscription.slug: subscription
        for subscription in database.list_subscriptions()
    }
    assert subscriptions["custom-football"].focus_type == "sports"
    assert subscriptions["custom-research"].focus_type == "industry"
    assert subscriptions["custom-jokes"].focus_type == "entertainment"
    assert subscriptions["custom-xiaomi-su7"].focus_type == "product"
    assert "内容本身" in subscriptions["custom-jokes"].topic
    assert "相关新闻" in subscriptions["custom-jokes"].topic


def test_focus_inference_distinguishes_product_models_from_years():
    assert infer_focus_type("小米 SU7", ["小米汽车", "汽车"]) == "product"
    assert infer_focus_type("Trend 2026", ["行业趋势"]) == "industry"
    assert infer_focus_type("梅西", ["足球", "迈阿密国际"]) == "person"
    assert infer_focus_type("阿根廷国家队", ["足球"]) == "team"
    assert (
        infer_focus_domain(
            "小米 SU7",
            ["小米汽车", "汽车"],
            infer_focus_type("小米 SU7", ["小米汽车", "汽车"]),
        )
        == "automotive"
    )


def test_create_subscription_upgrades_generic_content_goal(tmp_path: Path):
    database = Database(tmp_path / "content-goal.sqlite3")
    database.initialize()

    jokes = database.create_subscription(
        SubscriptionCreate(
            name="段子",
            slug="custom-fresh-jokes",
            topic="持续发现 段子 的最新公开内容与动态",
            include_keywords=["段子", "搞笑"],
            focus_type="auto",
        )
    )

    assert jokes.focus_type == "entertainment"
    assert "可直接阅读或观看" in jokes.topic
    assert "创作者原帖" in jokes.topic
    assert "不只追踪相关新闻" in jokes.topic


def test_initialize_migrates_existing_entertainment_focus_once(tmp_path: Path):
    database = Database(tmp_path / "existing-focus.sqlite3")
    database.initialize()
    jokes = database.create_subscription(
        SubscriptionCreate(
            name="段子",
            slug="custom-existing-jokes",
            topic="持续追踪段子和搞笑内容",
            include_keywords=["搞笑", "抖机灵"],
            focus_type="industry",
        )
    )
    with database.connect() as connection:
        connection.execute(
            "DELETE FROM data_migrations "
            "WHERE name = '2026-08-01-custom-entertainment-focus'"
        )

    database.initialize()
    assert database.get_subscription(jokes.id).focus_type == "entertainment"

    with database.connect() as connection:
        connection.execute(
            "UPDATE subscriptions SET focus_type = 'industry' WHERE id = ?",
            (jokes.id,),
        )
    database.initialize()
    assert database.get_subscription(jokes.id).focus_type == "industry"


def test_initialize_migrates_existing_product_focus_once(tmp_path: Path):
    database = Database(tmp_path / "existing-product-focus.sqlite3")
    database.initialize()
    product = database.create_subscription(
        SubscriptionCreate(
            name="小米 SU7",
            slug="custom-existing-xiaomi-su7",
            topic="持续发现小米 SU7 的最新公开内容与动态",
            include_keywords=["小米汽车", "汽车"],
            focus_type="industry",
        )
    )
    with database.connect() as connection:
        connection.execute(
            "DELETE FROM data_migrations "
            "WHERE name = '2026-08-04-custom-product-focus'"
        )

    database.initialize()
    migrated = database.get_subscription(product.id)
    assert migrated is not None
    assert migrated.focus_type == "product"

    with database.connect() as connection:
        connection.execute(
            "UPDATE subscriptions SET focus_type = 'industry' WHERE id = ?",
            (product.id,),
        )
    database.initialize()
    unchanged = database.get_subscription(product.id)
    assert unchanged is not None
    assert unchanged.focus_type == "industry"


def test_initialize_backfills_legacy_search_results_idempotently(harness):
    _, database, _, _ = harness
    subscription = subscription_by_slug(database, "ai-agent")
    first_run = database.create_run(
        subscription_id=subscription.id,
        trigger="manual",
        goal="迁移历史候选新闻一",
        delivery_mode="web_inbox",
        idempotency_key=None,
    )
    second_run = database.create_run(
        subscription_id=subscription.id,
        trigger="manual",
        goal="迁移历史候选新闻二",
        delivery_mode="web_inbox",
        idempotency_key=None,
    )
    first_call = database.create_tool_call(
        first_run.id, "search_sources", {}, "legacy"
    )
    second_call = database.create_tool_call(
        second_run.id, "search_sources", {}, "legacy"
    )
    database.update_tool_call(
        first_call,
        status="completed",
        result={
            "documents": [
                legacy_document(
                    "legacy_source_1",
                    "https://example.com/news?id=7&utm_source=radar#top",
                )
            ]
        },
    )
    database.update_tool_call(
        second_call,
        status="completed",
        result={
            "documents": [
                legacy_document(
                    "legacy_source_2",
                    "https://example.com/news?id=7",
                )
            ]
        },
    )

    database.initialize()
    database.initialize()

    documents = database.list_source_documents(
        subscription_id=subscription.id
    )
    assert len(documents) == 1
    assert documents[0].canonical_url == "https://example.com/news?id=7"
    assert documents[0].seen_count == 2
    assert len(database.list_run_documents(first_run.id)) == 1
    assert len(database.list_run_documents(second_run.id)) == 1


def test_source_runtime_health_degrades_and_recovers(harness):
    _, database, _, _ = harness
    subscription = subscription_by_slug(database, "ai-agent")
    for _ in range(3):
        changes = database.record_source_runtime_updates(
            subscription.id,
            [
                {
                    "source_key": "official-feed",
                    "success": False,
                    "duration_ms": 120,
                }
            ],
        )

    state = database.list_source_runtime_states(
        subscription_id=subscription.id
    )[0]
    assert state.health_status == "degraded"
    assert state.consecutive_failures == 3
    assert changes == [
        {
            "source_key": "official-feed",
            "from": "healthy",
            "to": "degraded",
        }
    ]

    changes = database.record_source_runtime_updates(
        subscription.id,
        [
            {
                "source_key": "official-feed",
                "success": True,
                "etag": '"v3"',
                "duration_ms": 60,
                "new_document_count": 2,
                "fulltext_success_count": 1,
            }
        ],
    )
    state = database.list_source_runtime_states(
        subscription_id=subscription.id
    )[0]
    assert state.health_status == "healthy"
    assert state.consecutive_failures == 0
    assert state.etag == '"v3"'
    assert state.new_document_count == 2
    assert state.fulltext_success_count == 1
    assert changes[0]["from"] == "degraded"
    assert changes[0]["to"] == "healthy"

    for _ in range(10):
        database.record_source_runtime_updates(
            subscription.id,
            [
                {
                    "source_key": "silent-feed",
                    "success": True,
                    "duration_ms": 20,
                }
            ],
        )
    states = {
        item.source_key: item
        for item in database.list_source_runtime_states(
            subscription_id=subscription.id
        )
    }
    assert states["silent-feed"].health_status == "stale"


def test_deferred_documents_and_query_metrics_are_persisted(harness):
    _, database, _, _ = harness
    subscription = subscription_by_slug(database, "ai-agent")
    run = database.create_run(
        subscription_id=subscription.id,
        trigger="manual",
        goal="验证证据池",
        delivery_mode="web_inbox",
        idempotency_key=None,
    )
    first = legacy_document(
        "evidence_source",
        "https://example.com/evidence",
    )
    first.update(
        {
            "configured_source_id": "query-source",
            "query_template_id": "query-product",
            "retrieval_channel": "ai_web_search",
            "source_group": "ai_search",
            "ranking_score": 0.88,
            "ranking_reasons": ["relevance:1.00"],
            "fetch_status": "fetched",
            "extraction_status": "feed_only",
        }
    )
    second = legacy_document(
        "deferred_source",
        "https://example.com/deferred",
    )
    second.update(
        {
            "configured_source_id": "query-source",
            "query_template_id": "query-product",
            "retrieval_channel": "ai_web_search",
            "source_group": "ai_search",
            "ranking_score": 0.55,
            "ranking_reasons": ["deferred:evidence_capacity"],
            "fetch_status": "fetched",
            "extraction_status": "feed_only",
        }
    )

    database.save_source_documents(
        run.id,
        subscription.id,
        [first, second],
        evidence_source_ids={"evidence_source"},
    )
    database.update_run_document_outcomes(run.id, {"evidence_source"})

    run_documents = database.list_run_documents(run.id)
    assert {document.last_outcome for document in run_documents} == {
        "selected",
        "deferred",
    }
    assert len(
        database.list_source_documents(
            subscription_id=subscription.id,
            outcome="deferred",
            retrieval_channel="ai_web_search",
        )
    ) == 1
    metrics = database.list_source_query_metrics(
        subscription_id=subscription.id
    )
    assert metrics == [
        {
            "query_template_id": "query-product",
            "discovery_count": 2,
            "new_document_count": 2,
            "evidence_count": 1,
            "selected_count": 1,
            "new_content_rate": 1.0,
            "evidence_rate": 0.5,
            "selection_rate": 1.0,
            "latest_published_at": "2026-07-26T00:00:00+00:00",
            "last_run_at": metrics[0]["last_run_at"],
        }
    ]


def test_legacy_event_and_source_categories_are_normalized_on_read(harness):
    _, database, _, _ = harness
    subscription = subscription_by_slug(database, "digital-human")
    run = database.create_run(
        subscription_id=subscription.id,
        trigger="manual",
        goal="验证历史分类兼容",
        delivery_mode="web_inbox",
        idempotency_key=None,
    )
    source = IntelSource(
        source_id="legacy_interview_source",
        title="WAIC 观察：数字人访谈成为现实",
        url="https://example.com/digital-human-interview",
        publisher="Example News",
        source_type="industry",
        published_at=utc_now(),
        content="这是一篇数字人行业访谈。",
        translated_content="这是一篇已保存的中文译文。",
    )
    draft = IntelEventDraft(
        title="WAIC 聚焦数字人产业进展",
        summary="大会集中展示数字人行业应用。",
        category="industry_update",
        tags=["数字人"],
        event_time=utc_now(),
        importance_score=7.5,
        importance_reason="反映行业集中发布与交流。",
        confidence_level="medium",
        confidence_score=0.78,
        confidence_reason="来源可信但仍需交叉验证。",
        verification_status="partially_confirmed",
        facts=[
            IntelFact(
                text="WAIC 展示了数字人行业应用。",
                source_ids=[source.source_id],
            )
        ],
        source_ids=[source.source_id],
        sources=[source],
    )
    saved = database.save_intel_events(
        run.id,
        subscription.id,
        [draft],
    )[0]
    legacy_source = source.model_dump(mode="json", exclude={"category"})
    with database.connect() as connection:
        connection.execute(
            """
            UPDATE intel_events
            SET category = ?, sources = ?
            WHERE id = ?
            """,
            (
                "industry_update",
                json.dumps([legacy_source], ensure_ascii=False),
                saved.id,
            ),
        )

    restored = database.list_intel_events(
        subscription_id=subscription.id
    )[0]

    assert restored.category == "event"
    assert restored.sources[0].category == "interview"
    assert restored.sources[0].translated_content == "这是一篇已保存的中文译文。"


async def _complete_fixture_run(harness):
    _, database, _, runtime = harness
    subscription = subscription_by_slug(database, "live2d")
    run = database.create_run(
        subscription_id=subscription.id,
        trigger="manual",
        goal="验证稳定事件去重",
        delivery_mode="web_inbox",
        idempotency_key=None,
    )
    await runtime.execute(run.id)
    return database, subscription


@pytest.mark.asyncio
async def test_intel_dedupe_is_independent_of_source_order(harness):
    database, subscription = await _complete_fixture_run(harness)
    existing = database.list_intel_events(subscription_id=subscription.id)[0]
    draft = IntelEventDraft.model_validate(
        existing.model_dump(
            exclude={
                "id",
                "run_id",
                "subscription_id",
                "first_seen_at",
                "created_at",
            }
        )
    ).model_copy(
        update={
            "source_ids": list(reversed(existing.source_ids)),
            "sources": list(reversed(existing.sources)),
        }
    )
    repeat = database.create_run(
        subscription_id=subscription.id,
        trigger="manual",
        goal="以不同来源顺序保存同一事件",
        delivery_mode="web_inbox",
        idempotency_key=None,
    )

    saved = database.save_intel_events(
        repeat.id,
        subscription.id,
        [draft],
    )

    assert saved[0].id == existing.id


def _story_draft(
    *,
    source_id: str,
    url: str,
    title: str,
    event_time: str,
    tags: list[str],
) -> IntelEventDraft:
    source = IntelSource(
        source_id=source_id,
        title=title,
        url=url,
        publisher="Example News",
        source_type="industry",
        published_at=datetime.fromisoformat(event_time),
        content=title,
        reliability=0.8,
    )
    return IntelEventDraft(
        title=title,
        summary="同一行业事件的不同媒体报道。",
        category="news",
        tags=tags,
        event_time=datetime.fromisoformat(event_time),
        importance_score=8.0,
        importance_reason="事件会影响行业进展。",
        confidence_level="medium",
        confidence_score=0.8,
        confidence_reason="存在来源支持。",
        verification_status="partially_confirmed",
        facts=[
            IntelFact(
                text=title,
                source_ids=[source_id],
            )
        ],
        source_ids=[source_id],
        sources=[source],
    )


def test_late_feed_syndication_reuses_the_existing_story(harness):
    _, database, _, _ = harness
    subscription = database.create_subscription(
        SubscriptionCreate(
            name="林舟",
            slug="custom-linzhou-syndication",
            topic="持续追踪林舟的比赛与公开动态",
            include_keywords=["林舟", "海港俱乐部"],
            focus_type="person",
        )
    )
    first_run = database.create_run(
        subscription_id=subscription.id,
        trigger="manual",
        goal="保存最早的复出报道",
        delivery_mode="web_inbox",
        idempotency_key=None,
    )
    repeat_run = database.create_run(
        subscription_id=subscription.id,
        trigger="manual",
        goal="保存晚到的重复转载",
        delivery_mode="web_inbox",
        idempotency_key=None,
    )
    first = database.save_intel_events(
        first_run.id,
        subscription.id,
        [
            _story_draft(
                source_id="return-feed-first",
                url="https://example.com/return/first",
                title="林舟复出时间曝光，海港新援赞誉其为球队榜样",
                event_time="2026-07-31T22:44:35+00:00",
                tags=["林舟", "海港俱乐部", "复出", "新援"],
            )
        ],
    )[0]
    repeat = database.save_intel_events(
        repeat_run.id,
        subscription.id,
        [
            _story_draft(
                source_id="return-feed-repeat",
                url="https://example.net/return/repeat",
                title="林舟复出时间曝光，获海港新援盛赞：球队榜样",
                event_time="2026-08-04T22:13:00+00:00",
                tags=["林舟", "海港俱乐部", "复出", "新援"],
            )
        ],
    )[0]

    assert repeat.story_id == first.story_id
    assert len(database.list_story_timeline(first.story_id)) == 2


def test_realized_fact_marks_a_late_forecast_stale_and_hides_it_from_feed(
    harness,
):
    _, database, _, _ = harness
    subscription = database.create_subscription(
        SubscriptionCreate(
            name="林舟",
            slug="custom-linzhou-lifecycle",
            topic="持续追踪林舟的比赛与公开动态",
            include_keywords=["林舟", "海港俱乐部"],
            focus_type="person",
        )
    )
    result_run = database.create_run(
        subscription_id=subscription.id,
        trigger="manual",
        goal="保存已经发生的比赛事实",
        delivery_mode="web_inbox",
        idempotency_key=None,
    )
    forecast_run = database.create_run(
        subscription_id=subscription.id,
        trigger="manual",
        goal="保存晚到的旧预测",
        delivery_mode="web_inbox",
        idempotency_key=None,
    )
    realized = database.save_intel_events(
        result_run.id,
        subscription.id,
        [
            _story_draft(
                source_id="match-result",
                url="https://example.com/match/result",
                title="海港队战平对手，林舟替补登场",
                event_time="2026-08-02T08:10:00+00:00",
                tags=["林舟", "海港俱乐部", "比赛"],
            ).model_copy(
                update={
                    "confidence_level": "high",
                    "confidence_score": 0.9,
                    "verification_status": "confirmed",
                }
            )
        ],
    )[0]
    stale_forecast = database.save_intel_events(
        forecast_run.id,
        subscription.id,
        [
            _story_draft(
                source_id="late-return-forecast",
                url="https://example.net/return/late",
                title="林舟复出时间曝光，海港新援称赞其表现",
                event_time="2026-08-04T22:13:00+00:00",
                tags=["林舟", "海港俱乐部", "复出", "新援"],
            ).model_copy(
                update={
                    "confidence_level": "low",
                    "confidence_score": 0.55,
                    "verification_status": "unconfirmed",
                }
            )
        ],
    )[0]

    assert database.get_story(stale_forecast.story_id).status == "stale"
    relations = database.list_story_relations(stale_forecast.story_id)
    lifecycle_relation = next(
        relation
        for relation in relations
        if relation.relation == "superseded_by"
    )
    assert lifecycle_relation.from_story_id == stale_forecast.story_id
    assert lifecycle_relation.to_story_id == realized.story_id
    visible = database.list_intel_events(
        subscription_id=subscription.id,
        include_stale_stories=False,
    )
    assert [event.id for event in visible] == [realized.id]
    assert stale_forecast.id in {
        event.id
        for event in database.list_intel_events(
            subscription_id=subscription.id,
            include_stale_stories=True,
        )
    }


def test_related_reports_share_story_without_rewriting_run_evidence(harness):
    _, database, _, _ = harness
    subscription = subscription_by_slug(database, "robot")
    first_run = database.create_run(
        subscription_id=subscription.id,
        trigger="manual",
        goal="保存第一篇事件报道",
        delivery_mode="web_inbox",
        idempotency_key=None,
    )
    second_run = database.create_run(
        subscription_id=subscription.id,
        trigger="manual",
        goal="保存另一家媒体的同事件报道",
        delivery_mode="web_inbox",
        idempotency_key=None,
    )
    first = database.save_intel_events(
        first_run.id,
        subscription.id,
        [
            _story_draft(
                source_id="robot_source_1",
                url="https://example.com/robot/first",
                title="小鹏 IRON 人形机器人广州工厂开启试生产，年底冲刺量产",
                event_time="2026-07-26T07:40:00+00:00",
                tags=["小鹏", "IRON", "人形机器人", "试生产"],
            )
        ],
    )[0]
    second = database.save_intel_events(
        second_run.id,
        subscription.id,
        [
            _story_draft(
                source_id="robot_source_2",
                url="https://example.net/robot/follow-up",
                title="小鹏人形机器人 IRON 试生产，2027 年门店上岗",
                event_time="2026-07-26T09:00:00+00:00",
                tags=["小鹏", "IRON", "人形机器人", "试生产"],
            )
        ],
    )[0]

    assert first.id != second.id
    assert first.run_id == first_run.id
    assert second.run_id == second_run.id
    assert first.story_id == second.story_id


def test_different_actions_do_not_share_story(harness):
    _, database, _, _ = harness
    subscription = subscription_by_slug(database, "robot")
    first_run = database.create_run(
        subscription_id=subscription.id,
        trigger="manual",
        goal="保存量产事件",
        delivery_mode="web_inbox",
        idempotency_key=None,
    )
    second_run = database.create_run(
        subscription_id=subscription.id,
        trigger="manual",
        goal="保存召回事件",
        delivery_mode="web_inbox",
        idempotency_key=None,
    )
    first = database.save_intel_events(
        first_run.id,
        subscription.id,
        [
            _story_draft(
                source_id="production_source",
                url="https://example.com/robot/production",
                title="小鹏 IRON 人形机器人正式量产",
                event_time="2026-07-26T07:40:00+00:00",
                tags=["小鹏", "IRON", "人形机器人"],
            )
        ],
    )[0]
    second = database.save_intel_events(
        second_run.id,
        subscription.id,
        [
            _story_draft(
                source_id="recall_source",
                url="https://example.net/robot/recall",
                title="小鹏 IRON 人形机器人宣布召回",
                event_time="2026-07-26T09:00:00+00:00",
                tags=["小鹏", "IRON", "人形机器人"],
            )
        ],
    )[0]

    assert first.story_id != second.story_id


def test_deep_dive_can_append_a_new_event_to_target_story(harness):
    _, database, _, _ = harness
    subscription = subscription_by_slug(database, "robot")
    initial_run = database.create_run(
        subscription_id=subscription.id,
        trigger="manual",
        goal="建立持续故事",
        delivery_mode="web_inbox",
        idempotency_key=None,
    )
    initial = database.save_intel_events(
        initial_run.id,
        subscription.id,
        [
            _story_draft(
                source_id="target_story_source",
                url="https://example.com/robot/target",
                title="小鹏 IRON 人形机器人正式量产",
                event_time="2026-07-26T07:40:00+00:00",
                tags=["小鹏", "IRON", "人形机器人"],
            )
        ],
    )[0]
    deep_dive_run = database.create_run(
        subscription_id=subscription.id,
        trigger="manual",
        goal="深挖既有故事",
        research_mode="deep_dive",
        story_id=initial.story_id,
        research_focus="background",
        delivery_mode="web_inbox",
        idempotency_key=None,
    )
    follow_up = database.save_intel_events(
        deep_dive_run.id,
        subscription.id,
        [
            _story_draft(
                source_id="deep_dive_follow_up",
                url="https://example.net/interview/follow-up",
                title="公司管理层回应外界疑问并披露后续计划",
                event_time="2026-07-27T09:00:00+00:00",
                tags=["管理层", "回应"],
            )
        ],
        target_story_id=initial.story_id,
    )[0]

    persisted_run = database.get_run(deep_dive_run.id)
    assert persisted_run.research_mode == "deep_dive"
    assert persisted_run.story_id == initial.story_id
    assert persisted_run.research_focus == "background"
    assert follow_up.story_id == initial.story_id
    assert len(database.list_story_timeline(initial.story_id)) == 2


def test_initialize_backfills_missing_story_id(harness):
    _, database, _, _ = harness
    subscription = subscription_by_slug(database, "robot")
    run = database.create_run(
        subscription_id=subscription.id,
        trigger="manual",
        goal="验证 Story 迁移",
        delivery_mode="web_inbox",
        idempotency_key=None,
    )
    saved = database.save_intel_events(
        run.id,
        subscription.id,
        [
            _story_draft(
                source_id="migration_source",
                url="https://example.com/robot/migration",
                title="机器人事件迁移 Story 标识",
                event_time="2026-07-26T09:00:00+00:00",
                tags=["机器人", "迁移"],
            )
        ],
    )[0]
    with database.connect() as connection:
        connection.execute(
            "UPDATE intel_events SET story_id = NULL WHERE id = ?",
            (saved.id,),
        )

    database.initialize()

    restored = database.list_intel_events(
        subscription_id=subscription.id,
    )[0]
    assert restored.story_id.startswith("story_")
