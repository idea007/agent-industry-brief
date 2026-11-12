from __future__ import annotations

from datetime import datetime, timezone

from app.harness.source_ranking import rank_and_allocate


def document(
    index: int,
    *,
    configured_source_id: str,
    publisher: str,
    source_type: str,
    retrieval_channel: str = "rss",
) -> dict:
    return {
        "source_id": f"source_{index}",
        "configured_source_id": configured_source_id,
        "title": f"行业新闻 {index}",
        "url": f"https://example.com/news/{index}",
        "publisher": publisher,
        "source_type": source_type,
        "source_tier": "industry",
        "retrieval_channel": retrieval_channel,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "body": "行业产品技术发布与商业进展。" * 20,
        "word_count": 120,
        "reliability": 0.8,
        "relevance_hits": 3,
        "safety_flags": [],
    }


def test_rank_and_allocate_applies_two_stage_caps_and_soft_quotas():
    documents = [
        document(
            index,
            configured_source_id="one-source",
            publisher="One Publisher",
            source_type="industry_media",
        )
        for index in range(10)
    ]
    documents.extend(
        [
            document(
                20,
                configured_source_id="official",
                publisher="Official Lab",
                source_type="official",
            ),
            document(
                21,
                configured_source_id="search-one",
                publisher="Search Publisher A",
                source_type="aggregator",
                retrieval_channel="ai_web_search",
            ),
            document(
                22,
                configured_source_id="capital",
                publisher="Capital Wire",
                source_type="funding",
            ),
            document(
                23,
                configured_source_id="community",
                publisher="Developer Forum",
                source_type="forum",
            ),
        ]
    )

    result = rank_and_allocate(
        documents,
        lookback_hours=72,
        discovery_limit=12,
        evidence_limit=8,
        per_source_cap=2,
        per_publisher_cap=3,
    )

    assert result["discovery_count"] <= 12
    assert result["discovery_count"] > result["evidence_count"]
    assert result["evidence_count"] <= 8
    assert result["deferred_count"] >= 1
    assert {
        "official_core",
        "ai_search",
        "policy_capital_events",
        "community",
    }.issubset(result["group_counts"])
    assert (
        sum(
            document["configured_source_id"] == "one-source"
            for document in result["documents"]
        )
        == 2
    )
    assert all(
        document["ranking_reasons"]
        for document in result["discovery_documents"]
    )


def test_product_evidence_prioritizes_direct_and_explicit_related_items():
    documents = [
        document(
            index,
            configured_source_id=f"generic-{index}",
            publisher=f"Generic Publisher {index}",
            source_type="official" if index == 0 else "industry_media",
        )
        for index in range(6)
    ]
    for index, title in enumerate(
        [
            "新款小米SU7公布售价与交付计划",
            "小米 SU7 推送新版本 OTA",
            "小米SU7召回方案正式公布",
        ],
        start=20,
    ):
        item = document(
            index,
            configured_source_id=f"product-{index}",
            publisher=f"Product Publisher {index}",
            source_type="aggregator",
            retrieval_channel="ai_web_search",
        )
        item["title"] = title
        item["body"] = f"{title}，相关细节已经公开。"
        item["relevance_hits"] = 1
        documents.append(item)
    parent = document(
        30,
        configured_source_id="xiaomi-auto",
        publisher="小米汽车官方",
        source_type="official",
    )
    parent["title"] = "小米汽车公布最新季度交付与研发投入"
    parent["body"] = "小米汽车披露汽车业务交付和研发投入。"
    documents.append(parent)

    result = rank_and_allocate(
        documents,
        lookback_hours=72,
        discovery_limit=10,
        evidence_limit=5,
        per_source_cap=2,
        per_publisher_cap=3,
        direct_focus_terms=("小米 SU7", "SU7"),
        related_focus_terms=("小米汽车",),
        require_focus_match=True,
    )

    assert result["evidence_count"] == 4
    assert [
        item["focus_match_level"] for item in result["documents"][:3]
    ] == ["direct", "direct", "direct"]
    assert result["documents"][3]["focus_match_level"] == "related"
    assert all(
        "小米" in f"{item['title']} {item['body']}"
        for item in result["documents"]
    )


def test_context_evidence_has_a_higher_threshold_and_feedback_changes_rank():
    core = document(
        40,
        configured_source_id="core",
        publisher="产品官方",
        source_type="official",
    )
    core["title"] = "小米 SU7 发布新版本"
    related = document(
        41,
        configured_source_id="related",
        publisher="小米汽车",
        source_type="industry_media",
    )
    related["title"] = "小米汽车公布交付计划"
    context = document(
        42,
        configured_source_id="context",
        publisher="科技媒体",
        source_type="industry_media",
    )
    context["title"] = "小米手机业务发布季度进展"
    context["relevance_hits"] = 1
    weak_context = document(
        43,
        configured_source_id="weak-context",
        publisher="低可信来源",
        source_type="aggregator",
    )
    weak_context["title"] = "小米手机业务传闻"
    weak_context["reliability"] = 0.55
    weak_context["relevance_hits"] = 1

    result = rank_and_allocate(
        [weak_context, context, related, core],
        lookback_hours=72,
        discovery_limit=8,
        evidence_limit=8,
        per_source_cap=2,
        per_publisher_cap=3,
        direct_focus_terms=("小米 SU7",),
        related_focus_terms=("小米汽车",),
        context_focus_terms=("小米手机",),
        require_focus_match=True,
        preference_weights={"小米汽车": 0.35, "小米手机": 0.15},
    )

    assert [item["focus_tier"] for item in result["documents"]] == [
        "core",
        "related",
        "context",
    ]
    weak = next(
        item
        for item in result["discovery_documents"]
        if item["source_id"] == "source_43"
    )
    assert "deferred:context_threshold" in weak["ranking_reasons"]
    assert any(
        reason.startswith("preference:")
        for reason in result["documents"][1]["ranking_reasons"]
    )
