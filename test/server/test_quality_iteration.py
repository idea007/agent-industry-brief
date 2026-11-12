from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.domain.models import (
    AlertRuleCreate,
    IntelEventDraft,
    IntelFact,
    IntelFeedbackCreate,
    SubscriptionCreate,
    SubscriptionPreferencesUpdate,
)
from app.domain.quality_pipeline import (
    QualityPipeline,
    build_fact_citations,
)
from app.harness.evals import EvalRunner


def _subscription(database):
    return next(
        item
        for item in database.list_subscriptions()
        if item.slug == "ai-agent"
    )


def _document(
    source_id: str,
    *,
    url: str,
    body: str,
    publisher: str = "星海科技",
    source_type: str = "official",
    attributed_publisher: str | None = None,
) -> dict:
    return {
        "source_id": source_id,
        "title": "星海科技发布 AI Agent 平台，首批投入 10 亿元",
        "url": url,
        "publisher": publisher,
        "source_type": source_type,
        "published_at": "2026-07-27T02:00:00+00:00",
        "body": body,
        "reliability": 0.9,
        "content_origin": "feed",
        "attributed_publisher": attributed_publisher,
        "is_new": True,
    }


def _draft(
    source_ids: list[str],
    *,
    summary: str = "星海科技发布了 AI Agent 平台。",
    event_time: datetime | None = None,
) -> IntelEventDraft:
    return IntelEventDraft(
        title="星海科技发布 AI Agent 平台",
        summary=summary,
        category="technology",
        tags=["AI Agent", "星海科技"],
        event_time=event_time or datetime(2026, 7, 27, tzinfo=timezone.utc),
        importance_score=8.2,
        importance_reason="影响企业级 Agent 平台供给。",
        confidence_level="medium",
        confidence_score=0.78,
        confidence_reason="存在可回溯来源。",
        verification_status="partially_confirmed",
        facts=[
            IntelFact(
                text="星海科技宣布首批投入 10 亿元。",
                source_ids=source_ids,
            )
        ],
        source_ids=source_ids,
    )


def test_quality_pipeline_exposes_score_components_and_evidence_chains(
    harness,
):
    _, database, _, _ = harness
    subscription = _subscription(database)
    documents = [
        _document(
            "official_1",
            url="https://star.example/launch",
            body="星海科技宣布首批投入 10 亿元，发布 AI Agent 平台。",
        ),
        _document(
            "syndicated_1",
            url="https://news-a.example/story",
            body="星海科技宣布首批投入 10 亿元，发布 AI Agent 平台。",
            publisher="转载站 A",
            source_type="aggregator",
            attributed_publisher="星海科技",
        ),
        _document(
            "syndicated_2",
            url="https://news-b.example/story",
            body="星海科技宣布首批投入 10 亿元，发布 AI Agent 平台。",
            publisher="转载站 B",
            source_type="aggregator",
            attributed_publisher="星海科技",
        ),
    ]

    result = QualityPipeline().analyze_documents(
        subscription, documents
    )
    analyzed = result["documents"]

    first = analyzed[0]
    expected_relevance = round(
        0.25 * first["keyword_match_score"]
        + 0.20 * first["entity_match_score"]
        + 0.15 * first["semantic_match_score"]
        + 0.15 * first["source_prior_score"]
        + 0.15 * first["focus_relation_score"]
        + 0.10 * ((first["user_preference_score"] + 1) / 2),
        4,
    )
    assert first["relevance_score"] == expected_relevance
    assert set(first["novelty_components"]) == {
        "url",
        "content",
        "story",
        "key_number_change",
        "action_change",
    }
    assert result["cluster_count"] == 1
    assert analyzed[1]["cluster_relation"] == "duplicate"
    assert (
        analyzed[1]["evidence_chain_id"]
        == analyzed[2]["evidence_chain_id"]
    )


def test_product_relevance_uses_product_name_and_ignores_broad_category(harness):
    _, database, _, _ = harness
    subscription = database.create_subscription(
        SubscriptionCreate(
            name="小米 SU7",
            slug="custom-quality-xiaomi-su7",
            topic="持续发现小米 SU7 的最新公开内容与动态",
            include_keywords=["SU7", "小米汽车", "汽车"],
            focus_type="auto",
        )
    )
    documents = [
        {
            **_document(
                "direct-product",
                url="https://auto.example/su7",
                body="新款小米SU7公布售价并启动交付。",
                publisher="汽车媒体",
                source_type="industry_media",
            ),
            "title": "新款小米SU7公布售价并启动交付",
        },
        {
            **_document(
                "generic-auto",
                url="https://auto.example/generic",
                body="大众汽车集团启动组织架构调整。",
                publisher="综合媒体",
                source_type="industry_media",
            ),
            "title": "大众汽车集团启动组织架构调整",
        },
    ]

    analyzed = QualityPipeline().analyze_documents(
        subscription,
        documents,
    )["documents"]
    by_id = {item["source_id"]: item for item in analyzed}

    assert subscription.focus_type == "product"
    assert by_id["direct-product"]["keyword_match_score"] > 0
    assert by_id["generic-auto"]["keyword_match_score"] == 0
    assert (
        by_id["direct-product"]["relevance_score"]
        > by_id["generic-auto"]["relevance_score"]
    )


def test_structured_citations_distinguish_support_and_conflict(harness):
    _, database, _, _ = harness
    subscription = _subscription(database)
    documents = QualityPipeline().analyze_documents(
        subscription,
        [
            _document(
                "support",
                url="https://star.example/support",
                body="星海科技宣布首批投入 10 亿元。",
            ),
            _document(
                "conflict",
                url="https://other.example/conflict",
                body="星海科技宣布首批投入 20 亿元。",
                publisher="另一来源",
            ),
        ],
    )["documents"]
    documents_by_id = {
        document["source_id"]: document for document in documents
    }

    citations = build_fact_citations(
        "星海科技宣布首批投入 10 亿元。",
        ["support", "conflict"],
        documents_by_id,
    )

    assert [citation.relation for citation in citations] == [
        "supports",
        "contradicts",
    ]
    assert all(citation.quote_hash for citation in citations)
    assert all(citation.locator.paragraph == 0 for citation in citations)


def test_structured_citations_support_fact_spanning_adjacent_sentences():
    fact = (
        "avatarin uses OpenAI’s GPT-Realtime to give Yamada Denki shoppers "
        "24/7 multilingual support. In two weeks, 30,000 people used the "
        "agent and 92% of survey responses were positive."
    )
    document = _document(
        "avatarin",
        url="https://openai.com/index/avatarin",
        body=fact,
        publisher="OpenAI News",
    )
    draft = _draft(["avatarin"], summary=fact).model_copy(
        update={
            "facts": [
                IntelFact(text=fact, source_ids=["avatarin"])
            ]
        }
    )

    result, evaluated = EvalRunner().evaluate(
        [draft.model_dump(mode="json")],
        allowed_source_ids={"avatarin"},
        blocked_source_ids=set(),
        documents=[document],
    )

    citation = evaluated[0].facts[0].citations[0]
    assert result.passed is True
    assert result.metrics["citation_support_rate"] == 1.0
    assert citation.relation == "supports"
    assert citation.quote == fact


def test_eval_supports_feed_fact_split_across_title_body_and_metadata():
    document = _document(
        "fresh-joke",
        url="https://community.example/jokes/fresh",
        body=(
            "Nothing, it just waved. submitted by /u/FreshJoker "
            "[link] [comments]"
        ),
        publisher="Reddit · Jokes",
        source_type="community_content",
    )
    document.update(
        {
            "title": "What did the ocean say to the beach?",
            "published_at": "2026-08-02T00:31:31Z",
        }
    )
    fact = (
        "Reddit 用户 FreshJoker 于 2026-08-02 00:31:31 UTC 在 r/Jokes "
        "发布段子：“What did the ocean say to the beach? "
        "Nothing, it just waved.”"
    )
    draft = _draft(["fresh-joke"]).model_copy(
        update={
            "category": "content",
            "facts": [IntelFact(text=fact, source_ids=["fresh-joke"])],
        }
    )

    result, evaluated = EvalRunner().evaluate(
        [draft.model_dump(mode="json")],
        allowed_source_ids={"fresh-joke"},
        blocked_source_ids=set(),
        documents=[document],
    )

    assert result.passed is True
    assert result.metrics["citation_support_rate"] == 1.0
    assert evaluated[0].facts[0].citations[0].relation == "context"


def test_eval_rejects_fabricated_quote_in_compound_feed_fact():
    document = _document(
        "fresh-joke",
        url="https://community.example/jokes/fresh",
        body=(
            "Nothing, it just waved. submitted by /u/FreshJoker "
            "[link] [comments]"
        ),
        publisher="Reddit · Jokes",
        source_type="community_content",
    )
    document.update(
        {
            "title": "What did the ocean say to the beach?",
            "published_at": "2026-08-02T00:31:31Z",
        }
    )
    fabricated_fact = (
        "Reddit 用户 FreshJoker 于 2026-08-02 00:31:31 UTC 在 r/Jokes "
        "发布段子：“What did the ocean say to the beach? "
        "It invented a submarine.”"
    )
    draft = _draft(["fresh-joke"]).model_copy(
        update={
            "category": "content",
            "facts": [
                IntelFact(
                    text=fabricated_fact,
                    source_ids=["fresh-joke"],
                )
            ],
        }
    )

    result, _ = EvalRunner().evaluate(
        [draft.model_dump(mode="json")],
        allowed_source_ids={"fresh-joke"},
        blocked_source_ids=set(),
        documents=[document],
    )

    assert result.passed is False
    coverage = next(
        check
        for check in result.checks
        if check["name"] == "fact_citation_coverage"
    )
    assert coverage["passed"] is False
    assert coverage["detail"] == {
        "unsupported_claims": [fabricated_fact]
    }


def test_eval_items_keeps_supported_draft_and_rejects_weak_draft():
    supported_document = _document(
        "training",
        url="https://example.com/messi-training",
        body="记者确认梅西已经回归球队训练。",
        publisher="Example Sports",
    )
    weak_document = _document(
        "nickname",
        url="https://example.com/casemiro-comment",
        body="34岁胖虎改口：梅西是足球之神，梦想与他踢球。",
        publisher="Example Sports",
    )
    supported = _draft(
        ["training"],
        summary="梅西已经回归球队训练。",
    ).model_copy(
        update={
            "title": "梅西回归球队训练",
            "facts": [
                IntelFact(
                    text="梅西已经回归球队训练。",
                    source_ids=["training"],
                )
            ],
        }
    )
    weak = _draft(
        ["nickname"],
        summary="卡塞米罗评论了梅西。",
    ).model_copy(
        update={
            "title": "卡塞米罗评论梅西",
            "facts": [
                IntelFact(
                    text="卡塞米罗表示梦想与梅西踢球。",
                    source_ids=["nickname"],
                )
            ],
        }
    )
    runner = EvalRunner()

    result, accepted = runner.evaluate_items(
        [
            supported.model_dump(mode="json"),
            weak.model_dump(mode="json"),
        ],
        allowed_source_ids={"training", "nickname"},
        blocked_source_ids=set(),
        documents=[supported_document, weak_document],
    )

    assert result.passed is True
    assert [draft.title for draft in accepted] == ["梅西回归球队训练"]
    assert result.metrics["input_item_count"] == 2
    assert result.metrics["accepted_item_count"] == 1
    assert result.metrics["rejected_item_count"] == 1
    item_filter = next(
        check
        for check in result.checks
        if check["name"] == "item_quality_filter"
    )
    assert item_filter["detail"]["rejected_items"] == [
        {
            "index": 1,
            "title": "卡塞米罗评论梅西",
            "failed_checks": ["fact_citation_coverage"],
        }
    ]

    failed, accepted = runner.evaluate_items(
        [weak.model_dump(mode="json")],
        allowed_source_ids={"nickname"},
        blocked_source_ids=set(),
        documents=[weak_document],
    )
    assert failed.passed is False
    assert accepted == []
    assert failed.metrics["accepted_item_count"] == 0
    assert failed.metrics["rejected_item_count"] == 1


def test_eval_runner_accepts_an_explicit_empty_model_result():
    result, accepted = EvalRunner().evaluate_items(
        [],
        allowed_source_ids={"candidate-source"},
        blocked_source_ids=set(),
        documents=[
            {
                "source_id": "candidate-source",
                "body": "候选内容与关注主题相关性不足。",
            }
        ],
    )

    assert result.passed is True
    assert accepted == []
    assert result.metrics["input_item_count"] == 0
    assert result.metrics["accepted_item_count"] == 0
    assert result.metrics["rejected_item_count"] == 0
    item_filter = next(
        check
        for check in result.checks
        if check["name"] == "item_quality_filter"
    )
    assert item_filter["passed"] is True


def test_structured_citations_support_paraphrase_and_cross_language_evidence():
    documents_by_id = {
        "medical": {
            "source_id": "medical",
            "body": (
                "双方将围绕具身智能在医疗场景中的数据采集、世界模型与"
                "仿真训练展开联合创新，务实构建一条从「拟真训练」到"
                "「场景验证」、再到「医院应用」的完整落地路径。"
            ),
        },
        "atoms": {
            "source_id": "atoms",
            "body": (
                "Atoms, the physical AI startup founded by Uber founder "
                "Travis Kalanick, raised $1.7 billion in a funding round."
            ),
        },
        "ising": {
            "source_id": "ising",
            "body": (
                "This post introduces the latest model release, NVIDIA Ising "
                "Calibration 1.5, which advances AI-based QPU calibration."
            ),
        },
        "nooa": {
            "source_id": "nooa",
            "body": (
                "NVIDIA Labs Object-Oriented Agents (NOOA) is an open-source "
                "research preview. It includes a Python framework."
            ),
        },
    }

    claims = {
        "medical": "合作旨在构建从拟真训练到场景验证再到医院应用的完整落地路径。",
        "atoms": "Atoms完成17亿美元融资，由Uber创始人Travis Kalanick创立。",
        "ising": "NVIDIA发布Ising Calibration 1.5，用于量子计算机校准。",
        "nooa": "NVIDIA发布NOOA开源Agent框架。",
    }

    for source_id, claim in claims.items():
        citations = build_fact_citations(
            claim,
            [source_id],
            documents_by_id,
        )
        assert citations[0].relation == "supports"

    atoms_quote = build_fact_citations(
        claims["atoms"],
        ["atoms"],
        documents_by_id,
    )[0].quote
    ising_quote = build_fact_citations(
        claims["ising"],
        ["ising"],
        documents_by_id,
    )[0].quote
    assert "$1.7 billion" in atoms_quote
    assert "Calibration 1.5" in ising_quote


def test_different_primary_subjects_do_not_share_a_cluster(harness):
    _, database, _, _ = harness
    subscription = _subscription(database)
    first = _document(
        "star",
        url="https://star.example/launch",
        body="星海科技宣布首批投入 10 亿元，发布 AI Agent 平台。",
    )
    second = _document(
        "cloud",
        url="https://cloud.example/launch",
        body="云海科技宣布首批投入 10 亿元，发布 AI Agent 平台。",
        publisher="云海科技",
    )
    second["title"] = "云海科技发布 AI Agent 平台，首批投入 10 亿元"

    result = QualityPipeline().analyze_documents(
        subscription, [first, second]
    )

    assert result["cluster_count"] == 2
    assert (
        result["documents"][0]["cluster_id"]
        != result["documents"][1]["cluster_id"]
    )


def test_muted_source_is_explainable_and_subscription_scoped(harness):
    _, database, _, _ = harness
    subscription = _subscription(database)
    other_subscription = next(
        item
        for item in database.list_subscriptions()
        if item.slug == "robot"
    )
    preferences = database.update_subscription_preferences(
        subscription.id,
        SubscriptionPreferencesUpdate(
            muted_sources=["转载站 A"],
            source_weights={"转载站 A": -1},
        ),
    )
    document = _document(
        "muted",
        url="https://news-a.example/story",
        body="星海科技发布 AI Agent 平台。",
        publisher="转载站 A",
        source_type="aggregator",
    )

    analyzed = QualityPipeline().analyze_documents(
        subscription, [document], preferences
    )["documents"][0]

    assert analyzed["personalization_muted"] is True
    assert "personalization:muted_source" in analyzed["ranking_reasons"]
    assert (
        database.get_subscription_preferences(
            other_subscription.id
        ).muted_sources
        == []
    )


def test_eval_hard_gates_summary_numbers_and_marks_conflicts(harness):
    _, database, _, _ = harness
    subscription = _subscription(database)
    documents = QualityPipeline().analyze_documents(
        subscription,
        [
            _document(
                "support",
                url="https://star.example/support",
                body="星海科技宣布首批投入 10 亿元。",
            ),
            _document(
                "conflict",
                url="https://other.example/conflict",
                body="星海科技宣布首批投入 20 亿元。",
                publisher="另一来源",
            ),
        ],
    )["documents"]
    draft = _draft(["support", "conflict"])

    result, evaluated = EvalRunner().evaluate(
        [draft.model_dump(mode="json")],
        allowed_source_ids={"support", "conflict"},
        blocked_source_ids=set(),
        documents=documents,
    )

    assert result.passed is True
    assert result.metrics["contradiction_count"] == 1
    assert evaluated[0].verification_status == "conflicting"
    assert evaluated[0].confidence_score == 0.55
    assert evaluated[0].facts[0].citations

    unsupported_summary = _draft(
        ["support"],
        summary="星海科技宣布首批投入 30 亿元。",
    )
    failed, _ = EvalRunner().evaluate(
        [unsupported_summary.model_dump(mode="json")],
        allowed_source_ids={"support"},
        blocked_source_ids=set(),
        documents=[documents[0]],
    )
    assert failed.passed is False
    faithfulness = next(
        check
        for check in failed.checks
        if check["name"] == "summary_faithfulness"
    )
    assert faithfulness["passed"] is False


def test_eval_accepts_equivalent_scaled_amount_and_event_year():
    document = _document(
        "atoms",
        url="https://example.com/atoms",
        body=(
            "Atoms, the physical AI startup founded by Uber founder "
            "Travis Kalanick, raised $1.7 billion in a funding round."
        ),
        publisher="Crunchbase News",
        source_type="funding",
    )
    draft = _draft(
        ["atoms"],
        summary="Atoms 在 2026 年完成 17 亿美元融资。",
        event_time=datetime(2026, 7, 27, tzinfo=timezone.utc),
    ).model_copy(
        update={
            "facts": [
                IntelFact(
                    text=(
                        "Atoms完成17亿美元融资，"
                        "由Uber创始人Travis Kalanick创立。"
                    ),
                    source_ids=["atoms"],
                )
            ]
        }
    )

    result, evaluated = EvalRunner().evaluate(
        [draft.model_dump(mode="json")],
        allowed_source_ids={"atoms"},
        blocked_source_ids=set(),
        documents=[document],
    )

    assert result.passed is True
    assert result.metrics["citation_support_rate"] == 1.0
    assert evaluated[0].facts[0].citations[0].relation == "supports"


def test_story_feedback_alert_and_digest_are_durable_and_reversible(
    harness,
):
    _, database, _, _ = harness
    subscription = _subscription(database)
    run = database.create_run(
        subscription_id=subscription.id,
        trigger="manual",
        goal="质量迭代持久化测试",
        delivery_mode="web_inbox",
        idempotency_key=None,
    )
    analyzed = QualityPipeline().analyze_documents(
        subscription,
        [
            _document(
                "support",
                url="https://star.example/support",
                body="星海科技宣布首批投入 10 亿元。",
            )
        ],
    )["documents"]
    database.save_source_documents(
        run.id,
        subscription.id,
        analyzed,
        evidence_source_ids={"support"},
    )
    alert = database.create_alert_rule(
        AlertRuleCreate(
            subscription_id=subscription.id,
            name="高价值 Agent 动态",
            entities=["AI Agent"],
            minimum_importance=7,
            minimum_confidence=0.6,
            minimum_evidence_chains=1,
        )
    )

    first_event = database.save_intel_events(
        run.id,
        subscription.id,
        [_draft(["support"])],
    )[0]
    original_facts = first_event.model_dump(mode="json")["facts"]

    story = database.get_story(first_event.story_id)
    assert story is not None
    assert database.list_story_documents(first_event.story_id)
    assert database.list_alert_matches(
        subscription_id=subscription.id
    )[0].alert_id == alert.id
    assert database.list_digests(
        subscription_id=subscription.id
    )[0].intel_event_ids == [first_event.id]

    feedback = database.create_feedback(
        first_event.id,
        IntelFeedbackCreate(feedback_type="valuable"),
    )
    duplicate_feedback = database.create_feedback(
        first_event.id,
        IntelFeedbackCreate(feedback_type="valuable"),
    )
    assert duplicate_feedback.id == feedback.id
    stored_event = next(
        event
        for event in database.list_intel_events(
            subscription_id=subscription.id
        )
        if event.id == first_event.id
    )
    assert stored_event.model_dump(mode="json")["facts"] == original_facts
    preferences = database.get_subscription_preferences(
        subscription.id
    )
    assert preferences.entity_weights["AI Agent"] == 0.1
    assert database.delete_feedback(
        first_event.id, "valuable"
    ) is True
    assert (
        "AI Agent"
        not in database.get_subscription_preferences(
            subscription.id
        ).entity_weights
    )

    second_run = database.create_run(
        subscription_id=subscription.id,
        trigger="manual",
        goal="同一事件后续",
        delivery_mode="web_inbox",
        idempotency_key=None,
    )
    second_event = database.save_intel_events(
        second_run.id,
        subscription.id,
        [
            _draft(
                ["follow_up_source"],
                summary="星海科技发布了 Agent 平台的后续进展。",
                event_time=datetime(2026, 7, 27, tzinfo=timezone.utc)
                + timedelta(hours=6),
            )
        ],
    )[0]
    assert second_event.story_id == first_event.story_id
    timeline = database.list_story_timeline(first_event.story_id)
    assert [event.id for event in timeline] == [
        first_event.id,
        second_event.id,
    ]
    assert timeline[-1].change_summary

    follow_up_run = database.create_run(
        subscription_id=subscription.id,
        trigger="manual",
        goal="关联后续进展",
        delivery_mode="web_inbox",
        idempotency_key=None,
    )
    follow_up = _draft(
        ["production_source"],
        summary="星海科技的 AI Agent 平台进入量产交付。",
        event_time=datetime(2026, 7, 28, tzinfo=timezone.utc),
    ).model_copy(
        update={"title": "星海科技量产 AI Agent 平台"}
    )
    follow_up_event = database.save_intel_events(
        follow_up_run.id,
        subscription.id,
        [follow_up],
    )[0]
    assert follow_up_event.story_id != first_event.story_id
    relations = database.list_story_relations(
        follow_up_event.story_id
    )
    assert relations[0].relation == "follow_up"
