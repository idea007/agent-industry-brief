from __future__ import annotations

from datetime import datetime, timezone

from app.domain.focus_learning import derive_focus_learning_candidates
from app.domain.models import IntelEvent, IntelFact, IntelSource


NOW = datetime(2026, 8, 4, tzinfo=timezone.utc)


def event(story_id: str, *, url: str) -> IntelEvent:
    source_id = f"source-{story_id}"
    return IntelEvent(
        id=f"intel-{story_id}",
        story_id=story_id,
        run_id="run-learning",
        subscription_id="sub-product",
        title=f"小米生态动态 {story_id}",
        summary="公开报道同时提及小米手机业务。",
        category="news",
        tags=["小米 SU7", "小米手机"],
        event_time=NOW,
        importance_score=7,
        importance_reason="与关注对象存在可解释关系。",
        confidence_level="medium",
        confidence_score=0.8,
        confidence_reason="来自稳定公开来源。",
        verification_status="partially_confirmed",
        facts=[IntelFact(text="公开报道提及小米手机。", source_ids=[source_id])],
        source_ids=[source_id],
        sources=[
            IntelSource(
                source_id=source_id,
                title=f"生态动态 {story_id}",
                url=url,
                publisher="可信科技媒体",
                source_type="industry_media",
                published_at=NOW,
                content="公开报道正文。",
                reliability=0.86,
            )
        ],
        first_seen_at=NOW,
        created_at=NOW,
    )


def test_learning_candidates_require_repeated_evidence_and_keep_tiers():
    relations, sources = derive_focus_learning_candidates(
        [
            event("one", url="https://tech.example/news/one"),
            event("two", url="https://tech.example/news/two"),
        ],
        known_terms=["小米 SU7", "SU7", "小米汽车"],
        followed_entities=[],
        context_entities=[],
        muted_entities=[],
        muted_sources=[],
        focus_type="product",
        focus_domain="automotive",
    )

    assert [(item.name, item.tier, item.evidence_count) for item in relations] == [
        ("小米手机", "context", 2)
    ]
    assert [(item.publisher, item.url, item.story_count) for item in sources] == [
        ("可信科技媒体", "https://tech.example/", 2)
    ]

    confirmed_relations, muted_sources = derive_focus_learning_candidates(
        [
            event("one", url="https://tech.example/news/one"),
            event("two", url="https://tech.example/news/two"),
        ],
        known_terms=["小米 SU7", "SU7", "小米汽车"],
        followed_entities=[],
        context_entities=["小米手机"],
        muted_entities=[],
        muted_sources=["可信科技媒体"],
        focus_type="product",
        focus_domain="automotive",
    )
    assert confirmed_relations == []
    assert muted_sources == []
