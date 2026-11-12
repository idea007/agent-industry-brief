"use client";

import { useState } from "react";
import type { CSSProperties } from "react";
import {
  FOCUS_TYPE_LABELS,
  type FocusType,
  type Subscription,
} from "../radar-types";
import { useModalA11y } from "./use-modal-a11y";

type Props = {
  subscriptions: Subscription[];
  initialSlugs: string[];
  required: boolean;
  onConfirm: (slugs: string[]) => void;
  onCreateCustom: (input: CustomFocusInput) => Promise<Subscription | null>;
  onClose: () => void;
};

export type CustomFocusInput = {
  name: string;
  topic: string;
  keywords: string[];
  focusType: FocusType | "auto";
};

const FOCUS_TYPE_OPTIONS: { value: FocusType | "auto"; label: string }[] = [
  { value: "auto", label: "自动识别（推荐）" },
  ...Object.entries(FOCUS_TYPE_LABELS).map(([value, label]) => ({
    value: value as FocusType,
    label,
  })),
];

export default function OnboardingDialog({
  subscriptions,
  initialSlugs,
  required,
  onConfirm,
  onCreateCustom,
  onClose,
}: Props) {
  const [picked, setPicked] = useState<string[]>(
    initialSlugs.length
      ? initialSlugs
      : subscriptions.slice(0, 1).map((item) => item.slug),
  );
  const [customOpen, setCustomOpen] = useState(false);
  const [customName, setCustomName] = useState("");
  const [customKeywords, setCustomKeywords] = useState("");
  const [customFocusType, setCustomFocusType] = useState<FocusType | "auto">(
    "auto",
  );
  const [customError, setCustomError] = useState("");
  const [customSaving, setCustomSaving] = useState(false);
  const panelRef = useModalA11y(required ? () => undefined : onClose);

  function toggle(slug: string) {
    setPicked((current) =>
      current.includes(slug)
        ? current.filter((item) => item !== slug)
        : [...current, slug],
    );
  }

  async function createCustomFocus() {
    const name = customName.trim();
    const keywords = customKeywords
      .split(/[,，、\n]/)
      .map((item) => item.trim())
      .filter(Boolean);
    if (name.length < 2) {
      setCustomError("请输入至少 2 个字的主题名称");
      return;
    }
    if (!keywords.length) {
      setCustomError("请至少填写 1 个关键词");
      return;
    }

    setCustomSaving(true);
    setCustomError("");
    const created = await onCreateCustom({
      name,
      topic: `持续发现 ${name} 的最新公开内容与动态`,
      keywords,
      focusType: customFocusType,
    });
    setCustomSaving(false);
    if (!created) {
      setCustomError("创建失败，请确认情报服务已连接后重试");
      return;
    }
    setPicked((current) => [...new Set([...current, created.slug])]);
    setCustomName("");
    setCustomKeywords("");
    setCustomFocusType("auto");
    setCustomOpen(false);
  }

  return (
    <div className="onboarding-backdrop">
      <div
        className="onboarding-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="onboarding-title"
        ref={panelRef}
      >
        {!required && (
          <button
            type="button"
            className="close-button onboarding-close"
            aria-label="关闭行业设置"
            onClick={onClose}
          >
            ×
          </button>
        )}

        <div className="onboarding-scroll">
          <div className="onboarding-brand" aria-hidden="true">
            <span className="radar-mark large">
              <i />
            </span>
          </div>
          <h1 id="onboarding-title">欢迎使用新闻简报</h1>
          <p className="onboarding-copy">
            选择你关心的行业或对象，系统会聚合最新动态，并把事实与推断分开呈现。
          </p>

          <div className="onboarding-section-label">
            <strong>选择关注</strong>
            <span>
              {picked.length
                ? `已选 ${picked.length} 个`
                : "至少选择 1 个"}
            </span>
          </div>

          <section className="custom-industry-section">
            <button
              type="button"
              className="custom-industry-toggle"
              aria-expanded={customOpen}
              onClick={() => {
                setCustomOpen((current) => !current);
                setCustomError("");
              }}
            >
              <span aria-hidden="true">＋</span>
              没有合适的选项？创建自定义关注
            </button>
            {customOpen && (
              <div className="custom-industry-form">
                <label>
                  <span>关注名称</span>
                  <input
                    value={customName}
                    onChange={(event) => {
                      setCustomName(event.target.value);
                      setCustomError("");
                    }}
                    placeholder="例如：空间机器人"
                  />
                </label>
                <label>
                  <span>关注类型</span>
                  <select
                    value={customFocusType}
                    onChange={(event) =>
                      setCustomFocusType(
                        event.target.value as FocusType | "auto",
                      )
                    }
                  >
                    {FOCUS_TYPE_OPTIONS.map((option) => (
                      <option value={option.value} key={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>
                    {customFocusType === "product"
                      ? "产品别名 / 关联主体"
                      : "关注关键词"}
                  </span>
                  <input
                    value={customKeywords}
                    onChange={(event) => {
                      setCustomKeywords(event.target.value);
                      setCustomError("");
                    }}
                    placeholder={
                      customFocusType === "product"
                        ? "例如：SU7，小米汽车；不要只填“汽车”"
                        : "用逗号分隔，例如：在轨服务，机械臂，商业航天"
                    }
                  />
                </label>
                <button
                  type="button"
                  className="secondary-button"
                  disabled={customSaving}
                  onClick={() => void createCustomFocus()}
                >
                  {customSaving ? "正在创建…" : "创建并关注"}
                </button>
                {customError && (
                  <p className="form-error" role="alert">
                    {customError}
                  </p>
                )}
              </div>
            )}
          </section>

          <div className="industry-choice-grid">
            {subscriptions.map((subscription) => {
              const selected = picked.includes(subscription.slug);
              return (
                <button
                  type="button"
                  key={subscription.id}
                  className={`industry-choice${selected ? " selected" : ""}`}
                  style={
                    {
                      "--industry-accent": subscription.accent,
                    } as CSSProperties
                  }
                  aria-pressed={selected}
                  onClick={() => toggle(subscription.slug)}
                >
                  <span className="choice-check" aria-hidden="true">
                    {selected ? "✓" : ""}
                  </span>
                  <i aria-hidden="true" />
                  <strong>
                    {subscription.name}
                    <span className="focus-type-badge">
                      {FOCUS_TYPE_LABELS[subscription.focus_type]}
                    </span>
                  </strong>
                  <p>{subscription.topic}</p>
                  <div>
                    {subscription.include_keywords
                      .slice(0, 3)
                      .map((keyword) => (
                        <span key={keyword}>{keyword}</span>
                      ))}
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        <footer className="onboarding-actions">
          <button
            type="button"
            className="primary-button"
            disabled={!picked.length}
            onClick={() => onConfirm(picked)}
          >
            开始追踪情报
            <span aria-hidden="true">→</span>
          </button>
          <button
            type="button"
            className="follow-all-button"
            onClick={() => onConfirm(subscriptions.map((item) => item.slug))}
          >
            全部关注
          </button>
        </footer>
      </div>
    </div>
  );
}
