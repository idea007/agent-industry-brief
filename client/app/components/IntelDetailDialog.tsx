"use client";

import {
  useMemo,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type MouseEvent,
} from "react";
import ReactMarkdown from "react-markdown";
import {
  hasSubstantiveNewsContent,
  resolveNewsContent,
  selectOriginalArticleSource,
} from "../news-content";
import { preferenceTargets } from "../feed-view.mjs";
import {
  categoryLabel,
  confidenceLabel,
  estimateReadMinutes,
  formatArticleDate,
  formatRelativeTime,
  formatTime,
  sourceTypeLabel,
  storySourceInsight,
  verificationLabel,
  type StoryContextTimeline as StoryContextTimelineData,
  type IntelEvent,
  type IntelFeedback,
  type IntelFeedbackType,
  type IntelSource,
  type NewsArticle,
  type ResearchFocus,
  type StoryDetail,
  type StoryRelation,
  type StoryWatch,
  type StoryWatchCadence,
  type Subscription,
} from "../radar-types";
import StoryContextTimeline from "./FocusTimeline";
import { useModalA11y } from "./use-modal-a11y";

type Props = {
  article: NewsArticle;
  subscription?: Subscription;
  relatedArticles: NewsArticle[];
  timeline: IntelEvent[];
  storyContextTimeline: StoryContextTimelineData | null;
  storyDetail: StoryDetail | null;
  detailContextStatus: "loading" | "loaded" | "error";
  feedback: IntelFeedback[];
  feedbackSaving: boolean;
  deepDiveStartingFocus: ResearchFocus | null;
  deepDiveActiveFocus: ResearchFocus | null;
  watch: StoryWatch | null;
  watchSaving: boolean;
  watchChecking: boolean;
  schedulerEnabled: boolean;
  onClose: () => void;
  onOpenRelated: (articleId: string) => void;
  onOpenTrace: (runId: string) => void;
  onDeepDive: (researchFocus: ResearchFocus) => void;
  onSaveWatch: (payload: {
    research_focus: ResearchFocus;
    question: string;
    cadence: StoryWatchCadence;
    enabled: boolean;
  }) => void;
  onCheckWatch: () => void;
  onToggleFeedback: (
    feedbackType: IntelFeedbackType,
    target?: string,
  ) => void;
};

const STORY_CONTENT_TABS = [
  ["content", "事件内容"],
  ["importance", "为什么值得关注"],
  ["facts", "关键事实"],
  ["assessment", "判断依据"],
  ["sources", "来源追溯"],
] as const;

type StoryContentTab = (typeof STORY_CONTENT_TABS)[number][0];

function isHttpUrl(value?: string | null): value is string {
  if (!value) return false;
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

function escapeMarkdown(value: string): string {
  return value
    .replace(/\\/g, "\\\\")
    .replace(/([`*_[\]{}#+.!>|])/g, "\\$1")
    .replace(/(^|\n)(\s*)-/g, "$1$2\\-");
}

function markdownLink(label: string, url: string): string {
  const safeUrl = isHttpUrl(url)
    ? url.replace(/\(/g, "%28").replace(/\)/g, "%29")
    : "";
  return safeUrl
    ? `[${escapeMarkdown(label)}](${safeUrl})`
    : escapeMarkdown(label);
}

function sourceLabels(
  sourceIds: string[],
  sources: IntelSource[],
): string {
  const labels = sourceIds
    .map((sourceId) => {
      const source = sources.find((item) => item.source_id === sourceId);
      return source?.publisher || source?.title || "";
    })
    .filter(Boolean);
  return [...new Set(labels)].join("、");
}

function contentOriginLabel(origin?: string, url?: string): string {
  if (origin === "fulltext") return "已提取原文";
  if (origin === "fixture" || url?.includes(".example.test")) return "演示内容";
  return "Feed 摘要";
}

function citationRelationLabel(
  relation: "supports" | "contradicts" | "context",
): string {
  if (relation === "contradicts") return "冲突证据";
  if (relation === "context") return "背景证据";
  return "支持证据";
}

function storyRelationLabel(
  relation: StoryRelation | undefined,
  currentStoryId: string,
): string {
  if (relation?.relation === "superseded_by") {
    return relation.from_story_id === currentStoryId
      ? "后续事实"
      : "已更新前情";
  }
  if (relation?.relation === "follow_up") return "后续进展";
  if (relation?.relation === "same_event") return "同一事件";
  if (relation?.relation === "duplicate") return "重复报道";
  return "相关故事";
}

function buildRelatedReportsMarkdown(item: IntelEvent): string {
  const insight = storySourceInsight(item);
  const lines = [
    `## 相关报道（${insight.sourceCount}）`,
    "",
    ...(item.sources.length
      ? item.sources.map((itemSource) => {
          const roles = [
            itemSource.source_id === insight.officialSource?.source_id
              ? "官方来源候选"
              : "",
            itemSource.source_id === insight.earliestSource?.source_id
              ? "本次最早发布"
              : "",
          ].filter(Boolean);
          const roleLabel = roles.length ? `【${roles.join(" · ")}】` : "";
          return `- ${roleLabel}${markdownLink(`${itemSource.publisher}：${itemSource.title}`, itemSource.url)}`;
        })
      : ["- 这条历史情报暂未保存原文地址。"]),
  ];

  return lines.join("\n");
}

export default function IntelDetailDialog({
  article,
  subscription,
  relatedArticles,
  timeline,
  storyContextTimeline,
  storyDetail,
  detailContextStatus,
  feedback,
  feedbackSaving,
  deepDiveStartingFocus,
  deepDiveActiveFocus,
  watch,
  watchSaving,
  watchChecking,
  schedulerEnabled,
  onClose,
  onOpenRelated,
  onOpenTrace,
  onDeepDive,
  onSaveWatch,
  onCheckWatch,
  onToggleFeedback,
}: Props) {
  const [activeContentTab, setActiveContentTab] =
    useState<StoryContentTab>("content");
  const [timelineExpanded, setTimelineExpanded] = useState(false);
  const [watchEditorOpen, setWatchEditorOpen] = useState(Boolean(watch?.enabled));
  const [watchQuestion, setWatchQuestion] = useState(
    watch?.question ?? "下一次实质变化是什么，会在何时由哪一方确认？",
  );
  const [watchFocus, setWatchFocus] = useState<ResearchFocus>(
    watch?.research_focus ?? "latest",
  );
  const [watchCadence, setWatchCadence] = useState<StoryWatchCadence>(
    watch?.cadence ?? "manual",
  );
  const panelRef = useModalA11y(onClose);
  const { event: item, source } = article;
  const accent = subscription?.accent ?? "#6366f1";
  const publishedAt = item.event_time;
  const sourceInsight = storySourceInsight(item);
  const relatedStoryIds = new Set(
    storyDetail?.related_stories.map((relatedStory) => relatedStory.id) ?? [],
  );
  const related = relatedArticles
    .filter((relatedArticle) =>
      relatedStoryIds.has(relatedArticle.event.story_id),
    )
    .slice(0, 5);
  const content = useMemo(
    () => resolveNewsContent(item, source),
    [item, source],
  );
  const originalArticleSource = useMemo(
    () => selectOriginalArticleSource(item.sources, source),
    [item.sources, source],
  );
  const originalFallbackSource = source ?? item.sources[0] ?? null;
  const snapshotSource = originalArticleSource ?? originalFallbackSource;
  const relatedReportsMarkdown = useMemo(
    () => buildRelatedReportsMarkdown(item),
    [item],
  );
  const contentSource = content.source ?? source;
  const readMinutes = estimateReadMinutes(item, contentSource);
  const showTimeline = article.story_event_count > 1;
  const orderedTimeline = useMemo(() => [...timeline].reverse(), [timeline]);
  const visibleTimeline = timelineExpanded
    ? orderedTimeline
    : orderedTimeline.slice(0, 3);
  const evidenceChainCount =
    storyDetail?.evidence_chain_count ?? item.independent_evidence_count ?? 0;
  const deepDiveBusyFocus = deepDiveStartingFocus ?? deepDiveActiveFocus;
  const watchBusy = watchSaving || watchChecking || Boolean(deepDiveBusyFocus);
  const contradictionCount = item.facts.reduce(
    (count, fact) =>
      count +
      (fact.citations ?? []).filter(
        (citation) => citation.relation === "contradicts",
      ).length,
    0,
  );
  const citationCount = item.facts.reduce(
    (count, fact) => count + (fact.citations?.length ?? 0),
    0,
  );
  const fulltextSourceCount = item.sources.filter(
    (candidate) =>
      candidate.content_origin === "fulltext" &&
      hasSubstantiveNewsContent(candidate),
  ).length;
  const evidenceReadiness =
    item.verification_status === "conflicting"
      ? "conflicting"
      : originalArticleSource && evidenceChainCount >= 2
        ? "strong"
        : originalArticleSource || evidenceChainCount >= 2
          ? "partial"
          : "limited";
  const evidenceReadinessLabel = {
    strong: "证据较完整",
    partial: "可以继续核验",
    limited: "当前是线索级信息",
    conflicting: "存在证据冲突",
  }[evidenceReadiness];
  const evidenceGuidance = {
    strong:
      "深挖会重点补充背景、不同观点和下一步影响。",
    partial:
      "深挖会优先补齐官方来源、完整正文或第二条独立证据链。",
    limited:
      "深挖会先寻找完整正文、官方来源和第二条独立证据，再形成判断。",
    conflicting:
      "深挖会先定位来源分歧，核对原文和时间顺序。",
  }[evidenceReadiness];
  const sourceOriginSummary = sourceInsight.officialSource
    ? `${sourceInsight.officialSource.publisher}（官方来源候选）`
    : "官方来源待补充";
  const snapshotFormat =
    snapshotSource?.content_origin === "fixture" ||
    snapshotSource?.url.includes(".example.test")
      ? "演示内容"
      : originalArticleSource
        ? "已保存原始正文"
        : "标题或 Feed 摘要";
  const earliestSourceSummary = sourceInsight.earliestSource
    ? `${sourceInsight.earliestSource.publisher}，${formatArticleDate(sourceInsight.earliestSource.published_at)}`
    : "发布时间信息不足";
  const unresolvedQuestions = [
    ...(sourceInsight.officialSource
      ? []
      : ["是否会出现官方、当事方或一手资料确认当前说法？"]),
    ...(evidenceChainCount >= 2
      ? []
      : ["能否找到第二条相互独立的证据链进行交叉验证？"]),
    ...(item.verification_status === "conflicting"
      ? ["冲突来源的关键分歧是什么，后续证据会支持哪一方？"]
      : item.verification_status === "unconfirmed"
        ? ["当前关键事实仍待哪些直接证据确认？"]
        : []),
  ];
  if (!unresolvedQuestions.length) {
    unresolvedQuestions.push("下一次实质变化会发生在什么时间，由哪一方首先披露？");
  }
  const preferenceTargetLabels = preferenceTargets(item.tags);
  const valuableFeedbackActive = feedback.some(
    (itemFeedback) =>
      itemFeedback.feedback_type === "valuable" && !itemFeedback.target,
  );
  const notRelevantFeedbackActive = feedback.some(
    (itemFeedback) =>
      itemFeedback.feedback_type === "not_relevant" && !itemFeedback.target,
  );
  const secondaryFeedbackOptions: {
    type: IntelFeedbackType;
    label: string;
    target?: string;
  }[] = [
    { type: "duplicate", label: "重复内容" },
    ...(item.tags[0]
      ? [
          {
            type: "follow_entity" as const,
            label: `关注 ${item.tags[0]}`,
            target: item.tags[0],
          },
        ]
      : []),
    ...(source?.publisher
      ? [
          {
            type: "mute_source" as const,
            label: `屏蔽 ${source.publisher}`,
            target: source.publisher,
          },
        ]
      : []),
  ];

  function closeFromBackdrop(event: MouseEvent<HTMLDivElement>) {
    if (event.target === event.currentTarget) onClose();
  }

  function switchContentTab(
    event: KeyboardEvent<HTMLButtonElement>,
    tabIndex: number,
  ) {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    event.preventDefault();
    const direction = event.key === "ArrowRight" ? 1 : -1;
    const nextIndex =
      (tabIndex + direction + STORY_CONTENT_TABS.length) %
      STORY_CONTENT_TABS.length;
    const nextTab = STORY_CONTENT_TABS[nextIndex][0];
    setActiveContentTab(nextTab);
    event.currentTarget.parentElement
      ?.querySelector<HTMLButtonElement>(`#story-content-tab-${nextTab}`)
      ?.focus();
  }

  return (
    <div
      className="dialog-backdrop markdown-detail-backdrop"
      onMouseDown={closeFromBackdrop}
    >
      <div
        ref={panelRef}
        className="intel-dialog markdown-detail-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="intel-dialog-title"
        style={{ "--dialog-accent": accent } as CSSProperties}
      >
        <header className="dialog-topbar markdown-detail-toolbar">
          <div className="dialog-labels">
            <span className="industry-tag">
              <i style={{ background: accent }} aria-hidden="true" />
              {subscription?.name ?? "关注动态"}
            </span>
            <span className="category-tag">
              {categoryLabel(item.category)}
            </span>
            <span className="extraction-tag">
              {sourceInsight.sourceCount > 1
                ? `${sourceInsight.sourceCount} 篇相关报道`
                : contentOriginLabel(source?.content_origin, source?.url)}
            </span>
          </div>
          <div className="dialog-tools">
            <span className="dialog-read-time">
              {formatRelativeTime(publishedAt)} · {readMinutes} 分钟阅读
            </span>
            <button
              type="button"
              className="close-button"
              onClick={onClose}
              aria-label="关闭故事详情"
            >
              ×
            </button>
          </div>
        </header>

        <div className="dialog-scroll markdown-detail-scroll">
          <div className="story-hub-shell">
            <section className="story-hub-hero">
              <div className="story-hub-heading">
                <span>
                  持续故事 · {storyDetail?.story.status === "resolved"
                    ? "已告一段落"
                    : storyDetail?.story.status === "stale"
                      ? "已被后续事实更新"
                      : "追踪中"}
                </span>
                <h1 id="intel-dialog-title">{item.title}</h1>
                <p>{item.summary}</p>
                <section
                  className="story-original-copy"
                  aria-labelledby="story-original-copy-title"
                >
                  <header>
                    <div>
                      <span>来源原文 · 未经 AI 处理</span>
                      <h2 id="story-original-copy-title">原始完整正文</h2>
                    </div>
                    <small>
                      {originalArticleSource
                        ? originalArticleSource.publisher
                        : "正文暂未获取"}
                    </small>
                  </header>
                  {originalArticleSource ? (
                    <>
                      <div className="story-original-copy-body">
                        {originalArticleSource.content}
                      </div>
                      {isHttpUrl(originalArticleSource.url) && (
                        <a
                          href={originalArticleSource.url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          打开 {originalArticleSource.publisher} 原文
                          <span aria-hidden="true"> ↗</span>
                        </a>
                      )}
                    </>
                  ) : (
                    <div className="story-original-copy-missing">
                      <p>
                        当前来源快照只保存了标题或 Feed 摘要，尚未取得完整正文。为避免把摘要冒充原文，这里不做 AI 补写。
                      </p>
                      {originalFallbackSource && isHttpUrl(originalFallbackSource.url) && (
                        <a
                          href={originalFallbackSource.url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          打开 {originalFallbackSource.publisher} 查看原始页面
                          <span aria-hidden="true"> ↗</span>
                        </a>
                      )}
                    </div>
                  )}
                </section>

              </div>

              {storyContextTimeline && storyContextTimeline.items.length > 1 ? (
                <StoryContextTimeline
                  timeline={storyContextTimeline}
                  accent={accent}
                  currentStoryId={item.story_id}
                  storyEvents={timeline}
                  onOpenStory={onOpenRelated}
                />
              ) : showTimeline ? (
                <section
                  className="story-inline-timeline"
                  aria-labelledby="story-timeline-title"
                >
                  <header>
                    <div>
                      <span>持续更新</span>
                      <h2 id="story-timeline-title">事件时间线</h2>
                    </div>
                    <p>{article.story_event_count} 次有证据支持的实质进展</p>
                  </header>
                  {detailContextStatus === "loading" ? (
                    <p className="story-timeline-state">正在读取事件历史…</p>
                  ) : detailContextStatus === "error" ? (
                    <p className="story-timeline-state">时间线暂时不可用，其他内容仍可正常阅读。</p>
                  ) : (
                    <ol>
                      {visibleTimeline.map((timelineItem, index) => (
                        <li key={timelineItem.id}>
                          <time dateTime={timelineItem.event_time}>
                            {index === 0 ? "最新 · " : ""}
                            {formatArticleDate(timelineItem.event_time)}
                          </time>
                          <strong>{timelineItem.title}</strong>
                          <p>{timelineItem.change_summary ?? timelineItem.summary}</p>
                        </li>
                      ))}
                    </ol>
                  )}
                  {detailContextStatus === "loaded" && orderedTimeline.length > 3 && (
                    <button
                      type="button"
                      className="story-timeline-toggle"
                      aria-expanded={timelineExpanded}
                      onClick={() => setTimelineExpanded((current) => !current)}
                    >
                      {timelineExpanded
                        ? "收起时间线"
                        : `展开全部 ${orderedTimeline.length} 条进展`}
                    </button>
                  )}
                </section>
              ) : null}
            </section>

            <section
              className="story-ai-judgement"
              aria-labelledby="story-ai-judgement-title"
            >
              <header className="story-section-heading">
                <span>事实与判断分开呈现</span>
                <h2 id="story-ai-judgement-title">AI 判断</h2>
              </header>
              <div className="story-ai-conclusion-copy">
                {item.inferences.length ? (
                  item.inferences.map((inference) => (
                    <article key={inference.text}>
                      <p>{inference.text}</p>
                      <small>
                        {sourceLabels(inference.source_ids, item.sources)
                          ? `依据：${sourceLabels(inference.source_ids, item.sources)}`
                          : "AI 推断，不作为已确认事实"}
                      </small>
                    </article>
                  ))
                ) : (
                  <p>当前没有需要单独列出的 AI 判断。</p>
                )}
              </div>
            </section>

            <section
              className="story-content-workspace"
              aria-labelledby="story-content-title"
            >
              <header className="story-section-heading">
                <span>内容、价值与证据集中查看</span>
                <h2 id="story-content-title">事件信息</h2>
                <p>左右切换查看同一事件的正文、关注价值、事实、判断依据和来源。</p>
              </header>
              <nav className="story-content-tabs" aria-label="事件信息" role="tablist">
                {STORY_CONTENT_TABS.map(([key, label], tabIndex) => (
                  <button
                    type="button"
                    role="tab"
                    key={key}
                    id={`story-content-tab-${key}`}
                    aria-selected={activeContentTab === key}
                    aria-controls={`story-content-panel-${key}`}
                    tabIndex={activeContentTab === key ? 0 : -1}
                    className={activeContentTab === key ? "active" : ""}
                    onClick={() => setActiveContentTab(key)}
                    onKeyDown={(event) => switchContentTab(event, tabIndex)}
                  >
                    {label}
                  </button>
                ))}
              </nav>

              {activeContentTab === "content" && (
                <section
                  className="story-content-panel story-event-content"
                  id="story-content-panel-content"
                  role="tabpanel"
                  aria-labelledby="story-content-tab-content"
                >
                  {content.note && <p className="story-content-note">{content.note}</p>}
                  <p className="story-content-origin">
                    {content.source
                      ? `当前正文来源：${content.source.publisher}（${sourceTypeLabel(content.source.source_type)}）`
                      : content.mode === "digest"
                        ? `内容形态：多源内容整理（${item.sources.length} 篇报道）`
                        : "当前正文来源待确认"}
                  </p>
                  <article className="markdown-news-document story-content-body">
                    <ReactMarkdown>{content.body}</ReactMarkdown>
                  </article>
                </section>
              )}

              {activeContentTab === "importance" && (
                <section
                  className="story-content-panel story-importance"
                  id="story-content-panel-importance"
                  role="tabpanel"
                  aria-labelledby="story-content-tab-importance"
                >
                  <div className="story-importance-score" aria-label={`重要度 ${item.importance_score.toFixed(1)} 分`}>
                    <strong>{item.importance_score.toFixed(1)}</strong>
                    <span>/ 10 重要度</span>
                  </div>
                  <div>
                    <h3>为什么值得关注</h3>
                    <p>{item.importance_reason}</p>
                    <small>发布时间：{formatArticleDate(publishedAt)}</small>
                  </div>
                </section>
              )}

              {activeContentTab === "facts" && (
                <section
                  className="story-content-panel"
                  id="story-content-panel-facts"
                  role="tabpanel"
                  aria-labelledby="story-content-tab-facts"
                >
                  {citationCount > 0 && (
                    <p className="story-content-origin">{citationCount} 段可定位引文</p>
                  )}
                  {item.facts.length ? (
                    <ol className="story-fact-list">
                      {item.facts.map((fact) => {
                        const labels = sourceLabels(fact.source_ids, item.sources);
                        return (
                          <li key={fact.text}>
                            <strong>{fact.text}</strong>
                            <small>{labels ? `来源：${labels}` : "来源信息待补充"}</small>
                            {(fact.citations ?? []).map((citation) => {
                              const citationSource = item.sources.find(
                                (candidate) => candidate.source_id === citation.source_id,
                              );
                              const locator = typeof citation.locator.paragraph === "number"
                                ? ` · 第 ${citation.locator.paragraph + 1} 段`
                                : "";
                              return (
                                <blockquote key={`${citation.source_id}-${citation.quote}`}>
                                  <b>{citationRelationLabel(citation.relation)} · {citationSource?.publisher ?? citation.source_id}{locator}</b>
                                  <p>“{citation.quote}”</p>
                                </blockquote>
                              );
                            })}
                          </li>
                        );
                      })}
                    </ol>
                  ) : (
                    <p className="story-content-empty">暂无可以单独列出的已验证事实。</p>
                  )}
                  {item.facts.length > 0 && citationCount === 0 && (
                    <p className="story-content-note">
                      这条历史情报只保存了来源级引用，暂时没有可定位的原文片段。
                    </p>
                  )}
                </section>
              )}

              {activeContentTab === "assessment" && (
                <section
                  className="story-content-panel story-assessment-evidence"
                  id="story-content-panel-assessment"
                  role="tabpanel"
                  aria-labelledby="story-content-tab-assessment"
                >
                  <div className="story-assessment-summary">
                    <span className={`story-evidence-status ${evidenceReadiness}`}>
                      {evidenceReadinessLabel}
                    </span>
                    <p>{item.confidence_reason}</p>
                  </div>
                  <dl>
                    <div>
                      <dt>可信度</dt>
                      <dd>{confidenceLabel(item.confidence_level)} · {Math.round(item.confidence_score * 100)}%</dd>
                    </div>
                    <div>
                      <dt>验证状态</dt>
                      <dd>{verificationLabel(item.verification_status)}</dd>
                    </div>
                    <div>
                      <dt>独立证据链</dt>
                      <dd>{evidenceChainCount} 条</dd>
                    </div>
                    <div>
                      <dt>冲突证据</dt>
                      <dd>
                        {contradictionCount
                          ? `${contradictionCount} 条待核对`
                          : "暂无冲突引文记录"}
                      </dd>
                    </div>
                  </dl>
                  <p className="story-assessment-guidance">{evidenceGuidance}</p>
                  <section aria-labelledby="story-unresolved-title">
                    <h3 id="story-unresolved-title">仍待确认</h3>
                    <ul>
                      {unresolvedQuestions.map((question) => (
                        <li key={question}>{question}</li>
                      ))}
                    </ul>
                  </section>
                </section>
              )}

              {activeContentTab === "sources" && (
                <section
                  className="story-content-panel story-source-trace"
                  id="story-content-panel-sources"
                  role="tabpanel"
                  aria-labelledby="story-content-tab-sources"
                >
                  <dl>
                    <div>
                      <dt>事实源</dt>
                      <dd>{sourceOriginSummary}</dd>
                    </div>
                    <div>
                      <dt>本次采集最早发布</dt>
                      <dd>{earliestSourceSummary}</dd>
                    </div>
                    <div>
                      <dt>覆盖范围</dt>
                      <dd>
                        {sourceInsight.sourceCount} 篇报道，来自 {sourceInsight.publisherCount} 家媒体
                        {fulltextSourceCount > 0 && ` · ${fulltextSourceCount} 篇有完整正文`}
                      </dd>
                    </div>
                    <div>
                      <dt>正文快照</dt>
                      <dd>
                        {snapshotSource
                          ? `${snapshotSource.publisher} · ${snapshotFormat}`
                          : "正文尚未取得"}
                      </dd>
                    </div>
                  </dl>
                  {!!sourceInsight.attributionHints.length && (
                    <div className="story-attribution-hints">
                      <span>署名线索</span>
                      {sourceInsight.attributionHints.map((hint) => (
                        <p key={`${hint.source.source_id}-${hint.publisher}`}>
                          {hint.source.publisher} 的标题显示可能转载或引用自 {hint.publisher}；该线索仍需原文确认。
                        </p>
                      ))}
                    </div>
                  )}
                  <p className="story-source-boundary">
                    最早采集到的发布时间不等于绝对首发；没有明确转载声明、原文链接或官方发布时，系统保持“源头待确认”。
                  </p>
                </section>
              )}
            </section>

            {!!related.length && (
              <section
                className="story-relation-map"
                aria-labelledby="story-relation-map-title"
              >
                <header>
                  <span>已有数据支持时才显示</span>
                  <h2 id="story-relation-map-title">故事关系</h2>
                  <p>关系来自跨 Run 的 Story 聚类，不根据相似关键词临时猜测。</p>
                </header>
                <div>
                  <article>
                    <span>当前故事</span>
                    <strong>{item.title}</strong>
                  </article>
                  <i aria-hidden="true">连接到</i>
                  <div>
                    {related.map((relatedArticle) => {
                      const relation = storyDetail?.relations.find(
                        (candidate) =>
                          candidate.from_story_id === relatedArticle.event.story_id ||
                          candidate.to_story_id === relatedArticle.event.story_id,
                      );
                      return (
                        <button
                          type="button"
                          key={relatedArticle.id}
                          onClick={() => onOpenRelated(relatedArticle.id)}
                        >
                          <span>
                            {storyRelationLabel(relation, item.story_id)}
                            {relation ? ` · ${Math.round(relation.confidence * 100)}%` : ""}
                          </span>
                          <strong>{relatedArticle.event.title}</strong>
                        </button>
                      );
                    })}
                  </div>
                </div>
              </section>
            )}

            <article className="markdown-news-document story-related-reports">
              <ReactMarkdown
                components={{
                  a: ({ children, href }) => (
                    <a href={href} target="_blank" rel="noreferrer">
                      {children}
                      <span aria-hidden="true"> ↗</span>
                    </a>
                  ),
                }}
              >
                {relatedReportsMarkdown}
              </ReactMarkdown>
            </article>

            <section
              className="detail-feedback"
              aria-labelledby="detail-feedback-title"
            >
              <h2 id="detail-feedback-title">调整后续动态</h2>
              <p>
                这条内容主要涉及
                {preferenceTargetLabels.length
                  ? `“${preferenceTargetLabels.join("、")}”`
                  : "类似主题"}
                。你的选择只影响后续排序，不会改写当前新闻和历史事实。
              </p>
              <div
                className="detail-preference-actions"
                role="group"
                aria-label="调整类似动态偏好"
              >
                <button
                  type="button"
                  className={valuableFeedbackActive ? "active" : ""}
                  aria-pressed={valuableFeedbackActive}
                  disabled={feedbackSaving}
                  onClick={() => onToggleFeedback("valuable")}
                >
                  {valuableFeedbackActive ? "✓ " : ""}多看这类
                </button>
                <button
                  type="button"
                  className={
                    notRelevantFeedbackActive ? "active negative" : ""
                  }
                  aria-pressed={notRelevantFeedbackActive}
                  disabled={feedbackSaving}
                  onClick={() => onToggleFeedback("not_relevant")}
                >
                  {notRelevantFeedbackActive ? "✓ " : ""}少看这类
                </button>
              </div>
              {!!secondaryFeedbackOptions.length && (
                <div className="detail-feedback-secondary">
                  <span>其他反馈</span>
                  <div>
                    {secondaryFeedbackOptions.map((option) => {
                      const active = feedback.some(
                        (itemFeedback) =>
                          itemFeedback.feedback_type === option.type &&
                          (itemFeedback.target ?? undefined) === option.target,
                      );
                      return (
                        <button
                          type="button"
                          key={`${option.type}:${option.target ?? ""}`}
                          className={active ? "active" : ""}
                          aria-pressed={active}
                          disabled={feedbackSaving}
                          onClick={() =>
                            onToggleFeedback(option.type, option.target)
                          }
                        >
                          {active ? "✓ " : ""}
                          {option.label}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
              <small aria-live="polite">
                {feedbackSaving
                  ? "正在保存反馈…"
                  : feedback.length
                    ? "反馈已保存；再次点击已选项即可撤销。"
                    : "你可以随时撤销反馈。"}
              </small>

              <div className="detail-follow-up-actions">
                <button
                  type="button"
                  className="story-deep-dive"
                  onClick={() => onDeepDive("comprehensive")}
                  disabled={Boolean(deepDiveBusyFocus)}
                >
                  <span>
                    <strong>
                      {deepDiveStartingFocus
                        ? "正在启动深挖…"
                        : deepDiveActiveFocus
                          ? "正在深挖…"
                          : evidenceReadiness === "limited"
                            ? "深挖并补齐证据"
                            : "深挖这个故事"}
                    </strong>
                    <small>核对最新进展、官方来源、不同观点和事件背景</small>
                  </span>
                  <span aria-hidden="true">→</span>
                </button>

                <button
                  type="button"
                  className={`story-watch-toggle${watch?.enabled ? " active" : ""}`}
                  aria-expanded={watchEditorOpen}
                  aria-controls={watchEditorOpen ? "story-watch-panel" : undefined}
                  onClick={() => setWatchEditorOpen((current) => !current)}
                >
                  <span aria-hidden="true">◎</span>
                  <span>
                    <strong>{watch?.enabled ? "正在持续追踪" : "持续追踪这个故事"}</strong>
                    <small>
                      {watch?.last_checked_at
                        ? `上次检查 ${formatRelativeTime(watch.last_checked_at)}`
                        : "设置问题，后续只提醒实质变化"}
                    </small>
                  </span>
                </button>

                {watchEditorOpen && (
                  <section
                    id="story-watch-panel"
                    className={`story-watch-panel${watch?.enabled ? " active" : ""}`}
                    aria-labelledby="story-watch-title"
                  >
                    <header>
                      <div>
                        <span>{watch?.enabled ? "持续追踪中" : "建立追踪任务"}</span>
                        <h2 id="story-watch-title">持续关注这个问题</h2>
                      </div>
                      {watch?.enabled && (
                        <b>{watch.cadence === "manual" ? "手动检查" : watch.cadence === "daily" ? "每天检查" : "每周检查"}</b>
                      )}
                    </header>
                    <label>
                      <span>你想持续确认什么？</span>
                      <textarea
                        value={watchQuestion}
                        maxLength={300}
                        rows={3}
                        disabled={watchBusy}
                        onChange={(event) => setWatchQuestion(event.target.value)}
                      />
                    </label>
                    <div className="story-watch-fields">
                      <label>
                        <span>优先调查</span>
                        <select
                          value={watchFocus}
                          disabled={watchBusy}
                          onChange={(event) => setWatchFocus(event.target.value as ResearchFocus)}
                        >
                          <option value="latest">追最新进展</option>
                          <option value="official">找官方信源</option>
                          <option value="perspectives">看不同观点</option>
                          <option value="background">补来龙去脉</option>
                          <option value="comprehensive">全面深挖</option>
                        </select>
                      </label>
                      <label>
                        <span>检查频率</span>
                        <select
                          value={watchCadence}
                          disabled={watchBusy}
                          onChange={(event) => setWatchCadence(event.target.value as StoryWatchCadence)}
                        >
                          <option value="manual">由我手动检查</option>
                          <option value="daily">每天自动检查</option>
                          <option value="weekly">每周自动检查</option>
                        </select>
                      </label>
                    </div>
                    {watchCadence !== "manual" && !schedulerEnabled && (
                      <p className="story-watch-note">
                        频率可以先保存；当前计划扫描未开启，不会自动调用模型或产生费用，你仍可手动检查。
                      </p>
                    )}
                    {watch?.next_check_at && schedulerEnabled && (
                      <p className="story-watch-note">
                        下次自动检查：{formatTime(watch.next_check_at)}。没有可靠新进展时会诚实记录为“暂无实质变化”。
                      </p>
                    )}
                    <footer>
                      <button
                        type="button"
                        className="story-watch-save"
                        disabled={watchBusy || watchQuestion.trim().length < 2}
                        onClick={() => onSaveWatch({
                          research_focus: watchFocus,
                          question: watchQuestion.trim(),
                          cadence: watchCadence,
                          enabled: true,
                        })}
                      >
                        {watchSaving ? "保存中…" : watch?.enabled ? "保存追踪设置" : "开始持续追踪"}
                      </button>
                      {watch?.enabled && (
                        <>
                          <button type="button" disabled={watchBusy} onClick={onCheckWatch}>
                            {watchChecking ? "正在启动…" : "立即检查更新"}
                          </button>
                          <button
                            type="button"
                            className="story-watch-pause"
                            disabled={watchBusy}
                            onClick={() => onSaveWatch({
                              research_focus: watchFocus,
                              question: watchQuestion.trim(),
                              cadence: watchCadence,
                              enabled: false,
                            })}
                          >
                            停止追踪
                          </button>
                        </>
                      )}
                    </footer>
                  </section>
                )}
              </div>
            </section>

            <footer className="markdown-detail-footer">
              <div className="detail-tags" aria-label="标签">
                {item.tags.map((tag) => <span key={tag}>#{tag}</span>)}
              </div>
              <button
                type="button"
                className="markdown-trace-button"
                onClick={() => onOpenTrace(item.run_id)}
              >
                <span>
                  <strong>查看 AI 整理过程</strong>
                  <small>检索、来源校验与生成记录</small>
                </span>
                <b aria-hidden="true">→</b>
              </button>
            </footer>
          </div>
        </div>
      </div>
    </div>
  );
}
