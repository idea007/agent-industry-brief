"use client";

import type { MouseEvent } from "react";
import {
  eventLabel,
  formatTime,
  researchFocusLabel,
  statusLabel,
  type Approval,
  type Run,
  type RunEvent,
  type Subscription,
} from "../radar-types";
import { useModalA11y } from "./use-modal-a11y";

type Props = {
  runs: Run[];
  selectedRun?: Run;
  runEvents: RunEvent[];
  approval?: Approval;
  subscriptions: Subscription[];
  connected: boolean;
  targetBusy: boolean;
  nextRunWillQueue: boolean;
  activeRunCount: number;
  queuedRunCount: number;
  maxConcurrentRuns: number;
  publicPreview: boolean;
  onPublicPreviewChange: (checked: boolean) => void;
  onSelectRun: (runId: string) => void;
  onRun: () => void;
  onCancel: () => void;
  onRetry: () => void;
  onDecision: (decision: "approve" | "reject") => void;
  onClose: () => void;
};

export default function RunTraceDrawer({
  runs,
  selectedRun,
  runEvents,
  approval,
  subscriptions,
  connected,
  targetBusy,
  nextRunWillQueue,
  activeRunCount,
  queuedRunCount,
  maxConcurrentRuns,
  publicPreview,
  onPublicPreviewChange,
  onSelectRun,
  onRun,
  onCancel,
  onRetry,
  onDecision,
  onClose,
}: Props) {
  const panelRef = useModalA11y(onClose);
  const subscription = subscriptions.find(
    (item) => item.id === selectedRun?.subscription_id,
  );

  function closeFromBackdrop(event: MouseEvent<HTMLDivElement>) {
    if (event.target === event.currentTarget) onClose();
  }

  return (
    <div className="drawer-backdrop" onMouseDown={closeFromBackdrop}>
      <div
        className="trace-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="trace-drawer-title"
        ref={panelRef}
      >
        <header className="trace-header">
          <div>
            <p className="detail-kicker">
              {selectedRun?.research_mode === "deep_dive"
                ? "DEEP DIVE"
                : "SCAN DETAILS"}
            </p>
            <h2 id="trace-drawer-title">
              {selectedRun?.research_mode === "deep_dive"
                ? "故事深挖详情"
                : "扫描详情"}
            </h2>
          </div>
          <div className="trace-header-actions">
            <span
              className={`run-status ${selectedRun?.status ?? "completed"}`}
            >
              {selectedRun ? statusLabel(selectedRun.status) : "空闲"}
            </span>
            <button
              type="button"
              className="close-button"
              onClick={onClose}
              aria-label="关闭执行轨迹"
            >
              ×
            </button>
          </div>
        </header>

        <div className="trace-scroll">
          <div className="runtime-banner">
            <span className={`health-dot${connected ? " online" : ""}`} />
            <div>
              <strong>{connected ? "情报服务已连接" : "交互演示模式"}</strong>
              <p>
                {connected
                  ? `${activeRunCount} / ${maxConcurrentRuns} 个扫描执行中${
                      queuedRunCount ? `，${queuedRunCount} 个排队` : ""
                    }`
                  : "启动服务端后将自动切换到真实扫描"}
              </p>
            </div>
          </div>

          {selectedRun && (
            <>
              <label className="run-selector">
                <span>最近任务</span>
                <select
                  value={selectedRun.id}
                  onChange={(event) => onSelectRun(event.target.value)}
                >
                  {runs.map((run) => {
                    const owner = subscriptions.find(
                      (item) => item.id === run.subscription_id,
                    );
                    return (
                      <option value={run.id} key={run.id}>
                        {run.research_mode === "deep_dive"
                          ? researchFocusLabel(run.research_focus)
                          : "扫描"} · {owner?.name ?? "其他关注"} · {formatTime(run.created_at)} ·{" "}
                        {statusLabel(run.status)}
                      </option>
                    );
                  })}
                </select>
              </label>

              <section className="run-goal">
                <div>
                  <span>
                    {selectedRun.research_mode === "deep_dive"
                      ? researchFocusLabel(selectedRun.research_focus)
                      : "当前目标"}
                  </span>
                  <small>{subscription?.name ?? selectedRun.subscription_id}</small>
                </div>
                <p>{selectedRun.goal}</p>
              </section>

              <div className="budget-strip">
                <div>
                  <span>模型步骤</span>
                  <strong>{selectedRun.usage.model_steps}</strong>
                </div>
                <div>
                  <span>工具调用</span>
                  <strong>{selectedRun.usage.tool_calls}</strong>
                </div>
                <div>
                  <span>Tokens</span>
                  <strong>
                    {(selectedRun.usage.input_tokens ?? 0) +
                      (selectedRun.usage.output_tokens ?? 0)}
                  </strong>
                </div>
                <div>
                  <span>当前阶段</span>
                  <strong>{selectedRun.stage}</strong>
                </div>
              </div>

              {approval && (
                <section className="approval-card">
                  <p className="detail-kicker">APPROVAL REQUIRED</p>
                  <h3>是否发送到公开预览？</h3>
                  <p>
                    将发送 {approval.request.item_count ?? 0} 条情报。
                    {approval.request.reason}
                  </p>
                  <div>
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
              )}

              <section className="timeline-section">
                <div className="trace-section-heading">
                  <h3>事件时间线</h3>
                  <span>{runEvents.length} 个事件</span>
                </div>
                <div className="timeline">
                  {runEvents.map((event) => (
                    <div className="timeline-event" key={event.id}>
                      <span
                        className={`timeline-node${
                          event.type.includes("failed") ? " failed" : ""
                        }`}
                      />
                      <div>
                        <strong>{eventLabel(event)}</strong>
                        <p>
                          {event.actor.type} · {formatTime(event.timestamp)}
                        </p>
                      </div>
                      <small>#{event.seq}</small>
                    </div>
                  ))}
                  {!runEvents.length && (
                    <div className="timeline-loading">
                      <span aria-hidden="true" />
                      <p>等待第一个执行事件…</p>
                    </div>
                  )}
                </div>
              </section>

              {selectedRun.error && (
                <div className="run-error" role="alert">
                  <strong>{selectedRun.error.code}</strong>
                  <p>{selectedRun.error.message}</p>
                </div>
              )}
            </>
          )}

          <aside className="trust-note">
            <span aria-hidden="true">⌾</span>
            <div>
              <strong>外部内容是不可信资料</strong>
              <p>来源访问、事实引用与外部发送均由服务端强制校验。</p>
            </div>
          </aside>
        </div>

        <footer className="trace-footer">
          <label className="preview-toggle">
            <input
              type="checkbox"
              checked={publicPreview}
              onChange={(event) =>
                onPublicPreviewChange(event.target.checked)
              }
            />
            <span>公开预览需审批</span>
          </label>
          {selectedRun && ["queued", "running"].includes(selectedRun.status) && connected ? (
            <button type="button" className="secondary-button" onClick={onCancel}>
              {selectedRun.status === "queued" ? "取消排队" : "取消扫描"}
            </button>
          ) : selectedRun?.status === "failed" ? (
            <button type="button" className="secondary-button" onClick={onRetry}>
              重试
            </button>
          ) : (
            <button
              type="button"
              className="primary-button"
              onClick={onRun}
              disabled={targetBusy || !subscriptions.length}
            >
              {targetBusy
                ? "当前关注运行中…"
                : nextRunWillQueue
                  ? "加入扫描队列"
                  : "开始新扫描"}
              <span aria-hidden="true">↗</span>
            </button>
          )}
        </footer>
      </div>
    </div>
  );
}
