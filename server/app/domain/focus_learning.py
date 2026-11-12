from __future__ import annotations

from collections import defaultdict
from urllib.parse import urlsplit

from app.domain.focus import (
    CONTEXT_RELATION_MARKERS,
    infer_focus_domain,
    infer_focus_type,
    normalize_focus_text,
)
from app.domain.models import (
    FocusDomain,
    FocusRelationProfile,
    FocusSourceSuggestion,
    FocusType,
    IntelEvent,
)


GENERIC_LEARNING_TAGS = {
    "新闻",
    "动态",
    "行业",
    "技术",
    "产品",
    "公司",
    "人物",
    "事件",
    "融资",
    "活动",
}


def derive_focus_learning_candidates(
    events: list[IntelEvent],
    *,
    known_terms: list[str],
    followed_entities: list[str],
    context_entities: list[str],
    muted_entities: list[str],
    muted_sources: list[str],
    focus_type: FocusType,
    focus_domain: FocusDomain,
) -> tuple[list[FocusRelationProfile], list[FocusSourceSuggestion]]:
    """Derive shadow candidates without activating them automatically."""

    excluded_terms = {
        normalize_focus_text(value)
        for value in [
            *known_terms,
            *followed_entities,
            *context_entities,
            *muted_entities,
            *GENERIC_LEARNING_TAGS,
        ]
        if normalize_focus_text(value)
    }
    relation_stories: dict[str, set[str]] = defaultdict(set)
    relation_labels: dict[str, str] = {}
    source_stories: dict[tuple[str, str], set[str]] = defaultdict(set)
    source_reliability: dict[tuple[str, str], float] = {}
    muted_source_keys = {value.casefold() for value in muted_sources}

    for event in events:
        for tag in event.tags:
            normalized = normalize_focus_text(tag)
            if (
                len(normalized) < 2
                or normalized in excluded_terms
                or normalized.isdigit()
            ):
                continue
            relation_stories[normalized].add(event.story_id)
            relation_labels.setdefault(normalized, tag.strip())

        for source in event.sources:
            if (
                source.source_type
                in {"aggregator", "forum", "community", "social"}
                or source.reliability < 0.72
                or source.publisher.casefold() in muted_source_keys
            ):
                continue
            parsed = urlsplit(source.url)
            if parsed.scheme != "https" or not parsed.hostname:
                continue
            origin = f"https://{parsed.hostname}/"
            key = (source.publisher, origin)
            source_stories[key].add(event.story_id)
            source_reliability[key] = max(
                source_reliability.get(key, 0),
                source.reliability,
            )

    relations: list[FocusRelationProfile] = []
    for normalized, story_ids in relation_stories.items():
        if len(story_ids) < 2:
            continue
        label = relation_labels[normalized]
        candidate_type = infer_focus_type(label, [])
        candidate_domain = infer_focus_domain(label, [], candidate_type)
        tier = (
            "context"
            if (
                any(
                    normalize_focus_text(marker) in normalized
                    for marker in CONTEXT_RELATION_MARKERS
                )
                or (
                    candidate_domain != FocusDomain.GENERAL
                    and candidate_domain != focus_domain
                )
                or (
                    focus_type == FocusType.PRODUCT
                    and candidate_type == FocusType.PRODUCT
                )
            )
            else "related"
        )
        relations.append(
            FocusRelationProfile(
                name=label,
                tier=tier,
                relation_type="observed_entity",
                origin="observed",
                confidence=min(0.85, 0.45 + len(story_ids) * 0.1),
                evidence_count=len(story_ids),
            )
        )
    relations.sort(key=lambda item: (-item.evidence_count, item.name))

    sources = [
        FocusSourceSuggestion(
            publisher=publisher,
            url=url,
            story_count=len(story_ids),
            reliability=source_reliability[(publisher, url)],
        )
        for (publisher, url), story_ids in source_stories.items()
        if len(story_ids) >= 2
    ]
    sources.sort(
        key=lambda item: (-item.story_count, -item.reliability, item.publisher)
    )
    return relations[:8], sources[:6]
