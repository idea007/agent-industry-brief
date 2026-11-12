import type { CSSProperties } from "react";
import {
  categoryLabel,
  estimateReadMinutes,
  formatRelativeTime,
  sourceTypeLabel,
  storySourceInsight,
  type IntelEvent,
  type IntelSource,
  type Subscription,
} from "../radar-types";

type Props = {
  item: IntelEvent;
  source: IntelSource | null;
  subscription?: Subscription;
  storyEvents?: IntelEvent[];
  watched?: boolean;
  featured?: boolean;
  changeType?: "new" | "progress";
  onOpen: () => void;
};

export default function IntelCard({
  item,
  source,
  subscription,
  storyEvents = [],
  watched = false,
  featured = false,
  changeType,
  onOpen,
}: Props) {
  const accent = subscription?.accent ?? "#6366F1";
  const readMinutes = estimateReadMinutes(item, source);
  const headline = item.title;
  const publishedAt = item.event_time;
  const sourceInsight = storySourceInsight(item);
  const hasRelatedReports = sourceInsight.sourceCount > 1;
  const storyline = storyEvents.length > 1 ? storyEvents.slice(-3) : [];
  const hasStoryline = storyline.length > 1;

  return (
    <article
      className={`intel-card${featured ? " featured" : ""}`}
      style={{ "--card-accent": accent } as CSSProperties}
    >
      <button
        type="button"
        className="intel-card-open"
        data-testid={`story-card-${item.story_id || item.id}`}
        onClick={onOpen}
        aria-label={`查看持续故事详情：${headline}`}
      />
      <div className="intel-card-content">
        <div className="card-labels">
          <span className="industry-tag">
            <i style={{ background: accent }} aria-hidden="true" />
            {subscription?.name ?? "关注动态"}
          </span>
          <span className="category-tag">
            {categoryLabel(item.category)}
          </span>
          {featured && <span className="featured-label">精选</span>}
          {changeType && (
            <span className={`feed-change-label ${changeType}`}>
              {changeType === "progress" ? "实质进展" : "新故事"}
            </span>
          )}
          {watched && (
            <span className="story-watch-label">持续追踪</span>
          )}
        </div>

        {(source || hasRelatedReports) && (
          <p className="card-source">
            <span>
              {hasRelatedReports
                ? "多源报道"
                : source
                  ? sourceTypeLabel(source.source_type)
                  : "公开来源"}
            </span>
            <i aria-hidden="true">/</i>
            {hasRelatedReports
              ? `${sourceInsight.sourceCount} 篇报道 · ${sourceInsight.publisherCount} 家媒体`
              : source?.publisher}
          </p>
        )}
        <h3>{headline}</h3>
        <p className="intel-summary">{item.summary}</p>

        {hasStoryline && (
          <section className="card-storyline" aria-label="关键故事线">
            <header>
              <span>关键故事线</span>
              <b>{storyEvents.length} 次实质进展</b>
            </header>
            <ol>
              {storyline.map((event, index) => (
                <li
                  key={event.id}
                  className={index === storyline.length - 1 ? "latest" : ""}
                >
                  <time dateTime={event.event_time}>
                    {formatRelativeTime(event.event_time)}
                  </time>
                  <p>{event.change_summary?.trim() || event.title}</p>
                </li>
              ))}
            </ol>
          </section>
        )}

        <footer className="card-footer">
          <span>
            {formatRelativeTime(publishedAt)}
            <i aria-hidden="true">·</i>
            {readMinutes} 分钟阅读
          </span>
          <strong className="read-story">
            {hasStoryline
              ? "查看故事线 ↗"
              : hasRelatedReports
                ? "查看来源与详情 ↗"
                : "查看动态详情 ↗"}
          </strong>
        </footer>
      </div>
    </article>
  );
}
