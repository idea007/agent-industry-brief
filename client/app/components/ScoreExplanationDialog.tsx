"use client";

import type { CSSProperties, MouseEvent } from "react";
import {
  confidenceLabel,
  storySourceInsight,
  verificationLabel,
  type IntelEvent,
  type IntelSource,
  type Subscription,
} from "../radar-types";
import { useModalA11y } from "./use-modal-a11y";

export type ScoreMetric = "importance" | "confidence";

type Props = {
  item: IntelEvent;
  source: IntelSource | null;
  subscription?: Subscription;
  metric: ScoreMetric;
  onClose: () => void;
};

export default function ScoreExplanationDialog({
  item,
  source,
  subscription,
  metric,
  onClose,
}: Props) {
  const panelRef = useModalA11y(onClose);
  const accent = subscription?.accent ?? "#6366F1";
  const isImportance = metric === "importance";
  const metricName = isImportance ? "重要度" : "可信度";
  const score = isImportance
    ? `${item.importance_score.toFixed(1)} / 10`
    : `${Math.round(item.confidence_score * 100)}%`;
  const scoreLabel = isImportance
    ? item.importance_score >= 8
      ? "优先关注"
      : item.importance_score >= 6
        ? "值得关注"
        : "持续观察"
    : confidenceLabel(item.confidence_level);
  const reason = isImportance
    ? item.importance_reason
    : item.confidence_reason;
  const factors = isImportance
    ? ["行业相关性", "潜在影响", "信息时效性", "行动参考价值"]
    : ["来源可靠性", "独立来源数量", "直接证据完整度", "多来源一致性"];
  const evidenceCount = Math.max(
    item.sources.length,
    item.source_ids.length,
  );
  const sourceInsight = storySourceInsight(item);
  const threshold = subscription?.minimum_importance;
  let thresholdExplanation = `当前为「${scoreLabel}」档位。`;
  if (threshold !== undefined) {
    const difference = item.importance_score - threshold;
    const thresholdLabel = `「${subscription?.name ?? "当前订阅"}」的 ${threshold.toFixed(1)} 分入选线`;
    thresholdExplanation =
      Math.abs(difference) < 0.05
        ? `等于${thresholdLabel}，属于「${scoreLabel}」档位的起点。`
        : difference > 0
          ? `比${thresholdLabel}高 ${difference.toFixed(1)} 分，当前为「${scoreLabel}」档位。`
          : `比${thresholdLabel}低 ${Math.abs(difference).toFixed(1)} 分，当前仅建议持续观察。`;
  }
  const factSource =
    sourceInsight.officialSource?.publisher ??
    (source ? "待确认" : "暂无来源");
  const evidenceLimitsUpgrade =
    evidenceCount <= 1 ||
    sourceInsight.publisherCount <= 1 ||
    item.verification_status !== "confirmed";
  const evidenceExplanation =
    `当前有 ${evidenceCount} 篇相关报道，覆盖 ${sourceInsight.publisherCount} 家媒体，` +
    `验证状态为「${verificationLabel(item.verification_status)}」，事实源为「${factSource}」。` +
    (evidenceLimitsUpgrade
      ? "现有证据不足以支持进入更高档位。"
      : "现有证据覆盖较完整，支持当前档位。");
  const nextJudgment =
    item.inferences[0]?.text ?? "当前记录没有保存进一步行动建议。";

  function closeFromBackdrop(event: MouseEvent<HTMLDivElement>) {
    if (event.target === event.currentTarget) onClose();
  }

  return (
    <div
      className="dialog-backdrop score-explanation-backdrop"
      onMouseDown={closeFromBackdrop}
    >
      <div
        ref={panelRef}
        className="intel-dialog score-explanation-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="score-explanation-title"
        style={{ "--score-accent": accent } as CSSProperties}
      >
        <header className="dialog-topbar score-explanation-toolbar">
          <div>
            <small>AI SCORE EXPLAINER</small>
            <h2 id="score-explanation-title">{metricName}评分说明</h2>
          </div>
          <button
            type="button"
            className="close-button"
            onClick={onClose}
            aria-label={`关闭${metricName}评分说明`}
          >
            ×
          </button>
        </header>

        <div className="score-explanation-content">
          <section className="score-explanation-hero">
            <span>{metricName}</span>
            <strong>{score}</strong>
            <b>{scoreLabel}</b>
          </section>

          <section className="score-explanation-section">
            <small>HOW IT IS ASSESSED / 如何得出</small>
            <p>
              {isImportance
                ? `本条 ${item.importance_score.toFixed(1)} 分由本轮 AI 整理结果直接给出，综合考虑下列维度，不是按热度排序，也不是四项子分的机械相加。`
                : "AI 根据当前 Run 中可引用来源的质量、独立性和相互印证情况综合判断。"}
            </p>
            <div className="score-factor-list">
              {factors.map((factor) => (
                <span key={factor}>{factor}</span>
              ))}
            </div>
          </section>

          {isImportance ? (
            <section className="score-explanation-section">
              <small>
                WHY {item.importance_score.toFixed(1)} / 为什么是{" "}
                {item.importance_score.toFixed(1)} 分
              </small>
              <div className="score-derivation-list">
                <div>
                  <span>模型依据</span>
                  <p>{reason}</p>
                </div>
                <div>
                  <span>档位定位</span>
                  <p>{thresholdExplanation}</p>
                </div>
                <div>
                  <span>证据约束</span>
                  <p>{evidenceExplanation}</p>
                </div>
                <div>
                  <span>后续判断</span>
                  <p>{nextJudgment}</p>
                </div>
              </div>
            </section>
          ) : (
            <section className="score-explanation-section current-score-reason">
              <small>CURRENT REASON / 本条评分依据</small>
              <p>{reason}</p>
            </section>
          )}

          <footer className="score-explanation-evidence">
            <span>
              <small>相关报道</small>
              <strong>{evidenceCount} 篇</strong>
            </span>
            <span>
              <small>媒体覆盖</small>
              <strong>{sourceInsight.publisherCount} 家</strong>
            </span>
            <span>
              <small>事实源</small>
              <strong>
                {sourceInsight.officialSource?.publisher ??
                  (source ? "待确认" : "暂无来源")}
              </strong>
            </span>
          </footer>

          <p className="score-explanation-note">
            评分用于辅助排序和快速判断，不代表统计学结论；证据不足或来源冲突时应以详情中的
            原始来源为准。
          </p>
        </div>
      </div>
    </div>
  );
}
