"use client";

import type { CSSProperties, MouseEvent } from "react";
import type { AIAssessment } from "../ai-assessment";
import {
  categoryLabel,
  formatArticleDate,
  sourceTypeLabel,
} from "../radar-types";
import { useModalA11y } from "./use-modal-a11y";

type Props = {
  assessment: AIAssessment;
  onClose: () => void;
  onOpenArticle: (articleId: string) => void;
};

function isHttpUrl(value?: string | null): value is string {
  return !!value && /^https?:\/\//i.test(value);
}

export default function AIAssessmentDialog({
  assessment,
  onClose,
  onOpenArticle,
}: Props) {
  const panelRef = useModalA11y(onClose);

  function closeFromBackdrop(event: MouseEvent<HTMLDivElement>) {
    if (event.target === event.currentTarget) onClose();
  }

  return (
    <div
      className="dialog-backdrop assessment-backdrop"
      onMouseDown={closeFromBackdrop}
    >
      <div
        ref={panelRef}
        className="intel-dialog assessment-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="assessment-dialog-title"
        style={
          { "--assessment-accent": assessment.accent } as CSSProperties
        }
      >
        <header className="dialog-topbar assessment-toolbar">
          <div className="dialog-labels">
            <span className="industry-tag">
              <i style={{ background: assessment.accent }} aria-hidden="true" />
              {assessment.industryName}
            </span>
            <span className="assessment-type-tag">
              <i aria-hidden="true">✦</i>
              AI 综合研判
            </span>
            <span className="extraction-tag">{assessment.periodLabel}</span>
          </div>
          <button
            type="button"
            className="close-button"
            onClick={onClose}
            aria-label="关闭综合研判"
          >
            ×
          </button>
        </header>

        <div className="dialog-scroll assessment-scroll">
          <article className="assessment-sheet">
            <header className="assessment-hero">
              <div className="assessment-kicker">
                <span>AI EDITORIAL INTELLIGENCE</span>
                <span>{formatArticleDate(assessment.updatedAt)}</span>
              </div>
              <p className="assessment-eyebrow">本轮行业信号综合评估</p>
              <h1 id="assessment-dialog-title">{assessment.title}</h1>
              <p className="assessment-deck">{assessment.summary}</p>
              <div className="assessment-metrics">
                <div>
                  <strong>{assessment.articleCount}</strong>
                  <span>新闻样本</span>
                </div>
                <div>
                  <strong>{assessment.sourceCount}</strong>
                  <span>信息来源</span>
                </div>
                <div>
                  <strong>{assessment.eventCount}</strong>
                  <span>独立事件</span>
                </div>
                <div>
                  <strong>{assessment.confidenceScore}%</strong>
                  <span>综合置信度</span>
                </div>
              </div>
            </header>

            <section className="assessment-conclusion">
              <span>EDITOR&apos;S NOTE / 核心结论</span>
              <p>{assessment.conclusion}</p>
            </section>

            <section className="assessment-section">
              <header>
                <span>01</span>
                <div>
                  <small>SIGNAL MAP</small>
                  <h2>核心信号</h2>
                </div>
              </header>
              <div className="assessment-signals">
                {assessment.signals.map((signal) => (
                  <article key={signal.id}>
                    <div>
                      <span>{signal.label}</span>
                      <b>{signal.score}</b>
                    </div>
                    <h3>{signal.title}</h3>
                    <p>{signal.detail}</p>
                    <small>{signal.evidenceCount} 个来源提供依据</small>
                  </article>
                ))}
              </div>
            </section>

            <section className="assessment-section">
              <header>
                <span>02</span>
                <div>
                  <small>DECISION WINDOW</small>
                  <h2>机会与风险</h2>
                </div>
              </header>
              <div className="assessment-decision-grid">
                <article className="opportunity">
                  <span>OPPORTUNITY</span>
                  <h3>值得行动</h3>
                  <ul>
                    {assessment.opportunities.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </article>
                <article className="risk">
                  <span>RISK</span>
                  <h3>仍需验证</h3>
                  <ul>
                    {assessment.risks.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </article>
              </div>
            </section>

            <section className="assessment-section supporting-news-section">
              <header>
                <span>03</span>
                <div>
                  <small>EVIDENCE INDEX</small>
                  <h2>支撑新闻与原文</h2>
                </div>
              </header>
              <div className="supporting-news-list">
                {assessment.supportingArticles.map((article, index) => {
                  const headline = article.source?.title ?? article.event.title;
                  const sourceLabel = article.source
                    ? `${sourceTypeLabel(article.source.source_type)} · ${article.source.publisher}`
                    : "行业新闻简报";
                  return (
                    <article key={article.id}>
                      <span>{String(index + 1).padStart(2, "0")}</span>
                      <button
                        type="button"
                        onClick={() => onOpenArticle(article.id)}
                      >
                        <small>
                          {categoryLabel(
                            article.source?.category ?? article.event.category,
                          )}{" "}
                          / {sourceLabel}
                        </small>
                        <strong>{headline}</strong>
                      </button>
                      {isHttpUrl(article.source?.url) ? (
                        <a
                          href={article.source.url}
                          target="_blank"
                          rel="noreferrer"
                        >
                          原文 ↗
                        </a>
                      ) : (
                        <em>演示来源</em>
                      )}
                    </article>
                  );
                })}
              </div>
            </section>
          </article>
        </div>
      </div>
    </div>
  );
}
