from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.domain.models import IntelEvent


@dataclass(frozen=True)
class LifecycleFamily:
    label: str
    topic_markers: tuple[str, ...]
    realized_markers: tuple[str, ...]
    cancelled_markers: tuple[str, ...] = ()


@dataclass(frozen=True)
class LifecycleSignal:
    family: str
    label: str
    stage: str


@dataclass(frozen=True)
class StorySupersession:
    anticipated_story_id: str
    resolution_story_id: str
    family: str
    confidence: float
    reason: str
    note: str


LIFECYCLE_FAMILIES: dict[str, LifecycleFamily] = {
    "participation": LifecycleFamily(
        label="出场或复出安排",
        topic_markers=(
            "复出",
            "回归",
            "伤愈",
            "出场",
            "登场",
            "首发",
            "参赛",
            "出战",
        ),
        realized_markers=(
            "替补登场",
            "替补出场",
            "首发登场",
            "完成复出",
            "正式复出",
            "回归赛场",
            "已经复出",
            "已复出",
            "出战",
            "登场",
            "出场",
        ),
        cancelled_markers=(
            "复出推迟",
            "继续缺阵",
            "无缘出场",
            "退出比赛",
            "再次伤缺",
        ),
    ),
    "release": LifecycleFamily(
        label="发布或上市安排",
        topic_markers=(
            "发布",
            "推出",
            "上线",
            "上市",
            "开售",
            "发售",
            "交付",
            "launch",
            "release",
        ),
        realized_markers=(
            "发布",
            "推出",
            "上线",
            "上市",
            "开售",
            "发售",
            "正式发布",
            "正式推出",
            "正式上线",
            "正式上市",
            "正式开售",
            "开启交付",
            "开始交付",
            "launched",
            "released",
        ),
        cancelled_markers=(
            "延期发布",
            "推迟发布",
            "取消发布",
            "暂停上市",
            "停止交付",
            "下架",
        ),
    ),
    "transaction": LifecycleFamily(
        label="融资或交易安排",
        topic_markers=(
            "融资",
            "募资",
            "收购",
            "并购",
            "交易",
            "交割",
            "签约",
            "funding",
            "acquisition",
        ),
        realized_markers=(
            "收购",
            "交割",
            "签约",
            "完成融资",
            "获得融资",
            "宣布融资",
            "完成收购",
            "正式收购",
            "完成交割",
            "正式签约",
            "融资到账",
            "closedfunding",
            "completedacquisition",
        ),
        cancelled_markers=(
            "终止收购",
            "取消收购",
            "交易终止",
            "融资失败",
            "终止融资",
        ),
    ),
    "appointment": LifecycleFamily(
        label="任命或任职安排",
        topic_markers=(
            "任命",
            "出任",
            "上任",
            "就任",
            "离任",
            "履新",
            "appoint",
        ),
        realized_markers=(
            "任命",
            "出任",
            "上任",
            "就任",
            "正式任命",
            "宣布任命",
            "正式出任",
            "正式上任",
            "已经上任",
            "履新",
            "appointed",
        ),
        cancelled_markers=("撤回任命", "不再出任", "辞任", "离任"),
    ),
    "scheduled_event": LifecycleFamily(
        label="活动或赛事安排",
        topic_markers=(
            "举行",
            "举办",
            "开幕",
            "召开",
            "比赛",
            "活动",
            "大会",
            "赛事",
        ),
        realized_markers=(
            "举行",
            "举办",
            "正式举行",
            "正式举办",
            "正式开幕",
            "顺利举行",
            "召开",
            "开幕",
            "完赛",
            "落幕",
        ),
        cancelled_markers=(
            "取消举行",
            "延期举行",
            "推迟举行",
            "赛事取消",
            "活动取消",
        ),
    ),
    "policy": LifecycleFamily(
        label="政策或规则安排",
        topic_markers=(
            "政策",
            "法规",
            "条例",
            "规则",
            "标准",
            "生效",
            "实施",
        ),
        realized_markers=(
            "正式发布",
            "正式实施",
            "正式生效",
            "开始实施",
            "施行",
        ),
        cancelled_markers=("暂缓实施", "停止实施", "废止", "撤回"),
    ),
}

ANTICIPATION_MARKERS = (
    "预计",
    "计划",
    "拟于",
    "拟将",
    "拟发布",
    "拟推出",
    "拟上线",
    "拟上市",
    "拟收购",
    "拟融资",
    "拟任命",
    "拟举行",
    "拟实施",
    "有望",
    "或将",
    "可能",
    "即将",
    "将于",
    "将复出",
    "将回归",
    "将出场",
    "将发布",
    "将推出",
    "将上线",
    "将上市",
    "将开售",
    "将收购",
    "将融资",
    "将任命",
    "将举行",
    "将实施",
    "时间曝光",
    "时间确认",
    "定档",
    "传闻",
    "考虑",
    "目标是",
    "expected",
    "plans",
    "planned",
    "could",
    "may",
)

GENERIC_SUBJECT_TAGS = {
    "新闻",
    "动态",
    "行业",
    "公司",
    "人物",
    "产品",
    "技术",
    "活动",
    "赛事",
    "比赛",
    "融资",
    "访谈",
    "评价",
    "评论",
    "复出",
    "回归",
    "出场",
    "登场",
    "发布",
    "上线",
    "上市",
    "收购",
    "任命",
    "政策",
    "规则",
    "news",
    "event",
    "technology",
    "funding",
}

FORWARD_RESOLUTION_WINDOW = timedelta(days=45)
LATE_REPOST_WINDOW = timedelta(days=7)


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


def lifecycle_signals(event: IntelEvent) -> tuple[LifecycleSignal, ...]:
    text = _normalize(" ".join((event.title, event.summary, *event.tags)))
    is_anticipated = any(
        _normalize(marker) in text for marker in ANTICIPATION_MARKERS
    )
    signals: list[LifecycleSignal] = []
    for family_name, family in LIFECYCLE_FAMILIES.items():
        if not any(_normalize(marker) in text for marker in family.topic_markers):
            continue
        cancelled = any(
            _normalize(marker) in text for marker in family.cancelled_markers
        )
        realized = any(
            _normalize(marker) in text for marker in family.realized_markers
        )
        stage = (
            "cancelled"
            if cancelled
            else "anticipated"
            if is_anticipated
            else "realized"
            if realized
            else "neutral"
        )
        if stage != "neutral":
            signals.append(
                LifecycleSignal(
                    family=family_name,
                    label=family.label,
                    stage=stage,
                )
            )
    return tuple(signals)


def _subject_terms(event: IntelEvent) -> set[str]:
    terms: set[str] = set()
    lifecycle_markers = {
        _normalize(marker)
        for family in LIFECYCLE_FAMILIES.values()
        for marker in (*family.topic_markers, *family.realized_markers)
    }
    generic = {_normalize(tag) for tag in GENERIC_SUBJECT_TAGS}
    for tag in event.tags:
        normalized = _normalize(tag)
        if (
            len(normalized) >= 2
            and normalized not in generic
            and normalized not in lifecycle_markers
        ):
            terms.add(normalized)
    terms.update(
        token.casefold()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9.+-]{1,}", event.title)
        if token.casefold() not in generic
    )
    return terms


def _shares_subject(
    left: IntelEvent,
    right: IntelEvent,
    *,
    focus_name: str | None,
    focus_is_subject: bool,
) -> bool:
    if _subject_terms(left) & _subject_terms(right):
        return True
    normalized_focus = _normalize(focus_name or "")
    if not normalized_focus or not focus_is_subject:
        return False
    return all(
        normalized_focus in _normalize(f"{event.title} {event.summary}")
        for event in (left, right)
    )


def _is_feed_only(event: IntelEvent) -> bool:
    if not event.sources:
        return False
    return all(
        source.content_origin != "fulltext" and source.word_count < 120
        for source in event.sources
    )


def _verification_rank(event: IntelEvent) -> int:
    return {
        "confirmed": 3,
        "partially_confirmed": 2,
        "unconfirmed": 1,
        "conflicting": 0,
    }[event.verification_status]


def _can_resolve(
    anticipated: IntelEvent,
    resolution: IntelEvent,
) -> bool:
    anticipated_at = _aware(anticipated.event_time)
    resolution_at = _aware(resolution.event_time)
    if anticipated_at <= resolution_at:
        return (
            resolution_at - anticipated_at <= FORWARD_RESOLUTION_WINDOW
            and _verification_rank(resolution) >= 2
            and resolution.confidence_score >= 0.65
        )
    return (
        anticipated_at - resolution_at <= LATE_REPOST_WINDOW
        and _is_feed_only(anticipated)
        and anticipated.verification_status == "unconfirmed"
        and _verification_rank(resolution) >= 2
        and resolution.confidence_score
        >= anticipated.confidence_score + 0.15
    )


def find_story_supersessions(
    events: list[IntelEvent],
    *,
    focus_name: str | None = None,
    focus_is_subject: bool = False,
) -> list[StorySupersession]:
    signals_by_event = {
        event.id: lifecycle_signals(event) for event in events
    }
    matches_by_story: dict[str, tuple[float, StorySupersession]] = {}
    for anticipated in events:
        anticipated_signals = {
            signal.family: signal
            for signal in signals_by_event[anticipated.id]
            if signal.stage == "anticipated"
        }
        if not anticipated_signals:
            continue
        for resolution in events:
            if resolution.story_id == anticipated.story_id:
                continue
            resolution_signals = {
                signal.family: signal
                for signal in signals_by_event[resolution.id]
                if signal.stage in {"realized", "cancelled"}
            }
            shared_families = anticipated_signals.keys() & resolution_signals.keys()
            if not shared_families or not _shares_subject(
                anticipated,
                resolution,
                focus_name=focus_name,
                focus_is_subject=focus_is_subject,
            ):
                continue
            if not _can_resolve(anticipated, resolution):
                continue
            family = sorted(shared_families)[0]
            signal = resolution_signals[family]
            distance_days = abs(
                (_aware(resolution.event_time) - _aware(anticipated.event_time)).total_seconds()
            ) / 86400
            score = (
                resolution.confidence_score
                + _verification_rank(resolution) * 0.08
                - min(distance_days, 45) * 0.004
            )
            confidence = min(0.98, max(0.7, score))
            outcome_label = "后续取消或纠正信息" if signal.stage == "cancelled" else "后续已发生事实"
            match = StorySupersession(
                anticipated_story_id=anticipated.story_id,
                resolution_story_id=resolution.story_id,
                family=family,
                confidence=confidence,
                reason=f"lifecycle:{family}:anticipated_to_{signal.stage}",
                note=(
                    f"其中的{signal.label}已被{outcome_label}更新；"
                    "原报道仍作为前情和来源证据保留。"
                ),
            )
            existing = matches_by_story.get(anticipated.story_id)
            if existing is None or score > existing[0]:
                matches_by_story[anticipated.story_id] = (score, match)
    return [item[1] for item in matches_by_story.values()]
