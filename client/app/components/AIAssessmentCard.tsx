import type { CSSProperties } from "react";
import type { AIAssessment } from "../ai-assessment";
import { formatRelativeTime } from "../radar-types";

type Props = {
  assessment: AIAssessment;
  onOpen: () => void;
};

export default function AIAssessmentCard({ assessment, onOpen }: Props) {
  return (
    <article
      className="ai-assessment-card"
      style={{ "--assessment-accent": assessment.accent } as CSSProperties}
    >
      <button
        type="button"
        className="ai-assessment-card-button"
        data-testid="ai-assessment-card"
        onClick={onOpen}
      >
        <div className="assessment-card-topline">
          <div className="card-labels">
            <span className="industry-tag">
              <i style={{ background: assessment.accent }} aria-hidden="true" />
              {assessment.industryName}
            </span>
            <span className="assessment-type-tag">
              <i aria-hidden="true">✦</i>
              AI 综合研判
            </span>
          </div>
          <span className="assessment-period">{assessment.periodLabel}</span>
        </div>

        <p className="assessment-source">
          <span>AI EDITORIAL</span>
          <i aria-hidden="true">/</i>
          基于 {assessment.articleCount} 条新闻 · {assessment.sourceCount} 个来源
        </p>

        <h3>{assessment.title}</h3>
        <p className="assessment-summary">{assessment.summary}</p>

        <div className="assessment-signal-strip" aria-label="研判指标">
          <span>
            <b>{assessment.signals.length}</b>
            核心信号
          </span>
          <span>
            <b>{assessment.confidenceScore}%</b>
            综合置信度
          </span>
          <span>
            <b>{assessment.eventCount}</b>
            独立事件
          </span>
        </div>

        <footer className="assessment-card-footer">
          <span>{formatRelativeTime(assessment.updatedAt)}生成 · 4 分钟阅读</span>
          <strong>查看综合研判 ↗</strong>
        </footer>
      </button>
      <i className="assessment-orbit orbit-one" aria-hidden="true" />
      <i className="assessment-orbit orbit-two" aria-hidden="true" />
    </article>
  );
}
