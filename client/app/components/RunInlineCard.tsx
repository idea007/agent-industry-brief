import {
  researchFocusLabel,
  statusLabel,
  type Approval,
  type Run,
  type RunEvent,
  type Subscription,
} from "../radar-types";

type Props = {
  run?: Run;
  events: RunEvent[];
  subscription?: Subscription;
  approval?: Approval;
  connected: boolean;
  onOpenTrace: () => void;
  onDecision: (decision: "approve" | "reject") => void;
  onRetry: () => void;
};

export default function RunInlineCard({
  run,
  events,
  subscription,
  approval,
  connected,
  onOpenTrace,
  onDecision,
  onRetry,
}: Props) {
  if (!run) return null;
  const deepDive = run.research_mode === "deep_dive";
  const deepDiveLabel = researchFocusLabel(run.research_focus);

  if (approval) {
    return (
      <section className="inline-run-card approval" aria-live="polite">
        <div className="inline-run-icon" aria-hidden="true">
          !
        </div>
        <div className="inline-run-copy">
          <span>需要你的确认</span>
          <h2>情报已整理完成，是否发送到公开预览？</h2>
          <p>
            {subscription?.name ?? "当前领域"} ·{" "}
            {approval.request.item_count ?? 0} 条情报等待审批
          </p>
        </div>
        <div className="inline-approval-actions">
          <button type="button" onClick={() => onDecision("reject")}>
            只留草稿
          </button>
          <button
            type="button"
            className="approve"
            onClick={() => onDecision("approve")}
          >
            允许一次
          </button>
        </div>
      </section>
    );
  }

  if (["queued", "running"].includes(run.status)) {
    return (
      <section className="inline-run-card running" aria-live="polite">
        <div className="inline-run-icon scanning" aria-hidden="true">
          <i />
        </div>
        <div className="inline-run-copy">
          <span>
            {connected
              ? run.status === "queued"
                ? "等待执行"
                : "AI 正在整理"
              : "交互演示"}
          </span>
          <h2>
            {run.status === "queued"
              ? deepDive
                ? `${deepDiveLabel}已加入队列`
                : "已加入扫描队列"
              : deepDive
                ? `正在${deepDiveLabel}`
                : "正在扫描"}「
            {subscription?.name ?? "当前领域"}」
          </h2>
          <p>
            {run.status === "queued"
              ? `排队中 · 有执行槽后自动开始 · 已记录 ${events.length} 个事件`
              : `${statusLabel(run.status)} · 正在采集、去重并评估公开动态 · 已处理 ${events.length} 个步骤`}
          </p>
        </div>
        <button type="button" className="inline-trace-link" onClick={onOpenTrace}>
          查看运行过程 <span aria-hidden="true">→</span>
        </button>
      </section>
    );
  }

  if (run.status === "failed") {
    return (
      <section className="inline-run-card failed" role="alert">
        <div className="inline-run-icon" aria-hidden="true">
          ×
        </div>
        <div className="inline-run-copy">
          <span>{deepDive ? `${deepDiveLabel}未完成` : "扫描未完成"}</span>
          <h2>{subscription?.name ?? "当前领域"}{deepDive ? "深挖" : "扫描"}失败</h2>
          <p>{run.error?.message ?? "可以查看运行过程或立即重试。"}</p>
        </div>
        <div className="inline-approval-actions">
          <button type="button" onClick={onOpenTrace}>
            查看过程
          </button>
          <button type="button" className="approve" onClick={onRetry}>
            重试
          </button>
        </div>
      </section>
    );
  }

  if (run.status === "completed" && run.result?.empty_result) {
    return (
      <section className="inline-run-card empty-result" aria-live="polite">
        <div className="inline-run-icon" aria-hidden="true">
          ✓
        </div>
        <div className="inline-run-copy">
          <span>{deepDive ? `${deepDiveLabel}已完成` : "扫描已完成"}</span>
          <h2>{deepDive ? "本次没有找到新的可靠进展" : `本次未发现可靠的「${subscription?.name ?? "当前领域"}」内容`}</h2>
          <p>{run.result.empty_result.message}</p>
        </div>
        <div className="inline-approval-actions">
          <button type="button" onClick={onOpenTrace}>
            查看过程
          </button>
          <button type="button" className="approve" onClick={onRetry}>
            {deepDive ? "再次深挖" : "再次扫描"}
          </button>
        </div>
      </section>
    );
  }

  return null;
}
