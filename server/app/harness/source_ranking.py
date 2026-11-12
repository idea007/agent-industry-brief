from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from app.domain.focus import normalize_focus_text


SOURCE_GROUP_QUOTAS = {
    "official_core": 0.25,
    "industry_media": 0.20,
    "ai_search": 0.30,
    "policy_capital_events": 0.15,
    "community": 0.10,
}


def source_group(document: dict[str, Any]) -> str:
    channel = str(document.get("retrieval_channel") or "")
    source_type = str(document.get("source_type") or "").casefold()
    tier = str(document.get("source_tier") or "").casefold()
    if channel == "ai_web_search":
        return "ai_search"
    if source_type in {"official", "research", "policy"} or tier == "core":
        return "official_core"
    if source_type in {
        "funding",
        "capital_market",
        "event",
        "event_community",
    }:
        return "policy_capital_events"
    if source_type in {"forum", "community", "social"}:
        return "community"
    return "industry_media"


def _published_at(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _score_document(
    document: dict[str, Any],
    *,
    now: datetime,
    lookback_hours: int,
    preference_weights: dict[str, float],
    muted_sources: tuple[str, ...],
) -> tuple[float, list[str]]:
    relevance = min(max(float(document.get("relevance_hits") or 0) / 4, 0), 1)
    reliability = min(max(float(document.get("reliability") or 0.5), 0), 1)
    novelty = 1.0 if document.get("is_new", True) else 0.35
    age_hours = max(
        0.0,
        (now - _published_at(document.get("published_at"))).total_seconds()
        / 3600,
    )
    recency = max(0.0, 1 - age_hours / max(lookback_hours, 1))
    directness = {
        "official": 1.0,
        "research": 0.95,
        "policy": 0.95,
        "industry": 0.78,
        "industry_media": 0.78,
        "funding": 0.72,
        "capital_market": 0.72,
        "event": 0.62,
        "event_community": 0.55,
        "aggregator": 0.48,
        "forum": 0.35,
        "community": 0.35,
    }.get(str(document.get("source_type") or "").casefold(), 0.55)
    completeness = min(max(float(document.get("word_count") or 0) / 800, 0), 1)
    normalized_text = normalize_focus_text(
        f"{document.get('title', '')} {document.get('body', '')}"
    )
    matched_preferences = [
        float(weight)
        for term, weight in preference_weights.items()
        if normalize_focus_text(term)
        and normalize_focus_text(term) in normalized_text
    ]
    preference = (
        max(-1.0, min(1.0, sum(matched_preferences) / len(matched_preferences)))
        if matched_preferences
        else 0.0
    )
    source_keys = {
        str(value).casefold()
        for value in (
            document.get("configured_source_id"),
            document.get("publisher"),
            document.get("source_id"),
        )
        if value
    }
    muted = bool(source_keys & {value.casefold() for value in muted_sources})
    score = (
        relevance * 0.30
        + reliability * 0.20
        + novelty * 0.20
        + recency * 0.15
        + directness * 0.10
        + completeness * 0.05
        + preference * 0.08
    )
    reasons = [
        f"relevance:{relevance:.2f}",
        f"reliability:{reliability:.2f}",
        f"novelty:{novelty:.2f}",
        f"recency:{recency:.2f}",
        f"directness:{directness:.2f}",
        f"completeness:{completeness:.2f}",
    ]
    if preference:
        reasons.append(f"preference:{preference:+.2f}")
    if muted:
        score = 0
        reasons.append("blocked:muted_source")
    if document.get("safety_flags"):
        score = 0
        reasons.append("blocked:safety")
    return round(score, 4), reasons


def _focus_match_level(
    document: dict[str, Any],
    *,
    direct_terms: tuple[str, ...],
    related_terms: tuple[str, ...],
    context_terms: tuple[str, ...],
) -> str:
    text = normalize_focus_text(
        f"{document.get('title', '')} {document.get('body', '')}"
    )
    if any(
        normalize_focus_text(term) in text
        for term in direct_terms
        if normalize_focus_text(term)
    ):
        return "direct"
    if any(
        normalize_focus_text(term) in text
        for term in related_terms
        if normalize_focus_text(term)
    ):
        return "related"
    if any(
        normalize_focus_text(term) in text
        for term in context_terms
        if normalize_focus_text(term)
    ):
        return "context"
    return "none"


def _allocate_with_caps(
    documents: list[dict[str, Any]],
    *,
    limit: int,
    per_source_cap: int,
    per_publisher_cap: int,
    prefer_direct: bool = False,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    source_counts: Counter[str] = Counter()
    publisher_counts: Counter[str] = Counter()
    available_groups = {
        str(document["source_group"])
        for document in documents
        if not document.get("safety_flags")
    }
    group_targets = {
        group: max(1, math.floor(limit * ratio))
        for group, ratio in SOURCE_GROUP_QUOTAS.items()
        if group in available_groups
    }
    group_counts: Counter[str] = Counter()

    def can_select(document: dict[str, Any]) -> bool:
        source_key = str(
            document.get("configured_source_id")
            or document.get("source_id")
            or "unknown"
        )
        publisher = str(document.get("publisher") or "unknown").casefold()
        document_source_cap = min(
            per_source_cap,
            max(
                1,
                int(document.get("query_quota") or per_source_cap),
            ),
        )
        return (
            not document.get("safety_flags")
            and source_counts[source_key] < document_source_cap
            and publisher_counts[publisher] < per_publisher_cap
        )

    def remember(document: dict[str, Any]) -> None:
        source_key = str(
            document.get("configured_source_id")
            or document.get("source_id")
            or "unknown"
        )
        publisher = str(document.get("publisher") or "unknown").casefold()
        selected.append(document)
        selected_ids.add(str(document["source_id"]))
        source_counts[source_key] += 1
        publisher_counts[publisher] += 1
        group_counts[str(document["source_group"])] += 1

    if prefer_direct:
        for document in documents:
            if len(selected) >= limit:
                break
            if (
                document.get("focus_match_level") == "direct"
                and str(document["source_id"]) not in selected_ids
                and can_select(document)
            ):
                remember(document)

    for group, target in group_targets.items():
        for document in documents:
            if len(selected) >= limit or group_counts[group] >= target:
                break
            if (
                document["source_group"] == group
                and str(document["source_id"]) not in selected_ids
                and can_select(document)
            ):
                remember(document)

    # Quotas are deliberately soft: unused capacity flows to the best remaining
    # evidence while the per-source and per-publisher caps remain enforced.
    for document in documents:
        if len(selected) >= limit:
            break
        if (
            str(document["source_id"]) not in selected_ids
            and can_select(document)
        ):
            remember(document)
    return selected


def rank_and_allocate(
    documents: list[dict[str, Any]],
    *,
    lookback_hours: int,
    discovery_limit: int,
    evidence_limit: int,
    per_source_cap: int,
    per_publisher_cap: int,
    direct_focus_terms: tuple[str, ...] = (),
    related_focus_terms: tuple[str, ...] = (),
    context_focus_terms: tuple[str, ...] = (),
    require_focus_match: bool = False,
    preference_weights: dict[str, float] | None = None,
    muted_sources: tuple[str, ...] = (),
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    unique: dict[str, dict[str, Any]] = {}
    for raw_document in documents:
        document = dict(raw_document)
        document["configured_source_id"] = str(
            document.get("configured_source_id")
            or document.get("source_id")
            or "unknown"
        )
        document["retrieval_channel"] = str(
            document.get("retrieval_channel") or "fixture"
        )
        document["fetch_status"] = str(
            document.get("fetch_status") or "fetched"
        )
        document["extraction_status"] = str(
            document.get("extraction_status")
            or (
                "succeeded"
                if document.get("content_origin") == "fulltext"
                else "feed_only"
            )
        )
        document["source_group"] = source_group(document)
        document["focus_match_level"] = _focus_match_level(
            document,
            direct_terms=direct_focus_terms,
            related_terms=related_focus_terms,
            context_terms=context_focus_terms,
        )
        document["focus_tier"] = {
            "direct": "core",
            "related": "related",
            "context": "context",
        }.get(document["focus_match_level"], "unmatched")
        document["focus_relation_score"] = {
            "core": 1.0,
            "related": 0.72,
            "context": 0.48,
        }.get(document["focus_tier"], 0.0)
        score, reasons = _score_document(
            document,
            now=now,
            lookback_hours=lookback_hours,
            preference_weights=preference_weights or {},
            muted_sources=muted_sources,
        )
        document["ranking_score"] = score
        document["ranking_reasons"] = [
            *reasons,
            f"focus:{document['focus_match_level']}",
            f"focus_tier:{document['focus_tier']}",
            f"query_tier:{document.get('query_focus_tier', 'core')}",
        ]
        dedupe_key = str(
            document.get("canonical_url")
            or document.get("url")
            or document.get("source_id")
        )
        existing = unique.get(dedupe_key)
        if existing is None or score > float(existing["ranking_score"]):
            if existing is not None:
                document["duplicate_of_document_id"] = existing.get("source_id")
            unique[dedupe_key] = document

    ranked = sorted(
        unique.values(),
        key=lambda item: (
            bool(item.get("safety_flags")),
            {"direct": 0, "related": 1, "context": 2}.get(
                str(item.get("focus_match_level")),
                3,
            ),
            -float(item["ranking_score"]),
            -_published_at(item.get("published_at")).timestamp(),
            str(item.get("source_id")),
        ),
    )
    discovery = _allocate_with_caps(
        ranked,
        limit=discovery_limit,
        per_source_cap=max(per_source_cap * 2, per_source_cap),
        per_publisher_cap=max(per_publisher_cap * 2, per_publisher_cap),
    )
    blocked = [
        document
        for document in ranked
        if document.get("safety_flags") and document not in discovery
    ]
    discovery = (discovery + blocked)[:discovery_limit]
    evidence_candidates = []
    for document in discovery:
        match_level = document.get("focus_match_level")
        if require_focus_match and match_level == "none":
            continue
        if (
            match_level == "context"
            and (
                float(document.get("reliability") or 0) < 0.7
                or int(document.get("relevance_hits") or 0) < 1
            )
        ):
            document["ranking_reasons"].append(
                "deferred:context_threshold"
            )
            continue
        if "blocked:muted_source" in document.get("ranking_reasons", []):
            continue
        evidence_candidates.append(document)
    evidence = _allocate_with_caps(
        evidence_candidates,
        limit=evidence_limit,
        per_source_cap=per_source_cap,
        per_publisher_cap=per_publisher_cap,
        prefer_direct=require_focus_match,
    )
    evidence_ids = {str(document["source_id"]) for document in evidence}
    for document in discovery:
        document["evidence_selected"] = (
            str(document["source_id"]) in evidence_ids
        )
        if not document["evidence_selected"] and not document.get("safety_flags"):
            document["ranking_reasons"].append("deferred:evidence_capacity")

    return {
        "discovery_documents": discovery,
        "documents": evidence,
        "discovery_count": len(discovery),
        "evidence_count": len(evidence),
        "deferred_count": sum(
            not document["evidence_selected"]
            and not document.get("safety_flags")
            for document in discovery
        ),
        "blocked_count": sum(
            bool(document.get("safety_flags")) for document in discovery
        ),
        "group_counts": dict(
            Counter(str(document["source_group"]) for document in evidence)
        ),
    }
