from __future__ import annotations

import re

from app.domain.models import (
    FocusDomain,
    FocusProfile,
    FocusRelationProfile,
    FocusType,
)


SPORTS_MARKERS = (
    "体育",
    "足球",
    "football",
    "soccer",
    "篮球",
    "网球",
    "排球",
    "乒乓球",
    "羽毛球",
    "高尔夫",
    "赛车",
    "f1",
    "fifa",
    "mls",
    "nba",
    "cba",
    "世界杯",
    "欧冠",
    "联赛",
    "俱乐部",
    "球队",
    "球员",
    "梅西",
    "intermiami",
    "c罗",
    "姆巴佩",
    "内马尔",
    "皇马",
    "巴萨",
    "曼联",
    "曼城",
    "利物浦",
    "阿森纳",
)
ENTERTAINMENT_MARKERS = (
    "娱乐",
    "段子",
    "搞笑",
    "抖机灵",
    "热梗",
    "网络梗",
    "meme",
    "脱口秀",
    "单口喜剧",
    "喜剧",
    "综艺",
    "短视频",
)
CONTENT_DISCOVERY_MARKERS = (
    "段子",
    "笑话",
    "冷笑话",
    "搞笑",
    "抖机灵",
    "热梗",
    "网络梗",
    "梗图",
    "表情包",
    "趣图",
    "幽默",
    "meme",
)
CONTENT_GOAL_MARKERS = (
    "内容本身",
    "创作者原帖",
    "原帖",
    "作品本身",
    "可直接阅读",
    "可直接观看",
    "好玩",
    "好笑",
    "新鲜段子",
    "精选内容",
)
EVENT_MARKERS = (
    "大会",
    "峰会",
    "会议",
    "展会",
    "发布会",
    "颁奖",
    "选举",
    "事故",
    "活动",
)
TECHNOLOGY_MARKERS = (
    "技术",
    "产品",
    "模型",
    "平台",
    "框架",
    "软件",
    "硬件",
    "手机",
    "电脑",
    "消费电子",
    "芯片",
    "开源",
    "sdk",
    "api",
)
PERSON_MARKERS = (
    "创始人",
    "ceo",
    "董事长",
    "教授",
    "学者",
    "导演",
    "演员",
    "歌手",
    "作者",
    "运动员",
)
COMPANY_MARKERS = (
    "公司",
    "集团",
    "企业",
    "工作室",
    "实验室",
    "inc",
    "corp",
    "ltd",
)
TEAM_MARKERS = (
    "球队",
    "国家队",
    "俱乐部",
    "战队",
    "团队",
    "车队",
    "乐队",
    "组合",
    "team",
    "club",
)
KNOWN_PERSON_NAMES = (
    "梅西",
    "c罗",
    "姆巴佩",
    "内马尔",
)
AUTOMOTIVE_MARKERS = (
    "汽车",
    "车企",
    "车型",
    "新能源车",
    "新能源汽车",
    "电动车",
    "智能驾驶",
    "自动驾驶",
    "座舱",
    "交付量",
    "车主",
)
FINANCE_MARKERS = (
    "金融",
    "银行",
    "证券",
    "基金",
    "保险",
    "投资",
    "融资",
    "财报",
)
HEALTHCARE_MARKERS = (
    "医疗",
    "医药",
    "医院",
    "药物",
    "临床",
    "健康",
)
CONTEXT_RELATION_MARKERS = (
    "行业",
    "市场",
    "政策",
    "监管",
    "标准",
    "生态",
    "供应链",
    "竞品",
    "竞争对手",
)
PRODUCT_MODEL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z][A-Za-z0-9.+]*[- ]?)"
    r"\d+[A-Za-z0-9.+-]*(?![A-Za-z0-9])",
    re.I,
)
BROAD_PRODUCT_TERMS = frozenset(
    {
        "汽车",
        "车辆",
        "车型",
        "手机",
        "电脑",
        "产品",
        "设备",
        "软件",
        "硬件",
        "科技",
        "数码",
        "消费电子",
        "新能源",
        "电动车",
        "electricvehicle",
        "ev",
    }
)


def normalize_focus_text(value: str) -> str:
    return re.sub(
        r"[^0-9a-z\u3400-\u4dbf\u4e00-\u9fff]+",
        "",
        value.casefold(),
    )


def _looks_like_product_name(name: str) -> bool:
    for match in PRODUCT_MODEL_PATTERN.finditer(name):
        numbers = re.findall(r"\d+", match.group())
        if len(numbers) == 1 and re.fullmatch(r"(?:19|20)\d{2}", numbers[0]):
            continue
        return True
    return False


def product_focus_terms(
    name: str,
    keywords: list[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split product aliases from parent/company and ecosystem terms."""

    normalized_name = normalize_focus_text(name)
    direct = [name.strip()] if normalized_name else []
    related: list[str] = []
    for keyword in keywords:
        value = keyword.strip()
        normalized = normalize_focus_text(value)
        if (
            not normalized
            or normalized in BROAD_PRODUCT_TERMS
            or normalized == normalized_name
        ):
            continue
        if normalized in normalized_name or normalized_name in normalized:
            direct.append(value)
        else:
            related.append(value)
    return (
        tuple(dict.fromkeys(direct)),
        tuple(dict.fromkeys(related)),
    )


def effective_focus_keywords(
    *,
    name: str,
    focus_type: FocusType,
    keywords: list[str],
) -> list[str]:
    if focus_type != FocusType.PRODUCT:
        return list(
            dict.fromkeys(value.strip() for value in keywords if value.strip())
        )
    direct, related = product_focus_terms(name, keywords)
    return [*direct, *related]


def ranking_focus_terms(
    *,
    name: str,
    focus_type: FocusType,
    focus_domain: FocusDomain | None = None,
    keywords: list[str],
    learned_related_terms: list[str] | None = None,
    learned_context_terms: list[str] | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    profile = build_focus_profile(
        name=name,
        focus_type=focus_type,
        focus_domain=(
            focus_domain
            or infer_focus_domain(name, keywords, focus_type)
        ),
        keywords=keywords,
        learned_related_terms=learned_related_terms or [],
        learned_context_terms=learned_context_terms or [],
    )
    related = tuple(
        relation.name
        for relation in profile.relations
        if relation.tier == "related"
    )
    context = tuple(
        relation.name
        for relation in profile.relations
        if relation.tier == "context"
    )
    return tuple(profile.aliases), related, context


def is_narrow_entity_focus(focus_type: FocusType) -> bool:
    return focus_type in {
        FocusType.COMPANY,
        FocusType.PERSON,
        FocusType.PRODUCT,
        FocusType.TEAM,
        FocusType.EVENT,
    }


def _contains_name_marker(name: str, markers: tuple[str, ...]) -> bool:
    compact_name = normalize_focus_text(name)
    return any(normalize_focus_text(marker) in compact_name for marker in markers)


def infer_focus_type(name: str, keywords: list[str]) -> FocusType:
    """Infer a durable focus type without invoking a paid model."""

    text = " ".join([name, *keywords]).casefold()
    compact = re.sub(r"\s+", "", text)
    if _contains_name_marker(name, EVENT_MARKERS):
        return FocusType.EVENT
    if _contains_name_marker(name, KNOWN_PERSON_NAMES):
        return FocusType.PERSON
    if _contains_name_marker(name, TEAM_MARKERS):
        return FocusType.TEAM
    if _looks_like_product_name(name):
        return FocusType.PRODUCT
    if any(marker.casefold() in compact for marker in COMPANY_MARKERS):
        return FocusType.COMPANY
    if any(marker.casefold() in compact for marker in TECHNOLOGY_MARKERS):
        return FocusType.TECHNOLOGY
    if any(marker.casefold() in compact for marker in PERSON_MARKERS):
        return FocusType.PERSON
    if any(marker.casefold() in compact for marker in ENTERTAINMENT_MARKERS):
        return FocusType.ENTERTAINMENT
    if any(marker.casefold() in compact for marker in SPORTS_MARKERS):
        return FocusType.SPORTS
    return FocusType.INDUSTRY


def infer_focus_domain(
    name: str,
    keywords: list[str],
    focus_type: FocusType,
) -> FocusDomain:
    compact = normalize_focus_text(" ".join([name, *keywords]))
    for domain, markers in (
        (FocusDomain.SPORTS, SPORTS_MARKERS),
        (FocusDomain.AUTOMOTIVE, AUTOMOTIVE_MARKERS),
        (FocusDomain.ENTERTAINMENT, ENTERTAINMENT_MARKERS),
        (FocusDomain.FINANCE, FINANCE_MARKERS),
        (FocusDomain.HEALTHCARE, HEALTHCARE_MARKERS),
        (FocusDomain.TECHNOLOGY, TECHNOLOGY_MARKERS),
    ):
        if any(normalize_focus_text(marker) in compact for marker in markers):
            return domain
    if focus_type == FocusType.SPORTS:
        return FocusDomain.SPORTS
    if focus_type == FocusType.ENTERTAINMENT:
        return FocusDomain.ENTERTAINMENT
    if focus_type == FocusType.TECHNOLOGY:
        return FocusDomain.TECHNOLOGY
    return FocusDomain.GENERAL


def resolve_focus_domain(
    requested: FocusDomain | str,
    *,
    name: str,
    keywords: list[str],
    focus_type: FocusType,
) -> FocusDomain:
    if requested == "auto":
        return infer_focus_domain(name, keywords, focus_type)
    return FocusDomain(requested)


def _relation_type(value: str, domain: FocusDomain) -> str:
    normalized = normalize_focus_text(value)
    if any(normalize_focus_text(marker) in normalized for marker in TEAM_MARKERS):
        return "team"
    if any(
        normalize_focus_text(marker) in normalized
        for marker in COMPANY_MARKERS
    ):
        return "organization"
    if domain == FocusDomain.SPORTS:
        return "sports_entity"
    if domain == FocusDomain.AUTOMOTIVE:
        return "automotive_entity"
    return "associated"


def build_focus_profile(
    *,
    name: str,
    focus_type: FocusType,
    focus_domain: FocusDomain,
    keywords: list[str],
    learned_related_terms: list[str] | None = None,
    learned_context_terms: list[str] | None = None,
) -> FocusProfile:
    normalized_name = normalize_focus_text(name)
    aliases = [name.strip()] if normalized_name else []
    relation_values: list[tuple[str, str, str]] = []

    if focus_type == FocusType.PRODUCT:
        direct, related = product_focus_terms(name, keywords)
        aliases = list(direct)
        for value in related:
            related_domain = infer_focus_domain(
                value,
                [],
                infer_focus_type(value, []),
            )
            tier = (
                "context"
                if (
                    infer_focus_type(value, []) == FocusType.PRODUCT
                    or related_domain
                    not in {FocusDomain.GENERAL, focus_domain}
                    or any(
                        normalize_focus_text(marker)
                        in normalize_focus_text(value)
                        for marker in CONTEXT_RELATION_MARKERS
                    )
                )
                else "related"
            )
            relation_values.append((value, tier, "configured"))
    else:
        for raw_value in keywords:
            value = raw_value.strip()
            normalized = normalize_focus_text(value)
            if not normalized or normalized == normalized_name:
                continue
            if normalized in normalized_name or normalized_name in normalized:
                aliases.append(value)
                continue
            if infer_focus_domain(value, [], focus_type) == focus_domain and (
                normalized in BROAD_PRODUCT_TERMS
                or normalized in {normalize_focus_text(item) for item in SPORTS_MARKERS}
            ):
                continue
            tier = (
                "context"
                if any(
                    normalize_focus_text(marker) in normalized
                    for marker in CONTEXT_RELATION_MARKERS
                )
                else "related"
            )
            relation_values.append((value, tier, "configured"))

    for value in learned_related_terms or []:
        cleaned = value.strip()
        if cleaned:
            relation_values.append((cleaned, "related", "feedback"))
    for value in learned_context_terms or []:
        cleaned = value.strip()
        if cleaned:
            relation_values.append((cleaned, "context", "feedback"))

    relations: list[FocusRelationProfile] = []
    seen_relations: set[str] = set()
    for value, tier, origin in relation_values:
        normalized = normalize_focus_text(value)
        if not normalized or normalized in seen_relations:
            continue
        seen_relations.add(normalized)
        relations.append(
            FocusRelationProfile(
                name=value,
                tier=tier,
                relation_type=_relation_type(value, focus_domain),
                origin=origin,
                confidence=0.9 if origin == "feedback" else 0.75,
            )
        )

    return FocusProfile(
        entity_type=focus_type,
        domain=focus_domain,
        aliases=list(dict.fromkeys(aliases)),
        relations=relations,
    )


def resolve_focus_type(
    requested: FocusType | str,
    *,
    name: str,
    keywords: list[str],
) -> FocusType:
    if requested == "auto":
        return infer_focus_type(name, keywords)
    return FocusType(requested)


def contextual_focus_types(
    primary: FocusType,
    *,
    name: str,
    topic: str,
    keywords: list[str],
) -> tuple[FocusType, ...]:
    """Keep the saved focus while recovering an obvious vertical context.

    A person such as an athlete is still a person, but source selection and
    discovery also need the sports vertical. The same applies to legacy custom
    subscriptions that retained the generic industry default. Explicit
    specialist types remain authoritative and are not broadened here.
    """

    inferred = infer_focus_type(name, [topic, *keywords])
    domain = infer_focus_domain(name, [topic, *keywords], primary)
    if (
        primary in {FocusType.INDUSTRY, FocusType.PERSON, FocusType.TEAM}
        and (inferred == FocusType.SPORTS or domain == FocusDomain.SPORTS)
    ):
        return primary, FocusType.SPORTS
    return (primary,)


def is_content_discovery_focus(
    *,
    name: str,
    topic: str,
    keywords: list[str],
    slug: str = "",
) -> bool:
    """Identify custom focuses whose product is the content, not its news."""

    if slug and not slug.startswith("custom-"):
        return False
    text = " ".join([name, topic, *keywords]).casefold()
    compact = re.sub(r"\s+", "", text)
    return any(marker.casefold() in compact for marker in CONTENT_DISCOVERY_MARKERS)


def content_discovery_topic(name: str) -> str:
    return (
        f"发现近期新鲜、有趣且可直接阅读或观看的{name}内容，"
        "优先内容本身、创作者原帖与社区热帖，不只追踪相关新闻"
    )


def normalize_custom_focus_topic(
    *,
    name: str,
    topic: str,
    keywords: list[str],
    slug: str,
) -> str:
    """Upgrade generic custom-focus wording while preserving explicit goals."""

    if not is_content_discovery_focus(
        name=name,
        topic=topic,
        keywords=keywords,
        slug=slug,
    ):
        return topic
    compact_topic = re.sub(r"\s+", "", topic.casefold())
    if any(marker.casefold() in compact_topic for marker in CONTENT_GOAL_MARKERS):
        return topic
    return content_discovery_topic(name)


def build_monitor_goal(
    *,
    name: str,
    topic: str,
    keywords: list[str],
    slug: str,
    lookback_hours: int,
    scheduled: bool = False,
) -> str:
    prefix = "定时发现" if scheduled else "发现"
    if is_content_discovery_focus(
        name=name,
        topic=topic,
        keywords=keywords,
        slug=slug,
    ):
        return (
            f"{prefix}过去 {lookback_hours} 小时内公开发布的最新且真正有趣的"
            f"{name}内容，优先内容本身、创作者原帖和社区热帖，"
            "整理为可追溯的内容卡。"
        )
    return (
        f"{prefix}过去 {lookback_hours} 小时内值得关注的{name}，"
        "生成带证据的情报事件。"
    )
