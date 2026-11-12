from __future__ import annotations

import asyncio
from dataclasses import replace

import httpx
import pytest

from app.domain.models import RunStatus
from app.main import create_app


def subscription_by_slug(database, slug: str):
    return next(
        subscription
        for subscription in database.list_subscriptions()
        if subscription.slug == slug
    )


@pytest.mark.asyncio
async def test_deep_dive_run_requires_and_preserves_matching_story(harness):
    settings, database, _, runtime = harness
    subscription = subscription_by_slug(database, "live2d")
    seed_run = database.create_run(
        subscription_id=subscription.id,
        trigger="manual",
        goal="建立可深挖的持续故事",
        delivery_mode="web_inbox",
        idempotency_key=None,
    )
    await runtime.execute(seed_run.id)
    story = database.list_stories(subscription_id=subscription.id)[0]
    other_subscription = next(
        item
        for item in database.list_subscriptions()
        if item.id != subscription.id
    )

    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            missing_story = await client.post(
                "/api/runs",
                json={
                    "subscription_id": subscription.id,
                    "research_mode": "deep_dive",
                },
            )
            assert missing_story.status_code == 422

            monitor_with_story = await client.post(
                "/api/runs",
                json={
                    "subscription_id": subscription.id,
                    "research_mode": "monitor",
                    "story_id": story.id,
                },
            )
            assert monitor_with_story.status_code == 422

            monitor_with_focus = await client.post(
                "/api/runs",
                json={
                    "subscription_id": subscription.id,
                    "research_focus": "official",
                },
            )
            assert monitor_with_focus.status_code == 422

            monitor_with_question = await client.post(
                "/api/runs",
                json={
                    "subscription_id": subscription.id,
                    "research_question": "下一次官方回应是什么？",
                },
            )
            assert monitor_with_question.status_code == 422

            mismatched_story = await client.post(
                "/api/runs",
                json={
                    "subscription_id": other_subscription.id,
                    "research_mode": "deep_dive",
                    "story_id": story.id,
                },
            )
            assert mismatched_story.status_code == 409

            created = await client.post(
                "/api/runs",
                json={
                    "subscription_id": subscription.id,
                    "research_mode": "deep_dive",
                    "story_id": story.id,
                    "research_focus": "official",
                    "research_question": "下一次官方回应是什么？",
                    "delivery_mode": "web_inbox",
                },
            )
            assert created.status_code == 202
            assert created.json()["research_mode"] == "deep_dive"
            assert created.json()["story_id"] == story.id
            assert created.json()["research_focus"] == "official"
            assert created.json()["research_question"] == "下一次官方回应是什么？"
            assert story.canonical_title in created.json()["goal"]
            assert "官方声明" in created.json()["goal"]
            assert "下一次官方回应是什么" in created.json()["goal"]
            run_id = created.json()["id"]

            for _ in range(50):
                response = await client.get(f"/api/runs/{run_id}")
                if response.json()["status"] in {
                    RunStatus.COMPLETED.value,
                    RunStatus.FAILED.value,
                }:
                    break
                await asyncio.sleep(0.01)

            assert response.json()["status"] == RunStatus.COMPLETED.value
            assert response.json()["result"]["research_mode"] == "deep_dive"
            assert response.json()["result"]["story_id"] == story.id
            assert response.json()["result"]["research_focus"] == "official"
            assert response.json()["result"]["research_question"] == "下一次官方回应是什么？"
            history = await client.get(
                f"/api/runs/{run_id}/events/history"
            )
            assert history.json()[0]["payload"]["research_mode"] == "deep_dive"
            assert history.json()[0]["payload"]["story_id"] == story.id
            assert history.json()[0]["payload"]["research_focus"] == "official"
            assert history.json()[0]["payload"]["research_question"] == "下一次官方回应是什么？"


@pytest.mark.asyncio
async def test_story_watch_can_be_saved_checked_and_paused(harness):
    settings, database, _, runtime = harness
    subscription = subscription_by_slug(database, "live2d")
    seed_run = database.create_run(
        subscription_id=subscription.id,
        trigger="manual",
        goal="建立持续追踪故事",
        delivery_mode="web_inbox",
        idempotency_key=None,
    )
    await runtime.execute(seed_run.id)
    story = database.list_stories(subscription_id=subscription.id)[0]
    with database.connect() as connection:
        connection.execute(
            """
            UPDATE stories
            SET first_event_at = ?, latest_event_at = ?
            WHERE id = ?
            """,
            (
                story.first_event_at.replace(tzinfo=None).isoformat(),
                story.latest_event_at.replace(tzinfo=None).isoformat(),
                story.id,
            ),
        )

    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            saved = await client.put(
                f"/api/stories/{story.id}/watch",
                json={
                    "research_focus": "latest",
                    "question": "下一次产品更新会改变什么？",
                    "cadence": "manual",
                    "enabled": True,
                },
            )
            assert saved.status_code == 200
            assert saved.json()["story_id"] == story.id
            assert saved.json()["last_run_id"] is None

            dashboard = await client.get("/api/dashboard")
            assert dashboard.json()["story_watches"][0]["question"] == (
                "下一次产品更新会改变什么？"
            )
            detail = await client.get(f"/api/stories/{story.id}")
            assert detail.json()["watch"]["enabled"] is True
            overview = await client.get(
                "/api/story-watches/overview",
                params={"subscription_id": subscription.id},
            )
            assert overview.status_code == 200
            assert overview.json()["weekly_rewind"]["tracked_story_count"] == 1
            waiting_signal = overview.json()["waiting_answers"][0]
            assert waiting_signal["story_id"] == story.id
            assert waiting_signal["question"] == "下一次产品更新会改变什么？"
            assert {
                "fact_count",
                "evidence_chain_count",
                "has_official_source",
                "verification_status",
            }.issubset(waiting_signal)

            active_run = database.create_run(
                subscription_id=subscription.id,
                trigger="manual",
                goal="占用同一故事的研究任务",
                research_mode="deep_dive",
                story_id=story.id,
                research_focus="latest",
                delivery_mode="web_inbox",
                idempotency_key=None,
            )
            blocked = await client.post(
                f"/api/stories/{story.id}/watch/check"
            )
            assert blocked.status_code == 409
            assert blocked.json()["detail"]["run_id"] == active_run.id
            database.update_run(active_run.id, status=RunStatus.CANCELLED)

            checked = await client.post(
                f"/api/stories/{story.id}/watch/check"
            )
            assert checked.status_code == 202
            assert checked.json()["research_mode"] == "deep_dive"
            assert checked.json()["research_question"] == (
                "下一次产品更新会改变什么？"
            )
            run_id = checked.json()["id"]
            watch = database.get_story_watch(story.id)
            assert watch is not None
            assert watch.last_run_id == run_id
            assert watch.last_checked_at is not None

            for _ in range(50):
                response = await client.get(f"/api/runs/{run_id}")
                if response.json()["status"] in {
                    RunStatus.COMPLETED.value,
                    RunStatus.FAILED.value,
                }:
                    break
                await asyncio.sleep(0.01)
            assert response.json()["status"] == RunStatus.COMPLETED.value

            paused = await client.put(
                f"/api/stories/{story.id}/watch",
                json={
                    "research_focus": "latest",
                    "question": "下一次产品更新会改变什么？",
                    "cadence": "weekly",
                    "enabled": False,
                },
            )
            assert paused.status_code == 200
            assert paused.json()["enabled"] is False
            assert paused.json()["next_check_at"] is None
            rejected = await client.post(
                f"/api/stories/{story.id}/watch/check"
            )
            assert rejected.status_code == 409


@pytest.mark.asyncio
async def test_dashboard_and_manual_run(harness):
    settings, _, _, _ = harness
    app = create_app(settings)
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            dashboard = await client.get("/api/dashboard")
            assert dashboard.status_code == 200
            subscriptions = dashboard.json()["subscriptions"]
            assert dashboard.json()["system"]["runtime"] == {
                "max_concurrent_runs": 2,
                "active_run_count": 0,
                "queued_run_count": 0,
            }
            assert len(subscriptions) == 13
            assert len(
                [subscription for subscription in subscriptions if subscription["enabled"]]
            ) == 12

            profiles = await client.get("/api/source-profiles")
            assert profiles.status_code == 200
            assert len(profiles.json()) == 13
            ai_agent_profile = next(
                profile
                for profile in profiles.json()
                if profile["slug"] == "ai-agent"
            )
            assert ai_agent_profile["web_search"]["enabled"] is True
            assert all(
                {
                    "id",
                    "template",
                    "enabled",
                    "quota",
                    "priority",
                }.issubset(template)
                for template in ai_agent_profile["web_search"][
                    "query_templates"
                ]
            )
            assert len(ai_agent_profile["sources"]) >= 15
            assert {
                "forum",
                "funding",
                "capital_market",
                "event",
                "event_community",
            }.issubset(
                {
                    source["source_type"]
                    for source in ai_agent_profile["sources"]
                }
            )
            digital_human_profile = next(
                profile
                for profile in profiles.json()
                if profile["slug"] == "digital-human"
            )
            assert len(digital_human_profile["sources"]) >= 15
            assert digital_human_profile["web_search"]["max_queries"] == 8
            assert "AI主播说新闻" in digital_human_profile["exclude_keywords"]
            subscriptions_by_slug = {
                subscription["slug"]: subscription
                for subscription in subscriptions
            }
            for profile in profiles.json():
                subscription = subscriptions_by_slug[profile["slug"]]
                assert len(profile["sources"]) >= 15, profile["slug"]
                assert profile["web_search"]["max_queries"] == 8, profile["slug"]
                assert set(profile["exclude_keywords"]).issubset(
                    subscription["exclude_keywords"]
                ), profile["slug"]
                assert subscription["max_items"] >= 12, profile["slug"]

            custom_industry = await client.post(
                "/api/subscriptions",
                json={
                    "name": "空间机器人",
                    "slug": "custom-space-robot",
                    "topic": "持续追踪空间机器人行业",
                    "include_keywords": ["在轨服务", "机械臂", "商业航天"],
                },
            )
            assert custom_industry.status_code == 201
            profiles = await client.get("/api/source-profiles")
            custom_profile = next(
                profile
                for profile in profiles.json()
                if profile["slug"] == "custom-space-robot"
            )
            assert custom_profile["web_search"]["enabled"] is True
            assert custom_profile["keywords"] == [
                "在轨服务",
                "机械臂",
                "商业航天",
            ]
            assert custom_profile["web_search"]["max_queries"] == 8
            assert len(
                custom_profile["web_search"]["query_templates"]
            ) == 8
            assert {
                "bbc-news-top",
                "qbitai-news",
            }.issubset(
                {source["id"] for source in custom_profile["sources"]}
            )

            custom_product = await client.post(
                "/api/subscriptions",
                json={
                    "name": "小米 SU7",
                    "slug": "custom-xiaomi-su7",
                    "topic": "持续发现小米 SU7 的最新公开内容与动态",
                    "include_keywords": ["SU7", "小米汽车", "汽车"],
                    "focus_type": "auto",
                },
            )
            assert custom_product.status_code == 201
            assert custom_product.json()["focus_type"] == "product"
            assert custom_product.json()["focus_domain"] == "automotive"
            profiles = await client.get("/api/source-profiles")
            product_profile = next(
                profile
                for profile in profiles.json()
                if profile["slug"] == "custom-xiaomi-su7"
            )
            assert product_profile["focus_type"] == "product"
            assert product_profile["focus_domain"] == "automotive"
            assert product_profile["keywords"] == [
                "小米 SU7",
                "SU7",
                "小米汽车",
            ]
            assert product_profile["sources"] == []
            assert product_profile["focus_profile"]["aliases"] == [
                "小米 SU7",
                "SU7",
            ]
            assert product_profile["focus_profile"]["relations"][0][
                "name"
            ] == "小米汽车"
            assert product_profile["focus_profile"]["relations"][0][
                "tier"
            ] == "related"
            assert [
                template["id"]
                for template in product_profile["web_search"][
                    "query_templates"
                ]
            ] == [
                "default-query",
                "product-latest",
                "product-sales",
                "product-update",
                "product-quality",
                "product-reviews",
                "product-company",
                "product-ecosystem",
            ]
            assert [
                template["focus_tier"]
                for template in product_profile["web_search"][
                    "query_templates"
                ]
            ] == [
                "core",
                "core",
                "core",
                "core",
                "core",
                "core",
                "related",
                "context",
            ]

            custom_sports = await client.post(
                "/api/subscriptions",
                json={
                    "name": "足球",
                    "slug": "custom-football",
                    "topic": "持续追踪足球的最新动态",
                    "include_keywords": ["梅西", "世界杯"],
                    "focus_type": "auto",
                },
            )
            assert custom_sports.status_code == 201
            assert custom_sports.json()["focus_type"] == "sports"
            profiles = await client.get("/api/source-profiles")
            sports_profile = next(
                profile
                for profile in profiles.json()
                if profile["slug"] == "custom-football"
            )
            assert sports_profile["focus_type"] == "sports"
            assert {
                "bbc-sport-top",
                "mls-official-news",
                "inter-miami-official-news",
                "zhibo8-football",
            }.issubset(
                {source["id"] for source in sports_profile["sources"]}
            )
            assert "custom-football-verticals" in sports_profile[
                "automatic_source_rules"
            ]
            assert [
                template["id"]
                for template in sports_profile["web_search"][
                    "query_templates"
                ]
            ] == [
                "default-query",
                "sports-latest",
                "sports-results",
                "sports-lineup",
                "sports-injury",
                "sports-transfer",
                "sports-response",
                "sports-schedule",
            ]

            custom_entertainment = await client.post(
                "/api/subscriptions",
                json={
                    "name": "段子",
                    "slug": "custom-jokes",
                    "topic": "持续追踪新鲜段子和搞笑内容",
                    "include_keywords": ["搞笑", "抖机灵"],
                    "focus_type": "auto",
                },
            )
            assert custom_entertainment.status_code == 201
            assert (
                custom_entertainment.json()["focus_type"]
                == "entertainment"
            )
            profiles = await client.get("/api/source-profiles")
            entertainment_profile = next(
                profile
                for profile in profiles.json()
                if profile["slug"] == "custom-jokes"
            )
            assert entertainment_profile["focus_type"] == "entertainment"
            assert entertainment_profile["discovery_mode"] == "content"
            assert entertainment_profile["web_search"]["provider"] == (
                "bing_web_rss"
            )
            assert {
                "variety-entertainment",
                "deadline-entertainment",
                "qiushibaike-text",
                "reddit-jokes",
                "reddit-dadjokes",
            }.issubset(
                {source["id"] for source in entertainment_profile["sources"]}
            )
            assert [
                template["id"]
                for template in entertainment_profile["web_search"][
                    "query_templates"
                ]
            ] == [
                "content-latest",
                "content-fresh",
                "content-community",
                "content-short",
                "content-meme",
                "content-original",
                "content-video",
                "content-curated",
            ]

            created = await client.post(
                "/api/runs",
                json={
                    "subscription_id": subscriptions[0]["id"],
                    "delivery_mode": "web_inbox",
                },
            )
            assert created.status_code == 202
            run_id = created.json()["id"]

            for _ in range(50):
                response = await client.get(f"/api/runs/{run_id}")
                if response.json()["status"] in {
                    RunStatus.COMPLETED.value,
                    RunStatus.FAILED.value,
                }:
                    break
                await asyncio.sleep(0.01)

            assert response.json()["status"] == RunStatus.COMPLETED.value
            history = await client.get(f"/api/runs/{run_id}/events/history")
            assert history.status_code == 200
            assert history.json()[-1]["type"] == "run.completed"
            assert {
                "collection.discovery_completed",
                "collection.ranking_completed",
                "quality.relevance_scored",
                "clustering.completed",
                "extraction.completed",
            }.issubset({event["type"] for event in history.json()})

            intel = await client.get("/api/intel-events")
            assert intel.status_code == 200
            assert len(intel.json()) >= 1
            assert intel.json()[0]["story_id"].startswith("story_")
            assert intel.json()[0]["sources"]
            assert intel.json()[0]["sources"][0]["url"].startswith("https://")
            assert intel.json()[0]["facts"][0]["citations"]
            assert intel.json()[0]["independent_evidence_count"] >= 1
            intel_event = intel.json()[0]
            story = await client.get(
                f"/api/stories/{intel_event['story_id']}"
            )
            assert story.status_code == 200
            assert story.json()["evidence_chain_count"] >= 1
            timeline = await client.get(
                f"/api/stories/{intel_event['story_id']}/timeline"
            )
            assert timeline.status_code == 200
            assert intel_event["id"] in {
                item["id"] for item in timeline.json()
            }
            feedback = await client.post(
                f"/api/intel-events/{intel_event['id']}/feedback",
                json={"feedback_type": "valuable"},
            )
            assert feedback.status_code == 201
            assert (
                await client.get(
                    f"/api/intel-events/{intel_event['id']}/feedback"
                )
            ).json()[0]["feedback_type"] == "valuable"
            removed_feedback = await client.delete(
                f"/api/intel-events/{intel_event['id']}/feedback/valuable"
            )
            assert removed_feedback.status_code == 204
            assert (
                await client.get(
                    "/api/intel-events/missing/feedback"
                )
            ).status_code == 404
            assert (
                await client.get("/api/stories/missing")
            ).status_code == 404
            preferences = await client.get(
                f"/api/subscriptions/{subscriptions[0]['id']}/preferences"
            )
            assert preferences.status_code == 200
            assert preferences.json()["context_entities"] == []
            updated_preferences = await client.put(
                f"/api/subscriptions/{subscriptions[0]['id']}/preferences",
                json={
                    "digest_frequency": "daily",
                    "context_entities": ["手机业务"],
                },
            )
            assert updated_preferences.json()["digest_frequency"] == "daily"
            assert updated_preferences.json()["context_entities"] == [
                "手机业务"
            ]
            alert = await client.post(
                "/api/alerts",
                json={
                    "subscription_id": subscriptions[0]["id"],
                    "name": "高优先级行业动态",
                    "minimum_importance": 8,
                    "minimum_confidence": 0.6,
                },
            )
            assert alert.status_code == 201
            assert len((await client.get("/api/alerts")).json()) == 1
            missing_alert = await client.put(
                "/api/alerts/missing",
                json={
                    "subscription_id": subscriptions[0]["id"],
                    "name": "不存在的提醒",
                },
            )
            assert missing_alert.status_code == 404
            assert (
                await client.get("/api/alerts/matches")
            ).status_code == 200
            digests = await client.get(
                "/api/digests",
                params={"subscription_id": subscriptions[0]["id"]},
            )
            assert digests.status_code == 200
            assert digests.json()[0]["intel_event_ids"]
            industry_intel = await client.get(
                "/api/intel-events",
                params={"subscription_id": subscriptions[0]["id"]},
            )
            assert industry_intel.status_code == 200
            assert all(
                item["subscription_id"] == subscriptions[0]["id"]
                for item in industry_intel.json()
            )

            source_documents = await client.get(
                "/api/source-documents",
                params={"subscription_id": subscriptions[0]["id"]},
            )
            assert source_documents.status_code == 200
            assert len(source_documents.json()) >= 1
            assert source_documents.json()[0]["content_excerpt"]
            assert source_documents.json()[0]["ranking_reasons"]
            assert (
                source_documents.json()[0]["relevance_score"] is not None
            )
            assert source_documents.json()[0]["novelty_components"]
            assert source_documents.json()[0]["evidence_chain_id"]
            fixture_documents = await client.get(
                "/api/source-documents",
                params={
                    "subscription_id": subscriptions[0]["id"],
                    "channel": "fixture",
                },
            )
            assert fixture_documents.status_code == 200
            assert len(fixture_documents.json()) == len(
                source_documents.json()
            )
            run_documents = await client.get(
                f"/api/runs/{run_id}/source-documents"
            )
            assert run_documents.status_code == 200
            assert len(run_documents.json()) == len(source_documents.json())
            missing_documents = await client.get(
                "/api/source-documents",
                params={"subscription_id": "missing"},
            )
            assert missing_documents.status_code == 404
            source_health = await client.get(
                "/api/source-health",
                params={"subscription_id": subscriptions[0]["id"]},
            )
            assert source_health.status_code == 200
            assert source_health.json() == []
            query_metrics = await client.get(
                "/api/source-query-metrics",
                params={"subscription_id": subscriptions[0]["id"]},
            )
            assert query_metrics.status_code == 200
            assert query_metrics.json() == []
            missing_health = await client.get(
                "/api/source-health",
                params={"subscription_id": "missing"},
            )
            assert missing_health.status_code == 404

            async def inspect_custom_source(_payload):
                return {
                    "resolved_url": "https://example.com/feed.xml",
                    "collection_mode": "feed",
                    "candidate_count": 8,
                    "matched_candidate_count": 3,
                    "sample_titles": ["Example Research update"],
                    "probe_status": "ready",
                }

            app.state.registry.inspect_custom_source = inspect_custom_source
            preview = await client.post(
                "/api/custom-sources/preview",
                json={
                    "subscription_id": subscriptions[0]["id"],
                    "name": "Example Research",
                    "url": "https://example.com/",
                    "source_type": "website",
                },
            )
            assert preview.status_code == 200
            assert preview.json()["candidate_count"] == 8
            assert preview.json()["matched_candidate_count"] == 3
            assert preview.json()["probe_status"] == "ready"
            assert (
                await client.post(
                    "/api/custom-sources/preview",
                    json={
                        "subscription_id": "missing",
                        "name": "Example Research",
                        "url": "https://example.com/",
                        "source_type": "website",
                    },
                )
            ).status_code == 404
            custom = await client.post(
                "/api/custom-sources",
                json={
                    "subscription_id": subscriptions[0]["id"],
                    "name": "Example Research",
                    "url": "https://example.com/",
                    "source_type": "website",
                },
            )
            assert custom.status_code == 201
            assert custom.json()["collection_mode"] == "feed"

            sources = await client.get("/api/custom-sources")
            assert sources.status_code == 200
            assert [item["name"] for item in sources.json()] == [
                "Example Research"
            ]

            deleted = await client.delete(
                f"/api/custom-sources/{custom.json()['id']}"
            )
            assert deleted.status_code == 204
            assert (await client.get("/api/custom-sources")).json() == []

    rss_app = create_app(replace(settings, source_mode="rss"))
    rss_transport = httpx.ASGITransport(app=rss_app)
    async with rss_app.router.lifespan_context(rss_app):
        async with httpx.AsyncClient(
            transport=rss_transport, base_url="http://test"
        ) as client:
            dashboard = await client.get("/api/dashboard")
            assert dashboard.status_code == 200
            assert dashboard.json()["system"]["sources"]["mode"] == "rss"
            assert dashboard.json()["intel_events"] == []
            assert dashboard.json()["runs"] == []
            assert dashboard.json()["stats"]["intel_event_count"] == 0
            assert (await client.get("/api/intel-events")).json() == []
