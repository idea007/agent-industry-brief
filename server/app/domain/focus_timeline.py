from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from functools import cmp_to_key

from app.domain.models import (
    FocusType,
    IntelEvent,
    StoryRelation,
    StoryContextTimeline,
    StoryContextTimelineCounts,
    StoryContextTimelineItem,
    Subscription,
)
from app.domain.story_lifecycle import find_story_supersessions


AXIS_MARKERS: dict[str, tuple[str, ...]] = {
    "funding": (
        "融资",
        "募资",
        "资本",
        "投资",
        "上市",
        "ipo",
        "估值",
        "收购",
        "并购",
        "funding",
        "fundraising",
        "raises",
        "raised",
        "acquires",
        "acquired",
    ),
    "commercial": (
        "量产",
        "投产",
        "产线",
        "产能",
        "出货",
        "销量",
        "订单",
        "营收",
        "商业化",
        "市场规模",
        "供应链",
        "production",
        "commercial",
        "shipment",
        "revenue",
        "supplychain",
    ),
    "technology": (
        "技术",
        "模型",
        "算法",
        "研发",
        "发布",
        "上线",
        "推出",
        "开源",
        "平台",
        "系统",
        "推理",
        "性能",
        "api",
        "technology",
        "model",
        "research",
        "release",
        "launch",
    ),
    "match": (
        "比赛",
        "战平",
        "战胜",
        "首发",
        "替补",
        "出场",
        "登场",
        "进球",
        "助攻",
        "比分",
        "match",
        "game",
        "scores",
        "assists",
    ),
    "health": (
        "伤病",
        "受伤",
        "伤缺",
        "休战",
        "复出",
        "恢复",
        "回归",
        "injured",
        "returns",
        "recovery",
    ),
    "transfer": (
        "转会",
        "签约",
        "续约",
        "加盟",
        "离队",
        "新援",
        "transfer",
        "signs",
        "joins",
        "leaves",
    ),
    "reaction": (
        "评价",
        "评论",
        "称赞",
        "赞誉",
        "批评",
        "质疑",
        "回应",
        "观点",
        "采访",
        "表示",
        "says",
        "praises",
        "criticizes",
        "reaction",
        "opinion",
        "interview",
    ),
    "event": (
        "活动",
        "大会",
        "峰会",
        "仪式",
        "致敬",
        "纪念",
        "展会",
        "赛事",
        "event",
        "summit",
        "tribute",
    ),
}

AXIS_LABELS = {
    "funding": "融资",
    "commercial": "商业化",
    "technology": "技术",
    "match": "比赛",
    "health": "状态变化",
    "transfer": "转会",
    "reaction": "观点",
    "event": "活动",
}

CATEGORY_AXES = {
    "funding": "funding",
    "technology": "technology",
    "event": "event",
    "interview": "reaction",
}

AXIS_ADJACENCY = {
    "funding": {"commercial"},
    "commercial": {"funding", "technology"},
    "technology": {"commercial"},
    "match": {"health", "reaction"},
    "health": {"match", "reaction"},
    "transfer": {"reaction"},
    "reaction": {"match", "health", "transfer", "event"},
    "event": {"reaction"},
}

TOPIC_FAMILIES = (
    frozenset(
        {
            "机器人",
            "人形机器人",
            "具身智能",
            "embodiedai",
            "humanoid",
            "robot",
            "robotics",
        }
    ),
    frozenset({"aiagent", "agent", "智能体", "agenticai"}),
    frozenset({"大模型", "语言模型", "llm", "largelanguagemodel"}),
    frozenset({"自动驾驶", "智能驾驶", "autonomousdriving"}),
)

GENERIC_TOPIC_TAGS = {
    "新闻",
    "动态",
    "行业",
    "公司",
    "人物",
    "产品",
    "中国",
    "全球",
    "ai",
    "news",
}

NARROW_FOCUS_TYPES = {
    FocusType.COMPANY,
    FocusType.PERSON,
    FocusType.PRODUCT,
    FocusType.EVENT,
}

LIFECYCLE_SUBJECT_FOCUS_TYPES = {
    *NARROW_FOCUS_TYPES,
    FocusType.TEAM,
    FocusType.SPORTS,
}


def _normalize(value: str) -> str:
    return re.sub(
        r"[^0-9a-z\u3400-\u4dbf\u4e00-\u9fff]+",
        "",
        value.casefold(),
    )


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _focus_aliases(subscription: Subscription) -> tuple[str, ...]:
    subject = _normalize(subscription.name)
    aliases = [subject] if subject else []
    for keyword in subscription.include_keywords:
        normalized = _normalize(keyword)
        if (
            normalized
            and len(normalized) >= 2
            and (normalized in subject or subject in normalized)
        ):
            aliases.append(normalized)
    return tuple(dict.fromkeys(aliases))


def _matches_focus(event: IntelEvent, aliases: tuple[str, ...]) -> bool:
    values = (event.title, event.summary, *event.tags)
    return any(
        alias in _normalize(value)
        for value in values
        for alias in aliases
    )


def _event_axes(event: IntelEvent) -> frozenset[str]:
    haystack = _normalize(" ".join((event.title, *event.tags)))
    axes = {
        axis
        for axis, markers in AXIS_MARKERS.items()
        if any(_normalize(marker) in haystack for marker in markers)
    }
    category_axis = CATEGORY_AXES.get(event.category)
    if category_axis:
        axes.add(category_axis)
    return frozenset(axes)


def _axis_marker_values() -> frozenset[str]:
    return frozenset(
        _normalize(marker)
        for markers in AXIS_MARKERS.values()
        for marker in markers
    )


AXIS_MARKER_VALUES = _axis_marker_values()


def _topic_tags(
    subscription: Subscription,
    event: IntelEvent,
) -> tuple[tuple[str, str], ...]:
    focus_subject = _normalize(subscription.name)
    selected: list[tuple[str, str]] = []
    seen: set[str] = set()
    for tag in event.tags:
        normalized = _normalize(tag)
        if (
            len(normalized) < 2
            or normalized in seen
            or normalized == focus_subject
            or normalized in AXIS_MARKER_VALUES
            or normalized in GENERIC_TOPIC_TAGS
        ):
            continue
        selected.append((tag.strip(), normalized))
        seen.add(normalized)
    return tuple(selected)


def _topic_family(value: str) -> int | None:
    for index, family in enumerate(TOPIC_FAMILIES):
        if any(member in value or value in member for member in family):
            return index
    return None


def _tag_affinity(left: str, right: str) -> int:
    if left == right:
        return 3
    if min(len(left), len(right)) >= 3 and (
        left in right or right in left
    ):
        return 2
    left_family = _topic_family(left)
    right_family = _topic_family(right)
    if left_family is not None and left_family == right_family:
        return 2
    return 0


def _topic_affinity(
    subscription: Subscription,
    anchor: IntelEvent,
    candidate: IntelEvent,
) -> int:
    anchor_tags = _topic_tags(subscription, anchor)
    candidate_tags = _topic_tags(subscription, candidate)
    return max(
        (
            _tag_affinity(left, right)
            for _, left in anchor_tags
            for _, right in candidate_tags
        ),
        default=0,
    )


def _axis_relation(anchor: IntelEvent, candidate: IntelEvent) -> str:
    anchor_axes = _event_axes(anchor)
    candidate_axes = _event_axes(candidate)
    if anchor_axes & candidate_axes:
        return "same"
    if any(
        candidate_axis in AXIS_ADJACENCY.get(anchor_axis, set())
        for anchor_axis in anchor_axes
        for candidate_axis in candidate_axes
    ):
        return "adjacent"
    if anchor_axes and candidate_axes:
        return "different"
    if anchor.category == candidate.category and anchor.category != "news":
        return "same"
    return "unknown"


def _topic_label(subscription: Subscription, anchor: IntelEvent) -> str:
    parts = [label for label, _ in _topic_tags(subscription, anchor)[:2]]
    axes = _event_axes(anchor)
    preferred_axis = CATEGORY_AXES.get(anchor.category)
    axis = (
        preferred_axis
        if preferred_axis in axes
        else next((name for name in AXIS_MARKERS if name in axes), None)
    )
    if axis and not any(
        _normalize(AXIS_LABELS[axis]) in _normalize(part)
        for part in parts
    ):
        parts.append(AXIS_LABELS[axis])
    if parts:
        return " · ".join(parts)
    title = anchor.title.strip()
    return title if len(title) <= 32 else f"{title[:31]}…"


def _relation_by_story(
    current_story_id: str,
    relations: list[StoryRelation],
) -> dict[str, str]:
    related: dict[str, str] = {}
    priorities = {
        "unrelated": 5,
        "duplicate": 5,
        "superseded_by": 4,
        "same_event": 3,
        "follow_up": 3,
        "related": 1,
    }
    for relation in relations:
        story_id = (
            relation.to_story_id
            if relation.from_story_id == current_story_id
            else relation.from_story_id
        )
        current = related.get(story_id)
        if current is None or priorities.get(
            relation.relation, 0
        ) > priorities.get(current, 0):
            related[story_id] = relation.relation
    return related


def _classify_item(
    subscription: Subscription,
    anchor: IntelEvent,
    candidate: IntelEvent,
    *,
    story_id: str,
    current_story_id: str,
    explicit_relation: str | None,
) -> tuple[str, str, str] | None:
    if story_id == current_story_id:
        return "core", "direct", "current_story_anchor"
    if explicit_relation in {"duplicate", "unrelated"}:
        return None
    if explicit_relation in {"same_event", "follow_up"}:
        return "core", "follow_up", "explicit_story_progress"
    if explicit_relation == "superseded_by":
        return "related", "resolved_by", "explicit_lifecycle_update"
    if explicit_relation == "related":
        return "related", "topic_related", "explicit_story_relation"

    affinity = _topic_affinity(subscription, anchor, candidate)
    axis_relation = _axis_relation(anchor, candidate)
    if affinity >= 2 and axis_relation == "same":
        return "core", "direct", "same_topic_same_axis"
    if affinity >= 2 and axis_relation == "adjacent":
        return "related", "topic_related", "same_topic_adjacent_axis"
    if affinity >= 3 and axis_relation == "unknown":
        return "core", "direct", "same_topic_update"
    if affinity >= 3:
        return "context", "context", "same_topic_background"
    if affinity >= 2:
        return "context", "context", "related_topic_background"

    aliases = _focus_aliases(subscription)
    if (
        subscription.focus_type in NARROW_FOCUS_TYPES
        and _matches_focus(anchor, aliases)
        and _matches_focus(candidate, aliases)
    ):
        return "context", "context", "shared_narrow_focus_background"
    return None


def build_story_context_timeline(
    subscription: Subscription,
    events: list[IntelEvent],
    *,
    current_story_id: str,
    story_relations: list[StoryRelation] | None = None,
    window_days: int = 30,
    now: datetime | None = None,
) -> StoryContextTimeline:
    generated_at = _aware(now or datetime.now(timezone.utc))
    window_start = generated_at - timedelta(days=window_days)
    anchor_events = [
        event for event in events if event.story_id == current_story_id
    ]
    if not anchor_events:
        raise ValueError("Current story has no IntelEvent anchor")
    anchor = max(
        anchor_events,
        key=lambda item: (_aware(item.event_time), _aware(item.created_at)),
    )
    recent_events = [
        event
        for event in events
        if (
            _aware(event.event_time) >= window_start
            or event.story_id == current_story_id
        )
    ]
    events_by_story: dict[str, list[IntelEvent]] = defaultdict(list)
    for event in recent_events:
        events_by_story[event.story_id or event.id].append(event)

    relation_by_story = _relation_by_story(
        current_story_id,
        story_relations or [],
    )
    latest_by_story = {
        story_id: max(
            story_events,
            key=lambda item: (_aware(item.event_time), _aware(item.created_at)),
        )
        for story_id, story_events in events_by_story.items()
    }
    supersessions = find_story_supersessions(
        list(latest_by_story.values()),
        focus_name=subscription.name,
        focus_is_subject=(
            subscription.focus_type in LIFECYCLE_SUBJECT_FOCUS_TYPES
        ),
    )
    supersession_by_story = {
        item.anticipated_story_id: item for item in supersessions
    }
    resolution_story_ids = {
        item.resolution_story_id for item in supersessions
    }
    items: list[StoryContextTimelineItem] = []
    for story_id, story_events in events_by_story.items():
        ordered_events = sorted(
            story_events,
            key=lambda item: (_aware(item.event_time), _aware(item.created_at)),
        )
        latest = ordered_events[-1]
        current_supersession = supersession_by_story.get(current_story_id)
        item_supersession = supersession_by_story.get(story_id)
        if current_supersession and story_id == current_story_id:
            classification = (
                "related",
                "resolved_by",
                "current_story_superseded",
            )
        elif (
            current_supersession
            and story_id == current_supersession.resolution_story_id
        ):
            classification = (
                "core",
                "resolves",
                "resolves_current_story",
            )
        elif (
            item_supersession
            and item_supersession.resolution_story_id == current_story_id
        ):
            classification = (
                "related",
                "resolved_by",
                "resolved_history",
            )
        else:
            classification = _classify_item(
                subscription,
                anchor,
                latest,
                story_id=story_id,
                current_story_id=current_story_id,
                explicit_relation=relation_by_story.get(story_id),
            )
        if classification is None:
            continue
        tier, relation, reason = classification
        if (
            story_id == current_story_id
            and len(ordered_events) > 1
            and item_supersession is None
        ):
            relation = "follow_up"
            reason = "ongoing_story_progress"
        temporal_status = (
            "superseded"
            if item_supersession
            else "resolution"
            if story_id in resolution_story_ids
            else "current"
        )
        temporal_note = (
            item_supersession.note
            if item_supersession
            else (
                "这条后续事实更新了此前的预计、传闻或时间安排。"
                if temporal_status == "resolution"
                else None
            )
        )
        items.append(
            StoryContextTimelineItem(
                story_id=story_id,
                latest_event_id=latest.id,
                title=latest.title,
                summary=latest.summary,
                category=latest.category,
                event_time=latest.event_time,
                importance_score=latest.importance_score,
                tier=tier,
                relation=relation,
                reason=reason,
                event_count=len(ordered_events),
                temporal_status=temporal_status,
                resolved_by_story_id=(
                    item_supersession.resolution_story_id
                    if item_supersession
                    else None
                ),
                temporal_note=temporal_note,
            )
        )

    def compare_items(
        left: StoryContextTimelineItem,
        right: StoryContextTimelineItem,
    ) -> int:
        if left.resolved_by_story_id == right.story_id:
            return 1
        if right.resolved_by_story_id == left.story_id:
            return -1
        left_key = (_aware(left.event_time), left.importance_score)
        right_key = (_aware(right.event_time), right.importance_score)
        return -1 if left_key > right_key else 1 if left_key < right_key else 0

    items.sort(key=cmp_to_key(compare_items))
    counts = StoryContextTimelineCounts(
        core=sum(item.tier == "core" for item in items),
        related=sum(item.tier == "related" for item in items),
        context=sum(item.tier == "context" for item in items),
    )
    return StoryContextTimeline(
        subscription_id=subscription.id,
        current_story_id=current_story_id,
        subject=subscription.name,
        topic=_topic_label(subscription, anchor),
        focus_type=subscription.focus_type,
        window_days=window_days,
        window_start=window_start,
        generated_at=generated_at,
        counts=counts,
        items=items,
    )
