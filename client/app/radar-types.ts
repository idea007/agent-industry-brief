export type RunStatus =
  | "queued"
  | "running"
  | "waiting_approval"
  | "completed"
  | "failed"
  | "cancelled";

export type FocusType =
  | "industry"
  | "company"
  | "person"
  | "product"
  | "team"
  | "sports"
  | "entertainment"
  | "technology"
  | "event";

export const FOCUS_TYPE_LABELS: Record<FocusType, string> = {
  industry: "行业",
  company: "公司",
  person: "人物",
  product: "产品",
  team: "团队",
  sports: "体育",
  entertainment: "内容 / 娱乐",
  technology: "技术",
  event: "事件",
};

export type FocusDomain =
  | "general"
  | "sports"
  | "automotive"
  | "technology"
  | "entertainment"
  | "finance"
  | "healthcare";

export const FOCUS_DOMAIN_LABELS: Record<FocusDomain, string> = {
  general: "综合",
  sports: "体育",
  automotive: "汽车",
  technology: "科技",
  entertainment: "娱乐",
  finance: "财经",
  healthcare: "医疗健康",
};

export type Subscription = {
  id: string;
  name: string;
  slug: string;
  topic: string;
  include_keywords: string[];
  minimum_importance?: number;
  schedule_label: string;
  accent: string;
  focus_type: FocusType;
  focus_domain?: FocusDomain;
  enabled: boolean;
};

export type IntelFact = {
  text: string;
  source_ids: string[];
  citations?: IntelCitation[];
};

export type IntelCitation = {
  source_id: string;
  quote: string;
  quote_hash: string;
  locator: {
    paragraph?: number | null;
  };
  relation: "supports" | "contradicts" | "context";
};

export type IntelCategory =
  | "news"
  | "funding"
  | "technology"
  | "event"
  | "interview"
  | "content";

export type IntelSource = {
  source_id: string;
  title: string;
  url: string;
  canonical_url?: string | null;
  publisher: string;
  source_type: string;
  published_at: string;
  content: string;
  translated_content?: string | null;
  category: IntelCategory;
  author?: string | null;
  image_url?: string | null;
  content_origin?: "fixture" | "feed" | "fulltext";
  word_count?: number;
  reliability?: number;
  attributed_publisher?: string | null;
  attribution_evidence?: string | null;
};

export type IntelEvent = {
  id: string;
  story_id: string;
  run_id: string;
  subscription_id: string;
  title: string;
  summary: string;
  category: IntelCategory;
  tags: string[];
  event_time: string;
  importance_score: number;
  importance_reason: string;
  confidence_level: "high" | "medium" | "low";
  confidence_score: number;
  confidence_reason: string;
  verification_status:
    | "confirmed"
    | "partially_confirmed"
    | "unconfirmed"
    | "conflicting";
  facts: IntelFact[];
  inferences: { text: string; source_ids: string[] }[];
  source_ids: string[];
  sources: IntelSource[];
  change_summary?: string | null;
  independent_evidence_count?: number;
  first_seen_at?: string;
  created_at?: string;
};

export type IntelFeedbackType =
  | "valuable"
  | "not_relevant"
  | "duplicate"
  | "outdated"
  | "low_confidence"
  | "follow_entity"
  | "mute_source"
  | "missed_event";

export type IntelFeedback = {
  id: string;
  intel_event_id: string;
  subscription_id: string;
  feedback_type: IntelFeedbackType;
  reason_code?: string | null;
  note?: string | null;
  target?: string | null;
  created_at: string;
};

export type SourceDocument = {
  id: string;
  subscription_id: string;
  source_id: string;
  canonical_url: string;
  latest_url: string;
  title: string;
  publisher: string;
  source_type: string;
  published_at: string;
  content_excerpt: string;
  content_hash: string;
  content_origin: "fixture" | "feed" | "fulltext";
  author?: string | null;
  image_url?: string | null;
  word_count: number;
  reliability: number;
  safety_flags: string[];
  configured_source_id?: string | null;
  query_template_id?: string | null;
  query_focus_tier?: "core" | "related" | "context";
  retrieval_channel?: string | null;
  source_group?: string | null;
  ranking_score?: number | null;
  ranking_reasons: string[];
  focus_tier?: "core" | "related" | "context" | "unmatched";
  focus_relation_score?: number;
  fetch_status?: string | null;
  extraction_status?: string | null;
  duplicate_of_document_id?: string | null;
  relevance_score?: number | null;
  keyword_match_score?: number | null;
  entity_match_score?: number | null;
  semantic_match_score?: number | null;
  source_prior_score?: number | null;
  user_preference_score?: number | null;
  novelty_score?: number | null;
  novelty_components?: Record<string, number>;
  event_elements?: Record<string, unknown>;
  cluster_id?: string | null;
  cluster_relation?: string | null;
  evidence_chain_id?: string | null;
  evidence_relation_type?: string | null;
  independence_score?: number | null;
  first_seen_at: string;
  last_seen_at: string;
  last_run_id: string;
  seen_count: number;
  last_outcome:
    | "discovered"
    | "deferred"
    | "selected"
    | "reviewed"
    | "blocked";
};

export type NewsArticle = {
  id: string;
  event: IntelEvent;
  source: IntelSource | null;
  story_event_count: number;
  story_events: IntelEvent[];
};

export type StoryContextTier = "core" | "related" | "context";

export type StoryContextTimelineItem = {
  story_id: string;
  latest_event_id: string;
  title: string;
  summary: string;
  category: IntelCategory;
  event_time: string;
  importance_score: number;
  tier: StoryContextTier;
  relation:
    | "direct"
    | "follow_up"
    | "resolves"
    | "resolved_by"
    | "reaction"
    | "topic_related"
    | "context";
  reason: string;
  event_count: number;
  temporal_status: "current" | "resolution" | "superseded";
  resolved_by_story_id?: string | null;
  temporal_note?: string | null;
};

export type StoryContextTimeline = {
  subscription_id: string;
  current_story_id: string;
  subject: string;
  topic: string;
  focus_type: FocusType;
  window_days: number;
  window_start: string;
  generated_at: string;
  counts: Record<StoryContextTier, number>;
  items: StoryContextTimelineItem[];
};

export type Story = {
  id: string;
  subscription_id: string;
  canonical_title: string;
  primary_subjects: string[];
  event_type: IntelCategory;
  status: "active" | "resolved" | "stale";
  first_event_at: string;
  latest_event_at: string;
  current_intel_event_id: string;
  fingerprint: string;
  created_at: string;
  updated_at: string;
};

export type StoryRelation = {
  id: string;
  from_story_id: string;
  to_story_id: string;
  relation:
    | "same_event"
    | "follow_up"
    | "duplicate"
    | "related"
    | "superseded_by"
    | "unrelated";
  reason: string;
  confidence: number;
  created_at: string;
};

export type StoryDocument = {
  story_id: string;
  document_id: string;
  relation_type:
    | "official"
    | "original"
    | "reporting"
    | "syndicated"
    | "aggregator"
    | "commentary";
  evidence_chain_id: string;
  attributed_source?: string | null;
  is_primary: boolean;
  independence_score: number;
  created_at: string;
};

export type StoryDetail = {
  story: Story;
  relations: StoryRelation[];
  related_stories: Story[];
  documents: StoryDocument[];
  watch?: StoryWatch | null;
  evidence_chain_count: number;
};

export type ResearchFocus =
  | "comprehensive"
  | "latest"
  | "official"
  | "perspectives"
  | "background";

export type StoryWatchCadence = "manual" | "daily" | "weekly";

export type StoryWatch = {
  id: string;
  story_id: string;
  subscription_id: string;
  research_focus: ResearchFocus;
  question: string;
  cadence: StoryWatchCadence;
  enabled: boolean;
  last_run_id?: string | null;
  last_checked_at?: string | null;
  next_check_at?: string | null;
  created_at: string;
  updated_at: string;
};

export type StoryTrackingSignal = {
  story_id: string;
  subscription_id: string;
  watch_id?: string | null;
  title: string;
  summary: string;
  question: string;
  latest_event_at: string;
  change_summary?: string | null;
  verification_status: IntelEvent["verification_status"];
  event_count: number;
  fact_count: number;
  evidence_chain_count: number;
  has_official_source: boolean;
  official_source?: string | null;
  last_run_id?: string | null;
  last_run_status?: string | null;
  last_run_item_count?: number | null;
  last_checked_at?: string | null;
  tracking_status:
    | "new_progress"
    | "checking"
    | "waiting"
    | "no_change"
    | "attention"
    | "failed"
    | "untracked";
};

export type StoryWeeklyRewind = {
  window_start: string;
  tracked_story_count: number;
  progressed_story_count: number;
  new_story_count: number;
  attention_story_count: number;
  no_change_story_count: number;
  checked_story_count: number;
  highlights: StoryTrackingSignal[];
};

export type StoryTrackingOverview = {
  subscription_id: string;
  generated_at: string;
  new_progress: StoryTrackingSignal[];
  new_stories: StoryTrackingSignal[];
  attention_needed: StoryTrackingSignal[];
  waiting_answers: StoryTrackingSignal[];
  no_change: StoryTrackingSignal[];
  weekly_rewind: StoryWeeklyRewind;
};

export function researchFocusLabel(focus?: ResearchFocus | null): string {
  if (focus === "latest") return "追最新进展";
  if (focus === "official") return "找官方信源";
  if (focus === "perspectives") return "看不同观点";
  if (focus === "background") return "补来龙去脉";
  return "全面深挖";
}

export type Run = {
  id: string;
  subscription_id: string;
  goal: string;
  research_mode: "monitor" | "deep_dive";
  story_id?: string | null;
  research_focus?: ResearchFocus | null;
  research_question?: string | null;
  delivery_mode: string;
  status: RunStatus;
  stage: string;
  usage: {
    model_steps: number;
    tool_calls: number;
    search_calls: number;
    input_tokens?: number;
    output_tokens?: number;
  };
  result: {
    item_count?: number;
    delivery?: { status?: string; channel?: string };
    empty_result?: {
      reason_code: "NO_QUALIFYING_INTEL";
      message: string;
      research_summary?: string;
      discovery_count?: number;
      evidence_count?: number;
    };
  } | null;
  error: { code: string; message: string } | null;
  created_at: string;
  updated_at: string;
};

export type RunEvent = {
  id: string;
  run_id: string;
  seq: number;
  type: string;
  actor: { type: string; id: string };
  payload: Record<string, unknown>;
  timestamp: string;
};

export type Approval = {
  id: string;
  run_id: string;
  tool_name: string;
  status: "pending" | "approved" | "rejected";
  request: {
    channel?: string;
    item_count?: number;
    preview_titles?: string[];
    reason?: string;
  };
};

export type DashboardData = {
  subscriptions: Subscription[];
  runs: Run[];
  intel_events: IntelEvent[];
  approvals: Approval[];
  story_watches: StoryWatch[];
  system?: {
    model: {
      mode: string;
      provider: string;
      model: string;
      fallback_models?: string[];
    };
    sources: {
      mode: string;
      configured_count: number;
      profile_count?: number;
      supply_expansion?: {
        enabled: boolean;
        discovery_limit: number;
        evidence_limit: number;
        fulltext_limit: number;
        per_source_cap: number;
        per_publisher_cap: number;
      };
    };
    quality?: {
      observability_enabled: boolean;
      story_clustering_enabled: boolean;
      claim_eval_enabled: boolean;
      personalization_enabled: boolean;
    };
    runtime?: {
      max_concurrent_runs: number;
      active_run_count: number;
      queued_run_count: number;
    };
    scheduler: {
      enabled: boolean;
      running: boolean;
      timezone: string;
    };
  };
  stats: {
    subscription_count: number;
    intel_event_count: number;
    run_count: number;
    success_rate: number;
    pending_approval_count: number;
    source_count: number;
  };
};

export type SourceProfileSource = {
  id?: string | null;
  publisher: string;
  source_type: string;
  reliability: number;
  language: string;
  region: string;
  tier: "core" | "industry" | "hotspot" | "custom";
  url: string;
  mode: "rss" | "webpage" | "ai_web_search";
};

export type SourceProfile = {
  slug: string;
  name: string;
  focus_type: FocusType;
  focus_domain?: FocusDomain;
  focus_profile?: FocusProfile;
  discovery_mode?: "intelligence" | "content";
  keywords: string[];
  exclude_keywords?: string[];
  sources: SourceProfileSource[];
  automatic_source_rules?: string[];
  web_search: {
    enabled: boolean;
    provider?: "google_news_rss" | "bing_web_rss";
    query_templates?: SourceQueryTemplate[];
    max_queries?: number;
    language?: string;
    region?: string;
    edition?: string;
    reliability?: number;
  };
};

export type SourceQueryTemplate = {
  id: string;
  template: string;
  enabled: boolean;
  quota: number;
  priority: number;
  focus_tier?: "core" | "related" | "context";
};

export type FocusRelationProfile = {
  name: string;
  tier: "related" | "context";
  relation_type: string;
  origin: "configured" | "feedback" | "observed";
  confidence: number;
  evidence_count: number;
};

export type FocusSourceSuggestion = {
  publisher: string;
  url: string;
  story_count: number;
  reliability: number;
};

export type CustomSourcePreview = {
  requested_url: string;
  resolved_url: string;
  collection_mode: "feed" | "webpage";
  candidate_count: number;
  matched_candidate_count: number;
  sample_titles: string[];
  latest_published_at?: string | null;
  probe_status: "ready" | "limited";
};

export type FocusProfile = {
  entity_type: FocusType;
  domain: FocusDomain;
  aliases: string[];
  relations: FocusRelationProfile[];
  suggested_relations: FocusRelationProfile[];
  suggested_sources: FocusSourceSuggestion[];
  learning_mode: "controlled";
};

export type SourceHealth = {
  subscription_id: string;
  source_key: string;
  etag?: string | null;
  last_modified?: string | null;
  last_success_at?: string | null;
  last_failure_at?: string | null;
  consecutive_failures: number;
  last_new_document_at?: string | null;
  request_count: number;
  new_document_count: number;
  selected_document_count: number;
  fulltext_success_count: number;
  average_duration_ms: number;
  health_status: "healthy" | "stale" | "degraded" | "failing";
  updated_at: string;
};

export type SourceQueryMetric = {
  query_template_id: string;
  discovery_count: number;
  new_document_count: number;
  evidence_count: number;
  selected_count: number;
  new_content_rate: number;
  evidence_rate: number;
  selection_rate: number;
  latest_published_at?: string | null;
  last_run_at?: string | null;
};

export function sourceProfileSearchCount(profile?: SourceProfile): number {
  if (!profile?.web_search.enabled) return 0;
  const templates = (profile.web_search.query_templates ?? []).filter(
    (template) => template.enabled,
  );
  const maxQueries = profile.web_search.max_queries ?? templates.length;
  return templates.length
    ? Math.min(maxQueries, templates.length)
    : maxQueries;
}

export function displaySourceSearchTemplate(template: string): string {
  return template
    .replaceAll("{query}", "〔本次扫描主题〕")
    .replaceAll("{industry}", "〔当前关注〕")
    .replaceAll("{focus}", "〔当前关注〕")
    .replaceAll("{related}", "〔一级关系〕")
    .replaceAll("{context}", "〔周边背景〕");
}

export type CategoryKey =
  | "全部"
  | "新闻"
  | "内容"
  | "融资"
  | "技术"
  | "活动"
  | "访谈";

export const CATEGORY_OPTIONS: {
  key: CategoryKey;
  label: string;
}[] = [
  { key: "全部", label: "全部" },
  { key: "新闻", label: "新闻" },
  { key: "内容", label: "内容" },
  { key: "融资", label: "融资" },
  { key: "技术", label: "技术" },
  { key: "活动", label: "活动" },
  { key: "访谈", label: "访谈" },
];

export function categoryKey(category: string): Exclude<CategoryKey, "全部"> {
  const normalized = category.toLocaleLowerCase();
  if (
    normalized === "content" ||
    normalized === "humor" ||
    normalized === "joke" ||
    normalized === "meme" ||
    normalized.includes("内容") ||
    normalized.includes("段子")
  ) {
    return "内容";
  }
  if (
    normalized === "funding" ||
    normalized.includes("fund") ||
    normalized.includes("financ") ||
    normalized.includes("融资")
  ) {
    return "融资";
  }
  if (
    normalized === "event" ||
    normalized.includes("event") ||
    normalized.includes("conference") ||
    normalized.includes("活动")
  ) {
    return "活动";
  }
  if (
    normalized === "interview" ||
    normalized.includes("interview") ||
    normalized.includes("podcast") ||
    normalized.includes("访谈")
  ) {
    return "访谈";
  }
  if (
    [
      "technology",
      "technical",
      "tech",
      "sdk_release",
      "creator_tool",
      "engine_update",
      "agent_harness",
      "model_release",
      "research",
      "release",
    ].includes(normalized) ||
    normalized.includes("技术")
  ) {
    return "技术";
  }
  return "新闻";
}

export function categoryLabel(category: string): string {
  return categoryKey(category);
}

export function articleCategoryKey(
  article: NewsArticle,
): Exclude<CategoryKey, "全部"> {
  return categoryKey(article.event.category);
}

function sourceIdentity(source: IntelSource): string {
  const value = source.canonical_url || source.url;
  if (!value) return source.source_id;
  try {
    const url = new URL(value);
    for (const key of [...url.searchParams.keys()]) {
      if (
        key.toLocaleLowerCase().startsWith("utm_") ||
        ["fbclid", "gclid", "ref", "spm"].includes(
          key.toLocaleLowerCase(),
        )
      ) {
        url.searchParams.delete(key);
      }
    }
    url.hash = "";
    return url.toString().replace(/\/$/, "");
  } catch {
    return value;
  }
}

function sourceQuality(source: IntelSource): number {
  const type = source.source_type.toLocaleLowerCase();
  const typeScore = type.includes("official")
    ? 500
    : type.includes("research")
      ? 400
      : type.includes("industry")
        ? 300
        : type.includes("aggregator")
          ? 100
          : 200;
  return (
    typeScore +
    (source.content_origin === "fulltext" ? 80 : 0) +
    Math.round((source.reliability ?? 0.5) * 40) +
    Math.min(40, Math.floor((source.word_count ?? 0) / 100))
  );
}

export function selectPrimarySource(
  sources: IntelSource[],
): IntelSource | null {
  return (
    [...sources].sort((left, right) => {
      const quality = sourceQuality(right) - sourceQuality(left);
      if (quality) return quality;
      const leftTime = Date.parse(left.published_at);
      const rightTime = Date.parse(right.published_at);
      if (Number.isFinite(leftTime) && Number.isFinite(rightTime)) {
        return leftTime - rightTime;
      }
      return left.publisher.localeCompare(right.publisher, "zh-CN");
    })[0] ?? null
  );
}

function mergeCitations<
  T extends {
    text: string;
    source_ids: string[];
    citations?: IntelCitation[];
  },
>(
  groups: T[][],
): T[] {
  const merged = new Map<string, T>();
  for (const item of groups.flat()) {
    const existing = merged.get(item.text);
    if (!existing) {
      merged.set(item.text, {
        ...item,
        source_ids: [...new Set(item.source_ids)],
      });
      continue;
    }
    existing.source_ids = [
      ...new Set([...existing.source_ids, ...item.source_ids]),
    ];
    const citations = [
      ...(existing.citations ?? []),
      ...(item.citations ?? []),
    ];
    if (citations.length) {
      existing.citations = [
        ...new Map(
          citations.map((citation) => [
            `${citation.source_id}:${citation.quote_hash}:${citation.relation}`,
            citation,
          ]),
        ).values(),
      ];
    }
  }
  return [...merged.values()];
}

function mergeStoryEvents(events: IntelEvent[]): IntelEvent {
  const newestFirst = [...events].sort(
    (left, right) =>
      Date.parse(right.event_time) - Date.parse(left.event_time),
  );
  const representative = newestFirst[0];
  const sources = new Map<string, IntelSource>();
  for (const event of newestFirst) {
    for (const source of event.sources ?? []) {
      const identity = sourceIdentity(source);
      const existing = sources.get(identity);
      if (!existing || sourceQuality(source) > sourceQuality(existing)) {
        sources.set(identity, source);
      }
    }
  }
  return {
    ...representative,
    story_id: representative.story_id || representative.id,
    tags: [...new Set(newestFirst.flatMap((event) => event.tags))],
    source_ids: [
      ...new Set(newestFirst.flatMap((event) => event.source_ids)),
    ],
    sources: [...sources.values()],
    facts: mergeCitations(newestFirst.map((event) => event.facts)),
    inferences: mergeCitations(
      newestFirst.map((event) => event.inferences),
    ),
  };
}

export function expandNewsArticles(events: IntelEvent[]): NewsArticle[] {
  const stories = new Map<string, IntelEvent[]>();
  for (const event of events) {
    const storyId = event.story_id || event.id;
    const storyEvents = stories.get(storyId) ?? [];
    storyEvents.push(event);
    stories.set(storyId, storyEvents);
  }
  return [...stories.entries()].map(([storyId, storyEvents]) => {
    const event = mergeStoryEvents(storyEvents);
    const chronologicalEvents = [...storyEvents].sort(
      (left, right) =>
        Date.parse(left.event_time) - Date.parse(right.event_time),
    );
    return {
      id: storyId,
      event,
      source: selectPrimarySource(event.sources),
      story_event_count: storyEvents.length,
      story_events: chronologicalEvents,
    };
  });
}

function articleTimestamp(article: NewsArticle): number {
  const sources = article.event.sources?.length
    ? article.event.sources
    : article.source
      ? [article.source]
      : [];
  const sourceTimestamps = sources
    .map((source) => Date.parse(source.published_at))
    .filter(Number.isFinite);
  if (sourceTimestamps.length) return Math.max(...sourceTimestamps);
  const eventTimestamp = Date.parse(article.event.event_time);
  return Number.isFinite(eventTimestamp)
    ? eventTimestamp
    : Number.NEGATIVE_INFINITY;
}

export function sortNewsArticlesNewestFirst(
  articles: NewsArticle[],
): NewsArticle[] {
  return articles
    .map((article, index) => {
      return {
        article,
        index,
        timestamp: articleTimestamp(article),
      };
    })
    .sort(
      (left, right) =>
        right.timestamp - left.timestamp || left.index - right.index,
    )
    .map(({ article }) => article);
}

export function estimateReadMinutes(
  item: IntelEvent,
  source?: IntelSource | null,
): number {
  const characterCount =
    (source?.translated_content?.length ?? source?.content.length ?? 0) +
    item.summary.length +
    item.importance_reason.length +
    item.facts.reduce((total, fact) => total + fact.text.length, 0) +
    item.inferences.reduce(
      (total, inference) => total + inference.text.length,
      0,
    );
  return Math.max(2, Math.ceil(characterCount / 180));
}

export function sourceTypeLabel(sourceType: string): string {
  const normalized = sourceType.toLocaleLowerCase();
  if (normalized.includes("official")) return "官方发布";
  if (normalized.includes("research")) return "研究报告";
  if (normalized.includes("industry")) return "行业媒体";
  if (normalized.includes("community")) return "社区来源";
  if (normalized.includes("aggregator")) return "聚合来源";
  return "公开来源";
}

export type StorySourceInsight = {
  sourceCount: number;
  publisherCount: number;
  officialSource: IntelSource | null;
  earliestSource: IntelSource | null;
  attributionHints: {
    source: IntelSource;
    publisher: string;
    evidence: string;
  }[];
};

function inferredAttribution(source: IntelSource): string | null {
  if (source.attributed_publisher) return source.attributed_publisher;
  const parts = source.title
    .split(/\s+[-–—]\s+/u)
    .map((part) => part.trim())
    .filter(Boolean);
  if (parts.length < 3) return null;
  const carrier = parts.at(-1)?.replace(/\s+/g, "").toLocaleLowerCase();
  const publisher = source.publisher
    .replace(/\s+/g, "")
    .toLocaleLowerCase();
  if (
    !carrier ||
    (!carrier.includes(publisher) && !publisher.includes(carrier))
  ) {
    return null;
  }
  const candidate = parts.at(-2) ?? "";
  return candidate.length >= 2 && candidate.length <= 40
    ? candidate
    : null;
}

export function storySourceInsight(
  item: IntelEvent,
): StorySourceInsight {
  const sources = item.sources ?? [];
  const publishers = new Set(
    sources
      .map((source) => source.publisher.trim())
      .filter(Boolean),
  );
  const officialSource =
    sources.find((source) =>
      source.source_type.toLocaleLowerCase().includes("official"),
    ) ?? null;
  const earliestSource =
    [...sources]
      .filter((source) => Number.isFinite(Date.parse(source.published_at)))
      .sort(
        (left, right) =>
          Date.parse(left.published_at) - Date.parse(right.published_at),
      )[0] ?? null;
  const attributionHints = sources.flatMap((source) => {
    const publisher = inferredAttribution(source);
    return publisher
      ? [
          {
            source,
            publisher,
            evidence:
              source.attribution_evidence ??
              "新闻标题包含转载或署名来源线索",
          },
        ]
      : [];
  });
  return {
    sourceCount: sources.length,
    publisherCount: publishers.size,
    officialSource,
    earliestSource,
    attributionHints,
  };
}

export function formatArticleDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "long",
  }).format(new Date(value));
}

export function formatRelativeTime(value: string): string {
  const elapsed = Date.now() - new Date(value).getTime();
  if (!Number.isFinite(elapsed) || elapsed < 0) return formatTime(value);
  const minutes = Math.floor(elapsed / 60_000);
  if (minutes < 1) return "刚刚";
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days} 天前`;
  return formatTime(value);
}

export function formatTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

export function confidenceLabel(
  level: IntelEvent["confidence_level"],
): string {
  return { high: "高可信", medium: "中可信", low: "待验证" }[level];
}

export function verificationLabel(
  status: IntelEvent["verification_status"],
): string {
  return {
    confirmed: "已确认",
    partially_confirmed: "部分确认",
    unconfirmed: "待确认",
    conflicting: "存在冲突",
  }[status];
}

export function statusLabel(status: RunStatus): string {
  return {
    queued: "排队中",
    running: "运行中",
    waiting_approval: "等待审批",
    completed: "已完成",
    failed: "失败",
    cancelled: "已取消",
  }[status];
}

export function eventLabel(event: RunEvent): string {
  const labels: Record<string, string> = {
    "run.created": "已创建 Run",
    "run.queued": `等待执行槽 · 前方 ${String(
      event.payload.queue_position ?? 0,
    )} 个扫描`,
    "run.started": "开始研究",
    "run.stage_changed": `进入 ${String(event.payload.stage ?? "下一")} 阶段`,
    "model.started": "模型分析下一步",
    "model.responded": `模型返回 · ${String(event.payload.model ?? "")}`,
    "model.completed": "生成结构化情报草稿",
    "model.failed": "模型调用失败",
    "model.degraded": "切换到本地证据提取器",
    "tool.requested": `请求工具 · ${String(event.payload.tool ?? "")}`,
    "tool.allowed": "策略检查通过",
    "tool.denied": "策略拒绝动作",
    "tool.started": `执行工具 · ${String(event.payload.tool ?? "")}`,
    "tool.completed": `工具完成 · ${String(event.payload.tool ?? "")}`,
    "tool.failed": "工具执行失败",
    "approval.required": "等待人工审批",
    "approval.resolved": "审批已处理",
    "eval.completed": "引用与安全 Eval 完成",
    "delivery.completed": "已写入情报 Inbox",
    "delivery.skipped": "仅保留草稿",
    "run.no_results": "本次未发现可靠结果",
    "run.completed": "Run 已完成",
    "run.failed": "Run 执行失败",
    "run.cancel_requested": "已请求取消扫描",
    "run.cancelled": "Run 已取消",
  };
  return labels[event.type] ?? event.type;
}
