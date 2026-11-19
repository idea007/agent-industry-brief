"use client";

import Link from "next/link";
import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { apiUrl } from "../radar-api";
import { ModelManager } from "./model-manager.mjs";

type Feature = {
  id: string;
  name: string;
  group: string;
  kind: "tools" | "structured";
  selection: "single" | "multiple";
  modelId: string;
  allowedModelIds: string[];
};

type CatalogModel = {
  id: string;
  name: string;
  source: { name: string };
  contextWindow: number | null;
  reasoningEfforts: string[];
};

type State = {
  connection: { configured: boolean; checked: boolean; error: string };
  features: Feature[];
};

type DialogState =
  | { type: "details"; model: CatalogModel }
  | { type: "edit" | "remove"; feature: Feature }
  | { type: "add"; features: Feature[] };

function SettingsDialog({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (dialog && !dialog.open) dialog.showModal();
  }, []);

  return (
    <dialog
      className="settings-dialog"
      ref={ref}
      onClose={onClose}
      aria-labelledby="settings-dialog-title"
    >
      <header>
        <h2 id="settings-dialog-title">{title}</h2>
        <button type="button" aria-label="关闭" onClick={onClose}>×</button>
      </header>
      {children}
    </dialog>
  );
}

export default function ModelSettingsPage() {
  const managerRoot = useRef<HTMLDivElement>(null);
  const managerRef = useRef<ModelManager | null>(null);
  const [state, setState] = useState<State>();
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [dialog, setDialog] = useState<DialogState>();
  const [dialogError, setDialogError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    let manager: ModelManager | undefined;

    async function request(
      path: string,
      options?: { method: string; body: unknown },
    ) {
      const response = await fetch(apiUrl(path), {
        signal,
        cache: "no-store",
        ...(options && {
          method: options.method,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(options.body),
        }),
      });
      const data = await response.json();
      if (!response.ok) {
        const detail = typeof data.detail === "string" ? data.detail : "无法读取或保存模型设置。";
        throw new Error(detail);
      }
      return data;
    }

    async function load() {
      try {
        const snapshot: State = await request("/api/model-settings?refresh=true");
        if (signal.aborted || !managerRoot.current) return;
        const update = (next: State) => {
          if (!signal.aborted) setState(next);
        };
        manager = new ModelManager({
          api: request,
          onState: update,
          notify: (message: string, failed: boolean) => {
            if (failed && !signal.aborted) setNotice(message);
          },
          onDetails: (model: CatalogModel) => setDialog({ type: "details", model }),
          onFeatureAction: (action: string, feature?: Feature) => {
            setDialogError("");
            if (action === "add-route" && manager) {
              const existing = new Set(manager.draft.routes.map((route: Feature) => route.id));
              setDialog({
                type: "add",
                features: snapshot.features.filter((item) => !existing.has(item.id)),
              });
            } else if (feature && (action === "edit-route" || action === "delete-route")) {
              setDialog({ type: action === "edit-route" ? "edit" : "remove", feature });
            }
          },
        });
        managerRef.current = manager;
        manager.mount(managerRoot.current, snapshot);
        update(snapshot);
      } catch (cause) {
        if (!signal.aborted) {
          setError(cause instanceof Error ? cause.message : "无法连接情报服务。");
        }
      }
    }

    void load();
    return () => {
      controller.abort();
      manager?.dispose();
      managerRef.current = null;
    };
  }, [attempt]);

  const connection = state?.connection;
  const connectionLabel = connection?.error
    ? "连接异常"
    : connection?.checked
      ? "已连接服务端"
      : connection
        ? "未连接服务端"
        : "正在读取连接";
  const connectionClass = connection?.error ? "error" : connection?.checked ? "" : "pending";
  const closeDialog = () => setDialog(undefined);

  function submitFeature(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const manager = managerRef.current;
    if (!manager || !dialog) return;
    const fields = new FormData(event.currentTarget);
    try {
      if (dialog.type === "edit") {
        manager.upsertRoute({
          ...dialog.feature,
          name: String(fields.get("name") ?? ""),
          group: String(fields.get("group") ?? ""),
          selection: fields.get("selection") === "single" ? "single" : "multiple",
        });
      } else if (dialog.type === "add") {
        const feature = dialog.features.find((item) => item.id === fields.get("id"));
        if (!feature) return;
        manager.upsertRoute(manager.usable(feature.modelId) ? feature : {
          ...feature,
          modelId: "",
          allowedModelIds: [],
        });
      } else if (dialog.type === "remove") {
        manager.removeRoute(dialog.feature.id);
      }
      closeDialog();
    } catch (cause) {
      setDialogError(cause instanceof Error ? cause.message : "无法修改功能。");
    }
  }

  return (
    <div className="settings-shell">
      <aside className="settings-sidebar" aria-label="设置导航">
        <Link className="settings-brand" href="/" aria-label="新闻简报首页">
          <span className="radar-mark" aria-hidden="true"><i /></span>
          新闻简报
        </Link>
        <nav className="settings-nav" aria-label="新闻简报">
          <Link href="/"><span aria-hidden="true">‹</span> 返回首页</Link>
          <Link href="/settings" aria-current="page">
            <span aria-hidden="true">◈</span> 功能与模型
          </Link>
        </nav>
        <div className="settings-sidebar-status">{connectionLabel}</div>
      </aside>

      <main className="settings-page">
        <header className="settings-heading">
          <h1>功能与模型</h1>
          <span className={`settings-connection ${connectionClass}`} role="status">
            {connectionLabel}
          </span>
        </header>
        {connection?.error && <p className="cm-feedback error" role="alert">{connection.error}</p>}
        {connection?.configured === false && (
          <p className="settings-message">接入 Model Dock 后，可在此配置每个功能使用的授权模型。</p>
        )}
        {error && (
          <div className="settings-message" role="alert">
            {error}
            <button type="button" onClick={() => { setError(""); setAttempt(attempt + 1); }}>
              重试
            </button>
          </div>
        )}
        {!error && !state && <p className="settings-message" role="status">正在加载模型目录…</p>}
        {notice && <p className="cm-feedback error" role="alert">{notice}</p>}
        <div ref={managerRoot} />
      </main>

      {dialog?.type === "details" && (
        <SettingsDialog title={dialog.model.name} onClose={closeDialog}>
          <dl className="cm-details">
            <dt>模型 ID</dt><dd>{dialog.model.id}</dd>
            <dt>凭证来源</dt><dd>{dialog.model.source.name}</dd>
            <dt>上下文上限</dt>
            <dd>{dialog.model.contextWindow?.toLocaleString("zh-CN") ?? "未声明"}</dd>
            <dt>思考深度</dt><dd>{dialog.model.reasoningEfforts.join(" / ") || "未声明"}</dd>
          </dl>
        </SettingsDialog>
      )}

      {dialog && dialog.type !== "details" && (
        <SettingsDialog
          title={dialog.type === "add" ? "添加功能" : dialog.type === "edit" ? "编辑功能" : "移除功能配置"}
          onClose={closeDialog}
        >
          <form className="settings-feature-form" onSubmit={submitFeature}>
            {dialog.type === "edit" && (
              <>
                <label>功能名称<input name="name" defaultValue={dialog.feature.name} maxLength={100} required /></label>
                <label>分组<input name="group" defaultValue={dialog.feature.group} maxLength={80} placeholder="留空时作为独立功能" /></label>
                <label>
                  模型选择
                  <select name="selection" defaultValue={dialog.feature.selection}>
                    <option value="single">单一模型</option>
                    <option value="multiple">多个候选＋默认模型</option>
                  </select>
                </label>
              </>
            )}
            {dialog.type === "add" && (
              dialog.features.length ? (
                <label>
                  功能
                  <select name="id" required>
                    {dialog.features.map((feature) => (
                      <option value={feature.id} key={feature.id}>{feature.group} · {feature.name}</option>
                    ))}
                  </select>
                </label>
              ) : <p>新闻简报的所有模型功能均已添加。</p>
            )}
            {dialog.type === "remove" && (
              <p>移除「{dialog.feature.name}」的配置后，此步骤将使用服务端默认模型。</p>
            )}
            {dialogError && <p className="cm-feedback error" role="alert">{dialogError}</p>}
            <footer>
              <button type="button" onClick={closeDialog}>关闭</button>
              {(dialog.type !== "add" || dialog.features.length > 0) && (
                <button type="submit" className="primary">{dialog.type === "remove" ? "移除" : "加入草稿"}</button>
              )}
            </footer>
          </form>
        </SettingsDialog>
      )}
    </div>
  );
}
