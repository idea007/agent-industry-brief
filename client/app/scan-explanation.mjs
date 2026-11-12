/** @typedef {import("./radar-types").SourceDocument} SourceDocument */

const OUTCOME_LABELS = {
  discovered: "已发现",
  deferred: "暂缓采用",
  selected: "已入选",
  reviewed: "证据复核",
  blocked: "已拦截",
};

const FOCUS_TIER_LABELS = {
  core: "核心对象",
  related: "一级关系",
  context: "周边背景",
  unmatched: "关系不足",
};

const CONTENT_ORIGIN_LABELS = {
  fulltext: "完整正文",
  feed: "Feed 摘要",
  fixture: "演示资料",
};

function hasReason(document, prefix) {
  return (document.ranking_reasons ?? []).some(
    (reason) => reason === prefix || reason.startsWith(`${prefix}:`),
  );
}

/**
 * Turn internal ranking and quality signals into one user-facing explanation.
 * The explanation is deliberately conservative: it describes the observed
 * gate, not a model intention that was never persisted.
 *
 * @param {SourceDocument} document
 */
export function sourceDecisionReason(document) {
  if (document.last_outcome === "selected") {
    return "相关性与证据质量达到本次入选要求";
  }
  if (document.last_outcome === "reviewed") {
    return "已进入证据复核，用于交叉验证但未单独形成情报";
  }
  if (document.safety_flags?.length || hasReason(document, "blocked:safety")) {
    return "内容触发安全检查，不能进入事实整理";
  }
  if (
    hasReason(document, "blocked:muted_source") ||
    hasReason(document, "personalization:muted_source")
  ) {
    return "来源已被当前关注的偏好设置屏蔽";
  }
  if (
    document.duplicate_of_document_id ||
    document.cluster_relation === "duplicate"
  ) {
    return "与已收录报道重复，已合并到同一事件";
  }
  if (document.focus_tier === "unmatched") {
    return "只命中宽泛关键词，与当前关注缺少明确关系";
  }
  if (
    typeof document.relevance_score === "number" &&
    document.relevance_score < 0.35
  ) {
    return "与当前关注的综合相关性不足";
  }
  if (hasReason(document, "deferred:context_threshold")) {
    return "属于周边背景，但来源可靠性或直接关联不足";
  }
  if (document.extraction_status === "failed") {
    return "正文提取失败，当前证据不足以支撑独立结论";
  }
  if (hasReason(document, "deferred:evidence_capacity")) {
    return "候选有效，但本轮证据池优先保留了更直接的来源";
  }
  if (
    typeof document.novelty_score === "number" &&
    document.novelty_score < 0.45
  ) {
    return "缺少新的事实、数字或实质进展";
  }
  if (document.last_outcome === "blocked") {
    return "未通过本次安全或质量硬门槛";
  }
  if (document.last_outcome === "deferred") {
    return "暂未达到本轮证据池的采用优先级";
  }
  return "已发现，等待后续质量判断";
}

/** @param {SourceDocument["last_outcome"]} outcome */
export function sourceOutcomeLabel(outcome) {
  return OUTCOME_LABELS[outcome] ?? "等待判断";
}

/** @param {number | null | undefined} value */
export function formatQualityPercent(value) {
  return typeof value === "number" ? `${Math.round(value * 100)}%` : "待评估";
}

/**
 * @param {SourceDocument[]} documents
 */
export function buildScanExplanation(documents) {
  const outcomeCounts = {
    selected: 0,
    reviewed: 0,
    deferred: 0,
    blocked: 0,
    discovered: 0,
  };
  const focusTierCounts = {
    core: 0,
    related: 0,
    context: 0,
    unmatched: 0,
  };
  const contentOriginCounts = {
    fulltext: 0,
    feed: 0,
    fixture: 0,
  };
  const publishers = new Set();
  const evidenceChains = new Set();
  const reasonCounts = new Map();

  for (const document of documents) {
    outcomeCounts[document.last_outcome] += 1;
    focusTierCounts[document.focus_tier ?? "unmatched"] += 1;
    contentOriginCounts[document.content_origin ?? "feed"] += 1;
    if (document.publisher) publishers.add(document.publisher);
    if (document.evidence_chain_id) evidenceChains.add(document.evidence_chain_id);
    if (document.last_outcome !== "selected") {
      const reason = sourceDecisionReason(document);
      reasonCounts.set(reason, (reasonCounts.get(reason) ?? 0) + 1);
    }
  }

  const selectedDocuments = documents.filter(
    (document) => document.last_outcome === "selected",
  );
  const average = (field) => {
    const values = selectedDocuments
      .map((document) => document[field])
      .filter((value) => typeof value === "number");
    return values.length
      ? values.reduce((total, value) => total + value, 0) / values.length
      : null;
  };

  return {
    outcomeCounts,
    focusTiers: Object.entries(focusTierCounts).map(([key, count]) => ({
      key,
      label: FOCUS_TIER_LABELS[key],
      count,
    })),
    contentOrigins: Object.entries(contentOriginCounts).map(([key, count]) => ({
      key,
      label: CONTENT_ORIGIN_LABELS[key],
      count,
    })),
    publisherCount: publishers.size,
    evidenceChainCount: evidenceChains.size,
    selectedAverages: {
      relevance: average("relevance_score"),
      novelty: average("novelty_score"),
      reliability: average("reliability"),
    },
    reasonGroups: [...reasonCounts.entries()]
      .map(([reason, count]) => ({ reason, count }))
      .sort((left, right) => right.count - left.count || left.reason.localeCompare(right.reason, "zh-CN")),
    excludedSamples: documents
      .filter((document) => document.last_outcome !== "selected")
      .map((document) => ({
        document,
        reason: sourceDecisionReason(document),
      }))
      .sort(
        (left, right) =>
          (right.document.ranking_score ?? 0) -
            (left.document.ranking_score ?? 0) ||
          Date.parse(right.document.published_at) -
            Date.parse(left.document.published_at),
      )
      .slice(0, 5),
  };
}
