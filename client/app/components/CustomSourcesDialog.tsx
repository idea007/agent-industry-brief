"use client";

import { useRef, useState } from "react";
import type { MouseEvent } from "react";
import {
  displaySourceSearchTemplate,
  FOCUS_DOMAIN_LABELS,
  FOCUS_TYPE_LABELS,
  formatRelativeTime,
  sourceProfileSearchCount,
  type CustomSourcePreview,
  type SourceHealth,
  type SourceProfile,
  type SourceQueryMetric,
} from "../radar-types";
import { useModalA11y } from "./use-modal-a11y";

export type SourceType =
  | "rss"
  | "youtube"
  | "bilibili"
  | "twitter"
  | "podcast"
  | "website";

export type CustomSource = {
  id: string;
  name: string;
  url: string;
  type: SourceType;
  addedAt: string;
  subscriptionId?: string;
  collectionMode?: "feed" | "webpage";
  status?: "active" | "error" | "disabled";
};

const SOURCE_LABELS: Record<SourceType, string> = {
  rss: "RSS / Atom",
  youtube: "YouTube",
  bilibili: "哔哩哔哩",
  twitter: "X / Twitter",
  podcast: "播客",
  website: "网站",
};

const TIER_LABELS = {
  core: "核心",
  industry: "行业",
  hotspot: "热点",
  custom: "自定义",
} as const;

const SOURCE_STRATEGY_LABELS: Record<string, string> = {
  forum: "论坛",
  funding: "投融资",
  capital_market: "证券",
  event: "峰会",
  event_community: "沙龙",
  industry_media: "媒体",
};

type ProfileStrategy = "sources" | "searches" | "health";

const FOCUS_TIER_LABELS = {
  core: "核心检索",
  related: "相关检索",
  context: "周边检索",
} as const;

function searchProviderLabel(provider?: string): string {
  if (provider === "google_news_rss") return "Google News";
  if (provider === "bing_web_rss") return "Bing 公开内容搜索";
  return "AI 联网搜索";
}

function sourceStrategyLabel(
  source: SourceProfile["sources"][number],
): string {
  return SOURCE_STRATEGY_LABELS[source.source_type] ?? TIER_LABELS[source.tier];
}

function sourceHealthExplanation(item: SourceHealth): string {
  if (!item.request_count) return "等待首次采集";
  if (item.health_status === "failing") {
    return item.last_failure_at
      ? `连续 ${item.consecutive_failures} 次失败，最近失败 ${formatRelativeTime(item.last_failure_at)}`
      : `连续 ${item.consecutive_failures} 次失败，建议检查来源地址`;
  }
  if (item.health_status === "degraded") {
    return item.last_failure_at
      ? `近期出现采集失败，上次失败 ${formatRelativeTime(item.last_failure_at)}`
      : "近期采集不稳定，系统正在保留已有快照";
  }
  if (item.health_status === "stale") {
    return item.last_new_document_at
      ? `最近新增内容 ${formatRelativeTime(item.last_new_document_at)}`
      : "已请求但近期没有发现新内容";
  }
  return item.last_success_at
    ? `最近成功 ${formatRelativeTime(item.last_success_at)}`
    : "请求正常，等待更多采集记录";
}

export function sourceTypeLabel(type: SourceType): string {
  return SOURCE_LABELS[type];
}

function detectSourceType(url: string): SourceType {
  const value = url.toLocaleLowerCase();
  if (
    value.includes("/feed") ||
    value.endsWith(".xml") ||
    value.endsWith(".rss") ||
    value.endsWith(".atom")
  ) {
    return "rss";
  }
  if (value.includes("youtube.com") || value.includes("youtu.be")) {
    return "youtube";
  }
  if (value.includes("bilibili.com") || value.includes("b23.tv")) {
    return "bilibili";
  }
  if (value.includes("twitter.com") || value.includes("x.com")) {
    return "twitter";
  }
  if (
    value.includes("podcast") ||
    value.includes("spotify.com") ||
    value.includes("apple.com/podcast")
  ) {
    return "podcast";
  }
  return "website";
}

function guessName(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "").split(".")[0];
  } catch {
    return "";
  }
}

type Props = {
  sources: CustomSource[];
  targetName?: string;
  profile?: SourceProfile;
  sourceHealth: SourceHealth[];
  queryMetrics: SourceQueryMetric[];
  onAdd: (source: CustomSource) => Promise<boolean>;
  onPreview: (source: CustomSource) => Promise<CustomSourcePreview | null>;
  onRemove: (sourceId: string) => Promise<void>;
  onAdoptRelation: (
    name: string,
    tier: "related" | "context",
  ) => Promise<void>;
  onClose: () => void;
};

export default function CustomSourcesDialog({
  sources,
  targetName,
  profile,
  sourceHealth,
  queryMetrics,
  onAdd,
  onPreview,
  onRemove,
  onAdoptRelation,
  onClose,
}: Props) {
  const [url, setUrl] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [learningSaving, setLearningSaving] = useState("");
  const [sourceTrial, setSourceTrial] = useState<{
    source: CustomSource;
    preview: CustomSourcePreview;
    origin: "manual" | "suggested";
    storyCount?: number;
    reliability?: number;
  } | null>(null);
  const [profileStrategy, setProfileStrategy] =
    useState<ProfileStrategy>("sources");
  const inputRef = useRef<HTMLInputElement>(null);
  const panelRef = useModalA11y(onClose);
  const searchCount = sourceProfileSearchCount(profile);
  const searchTemplates = (
    profile?.web_search.query_templates ?? []
  )
    .filter((template) => template.enabled)
    .slice(0, searchCount);
  const queryMetricsById = new Map(
    queryMetrics.map((metric) => [metric.query_template_id, metric]),
  );
  const sourceHealthOrder = {
    failing: 0,
    degraded: 1,
    stale: 2,
    healthy: 3,
  } as const;
  const orderedSourceHealth = [...sourceHealth].sort(
    (left, right) =>
      sourceHealthOrder[left.health_status] -
        sourceHealthOrder[right.health_status] ||
      right.consecutive_failures - left.consecutive_failures,
  );
  const sourceHealthTotals = sourceHealth.reduce(
    (totals, item) => ({
      requests: totals.requests + item.request_count,
      discovered: totals.discovered + item.new_document_count,
      selected: totals.selected + item.selected_document_count,
      fulltext: totals.fulltext + item.fulltext_success_count,
    }),
    { requests: 0, discovered: 0, selected: 0, fulltext: 0 },
  );

  function closeFromBackdrop(event: MouseEvent<HTMLDivElement>) {
    if (event.target === event.currentTarget) onClose();
  }

  function normalizeUrl(value: string): string | null {
    const withProtocol = /^https?:\/\//i.test(value)
      ? value
      : `https://${value}`;
    try {
      const parsed = new URL(withProtocol);
      if (parsed.protocol !== "https:") return null;
      return parsed.toString();
    } catch {
      return null;
    }
  }

  async function previewManualSource() {
    const normalized = normalizeUrl(url.trim());
    if (!normalized) {
      setError("请输入有效的 HTTPS 链接");
      inputRef.current?.focus();
      return;
    }
    if (sources.some((source) => source.url === normalized)) {
      setError("这个来源已经添加过了");
      return;
    }
    setSaving(true);
    const source = {
      id: `custom-${Date.now()}`,
      name: name.trim() || guessName(normalized) || "自定义来源",
      url: normalized,
      type: detectSourceType(normalized),
      addedAt: new Date().toISOString(),
    } satisfies CustomSource;
    const preview = await onPreview(source);
    setSaving(false);
    if (!preview) {
      setError("来源试用失败，请确认页面或 RSS 地址可以公开访问");
      return;
    }
    setSourceTrial({ source, preview, origin: "manual" });
    setError("");
  }

  async function confirmSourceTrial() {
    if (!sourceTrial) return;
    setSaving(true);
    const added = await onAdd(sourceTrial.source);
    setSaving(false);
    if (!added) {
      setError("来源没有加入，请检查链接后重试");
      return;
    }
    setUrl("");
    setName("");
    setError("");
    setSourceTrial(null);
    inputRef.current?.focus();
  }

  async function adoptRelation(
    name: string,
    tier: "related" | "context",
  ) {
    setLearningSaving(`relation:${name}`);
    try {
      await onAdoptRelation(name, tier);
    } finally {
      setLearningSaving("");
    }
  }

  async function previewSuggestedSource(
    name: string,
    suggestedUrl: string,
    storyCount: number,
    reliability: number,
  ) {
    setLearningSaving(`source:${suggestedUrl}`);
    try {
      const source = {
        id: `suggested-${Date.now()}`,
        name,
        url: suggestedUrl,
        type: "website",
        addedAt: new Date().toISOString(),
      } satisfies CustomSource;
      const preview = await onPreview(source);
      if (!preview) return;
      setSourceTrial({
        source,
        preview,
        origin: "suggested",
        storyCount,
        reliability,
      });
    } finally {
      setLearningSaving("");
    }
  }

  function sourceTrialPanel(origin: "manual" | "suggested") {
    if (!sourceTrial || sourceTrial.origin !== origin) return null;
    const { preview } = sourceTrial;
    const historicallyUseful =
      (sourceTrial.storyCount ?? 0) >= 2 &&
      (sourceTrial.reliability ?? 0) >= 0.72;
    const recommended =
      preview.probe_status === "ready" || historicallyUseful;
    return (
      <section className={`source-trial-result ${recommended ? "ready" : "limited"}`}>
        <header>
          <div>
            <span>来源试用结果</span>
            <strong>{sourceTrial.source.name}</strong>
          </div>
          <b>{recommended ? "建议采用" : "谨慎采用"}</b>
        </header>
        <dl>
          <div>
            <dt>采集方式</dt>
            <dd>{preview.collection_mode === "feed" ? "RSS / Atom" : "网页监测"}</dd>
          </div>
          <div>
            <dt>可识别候选</dt>
            <dd>{preview.candidate_count} 条</dd>
          </div>
          <div>
            <dt>关注词样本命中</dt>
            <dd>{preview.matched_candidate_count} 条</dd>
          </div>
          {sourceTrial.storyCount !== undefined && (
            <div>
              <dt>历史采用</dt>
              <dd>{sourceTrial.storyCount} 个故事</dd>
            </div>
          )}
          {sourceTrial.storyCount === undefined && (
            <div>
              <dt>最近内容</dt>
              <dd>
                {preview.latest_published_at
                  ? formatRelativeTime(preview.latest_published_at)
                  : "等待正式扫描"}
              </dd>
            </div>
          )}
        </dl>
        {!!preview.sample_titles.length && (
          <ul>
            {preview.sample_titles.map((title) => (
              <li key={title}>{title}</li>
            ))}
          </ul>
        )}
        <p>
          {recommended
            ? "确认后进入正式来源；后续扫描会继续记录新增、入选、正文率与健康状态。"
            : "当前只能确认页面可访问，样本与关注的直接关系较弱；加入后仍会经过相关性与证据门禁。"}
        </p>
        <div>
          <button
            type="button"
            className="primary-button"
            disabled={saving}
            onClick={() => void confirmSourceTrial()}
          >
            {saving ? "正在加入…" : "确认加入来源"}
          </button>
          <button
            type="button"
            className="ghost-button"
            disabled={saving}
            onClick={() => setSourceTrial(null)}
          >
            暂不采用
          </button>
        </div>
      </section>
    );
  }

  return (
    <div className="dialog-backdrop compact" onMouseDown={closeFromBackdrop}>
      <div
        className="custom-source-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="custom-source-title"
        ref={panelRef}
      >
        <header className="custom-dialog-header">
          <div>
            <h2 id="custom-source-title">关注来源策略</h2>
            <p>固定来源配置 + AI 联网搜索 + 你的自定义来源</p>
          </div>
          <button
            type="button"
            className="close-button"
            onClick={onClose}
            aria-label="关闭关注来源策略"
          >
            ×
          </button>
        </header>

        <section className="source-profile-summary">
          <header>
            <div>
              <span>
                当前关注
                {profile && ` · ${FOCUS_TYPE_LABELS[profile.focus_type]}`}
                {profile?.focus_domain &&
                  ` · ${FOCUS_DOMAIN_LABELS[profile.focus_domain]}`}
              </span>
              <strong>{profile?.name ?? targetName ?? "等待选择"}</strong>
            </div>
            <div
              className="profile-metrics"
              role="tablist"
              aria-label="来源策略详情"
            >
              <button
                type="button"
                id="profile-sources-tab"
                role="tab"
                aria-selected={profileStrategy === "sources"}
                aria-controls="profile-strategy-panel"
                className={profileStrategy === "sources" ? "active" : ""}
                onClick={() => setProfileStrategy("sources")}
              >
                {profile?.sources.length ?? 0} 个定向来源
              </button>
              <button
                type="button"
                id="profile-health-tab"
                role="tab"
                aria-selected={profileStrategy === "health"}
                aria-controls="profile-strategy-panel"
                className={profileStrategy === "health" ? "health active" : "health"}
                onClick={() => setProfileStrategy("health")}
              >
                {sourceHealth.length
                  ? `${sourceHealth.filter((item) => item.health_status === "healthy").length}/${sourceHealth.length} 来源健康`
                  : "来源健康"}
              </button>
              <button
                type="button"
                id="profile-searches-tab"
                role="tab"
                aria-selected={profileStrategy === "searches"}
                aria-controls="profile-strategy-panel"
                className={
                  profileStrategy === "searches" ? "search active" : "search"
                }
                onClick={() => setProfileStrategy("searches")}
                disabled={!profile?.web_search.enabled}
              >
                {profile?.web_search.enabled
                  ? `${searchCount} 组 AI 检索`
                  : "AI 搜索待连接"}
              </button>
            </div>
          </header>
          {profile ? (
            <div
              id="profile-strategy-panel"
              className="profile-strategy-panel"
              role="tabpanel"
              aria-labelledby={
                profileStrategy === "sources"
                  ? "profile-sources-tab"
                  : profileStrategy === "searches"
                    ? "profile-searches-tab"
                    : "profile-health-tab"
              }
            >
              {profileStrategy === "sources" ? (
                <div className="profile-source-details">
                  {profile.focus_profile && (
                    <section className="focus-profile-map">
                      <strong>关注对象画像</strong>
                      <p>
                        核心对象：{profile.focus_profile.aliases.join("、")}
                      </p>
                      <p>
                        一级关系：
                        {profile.focus_profile.relations
                          .filter((relation) => relation.tier === "related")
                          .map((relation) => relation.name)
                          .join("、") || "等待确认"}
                      </p>
                      <p>
                        二级背景：
                        {profile.focus_profile.relations
                          .filter((relation) => relation.tier === "context")
                          .map((relation) => relation.name)
                          .join("、") || "按事件影响动态判断"}
                      </p>
                    </section>
                  )}
                  <div className="profile-source-list">
                    {profile.sources.map((source) => (
                      <a
                        href={source.url}
                        target="_blank"
                        rel="noreferrer"
                        key={source.id ?? source.url}
                      >
                        <span>{sourceStrategyLabel(source)}</span>
                        {source.publisher}
                      </a>
                    ))}
                    {!profile.sources.length && (
                      <p>当前关注以 AI 联网搜索为主，可在下方补充定向来源。</p>
                    )}
                  </div>
                  {!!profile.focus_profile?.suggested_relations.length && (
                    <section className="focus-learning-list">
                      <strong>待确认的对象关系</strong>
                      {profile.focus_profile.suggested_relations.map(
                        (relation) => (
                          <button
                            type="button"
                            key={relation.name}
                            disabled={
                              learningSaving === `relation:${relation.name}`
                            }
                            onClick={() =>
                              void adoptRelation(relation.name, relation.tier)
                            }
                          >
                            <span>{relation.evidence_count} 个故事提及</span>
                            {relation.name}
                            <b>
                              {relation.tier === "related"
                                ? "纳入相关检索"
                                : "纳入周边检索"}
                            </b>
                          </button>
                        ),
                      )}
                    </section>
                  )}
                  {!!profile.focus_profile?.suggested_sources.length && (
                    <>
                      <section className="focus-learning-list">
                        <strong>待确认的定向来源</strong>
                        {profile.focus_profile.suggested_sources.map(
                          (suggestion) => (
                            <button
                              type="button"
                              key={suggestion.url}
                              disabled={
                                learningSaving === `source:${suggestion.url}` ||
                                sources.some(
                                  (source) => source.url === suggestion.url,
                                )
                              }
                              onClick={() =>
                                void previewSuggestedSource(
                                  suggestion.publisher,
                                  suggestion.url,
                                  suggestion.story_count,
                                  suggestion.reliability,
                                )
                              }
                            >
                              <span>
                                {suggestion.story_count} 个故事采用 · 可靠度
                                {Math.round(suggestion.reliability * 100)}%
                              </span>
                              {suggestion.publisher}
                              <b>试用评估</b>
                            </button>
                          ),
                        )}
                      </section>
                      {sourceTrialPanel("suggested")}
                    </>
                  )}
                </div>
              ) : profileStrategy === "searches" ? (
                <div className="profile-search-details">
                  <p className="profile-search-meta">
                    {searchProviderLabel(profile.web_search.provider)}
                    {" · "}
                    {profile.web_search.language ?? "自动语言"}
                    {" · "}
                    {profile.web_search.region ?? "全球"}
                  </p>
                  <ol className="profile-search-list">
                    {searchTemplates.map((template, index) => {
                      const metric = queryMetricsById.get(template.id);
                      return (
                      <li key={template.id}>
                        <span>{String(index + 1).padStart(2, "0")}</span>
                        <div>
                          <code>
                            {displaySourceSearchTemplate(template.template)}
                          </code>
                          <small>
                            {FOCUS_TIER_LABELS[
                              template.focus_tier ?? "core"
                            ]}
                            {" · "}
                            {metric
                              ? `${metric.discovery_count} 条候选 · ${metric.new_document_count} 条新增 · ${metric.evidence_count} 条证据 · ${metric.selected_count} 条入选`
                              : `优先级 ${template.priority} · 单轮配额 ${template.quota}`}
                          </small>
                        </div>
                      </li>
                      );
                    })}
                  </ol>
                  <p className="profile-search-note">
                    “本次扫描主题”会在扫描时替换为 AI
                    根据当前关注生成的检索词。
                    “一级关系”和“周边背景”来自已确认的对象画像；系统观察到的新关系
                    只会作为候选，不会自动扩大关注范围。
                  </p>
                </div>
              ) : (
                <div className="profile-health-list">
                  {!!sourceHealth.length && (
                    <dl className="profile-health-summary">
                      <div>
                        <dt>请求</dt>
                        <dd>{sourceHealthTotals.requests}</dd>
                      </div>
                      <div>
                        <dt>新增</dt>
                        <dd>{sourceHealthTotals.discovered}</dd>
                      </div>
                      <div>
                        <dt>入选</dt>
                        <dd>{sourceHealthTotals.selected}</dd>
                      </div>
                      <div>
                        <dt>完整正文</dt>
                        <dd>{sourceHealthTotals.fulltext}</dd>
                      </div>
                    </dl>
                  )}
                  {orderedSourceHealth.map((item) => (
                    <article key={item.source_key}>
                      <span className={`health-dot ${item.health_status}`} />
                      <div>
                        <strong>{item.source_key}</strong>
                        <small>
                          {item.request_count} 次请求 · {item.new_document_count} 条新增 · {item.selected_document_count} 条入选 · {item.fulltext_success_count} 篇正文
                        </small>
                        <em>{sourceHealthExplanation(item)}</em>
                      </div>
                      <b>{{
                        healthy: "健康",
                        stale: "低产",
                        degraded: "降级",
                        failing: "异常",
                      }[item.health_status]}</b>
                    </article>
                  ))}
                  {!sourceHealth.length && (
                    <p>完成一次 RSS 或网页扫描后，这里会显示来源健康度。</p>
                  )}
                </div>
              )}
              <div className="profile-keywords" aria-label="关注关键词">
                {profile.keywords.slice(0, 6).map((keyword) => (
                  <span key={keyword}>{keyword}</span>
                ))}
              </div>
            </div>
          ) : (
            <p className="profile-offline-note">
              连接情报服务后会显示固定来源和搜索关键词；离线状态仍可保存自定义来源。
            </p>
          )}
        </section>

        <section className="source-form">
          <label>
            <span>来源链接</span>
            <input
              ref={inputRef}
              value={url}
              onChange={(event) => {
                setUrl(event.target.value);
                setError("");
                if (sourceTrial?.origin === "manual") setSourceTrial(null);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") void previewManualSource();
              }}
              placeholder="YouTube、B 站、博客或 RSS 地址"
            />
          </label>
          <div className="source-form-row">
            <label>
              <span>显示名称</span>
              <input
                value={name}
                onChange={(event) => {
                  setName(event.target.value);
                  if (sourceTrial?.origin === "manual") setSourceTrial(null);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter") void previewManualSource();
                }}
                placeholder="选填，将自动识别"
              />
            </label>
            <button
              type="button"
              className="primary-button"
              onClick={() => void previewManualSource()}
              disabled={saving}
            >
              {saving ? "正在试用…" : "先试用"}
            </button>
          </div>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <p className="source-hint">
            先检查公开访问、内容样本与关注词命中；确认后才会加入
            {targetName ? `「${targetName}」` : "当前关注"}扫描。
          </p>
          {sourceTrialPanel("manual")}
        </section>

        <section className="source-list">
          <div className="source-list-heading">
            <span>已添加来源</span>
            <b>{sources.length}</b>
          </div>
          {sources.length ? (
            sources.map((source) => (
              <article className="source-list-item" key={source.id}>
                <span className={`source-icon ${source.type}`} aria-hidden="true">
                  {SOURCE_LABELS[source.type].slice(0, 1)}
                </span>
                <div>
                  <strong>{source.name}</strong>
                  <a href={source.url} target="_blank" rel="noreferrer">
                    {source.url}
                  </a>
                </div>
                <span className="source-type">
                  {source.collectionMode === "feed"
                    ? "订阅源"
                    : source.collectionMode === "webpage"
                      ? "网页监测"
                      : SOURCE_LABELS[source.type]}
                </span>
                <button
                  type="button"
                  className="remove-source"
                  aria-label={`移除 ${source.name}`}
                  onClick={() => void onRemove(source.id)}
                >
                  移除
                </button>
              </article>
            ))
          ) : (
            <div className="source-empty">
              <span aria-hidden="true">＋</span>
              <strong>还没有自定义来源</strong>
              <p>粘贴一个链接，建立你的定向关注列表。</p>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
