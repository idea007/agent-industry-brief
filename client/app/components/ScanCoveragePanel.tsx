"use client";

import {
  buildScanExplanation,
  formatQualityPercent,
  sourceOutcomeLabel,
} from "../scan-explanation.mjs";
import type {
  Run,
  SourceDocument,
  SourceHealth,
  SourceQueryMetric,
} from "../radar-types";

type Props = {
  run: Pick<Run, "status" | "result">;
  documents: SourceDocument[];
  sourceHealth: SourceHealth[];
  queryMetrics: SourceQueryMetric[];
};

function safeExternalUrl(value: string): string | null {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:"
      ? url.toString()
      : null;
  } catch {
    return null;
  }
}

export default function ScanCoveragePanel({
  run,
  documents,
  sourceHealth,
  queryMetrics,
}: Props) {
  const explanation = buildScanExplanation(documents);
  const { selected, reviewed, deferred, blocked } = explanation.outcomeCounts;
  const generated = run.result?.item_count ?? 0;
  const stages = [
    `${documents.length} 条候选`,
    `${selected + reviewed} 条证据来源`,
  ];
  let note: string | undefined;
  switch (run.status) {
    case "failed":
      stages.push(generated > 0 ? "投递未完成" : "整理未完成");
      note = generated > 0 ? `${generated} 条情报已保留` : "本次未生成新情报";
      break;
    case "cancelled":
      stages.push("扫描已取消");
      note = "本次未生成新情报";
      break;
    case "queued":
    case "running":
      stages.push("正在整理");
      break;
    default:
      stages.push(`${selected} 条来源入选`, `${generated} 条情报`);
      note = `${deferred + reviewed + blocked} 条来源未采用`;
  }
  const unhealthySources = sourceHealth.filter(
    (item) => item.health_status !== "healthy",
  ).length;
  const queryTotals = queryMetrics.reduce(
    (totals, metric) => ({
      discovery: totals.discovery + metric.discovery_count,
      evidence: totals.evidence + metric.evidence_count,
      selected: totals.selected + metric.selected_count,
    }),
    { discovery: 0, evidence: 0, selected: 0 },
  );

  return (
    <details className="scan-explanation" data-run-status={run.status}>
      <summary>
        <span className="scan-funnel" role="status">
          <span className="scan-funnel-label">最近扫描</span>
          {stages.map((stage, index) => (
            <span className="scan-stage" key={stage}>
              {index > 0 && <i aria-hidden="true">→</i>}
              <strong>{stage}</strong>
            </span>
          ))}
          {note && <small>{note}</small>}
        </span>
        <span className="scan-explanation-action">查看筛选与来源覆盖</span>
      </summary>

      <div className="scan-explanation-body">
        <section className="scan-decision-overview">
          <header>
            <div>
              <span>筛选结果</span>
              <h3>一条来源最终会进入哪一步</h3>
            </div>
            <p>报道篇数不等于独立证据数；重复报道会合并到同一事件。</p>
          </header>
          <div className="scan-outcome-grid">
            <article className="selected">
              <strong>{explanation.outcomeCounts.selected}</strong>
              <span>最终入选</span>
              <small>参与生成新闻情报</small>
            </article>
            <article>
              <strong>{explanation.outcomeCounts.reviewed}</strong>
              <span>证据复核</span>
              <small>用于交叉验证或补充背景</small>
            </article>
            <article>
              <strong>{explanation.outcomeCounts.deferred}</strong>
              <span>暂缓采用</span>
              <small>优先级不足或等待更多证据</small>
            </article>
            <article className="blocked">
              <strong>{explanation.outcomeCounts.blocked}</strong>
              <span>硬门槛拦截</span>
              <small>安全或质量检查未通过</small>
            </article>
          </div>
        </section>

        <section className="scan-coverage-overview">
          <header>
            <div>
              <span>本次覆盖</span>
              <h3>搜到了什么</h3>
            </div>
            <p>
              {explanation.publisherCount} 家媒体 · {explanation.evidenceChainCount} 条独立证据链
            </p>
          </header>
          <div className="scan-coverage-groups">
            <dl>
              <div>
                <dt>关系层级</dt>
                <dd>
                  {explanation.focusTiers.map((tier) => (
                    <span key={tier.key}>{tier.label} {tier.count}</span>
                  ))}
                </dd>
              </div>
              <div>
                <dt>正文情况</dt>
                <dd>
                  {explanation.contentOrigins.map((origin) => (
                    <span key={origin.key}>{origin.label} {origin.count}</span>
                  ))}
                </dd>
              </div>
              <div>
                <dt>入选来源均值</dt>
                <dd>
                  <span>相关性 {formatQualityPercent(explanation.selectedAverages.relevance)}</span>
                  <span>新颖度 {formatQualityPercent(explanation.selectedAverages.novelty)}</span>
                  <span>可靠性 {formatQualityPercent(explanation.selectedAverages.reliability)}</span>
                </dd>
              </div>
            </dl>
            <aside>
              <strong>来源运行情况</strong>
              {sourceHealth.length ? (
                <p>
                  近期记录 {sourceHealth.length} 个来源，{unhealthySources
                    ? `${unhealthySources} 个需要检查`
                    : "目前没有异常来源"}。
                </p>
              ) : (
                <p>来源健康数据暂未形成，完成真实 RSS 或网页扫描后会补充。</p>
              )}
              {queryMetrics.length > 0 && (
                <p>
                  AI 检索累计发现 {queryTotals.discovery} 条候选，进入证据池 {queryTotals.evidence} 条，最终入选 {queryTotals.selected} 条。
                </p>
              )}
            </aside>
          </div>
        </section>

        <section className="scan-rejection-reasons">
          <header>
            <div>
              <span>未采用内容</span>
              <h3>
                {explanation.reasonGroups.length
                  ? `${explanation.reasonGroups.length} 类未采用原因`
                  : "未采用原因"}
              </h3>
            </div>
            <p>这里只解释已保存的质量信号，不猜测模型没有记录的原因。</p>
          </header>
          {explanation.reasonGroups.length ? (
            <div className="scan-reason-list">
              {explanation.reasonGroups.map((group) => (
                <p key={group.reason}>
                  <strong>{group.count}</strong>
                  <span>{group.reason}</span>
                </p>
              ))}
            </div>
          ) : (
            <p className="scan-explanation-empty">本次没有未采用来源。</p>
          )}
          {!!explanation.excludedSamples.length && (
            <div className="scan-excluded-samples">
              {explanation.excludedSamples.map(({ document, reason }) => {
                const url = safeExternalUrl(document.latest_url);
                const title = (
                  <>
                    <strong>{document.title}</strong>
                    <small>
                      {document.publisher} · {sourceOutcomeLabel(document.last_outcome)}
                    </small>
                  </>
                );
                return (
                  <article key={`${document.id}-${document.last_outcome}`}>
                    <span aria-hidden="true" />
                    <div>
                      {url ? (
                        <a href={url} target="_blank" rel="noreferrer">
                          {title}
                        </a>
                      ) : (
                        title
                      )}
                      <p>{reason}</p>
                    </div>
                    <dl>
                      <div>
                        <dt>相关性</dt>
                        <dd>{formatQualityPercent(document.relevance_score)}</dd>
                      </div>
                      <div>
                        <dt>新颖度</dt>
                        <dd>{formatQualityPercent(document.novelty_score)}</dd>
                      </div>
                    </dl>
                  </article>
                );
              })}
            </div>
          )}
        </section>
      </div>
    </details>
  );
}
