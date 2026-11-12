import { useMemo, useState, type CSSProperties } from "react";
import {
  categoryLabel,
  formatArticleDate,
  formatRelativeTime,
  type StoryContextTimeline as StoryContextTimelineData,
  type StoryContextTimelineItem,
  type IntelEvent,
} from "../radar-types";


type Props = {
  timeline: StoryContextTimelineData;
  accent: string;
  currentStoryId: string;
  storyEvents: IntelEvent[];
  onOpenStory: (storyId: string) => void;
};

const TIER_LABELS: Record<
  StoryContextTimelineItem["tier"],
  string
> = {
  core: "核心进展",
  related: "相关动态",
  context: "周边影响",
};

const DISPLAY_LIMITS = {
  core: 6,
  related: 4,
  context: 3,
} as const;

function compareTimelineItems(
  left: StoryContextTimelineItem,
  right: StoryContextTimelineItem,
): number {
  if (left.resolved_by_story_id === right.story_id) return 1;
  if (right.resolved_by_story_id === left.story_id) return -1;
  return Date.parse(right.event_time) - Date.parse(left.event_time);
}

function visibleTierItems(
  timeline: StoryContextTimelineData,
  tier: StoryContextTimelineItem["tier"],
  limit: number,
  currentStoryId: string,
): StoryContextTimelineItem[] {
  const tierItems = timeline.items
    .filter((item) => item.tier === tier)
    .sort(compareTimelineItems);
  const visible = tierItems.slice(0, limit);
  const currentItem = tierItems.find(
    (item) => item.story_id === currentStoryId,
  );
  if (
    currentItem &&
    !visible.some((item) => item.story_id === currentStoryId)
  ) {
    visible[Math.max(0, visible.length - 1)] = currentItem;
  }
  return visible;
}

function TimelineEntry({
  item,
  current,
  storyEvents,
  onOpen,
}: {
  item: StoryContextTimelineItem;
  current: boolean;
  storyEvents: IntelEvent[];
  onOpen: () => void;
}) {
  const className = [
    "focus-timeline-item",
    `tier-${item.tier}`,
    current ? "current" : "",
  ]
    .filter(Boolean)
    .join(" ");
  const tierLabel =
    item.temporal_status === "superseded"
      ? "前情 · 已更新"
      : item.temporal_status === "resolution"
        ? "后续事实"
        : TIER_LABELS[item.tier];

  return (
    <li className={className}>
      <button
        type="button"
        onClick={current ? undefined : onOpen}
        aria-current={current ? "true" : undefined}
      >
        <span className="focus-timeline-meta">
          <span className="focus-timeline-tier">
            {tierLabel}
          </span>
          {current && (
            <em>
              {item.temporal_status === "superseded"
                ? "当前新闻 · 已过期"
                : "当前新闻"}
            </em>
          )}
          <time dateTime={item.event_time}>
            {formatRelativeTime(item.event_time)}
          </time>
          <i aria-hidden="true">·</i>
          <span>
            {item.event_count > 1
              ? `${item.event_count} 次进展`
              : categoryLabel(item.category)}
          </span>
        </span>
        <strong>{item.title}</strong>
        <small>{item.summary}</small>
        {item.temporal_note && (
          <span className="focus-timeline-temporal-note">
            {item.temporal_note}
          </span>
        )}
      </button>
      {current && storyEvents.length > 1 && (
        <CurrentStoryProgress events={storyEvents} />
      )}
    </li>
  );
}

function CurrentStoryProgress({ events }: { events: IntelEvent[] }) {
  const [expanded, setExpanded] = useState(false);
  const orderedEvents = useMemo(
    () =>
      [...events].sort(
        (left, right) =>
          Date.parse(right.event_time) - Date.parse(left.event_time),
      ),
    [events],
  );
  const visibleEvents = expanded ? orderedEvents : orderedEvents.slice(0, 3);

  return (
    <section className="current-story-progress" aria-label="当前故事进展">
      <header>
        <strong>当前 Story 的连续进展</strong>
        <span>{orderedEvents.length} 次实质变化</span>
      </header>
      <ol>
        {visibleEvents.map((event, index) => (
          <li key={event.id}>
            <time dateTime={event.event_time}>
              {index === 0 ? "最新 · " : ""}
              {formatArticleDate(event.event_time)}
            </time>
            <strong>{event.title}</strong>
            <p>{event.change_summary ?? event.summary}</p>
          </li>
        ))}
      </ol>
      {orderedEvents.length > 3 && (
        <button
          type="button"
          aria-expanded={expanded}
          onClick={() => setExpanded((current) => !current)}
        >
          {expanded ? "收起 Story 进展" : `展开全部 ${orderedEvents.length} 条进展`}
        </button>
      )}
    </section>
  );
}

export default function StoryContextTimeline({
  timeline,
  accent,
  currentStoryId,
  storyEvents,
  onOpenStory,
}: Props) {
  if (timeline.items.length < 2) return null;

  const coreItems = visibleTierItems(
    timeline,
    "core",
    DISPLAY_LIMITS.core,
    currentStoryId,
  );
  const relatedItems = visibleTierItems(
    timeline,
    "related",
    DISPLAY_LIMITS.related,
    currentStoryId,
  );
  const contextItems = visibleTierItems(
    timeline,
    "context",
    DISPLAY_LIMITS.context,
    currentStoryId,
  );
  const visibleItems = [
    ...coreItems,
    ...relatedItems,
    ...contextItems,
  ].sort(compareTimelineItems);
  const currentItem = timeline.items.find(
    (item) => item.story_id === currentStoryId,
  );
  const resolutionItem = currentItem?.resolved_by_story_id
    ? timeline.items.find(
        (item) => item.story_id === currentItem.resolved_by_story_id,
      )
    : undefined;
  const displayedCount =
    coreItems.length + relatedItems.length + contextItems.length;
  const hiddenCount = Math.max(0, timeline.items.length - displayedCount);

  return (
    <section
      className="focus-timeline"
      style={{ "--timeline-accent": accent } as CSSProperties}
      aria-label={`${timeline.subject}关注下${timeline.topic}最近${timeline.window_days}天故事脉络`}
    >
      <header className="focus-timeline-heading">
        <div>
          <span>当前新闻的故事脉络</span>
          <h2>
            {timeline.subject} / {timeline.topic} · 最近 {timeline.window_days} 天
          </h2>
          <p className="focus-timeline-current-position">
            关注范围 <strong>{timeline.subject}</strong> · 三层关系围绕当前新闻主题计算
            {currentItem?.temporal_status === "superseded"
              ? " · 当前新闻中的时效性判断已被后续事实更新"
              : ""}
          </p>
        </div>
        <p>
          <strong>{timeline.counts.core} 项核心进展</strong>
          <span>{timeline.counts.related} 项相关动态</span>
          <span>{timeline.counts.context} 项周边影响</span>
        </p>
      </header>

      {currentItem?.temporal_status === "superseded" && (
        <aside className="focus-timeline-status-banner">
          <div>
            <strong>这不是最新状态</strong>
            <span>
              {currentItem.temporal_note ??
                "当前新闻中的预计或时间安排已被后续事实更新。"}
            </span>
          </div>
          {resolutionItem && (
            <button
              type="button"
              onClick={() => onOpenStory(resolutionItem.story_id)}
            >
              查看后续事实：{resolutionItem.title}
            </button>
          )}
        </aside>
      )}

      <div className="focus-timeline-layout">
        <header className="focus-timeline-stream-heading">
          <strong>最近动态</strong>
          <span>距离现在最近的在上 · 支线越远，与当前主题关系越间接</span>
        </header>
        <ol className="focus-timeline-stream">
          {visibleItems.map((item) => (
            <TimelineEntry
              key={item.story_id}
              item={item}
              current={item.story_id === currentStoryId}
              storyEvents={
                item.story_id === currentStoryId ? storyEvents : []
              }
              onOpen={() => onOpenStory(item.story_id)}
            />
          ))}
        </ol>
      </div>

      {hiddenCount > 0 && (
        <footer>其余 {hiddenCount} 条关联动态未在当前故事脉络中展开。</footer>
      )}
    </section>
  );
}
