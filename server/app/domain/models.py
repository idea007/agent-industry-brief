from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Literal
from urllib.parse import urlparse
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RunStage(StrEnum):
    PLANNING = "planning"
    COLLECTING = "collecting"
    EXTRACTING = "extracting"
    CLUSTERING = "clustering"
    VERIFYING = "verifying"
    SYNTHESIZING = "synthesizing"
    EVALUATING = "evaluating"
    DELIVERING = "delivering"


class FocusType(StrEnum):
    INDUSTRY = "industry"
    COMPANY = "company"
    PERSON = "person"
    PRODUCT = "product"
    TEAM = "team"
    SPORTS = "sports"
    ENTERTAINMENT = "entertainment"
    TECHNOLOGY = "technology"
    EVENT = "event"


class FocusDomain(StrEnum):
    GENERAL = "general"
    SPORTS = "sports"
    AUTOMOTIVE = "automotive"
    TECHNOLOGY = "technology"
    ENTERTAINMENT = "entertainment"
    FINANCE = "finance"
    HEALTHCARE = "healthcare"


FocusRelationTier = Literal["related", "context"]


class FocusRelationProfile(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    tier: FocusRelationTier
    relation_type: str = Field(default="associated", max_length=40)
    origin: Literal["configured", "feedback", "observed"] = "configured"
    confidence: float = Field(default=0.7, ge=0, le=1)
    evidence_count: int = Field(default=0, ge=0)


class FocusSourceSuggestion(BaseModel):
    publisher: str = Field(min_length=1, max_length=120)
    url: str
    story_count: int = Field(default=1, ge=1)
    reliability: float = Field(default=0.5, ge=0, le=1)


class FocusProfile(BaseModel):
    entity_type: FocusType
    domain: FocusDomain
    aliases: list[str] = Field(default_factory=list)
    relations: list[FocusRelationProfile] = Field(default_factory=list)
    suggested_relations: list[FocusRelationProfile] = Field(default_factory=list)
    suggested_sources: list[FocusSourceSuggestion] = Field(default_factory=list)
    learning_mode: Literal["controlled"] = "controlled"


class SubscriptionCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,48}$")
    topic: str = Field(min_length=3, max_length=500)
    include_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=lambda: ["zh-CN", "en"])
    lookback_hours: int = Field(default=36, ge=1, le=720)
    max_items: int = Field(default=8, ge=1, le=50)
    minimum_importance: float = Field(default=6.0, ge=0, le=10)
    schedule_label: str = "每天 09:00"
    accent: str = "#78e0c2"
    focus_type: FocusType | Literal["auto"] = FocusType.INDUSTRY
    focus_domain: FocusDomain | Literal["auto"] = "auto"


class Subscription(SubscriptionCreate):
    focus_type: FocusType = FocusType.INDUSTRY
    focus_domain: FocusDomain = FocusDomain.GENERAL
    id: str
    enabled: bool = True
    created_at: datetime
    updated_at: datetime


CustomSourceType = Literal[
    "website",
    "rss",
    "youtube",
    "bilibili",
    "twitter",
    "podcast",
]


class CustomSourceCreate(BaseModel):
    subscription_id: str = Field(min_length=3, max_length=80)
    name: str = Field(min_length=2, max_length=120)
    url: str
    source_type: CustomSourceType = "website"

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        parsed = urlparse(value.strip())
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("Custom source must use an absolute HTTPS URL")
        return value.strip()


class CustomSourcePreview(BaseModel):
    requested_url: str
    resolved_url: str
    collection_mode: Literal["feed", "webpage"]
    candidate_count: int = Field(default=0, ge=0)
    matched_candidate_count: int = Field(default=0, ge=0)
    sample_titles: list[str] = Field(default_factory=list, max_length=3)
    latest_published_at: datetime | None = None
    probe_status: Literal["ready", "limited"] = "limited"


class CustomSource(CustomSourceCreate):
    id: str
    resolved_url: str
    collection_mode: Literal["feed", "webpage"]
    status: Literal["active", "error", "disabled"] = "active"
    last_error: str | None = None
    created_at: datetime
    updated_at: datetime


class RunBudget(BaseModel):
    max_model_steps: int = 8
    max_tool_calls: int = 16
    max_search_calls: int = 4
    max_wall_time_seconds: int = 180


class RunUsage(BaseModel):
    model_steps: int = 0
    tool_calls: int = 0
    search_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


ResearchFocus = Literal[
    "comprehensive",
    "latest",
    "official",
    "perspectives",
    "background",
]


class RunCreate(BaseModel):
    subscription_id: str
    trigger: Literal["manual", "schedule"] = "manual"
    goal: str | None = Field(default=None, max_length=500)
    research_mode: Literal["monitor", "deep_dive"] = "monitor"
    story_id: str | None = Field(default=None, max_length=100)
    research_focus: ResearchFocus | None = None
    research_question: str | None = Field(default=None, max_length=300)
    delivery_mode: Literal["web_inbox", "public_preview"] = "web_inbox"
    idempotency_key: str | None = Field(default=None, max_length=120)


class Run(BaseModel):
    id: str
    subscription_id: str
    trigger: str
    goal: str
    research_mode: Literal["monitor", "deep_dive"] = "monitor"
    story_id: str | None = None
    research_focus: ResearchFocus | None = None
    research_question: str | None = None
    delivery_mode: str
    status: RunStatus
    stage: RunStage
    budget: RunBudget
    usage: RunUsage
    cancellation_requested: bool = False
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class RunEvent(BaseModel):
    id: str
    run_id: str
    seq: int
    type: str
    actor: dict[str, str]
    payload: dict[str, Any]
    visibility: Literal["user", "internal"] = "user"
    timestamp: datetime


class ToolCallIntent(BaseModel):
    kind: Literal["tool_call"] = "tool_call"
    tool: str
    args: dict[str, Any]
    reason: str


class StructuredResultIntent(BaseModel):
    kind: Literal["structured_result"] = "structured_result"
    items: list[dict[str, Any]]
    research_summary: str


class BlockedIntent(BaseModel):
    kind: Literal["blocked"] = "blocked"
    reason: str


ModelIntent = ToolCallIntent | StructuredResultIntent | BlockedIntent


class PolicyDecision(BaseModel):
    decision: Literal["allow", "deny", "require_approval"]
    reason_code: str
    message: str
    constraints: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_allowed(self) -> bool:
        return self.decision == "allow"

    @property
    def is_denied(self) -> bool:
        return self.decision == "deny"

    @property
    def requires_approval(self) -> bool:
        return self.decision == "require_approval"


class CitationLocator(BaseModel):
    paragraph: int | None = Field(default=None, ge=0)


class IntelQuote(BaseModel):
    source_id: str
    quote: str = Field(min_length=1, max_length=320)


class IntelCitation(IntelQuote):
    quote_hash: str
    locator: CitationLocator = Field(default_factory=CitationLocator)
    relation: Literal["supports", "contradicts", "context"] = "supports"


class IntelFact(BaseModel):
    text: str
    source_ids: list[str] = Field(min_length=1)
    citations: list[IntelCitation] = Field(default_factory=list)
    source_quotes: list[IntelQuote] | None = Field(
        default=None, min_length=1, exclude=True
    )

    @model_validator(mode="after")
    def citations_belong_to_fact_sources(self) -> "IntelFact":
        if self.citations and self.source_quotes:
            raise ValueError("Provide source quotes or citations")
        unknown = {
            citation.source_id
            for citation in (self.source_quotes or self.citations)
        } - set(self.source_ids)
        if unknown:
            raise ValueError(
                f"Citation sources must be listed in source_ids: {sorted(unknown)}"
            )
        return self


class IntelInference(BaseModel):
    text: str
    source_ids: list[str] = Field(default_factory=list)


IntelCategory = Literal[
    "news",
    "funding",
    "technology",
    "event",
    "interview",
    "content",
]

_INTEL_CATEGORY_ALIASES: dict[str, IntelCategory] = {
    "news": "news",
    "industry_update": "news",
    "business_application": "news",
    "policy_standard": "news",
    "legal_ip": "news",
    "product_launch": "news",
    "policy_rumor": "news",
    "funding": "funding",
    "financing": "funding",
    "fundraising": "funding",
    "investment": "funding",
    "technology": "technology",
    "technical": "technology",
    "tech": "technology",
    "sdk_release": "technology",
    "creator_tool": "technology",
    "engine_update": "technology",
    "agent_harness": "technology",
    "model_release": "technology",
    "research": "technology",
    "event": "event",
    "conference": "event",
    "summit": "event",
    "exhibition": "event",
    "interview": "interview",
    "podcast": "interview",
    "conversation": "interview",
    "content": "content",
    "entertainment_content": "content",
    "humor": "content",
    "joke": "content",
    "meme": "content",
}


def normalize_intel_category(
    category: Any,
    *,
    title: Any = "",
    tags: Any = (),
) -> IntelCategory:
    """Return the stable six-category product taxonomy.

    Models historically emitted free-form category values, while a single
    IntelEvent can contain multiple source articles. Exact non-news categories
    take priority; legacy/general categories are refined from each article
    title so historical records become useful without rewriting the database.
    """

    normalized = re.sub(
        r"[\s-]+",
        "_",
        str(category or "news").strip().lower(),
    )
    aliased = _INTEL_CATEGORY_ALIASES.get(normalized)
    if aliased and aliased != "news":
        return aliased

    tag_text = " ".join(str(tag) for tag in tags) if isinstance(tags, list) else ""
    subject = f"{normalized} {title or ''} {tag_text}".lower()
    if any(
        keyword in subject
        for keyword in (
            "访谈",
            "专访",
            "采访",
            "对话实录",
            "interview",
            "fireside chat",
        )
    ):
        return "interview"
    if any(
        keyword in subject
        for keyword in (
            "融资",
            "募资",
            "融资轮",
            "投资轮",
            "估值",
            "并购",
            "收购",
            "funding",
            "fundraising",
            "venture round",
            "series a",
            "series b",
            "acquisition",
        )
    ):
        return "funding"
    if any(
        keyword in subject
        for keyword in (
            "活动",
            "大会",
            "峰会",
            "展会",
            "论坛",
            "发布会",
            "waic",
            "world artificial intelligence conference",
            "conference",
            "summit",
            "expo",
        )
    ):
        return "event"
    if any(
        keyword in subject
        for keyword in (
            "技术",
            "模型",
            "算法",
            "框架",
            "引擎",
            "插件",
            "芯片",
            "开源",
            "sdk",
            "api",
            "plugin",
            "benchmark",
            "technical",
            "technology",
            "open source",
            "model release",
        )
    ):
        return "technology"
    return aliased or "news"


class IntelSource(BaseModel):
    source_id: str
    title: str
    url: str
    canonical_url: str | None = None
    publisher: str
    source_type: str
    published_at: datetime
    content: str
    translated_content: str | None = Field(default=None, max_length=1200)
    category: IntelCategory = "news"
    author: str | None = None
    image_url: str | None = None
    content_origin: Literal["fixture", "feed", "fulltext"] = "feed"
    word_count: int = Field(default=0, ge=0)
    reliability: float = Field(default=0.5, ge=0, le=1)
    attributed_publisher: str | None = None
    attribution_evidence: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_category(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = normalize_intel_category(
            value.get("category"),
            title=value.get("title"),
        )
        return {**value, "category": normalized}


class IntelSourceTranslation(BaseModel):
    source_id: str
    content_zh: str = Field(min_length=1, max_length=1200)


class IntelEventDraft(BaseModel):
    title: str
    summary: str
    category: IntelCategory
    tags: list[str]
    event_time: datetime
    importance_score: float = Field(ge=0, le=10)
    importance_reason: str
    confidence_level: Literal["high", "medium", "low"]
    confidence_score: float = Field(ge=0, le=1)
    confidence_reason: str
    verification_status: Literal[
        "confirmed", "partially_confirmed", "unconfirmed", "conflicting"
    ]
    facts: list[IntelFact] = Field(min_length=1)
    inferences: list[IntelInference] = Field(default_factory=list)
    source_ids: list[str] = Field(min_length=1)
    source_translations: list[IntelSourceTranslation] = Field(
        default_factory=list,
        exclude=True,
    )
    sources: list[IntelSource] = Field(default_factory=list)
    change_summary: str | None = Field(default=None, max_length=600)
    independent_evidence_count: int = Field(default=0, ge=0)

    @model_validator(mode="before")
    @classmethod
    def normalize_category(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = normalize_intel_category(
            value.get("category"),
            title=value.get("title"),
            tags=value.get("tags"),
        )
        return {**value, "category": normalized}


class IntelEvent(IntelEventDraft):
    id: str
    story_id: str
    run_id: str
    subscription_id: str
    first_seen_at: datetime
    created_at: datetime


StoryContextTier = Literal["core", "related", "context"]
StoryContextRelation = Literal[
    "direct",
    "follow_up",
    "resolves",
    "resolved_by",
    "reaction",
    "topic_related",
    "context",
]
StoryTemporalStatus = Literal["current", "resolution", "superseded"]


class StoryContextTimelineItem(BaseModel):
    story_id: str
    latest_event_id: str
    title: str
    summary: str
    category: IntelCategory
    event_time: datetime
    importance_score: float = Field(ge=0, le=10)
    tier: StoryContextTier
    relation: StoryContextRelation
    reason: str
    event_count: int = Field(ge=1)
    temporal_status: StoryTemporalStatus = "current"
    resolved_by_story_id: str | None = None
    temporal_note: str | None = None


class StoryContextTimelineCounts(BaseModel):
    core: int = Field(default=0, ge=0)
    related: int = Field(default=0, ge=0)
    context: int = Field(default=0, ge=0)


class StoryContextTimeline(BaseModel):
    subscription_id: str
    current_story_id: str
    subject: str
    topic: str
    focus_type: FocusType
    window_days: int = Field(ge=1, le=365)
    window_start: datetime
    generated_at: datetime
    counts: StoryContextTimelineCounts
    items: list[StoryContextTimelineItem]


class SourceDocument(BaseModel):
    id: str
    subscription_id: str
    source_id: str
    canonical_url: str
    latest_url: str
    title: str
    publisher: str
    source_type: str
    published_at: datetime
    content_excerpt: str
    content_hash: str
    content_origin: Literal["fixture", "feed", "fulltext"] = "feed"
    author: str | None = None
    image_url: str | None = None
    word_count: int = Field(default=0, ge=0)
    reliability: float = Field(default=0.5, ge=0, le=1)
    safety_flags: list[str] = Field(default_factory=list)
    configured_source_id: str | None = None
    query_template_id: str | None = None
    query_focus_tier: Literal["core", "related", "context"] = "core"
    retrieval_channel: str | None = None
    source_group: str | None = None
    ranking_score: float | None = None
    ranking_reasons: list[str] = Field(default_factory=list)
    focus_tier: Literal["core", "related", "context", "unmatched"] = (
        "unmatched"
    )
    focus_relation_score: float = Field(default=0, ge=0, le=1)
    fetch_status: str | None = None
    extraction_status: str | None = None
    duplicate_of_document_id: str | None = None
    relevance_score: float | None = Field(default=None, ge=0, le=1)
    keyword_match_score: float | None = Field(default=None, ge=0, le=1)
    entity_match_score: float | None = Field(default=None, ge=0, le=1)
    semantic_match_score: float | None = Field(default=None, ge=0, le=1)
    source_prior_score: float | None = Field(default=None, ge=0, le=1)
    user_preference_score: float | None = Field(default=None, ge=-1, le=1)
    novelty_score: float | None = Field(default=None, ge=0, le=1)
    novelty_components: dict[str, float] = Field(default_factory=dict)
    event_elements: dict[str, Any] = Field(default_factory=dict)
    cluster_id: str | None = None
    cluster_relation: Literal[
        "same_event",
        "follow_up",
        "duplicate",
        "related",
        "unrelated",
        "needs_review",
    ] | None = None
    evidence_chain_id: str | None = None
    evidence_relation_type: Literal[
        "official",
        "original",
        "reporting",
        "syndicated",
        "aggregator",
        "commentary",
    ] | None = None
    independence_score: float | None = Field(default=None, ge=0, le=1)
    first_seen_at: datetime
    last_seen_at: datetime
    last_run_id: str
    seen_count: int = Field(default=1, ge=1)
    last_outcome: Literal[
        "discovered", "deferred", "selected", "reviewed", "blocked"
    ] = "discovered"


class SourceRuntimeState(BaseModel):
    subscription_id: str
    source_key: str
    etag: str | None = None
    last_modified: str | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    consecutive_failures: int = Field(default=0, ge=0)
    last_new_document_at: datetime | None = None
    request_count: int = Field(default=0, ge=0)
    new_document_count: int = Field(default=0, ge=0)
    selected_document_count: int = Field(default=0, ge=0)
    fulltext_success_count: int = Field(default=0, ge=0)
    average_duration_ms: float = Field(default=0, ge=0)
    health_status: Literal["healthy", "stale", "degraded", "failing"] = "healthy"
    updated_at: datetime


class Story(BaseModel):
    id: str
    subscription_id: str
    canonical_title: str
    primary_subjects: list[str] = Field(default_factory=list)
    event_type: IntelCategory
    status: Literal["active", "resolved", "stale"] = "active"
    first_event_at: datetime
    latest_event_at: datetime
    current_intel_event_id: str
    fingerprint: str
    created_at: datetime
    updated_at: datetime


class StoryRelation(BaseModel):
    id: str
    from_story_id: str
    to_story_id: str
    relation: Literal[
        "same_event",
        "follow_up",
        "duplicate",
        "related",
        "superseded_by",
        "unrelated",
    ]
    reason: str
    confidence: float = Field(ge=0, le=1)
    created_at: datetime


class StoryDocument(BaseModel):
    story_id: str
    document_id: str
    relation_type: Literal[
        "official",
        "original",
        "reporting",
        "syndicated",
        "aggregator",
        "commentary",
    ]
    evidence_chain_id: str
    attributed_source: str | None = None
    is_primary: bool = False
    independence_score: float = Field(ge=0, le=1)
    created_at: datetime


StoryWatchCadence = Literal["manual", "daily", "weekly"]


class StoryWatchUpsert(BaseModel):
    research_focus: ResearchFocus = "latest"
    question: str = Field(min_length=2, max_length=300)
    cadence: StoryWatchCadence = "manual"
    enabled: bool = True

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 2:
            raise ValueError("Tracking question must contain at least 2 characters")
        return normalized


class StoryWatch(StoryWatchUpsert):
    id: str
    story_id: str
    subscription_id: str
    last_run_id: str | None = None
    last_checked_at: datetime | None = None
    next_check_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class StoryTrackingSignal(BaseModel):
    story_id: str
    subscription_id: str
    watch_id: str | None = None
    title: str
    summary: str
    question: str
    latest_event_at: datetime
    change_summary: str | None = None
    verification_status: Literal[
        "confirmed",
        "partially_confirmed",
        "unconfirmed",
        "conflicting",
    ]
    event_count: int = Field(ge=1)
    fact_count: int = Field(ge=0)
    evidence_chain_count: int = Field(ge=0)
    has_official_source: bool = False
    official_source: str | None = None
    last_run_id: str | None = None
    last_run_status: str | None = None
    last_run_item_count: int | None = Field(default=None, ge=0)
    last_checked_at: datetime | None = None
    tracking_status: Literal[
        "new_progress",
        "checking",
        "waiting",
        "no_change",
        "attention",
        "failed",
        "untracked",
    ]


class StoryWeeklyRewind(BaseModel):
    window_start: datetime
    tracked_story_count: int = Field(ge=0)
    progressed_story_count: int = Field(ge=0)
    new_story_count: int = Field(ge=0)
    attention_story_count: int = Field(ge=0)
    no_change_story_count: int = Field(ge=0)
    checked_story_count: int = Field(ge=0)
    highlights: list[StoryTrackingSignal] = Field(default_factory=list)


class StoryTrackingOverview(BaseModel):
    subscription_id: str
    generated_at: datetime
    new_progress: list[StoryTrackingSignal] = Field(default_factory=list)
    new_stories: list[StoryTrackingSignal] = Field(default_factory=list)
    attention_needed: list[StoryTrackingSignal] = Field(default_factory=list)
    waiting_answers: list[StoryTrackingSignal] = Field(default_factory=list)
    no_change: list[StoryTrackingSignal] = Field(default_factory=list)
    weekly_rewind: StoryWeeklyRewind


FeedbackType = Literal[
    "valuable",
    "not_relevant",
    "duplicate",
    "outdated",
    "low_confidence",
    "follow_entity",
    "mute_source",
    "missed_event",
]


class IntelFeedbackCreate(BaseModel):
    feedback_type: FeedbackType
    reason_code: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=300)
    target: str | None = Field(default=None, max_length=180)


class IntelFeedback(IntelFeedbackCreate):
    id: str
    intel_event_id: str
    subscription_id: str
    created_at: datetime


class SubscriptionPreferences(BaseModel):
    subscription_id: str
    category_weights: dict[str, float] = Field(default_factory=dict)
    entity_weights: dict[str, float] = Field(default_factory=dict)
    source_weights: dict[str, float] = Field(default_factory=dict)
    followed_entities: list[str] = Field(default_factory=list)
    context_entities: list[str] = Field(default_factory=list)
    muted_entities: list[str] = Field(default_factory=list)
    muted_sources: list[str] = Field(default_factory=list)
    minimum_importance: float = Field(default=0, ge=0, le=10)
    alert_importance_threshold: float = Field(default=8, ge=0, le=10)
    digest_frequency: Literal["none", "daily", "weekly"] = "weekly"
    updated_at: datetime


class SubscriptionPreferencesUpdate(BaseModel):
    category_weights: dict[str, float] | None = None
    entity_weights: dict[str, float] | None = None
    source_weights: dict[str, float] | None = None
    followed_entities: list[str] | None = None
    context_entities: list[str] | None = None
    muted_entities: list[str] | None = None
    muted_sources: list[str] | None = None
    minimum_importance: float | None = Field(default=None, ge=0, le=10)
    alert_importance_threshold: float | None = Field(
        default=None, ge=0, le=10
    )
    digest_frequency: Literal["none", "daily", "weekly"] | None = None


class AlertRuleCreate(BaseModel):
    subscription_id: str
    name: str = Field(min_length=2, max_length=100)
    entities: list[str] = Field(default_factory=list)
    event_types: list[IntelCategory] = Field(default_factory=list)
    minimum_importance: float = Field(default=8, ge=0, le=10)
    minimum_confidence: float = Field(default=0.7, ge=0, le=1)
    require_official: bool = False
    minimum_evidence_chains: int = Field(default=1, ge=1, le=10)
    frequency: Literal["instant", "daily", "weekly"] = "instant"
    enabled: bool = True


class AlertRule(AlertRuleCreate):
    id: str
    created_at: datetime
    updated_at: datetime


class AlertMatch(BaseModel):
    alert_id: str
    intel_event_id: str
    matched_at: datetime


class Digest(BaseModel):
    id: str
    subscription_id: str
    period: Literal["daily", "weekly"]
    period_key: str
    title: str
    content_markdown: str
    intel_event_ids: list[str]
    created_at: datetime


class Approval(BaseModel):
    id: str
    run_id: str
    tool_name: str
    status: Literal["pending", "approved", "rejected"]
    request: dict[str, Any]
    decision: dict[str, Any] | None = None
    created_at: datetime
    resolved_at: datetime | None = None


class ApprovalDecision(BaseModel):
    decision: Literal["approve", "reject"]
    reason: str | None = Field(default=None, max_length=300)


class EvalResult(BaseModel):
    passed: bool
    checks: list[dict[str, Any]]
    metrics: dict[str, float | int]
