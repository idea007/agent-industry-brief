from __future__ import annotations

import hashlib
import re
from collections import Counter
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from app.domain.focus import effective_focus_keywords
from app.domain.models import (
    CitationLocator,
    IntelCitation,
    IntelQuote,
    Subscription,
    SubscriptionPreferences,
)


ACTION_ALIASES = {
    "发布": "launch",
    "上线": "launch",
    "推出": "launch",
    "开源": "open_source",
    "融资": "funding",
    "募资": "funding",
    "收购": "acquisition",
    "并购": "acquisition",
    "合作": "partnership",
    "签约": "partnership",
    "获批": "approval",
    "批准": "approval",
    "召回": "recall",
    "量产": "production",
    "投产": "production",
    "试生产": "pilot_production",
    "发布会": "event",
    "峰会": "event",
    "访谈": "interview",
    "launch": "launch",
    "release": "launch",
    "funding": "funding",
    "raises": "funding",
    "acquires": "acquisition",
    "partnership": "partnership",
    "approved": "approval",
    "recall": "recall",
}
LOCATIONS = {
    "中国",
    "北京",
    "上海",
    "深圳",
    "广州",
    "杭州",
    "美国",
    "欧洲",
    "日本",
    "韩国",
    "新加坡",
}
GENERIC_ENTITIES = {
    "news",
    "technology",
    "report",
    "update",
    "industry",
    "company",
    "新闻",
    "行业",
    "技术",
    "产品",
}
EVIDENCE_CONCEPT_ALIASES = {
    "release": (
        "发布",
        "推出",
        "上线",
        "introduce",
        "introduces",
        "introduced",
        "launch",
        "launched",
        "release",
        "released",
    ),
    "open_source": ("开源", "open-source", "open source"),
    "framework": ("框架", "framework"),
    "funding": (
        "融资",
        "募资",
        "funding",
        "financing",
        "raised",
        "raises",
    ),
    "founder": ("创始", "创立", "founder", "founded"),
    "calibration": ("校准", "calibration"),
    "quantum_computing": (
        "量子计算",
        "量子处理器",
        "quantum computer",
        "quantum processor",
        "qpu",
    ),
    "partnership": ("合作", "携手", "partner", "partnership"),
}
GENERIC_EVIDENCE_IDENTIFIERS = {
    "agent",
    "agents",
    "ai",
    "framework",
    "model",
    "models",
    "open-source",
    "platform",
    "release",
    "research",
    "startup",
}
_NUMBER_PATTERN = re.compile(
    r"(?<![\w.])(?P<value>\d+(?:\.\d+)?)"
    r"\s*(?P<unit>万亿|亿|万|trillion|billion|million|bn|mn|[tbm])?",
    flags=re.IGNORECASE,
)
_NUMBER_SCALES = {
    "万": Decimal("10000"),
    "亿": Decimal("100000000"),
    "万亿": Decimal("1000000000000"),
    "million": Decimal("1000000"),
    "mn": Decimal("1000000"),
    "m": Decimal("1000000"),
    "billion": Decimal("1000000000"),
    "bn": Decimal("1000000000"),
    "b": Decimal("1000000000"),
    "trillion": Decimal("1000000000000"),
    "t": Decimal("1000000000000"),
}


def _clamp(value: float) -> float:
    return round(min(1.0, max(0.0, value)), 4)


def _normalize(value: str) -> str:
    return re.sub(
        r"[^0-9a-z\u3400-\u4dbf\u4e00-\u9fff]+",
        "",
        value.casefold(),
    )


def _tokens(value: str) -> set[str]:
    latin = {
        token.casefold()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9.+#-]{1,}", value)
        if token.casefold() not in GENERIC_ENTITIES
    }
    chinese_segments = re.findall(r"[\u3400-\u9fff]{2,}", value)
    chinese = {
        segment[index : index + 2]
        for segment in chinese_segments
        for index in range(len(segment) - 1)
    }
    return latin | chinese


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _concepts(value: str) -> set[str]:
    folded = value.casefold()
    return {
        concept
        for concept, aliases in EVIDENCE_CONCEPT_ALIASES.items()
        if any(alias in folded for alias in aliases)
    }


def _latin_identifiers(value: str) -> set[str]:
    return {
        token.casefold()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9.+#-]{1,}", value)
        if token.casefold()
        not in GENERIC_ENTITIES | GENERIC_EVIDENCE_IDENTIFIERS
    }


def _number_mentions(value: str) -> list[tuple[str, Decimal]]:
    mentions: list[tuple[str, Decimal]] = []
    for match in _NUMBER_PATTERN.finditer(value):
        raw = match.group("value")
        unit = (match.group("unit") or "").casefold()
        try:
            normalized = Decimal(raw) * _NUMBER_SCALES.get(
                unit, Decimal("1")
            )
        except InvalidOperation:
            continue
        mentions.append((raw, normalized))
    return mentions


def _number_support_rate(claim: str, evidence: str) -> float:
    claim_mentions = _number_mentions(claim)
    if not claim_mentions:
        return 0.0
    evidence_values = {
        normalized for _, normalized in _number_mentions(evidence)
    }
    return sum(
        normalized in evidence_values
        for _, normalized in claim_mentions
    ) / len(claim_mentions)


def document_supports_claim(
    claim: str,
    document: dict[str, Any],
) -> bool:
    """Check a compound claim against captured source text and metadata.

    Feed content commonly splits a post across its title, body, publisher and
    publication timestamp. The quote integrity gate still validates a literal
    body excerpt; this check prevents a correctly cited compound fact from
    failing only because its supporting fields are stored separately.
    """

    published_at = str(document.get("published_at") or "")
    readable_published_at = (
        published_at.replace("T", " ")
        .replace("+00:00", " UTC")
        .replace("Z", " UTC")
    )
    evidence = "\n".join(
        str(value)
        for value in (
            document.get("title"),
            document.get("body"),
            document.get("publisher"),
            document.get("author"),
            document.get("attributed_publisher"),
            published_at,
            readable_published_at,
        )
        if value
    )
    if not evidence.strip():
        return False

    quoted_spans = [
        match.group(1) or match.group(2)
        for match in re.finditer(
            r"“([^”]{8,})”|(?<![A-Za-z0-9])\"([^\"]{8,})\"",
            claim,
        )
    ]
    normalized_evidence = _normalize(evidence)
    if any(
        _normalize(span) not in normalized_evidence
        for span in quoted_spans
    ):
        return False

    claim_tokens = _tokens(claim)
    evidence_tokens = _tokens(evidence)
    overlap = _jaccard(claim_tokens, evidence_tokens)
    claim_coverage = (
        len(claim_tokens & evidence_tokens) / len(claim_tokens)
        if claim_tokens
        else 0.0
    )
    claim_mentions = _number_mentions(claim)
    numeric_compatible = (
        not claim_mentions
        or _number_support_rate(claim, evidence) == 1.0
    )
    claim_contains_chinese = bool(
        re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", claim)
    )
    evidence_contains_chinese = bool(
        re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", evidence)
    )
    cross_language_match = (
        claim_contains_chinese != evidence_contains_chinese
        and len(_latin_identifiers(claim) & _latin_identifiers(evidence)) >= 2
        and bool(_concepts(claim) & _concepts(evidence))
    )
    text_match = (
        overlap >= 0.18
        or claim_coverage >= 0.55
        or cross_language_match
    )
    return text_match and numeric_compatible


def find_unsupported_numbers(
    claim: str,
    evidence: str,
    *,
    contextual_years: set[int] | None = None,
) -> list[str]:
    evidence_values = {
        normalized for _, normalized in _number_mentions(evidence)
    }
    allowed_years = contextual_years or set()
    unsupported: list[str] = []
    for raw, normalized in _number_mentions(claim):
        if normalized in evidence_values:
            continue
        if (
            len(raw) == 4
            and raw.isdigit()
            and int(raw) in allowed_years
        ):
            continue
        unsupported.append(raw)
    return sorted(set(unsupported))


def _sentences(paragraph: str) -> list[str]:
    return [
        sentence.strip()
        for sentence in re.split(
            r"(?<=[。！？!?])\s*|(?<=\.)(?=\s|$)\s*",
            paragraph,
        )
        if sentence.strip()
    ]


def _citation_quotes(paragraph: str) -> list[str]:
    sentences = _sentences(paragraph)
    spans: list[tuple[int, int]] = []
    cursor = 0
    for sentence in sentences:
        start = paragraph.find(sentence, cursor)
        if start < 0:
            continue
        end = start + len(sentence)
        spans.append((start, end))
        cursor = end

    quotes: list[str] = []
    for start in range(len(spans)):
        for end in range(start, len(spans)):
            candidate = paragraph[
                spans[start][0] : spans[end][1]
            ].strip()
            if len(candidate) > 320:
                if start == end:
                    quotes.append(candidate[:320])
                break
            quotes.append(candidate)
    return quotes


def _parse_time(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def extract_event_elements(
    document: dict[str, Any],
    subscription: Subscription,
) -> dict[str, Any]:
    title = str(document.get("title") or "")
    body = str(document.get("body") or "")
    haystack = f"{title}\n{body[:1200]}"
    leading_subject = re.match(
        r"^(.{2,30}?)(?:宣布|发布|上线|推出|开源|融资|募资|收购|并购|合作|获批|批准|召回|量产|投产|试生产)",
        title,
    )
    primary_subjects = (
        [leading_subject.group(1).strip(" ：:，,")]
        if leading_subject
        else []
    )
    primary_subjects.extend(
        match
        for match in re.findall(
            r"[\u3400-\u9fffA-Za-z0-9]{2,24}(?:公司|集团|研究院|大学|平台|实验室)",
            title,
        )
    )
    focus_keywords = effective_focus_keywords(
        name=subscription.name,
        focus_type=subscription.focus_type,
        keywords=subscription.include_keywords,
    )
    normalized_haystack = _normalize(haystack)
    subjects = [
        keyword
        for keyword in focus_keywords
        if _normalize(keyword) in normalized_haystack
    ]
    subjects.extend(
        token
        for token in re.findall(r"\b[A-Z][A-Za-z0-9.+-]{1,24}\b", title)
        if token.casefold() not in GENERIC_ENTITIES
    )
    subjects = [*primary_subjects, *subjects]
    action = next(
        (
            normalized
            for marker, normalized in ACTION_ALIASES.items()
            if marker.casefold() in haystack.casefold()
        ),
        "update",
    )
    numbers = list(
        dict.fromkeys(
            re.findall(
                r"(?:[$¥￥]\s*)?\d+(?:\.\d+)?\s*(?:亿|万|万元|亿元|%|倍|B|M|GB|TB|美元|人民币|年|月|日)?",
                haystack,
                re.I,
            )
        )
    )[:12]
    locations = [location for location in LOCATIONS if location in haystack]
    event_type = "news"
    if action == "funding":
        event_type = "funding"
    elif action in {"open_source", "launch"} and any(
        marker in haystack.casefold()
        for marker in ("模型", "技术", "框架", "sdk", "api", "benchmark")
    ):
        event_type = "technology"
    elif action == "event":
        event_type = "event"
    elif action == "interview":
        event_type = "interview"
    return {
        "subjects": list(dict.fromkeys(subjects))[:12],
        "primary_subjects": list(
            dict.fromkeys(primary_subjects)
        )[:6],
        "action": action,
        "objects": list(
            dict.fromkeys(
                re.findall(
                    r"[《“\"]([^》”\"]{2,40})[》”\"]",
                    title,
                )
            )
        )[:8],
        "locations": locations,
        "event_time": _parse_time(
            document.get("published_at")
        ).isoformat(),
        "numbers": numbers,
        "event_type": event_type,
    }


def event_similarity(
    left: dict[str, Any],
    right: dict[str, Any],
) -> float:
    left_elements = left.get("event_elements") or {}
    right_elements = right.get("event_elements") or {}
    subjects = _jaccard(
        {_normalize(item) for item in left_elements.get("subjects", [])},
        {_normalize(item) for item in right_elements.get("subjects", [])},
    )
    left_primary_subjects = {
        _normalize(item)
        for item in left_elements.get("primary_subjects", [])
        if _normalize(item)
    }
    right_primary_subjects = {
        _normalize(item)
        for item in right_elements.get("primary_subjects", [])
        if _normalize(item)
    }
    subject_conflict = bool(
        left_primary_subjects
        and right_primary_subjects
        and left_primary_subjects.isdisjoint(right_primary_subjects)
    )
    left_action = str(left_elements.get("action") or "")
    right_action = str(right_elements.get("action") or "")
    action = 1.0 if left_action and left_action == right_action else 0.0
    semantic = _jaccard(
        _tokens(f"{left.get('title', '')} {left.get('body', '')[:500]}"),
        _tokens(f"{right.get('title', '')} {right.get('body', '')[:500]}"),
    )
    age_hours = abs(
        (
            _parse_time(left.get("published_at"))
            - _parse_time(right.get("published_at"))
        ).total_seconds()
        / 3600
    )
    time_proximity = max(0.0, 1 - age_hours / 168)
    left_numbers = set(left_elements.get("numbers", []))
    right_numbers = set(right_elements.get("numbers", []))
    number_consistency = (
        1.0
        if not left_numbers and not right_numbers
        else _jaccard(left_numbers, right_numbers)
    )
    score = (
        0.30 * subjects
        + 0.25 * action
        + 0.25 * semantic
        + 0.10 * time_proximity
        + 0.10 * number_consistency
    )
    if subject_conflict:
        score -= 0.28
    return _clamp(score)


def _relation_for(
    representative: dict[str, Any],
    document: dict[str, Any],
    similarity: float,
) -> str:
    if representative is document:
        return "same_event"
    representative_elements = representative.get("event_elements") or {}
    elements = document.get("event_elements") or {}
    text_similarity = _jaccard(
        _tokens(
            f"{representative.get('title', '')} "
            f"{representative.get('body', '')[:600]}"
        ),
        _tokens(f"{document.get('title', '')} {document.get('body', '')[:600]}"),
    )
    if similarity >= 0.82 and text_similarity >= 0.88:
        return "duplicate"
    if similarity >= 0.82:
        return "same_event"
    shared_subjects = set(representative_elements.get("subjects", [])) & set(
        elements.get("subjects", [])
    )
    if (
        shared_subjects
        and representative_elements.get("action")
        != elements.get("action")
        and similarity >= 0.52
    ):
        return "follow_up"
    if similarity >= 0.62:
        return "needs_review"
    if similarity >= 0.42:
        return "related"
    return "unrelated"


def _evidence_metadata(
    document: dict[str, Any],
    cluster_id: str,
) -> tuple[str, str, float]:
    source_type = str(document.get("source_type") or "").casefold()
    attributed = str(
        document.get("attributed_publisher")
        or document.get("publisher")
        or "unknown"
    )
    hostname = (
        urlparse(str(document.get("url") or "")).hostname or "unknown"
    ).casefold()
    if source_type in {"official", "policy", "research"}:
        relation = "official"
        chain_material = f"official:{hostname}"
        independence = 1.0
    elif document.get("attributed_publisher"):
        relation = "syndicated"
        chain_material = f"attributed:{_normalize(attributed)}"
        independence = 0.25
    elif source_type == "aggregator":
        relation = "aggregator"
        chain_material = f"aggregator:{cluster_id}"
        independence = 0.30
    elif source_type in {"forum", "community", "social"}:
        relation = "commentary"
        chain_material = f"commentary:{hostname}"
        independence = 0.40
    else:
        relation = "reporting"
        chain_material = f"reporting:{hostname}"
        independence = 0.75
    digest = hashlib.sha256(chain_material.encode("utf-8")).hexdigest()
    return f"chain_{digest[:16]}", relation, independence


class QualityPipeline:
    def analyze_documents(
        self,
        subscription: Subscription,
        documents: list[dict[str, Any]],
        preferences: SubscriptionPreferences | None = None,
    ) -> dict[str, Any]:
        preference = preferences or SubscriptionPreferences(
            subscription_id=subscription.id,
            updated_at=datetime.now(timezone.utc),
        )
        focus_keywords = effective_focus_keywords(
            name=subscription.name,
            focus_type=subscription.focus_type,
            keywords=subscription.include_keywords,
        )
        topic_tokens = _tokens(
            " ".join(
                [
                    subscription.name,
                    subscription.topic,
                    *focus_keywords,
                ]
            )
        )
        analyzed: list[dict[str, Any]] = []
        seen_content: Counter[str] = Counter()
        for raw_document in documents:
            document = dict(raw_document)
            title = str(document.get("title") or "")
            body = str(document.get("body") or "")
            haystack = f"{title}\n{body}".casefold()
            normalized_haystack = _normalize(haystack)
            matched_keywords = [
                keyword
                for keyword in focus_keywords
                if _normalize(keyword) in normalized_haystack
            ]
            elements = extract_event_elements(document, subscription)
            keyword_score = _clamp(
                len(matched_keywords)
                / max(1, min(4, len(focus_keywords)))
            )
            entity_score = _clamp(
                len(elements["subjects"])
                / max(1, min(4, len(focus_keywords)))
            )
            semantic_score = _clamp(
                _jaccard(_tokens(f"{title} {body[:1200]}"), topic_tokens) * 2.5
            )
            source_prior = _clamp(
                float(document.get("reliability") or 0.5)
            )
            focus_relation = _clamp(
                float(document.get("focus_relation_score") or 0)
            )
            preference_values = [
                preference.entity_weights.get(subject, 0)
                for subject in elements["subjects"]
            ]
            source_keys = {
                str(value)
                for value in (
                    document.get("configured_source_id"),
                    document.get("publisher"),
                    document.get("source_id"),
                )
                if value
            }
            preference_values.extend(
                preference.source_weights.get(source_key, 0)
                for source_key in source_keys
            )
            is_muted = bool(
                source_keys & set(preference.muted_sources)
            )
            if is_muted:
                preference_values.append(-1)
            raw_preference = (
                sum(preference_values) / len(preference_values)
                if preference_values
                else 0
            )
            normalized_preference = (min(1.0, max(-1.0, raw_preference)) + 1) / 2
            relevance = _clamp(
                0.25 * keyword_score
                + 0.20 * entity_score
                + 0.15 * semantic_score
                + 0.15 * source_prior
                + 0.15 * focus_relation
                + 0.10 * normalized_preference
            )
            content_key = hashlib.sha256(
                _normalize(f"{title} {body[:1200]}").encode("utf-8")
            ).hexdigest()
            seen_content[content_key] += 1
            novelty_components = {
                "url": 1.0 if document.get("is_new", True) else 0.2,
                "content": 1.0 if seen_content[content_key] == 1 else 0.0,
                "story": 1.0,
                "key_number_change": (
                    1.0 if elements["numbers"] else 0.5
                ),
                "action_change": 1.0,
            }
            novelty = _clamp(
                sum(novelty_components.values())
                / len(novelty_components)
            )
            ranking_reasons = [
                str(reason)
                for reason in document.get("ranking_reasons", [])
            ]
            if raw_preference:
                ranking_reasons.append(
                    f"personalization:preference:{raw_preference:+.2f}"
                )
            if is_muted:
                ranking_reasons.append(
                    "personalization:muted_source"
                )
            document.update(
                {
                    "keyword_match_score": keyword_score,
                    "entity_match_score": entity_score,
                    "semantic_match_score": semantic_score,
                    "source_prior_score": source_prior,
                    "focus_relation_score": focus_relation,
                    "user_preference_score": round(raw_preference, 4),
                    "relevance_score": relevance,
                    "novelty_score": novelty,
                    "novelty_components": novelty_components,
                    "event_elements": elements,
                    "ranking_reasons": list(
                        dict.fromkeys(ranking_reasons)
                    ),
                    "personalization_muted": is_muted,
                }
            )
            analyzed.append(document)

        clusters: list[list[dict[str, Any]]] = []
        for document in analyzed:
            best_cluster: list[dict[str, Any]] | None = None
            best_similarity = 0.0
            for cluster in clusters:
                similarity = event_similarity(cluster[0], document)
                if similarity > best_similarity:
                    best_cluster = cluster
                    best_similarity = similarity
            if best_cluster is not None and best_similarity >= 0.62:
                best_cluster.append(document)
            else:
                clusters.append([document])

        relation_counts: Counter[str] = Counter()
        for cluster in clusters:
            representative = cluster[0]
            cluster_material = "|".join(
                [
                    *(
                        representative.get("event_elements", {}).get(
                            "subjects", []
                        )
                    ),
                    str(
                        representative.get("event_elements", {}).get(
                            "action", "update"
                        )
                    ),
                    str(representative.get("published_at", ""))[:10],
                ]
            ) or str(representative.get("source_id"))
            cluster_digest = hashlib.sha256(
                cluster_material.casefold().encode("utf-8")
            ).hexdigest()
            cluster_id = f"cluster_{cluster_digest[:16]}"
            for document in cluster:
                similarity = event_similarity(representative, document)
                relation = _relation_for(
                    representative, document, similarity
                )
                representative_elements = representative.get(
                    "event_elements", {}
                )
                elements = document.get("event_elements", {})
                components = dict(
                    document.get("novelty_components", {})
                )
                components["story"] = {
                    "same_event": 0.35,
                    "duplicate": 0.0,
                    "follow_up": 0.9,
                    "needs_review": 0.5,
                    "related": 0.7,
                    "unrelated": 1.0,
                }.get(relation, 1.0)
                if representative is document:
                    components["key_number_change"] = (
                        1.0 if elements.get("numbers") else 0.5
                    )
                    components["action_change"] = 1.0
                else:
                    components["key_number_change"] = (
                        1.0
                        if set(elements.get("numbers", []))
                        != set(
                            representative_elements.get("numbers", [])
                        )
                        else 0.0
                    )
                    components["action_change"] = (
                        1.0
                        if elements.get("action")
                        != representative_elements.get("action")
                        else 0.0
                    )
                novelty_score = _clamp(
                    sum(components.values()) / max(1, len(components))
                )
                chain_id, evidence_relation, independence = (
                    _evidence_metadata(document, cluster_id)
                )
                document.update(
                    {
                        "cluster_id": cluster_id,
                        "cluster_relation": relation,
                        "evidence_chain_id": chain_id,
                        "evidence_relation_type": evidence_relation,
                        "independence_score": independence,
                        "novelty_components": components,
                        "novelty_score": novelty_score,
                    }
                )
                if relation == "duplicate":
                    document["novelty_score"] = min(
                        float(document["novelty_score"]), 0.25
                    )
                relation_counts[relation] += 1

        chain_count = len(
            {
                str(document["evidence_chain_id"])
                for document in analyzed
                if document.get("evidence_chain_id")
            }
        )
        return {
            "documents": analyzed,
            "cluster_count": len(clusters),
            "relation_counts": dict(relation_counts),
            "independent_evidence_chain_count": chain_count,
            "needs_review_count": relation_counts["needs_review"],
        }


def build_fact_citations(
    fact_text: str,
    source_ids: list[str],
    documents_by_id: dict[str, dict[str, Any]],
    *,
    source_quotes: list[IntelQuote] | None = None,
) -> list[IntelCitation]:
    citations: list[IntelCitation] = []
    quotes_by_source: dict[str, list[str]] = {}
    for source_quote in source_quotes or ():
        quotes_by_source.setdefault(source_quote.source_id, []).append(
            source_quote.quote
        )
    fact_tokens = _tokens(fact_text)
    fact_mentions = _number_mentions(fact_text)
    fact_latin_identifiers = _latin_identifiers(fact_text)
    fact_concepts = _concepts(fact_text)
    fact_contains_chinese = bool(
        re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", fact_text)
    )
    for source_id in source_ids:
        document = documents_by_id.get(source_id, {})
        body = str(document.get("body") or "")
        paragraphs = [
            re.sub(r"\s+", " ", paragraph).strip()
            for paragraph in re.split(r"\n\s*\n", body)
            if paragraph.strip()
        ]
        if not paragraphs and body.strip():
            paragraphs = [re.sub(r"\s+", " ", body).strip()]
        supplied = quotes_by_source.get(source_id)
        quote_spans: list[tuple[int | None, str]] = []
        if supplied:
            for quote in supplied:
                normalized_quote = re.sub(r"\s+", " ", quote).strip()
                paragraph_index = next(
                    (
                        index
                        for index, paragraph in enumerate(paragraphs)
                        if normalized_quote and normalized_quote in paragraph
                    ),
                    None,
                )
                # Keep unmatched quotes so Eval can reject them.
                quote_spans.append((paragraph_index, quote))
        else:
            quote_spans = [
                (index, quote)
                for index, paragraph in enumerate(paragraphs)
                for quote in _citation_quotes(paragraph)
            ]
        candidates: list[
            tuple[float, int | None, str, float, float, float, bool]
        ] = []
        for paragraph_index, quote in quote_spans:
            quote_tokens = _tokens(quote)
            overlap = _jaccard(fact_tokens, quote_tokens)
            fact_coverage = (
                len(fact_tokens & quote_tokens) / len(fact_tokens)
                if fact_tokens
                else 0.0
            )
            number_score = _number_support_rate(fact_text, quote)
            quote_contains_chinese = bool(
                re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", quote)
            )
            shared_identifiers = fact_latin_identifiers & _latin_identifiers(quote)
            shared_concepts = fact_concepts & _concepts(quote)
            cross_language_match = (
                fact_contains_chinese != quote_contains_chinese
                and len(shared_identifiers) >= 2
                and bool(shared_concepts)
            )
            lexical_rank = max(overlap, fact_coverage * 0.55)
            rank_score = (
                lexical_rank * 0.75
                + number_score * 0.25
                + (0.1 if cross_language_match else 0.0)
            )
            candidates.append(
                (
                    rank_score,
                    paragraph_index,
                    quote,
                    overlap,
                    fact_coverage,
                    number_score,
                    cross_language_match,
                )
            )
        if not candidates:
            continue
        if not supplied:
            candidates = [
                max(candidates, key=lambda item: (item[0], -len(item[2])))
            ]
        for (
            _,
            paragraph_index,
            quote,
            token_overlap,
            fact_coverage,
            number_score,
            cross_language_match,
        ) in candidates:
            quote_mentions = _number_mentions(quote)
            numeric_compatible = not fact_mentions or number_score == 1.0
            text_match = (
                token_overlap >= 0.18
                or fact_coverage >= 0.55
                or cross_language_match
            )
            if (
                fact_mentions
                and quote_mentions
                and not numeric_compatible
                and (
                    token_overlap >= 0.35
                    or fact_coverage >= 0.55
                    or cross_language_match
                )
            ):
                relation = "contradicts"
            else:
                relation = (
                    "supports"
                    if text_match and numeric_compatible
                    else "context"
                )
            citations.append(
                IntelCitation(
                    source_id=source_id,
                    quote=quote,
                    quote_hash=hashlib.sha256(quote.encode("utf-8")).hexdigest(),
                    locator=CitationLocator(paragraph=paragraph_index),
                    relation=relation,
                )
            )
    return citations
