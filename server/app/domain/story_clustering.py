from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta


STORY_WINDOW = timedelta(hours=72)
LATE_FEED_SYNDICATION_WINDOW = timedelta(days=14)
GENERIC_TAGS = {
    "ai",
    "news",
    "event",
    "funding",
    "interview",
    "technology",
    "产业",
    "事件",
    "行业",
    "技术",
    "新闻",
    "活动",
    "融资",
    "访谈",
}
ACTION_MARKERS = {
    "上市",
    "下线",
    "事故",
    "停产",
    "停售",
    "发布",
    "召回",
    "合作",
    "开源",
    "投产",
    "收购",
    "涨价",
    "获批",
    "裁员",
    "试生产",
    "量产",
    "降价",
}


@dataclass(frozen=True)
class StoryFingerprint:
    title: str
    category: str
    tags: frozenset[str]
    event_time: datetime
    source_ids: frozenset[str]
    source_urls: frozenset[str]
    content_origins: frozenset[str] = frozenset()


@dataclass(frozen=True)
class StoryMatch:
    score: float
    reason: str


@dataclass(frozen=True)
class StoryRelationMatch:
    relation: str
    score: float
    reason: str


def _normalize_text(value: str) -> str:
    return re.sub(
        r"[^0-9a-z\u3400-\u4dbf\u4e00-\u9fff]+",
        "",
        value.casefold(),
    )


def _meaningful_tags(tags: frozenset[str]) -> set[str]:
    normalized = {
        _normalize_text(tag)
        for tag in tags
        if _normalize_text(tag)
    }
    return {
        tag
        for tag in normalized
        if tag not in GENERIC_TAGS and len(tag) >= 2
    }


def _latin_entities(title: str) -> set[str]:
    return {
        token.casefold()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9.+-]{1,}", title)
        if token.casefold() not in GENERIC_TAGS
    }


def _bigrams(value: str) -> set[str]:
    normalized = _normalize_text(value)
    if len(normalized) < 2:
        return {normalized} if normalized else set()
    return {
        normalized[index : index + 2]
        for index in range(len(normalized) - 1)
    }


def _dice_similarity(left: str, right: str) -> float:
    left_bigrams = _bigrams(left)
    right_bigrams = _bigrams(right)
    if not left_bigrams or not right_bigrams:
        return 0.0
    return (
        2 * len(left_bigrams & right_bigrams)
        / (len(left_bigrams) + len(right_bigrams))
    )


def _actions(title: str) -> set[str]:
    return {
        marker
        for marker in ACTION_MARKERS
        if marker in title
    }


def match_story(
    left: StoryFingerprint,
    right: StoryFingerprint,
) -> StoryMatch | None:
    """Return a conservative match for two reports about the same story."""

    if left.source_ids & right.source_ids:
        return StoryMatch(score=1.0, reason="shared_source_id")
    if left.source_urls & right.source_urls:
        return StoryMatch(score=1.0, reason="shared_source_url")
    if left.category != right.category:
        return None

    distance = abs(left.event_time - right.event_time)
    left_actions = _actions(left.title)
    right_actions = _actions(right.title)
    if left_actions and right_actions and not (left_actions & right_actions):
        return None

    similarity = _dice_similarity(left.title, right.title)
    shared_tags = _meaningful_tags(left.tags) & _meaningful_tags(right.tags)
    shared_entities = _latin_entities(left.title) & _latin_entities(right.title)

    if distance > STORY_WINDOW:
        feed_only = (
            left.content_origins
            and right.content_origins
            and left.content_origins <= {"feed"}
            and right.content_origins <= {"feed"}
        )
        if (
            distance <= LATE_FEED_SYNDICATION_WINDOW
            and feed_only
            and similarity >= 0.68
            and len(shared_tags) >= 2
        ):
            return StoryMatch(
                score=min(0.95, similarity + 0.12),
                reason="late_feed_syndication",
            )
        return None

    if similarity >= 0.64:
        return StoryMatch(score=similarity, reason="high_title_similarity")
    if similarity >= 0.40 and (
        len(shared_tags) >= 2 or bool(shared_entities)
    ):
        return StoryMatch(
            score=min(0.99, similarity + 0.08),
            reason="title_and_entity_similarity",
        )
    return None


def classify_story_relation(
    left: StoryFingerprint,
    right: StoryFingerprint,
) -> StoryRelationMatch | None:
    exact = match_story(left, right)
    if exact is not None:
        relation = (
            "duplicate"
            if left.source_ids & right.source_ids
            or left.source_urls & right.source_urls
            else "same_event"
        )
        return StoryRelationMatch(
            relation=relation,
            score=exact.score,
            reason=exact.reason,
        )
    if abs(left.event_time - right.event_time) > timedelta(days=45):
        return None
    shared_tags = _meaningful_tags(left.tags) & _meaningful_tags(right.tags)
    shared_entities = _latin_entities(left.title) & _latin_entities(right.title)
    similarity = _dice_similarity(left.title, right.title)
    left_actions = _actions(left.title)
    right_actions = _actions(right.title)
    if (
        (shared_entities or len(shared_tags) >= 2)
        and left_actions
        and right_actions
        and not (left_actions & right_actions)
    ):
        return StoryRelationMatch(
            relation="follow_up",
            score=min(0.9, 0.62 + similarity * 0.25),
            reason="shared_subject_with_changed_action",
        )
    if similarity >= 0.34 and (shared_entities or shared_tags):
        return StoryRelationMatch(
            relation="related",
            score=min(0.78, similarity + 0.12),
            reason="shared_subject_or_tag",
        )
    return None
