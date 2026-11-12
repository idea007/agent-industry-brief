import {
  categoryKey,
  type CategoryKey,
  type IntelEvent,
  type NewsArticle,
  type Subscription,
} from "./radar-types";

export type AIAssessmentSignal = {
  id: string;
  label: string;
  title: string;
  detail: string;
  score: number;
  evidenceCount: number;
};

export type AIAssessment = {
  id: string;
  industryName: string;
  accent: string;
  category: CategoryKey;
  title: string;
  summary: string;
  conclusion: string;
  articleCount: number;
  eventCount: number;
  sourceCount: number;
  confidenceScore: number;
  periodLabel: string;
  updatedAt: string;
  signals: AIAssessmentSignal[];
  opportunities: string[];
  risks: string[];
  supportingArticles: NewsArticle[];
};

function uniqueBy<T>(items: T[], key: (item: T) => string): T[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    const value = key(item);
    if (seen.has(value)) return false;
    seen.add(value);
    return true;
  });
}

function normalizeConfidence(score: number): number {
  const normalized = score <= 1 ? score * 100 : score;
  return Math.max(0, Math.min(100, Math.round(normalized)));
}

function mostCommon(values: string[], fallback: string): string {
  const counts = new Map<string, number>();
  values
    .map((value) => value.trim())
    .filter(Boolean)
    .forEach((value) => counts.set(value, (counts.get(value) ?? 0) + 1));
  let selected = fallback;
  let highestCount = 0;
  for (const [value, count] of counts) {
    if (count > highestCount) {
      selected = value;
      highestCount = count;
    }
  }
  return selected;
}

function signalFromEvent(
  event: IntelEvent,
  index: number,
): AIAssessmentSignal {
  return {
    id: event.id,
    label: `信号 ${String(index + 1).padStart(2, "0")}`,
    title: event.title,
    detail:
      event.importance_reason ||
      event.summary ||
      "该信号在当前新闻集合中具有较高的行业相关性。",
    score: Math.round(event.importance_score * 10),
    evidenceCount: Math.max(event.sources.length, event.source_ids.length, 1),
  };
}

export function createAIAssessment(
  articles: NewsArticle[],
  subscriptions: Subscription[],
  category: CategoryKey,
): AIAssessment | null {
  if (!articles.length) return null;

  const events = uniqueBy(
    articles.map((article) => article.event),
    (event) => event.id,
  ).sort(
    (left, right) =>
      right.importance_score - left.importance_score ||
      new Date(right.event_time).getTime() - new Date(left.event_time).getTime(),
  );
  const subscriptionById = new Map(
    subscriptions.map((subscription) => [subscription.id, subscription]),
  );
  const dominantSubscriptionId = mostCommon(
    events.map((event) => event.subscription_id),
    events[0].subscription_id,
  );
  const dominantSubscription = subscriptionById.get(dominantSubscriptionId);
  const industryName = dominantSubscription?.name ?? "当前行业";
  const accent = dominantSubscription?.accent ?? "#6366f1";
  const sourceKeys = articles.map(
    (article) =>
      article.source?.source_id ||
      article.source?.url ||
      article.source?.publisher ||
      article.id,
  );
  const sourceCount = new Set(sourceKeys).size;
  const confidenceScore = Math.round(
    events.reduce(
      (total, event) => total + normalizeConfidence(event.confidence_score),
      0,
    ) / events.length,
  );
  const dominantTopic = mostCommon(
    events.flatMap((event) =>
      event.tags.filter(
        (tag) =>
          tag.toLowerCase() !== industryName.toLowerCase() &&
          categoryKey(event.category) !== tag,
      ),
    ),
    category === "全部" ? "行业变化" : category,
  );
  const secondaryTopic = mostCommon(
    events
      .slice(1)
      .flatMap((event) => event.tags)
      .filter((tag) => tag !== dominantTopic && tag !== industryName),
    "落地进展",
  );
  const highPriorityCount = events.filter(
    (event) => event.importance_score >= 8,
  ).length;
  const confirmedCount = events.filter(
    (event) => event.verification_status === "confirmed",
  ).length;
  const title =
    category === "全部"
      ? `${industryName} 综合研判：${dominantTopic}与${secondaryTopic}成为当前主线`
      : `${industryName} · ${category}研判：${dominantTopic}信号正在增强`;
  const summary = `AI 综合分析 ${articles.length} 条新闻、${sourceCount} 个来源，识别出 ${Math.min(events.length, 3)} 条核心信号。当前信息集中在${dominantTopic}与${secondaryTopic}，其中 ${highPriorityCount} 项被判定为高优先级。`;
  const conclusion = `当前${industryName}的变化已从单点消息转向可连续追踪的组合信号。建议优先验证${dominantTopic}相关进展，并把${secondaryTopic}纳入下一轮扫描与决策观察。`;
  const opportunities = uniqueBy(
    events.flatMap((event) =>
      event.inferences.map((inference) => inference.text),
    ),
    (item) => item,
  ).slice(0, 3);
  if (!opportunities.length) {
    opportunities.push(
      `围绕${dominantTopic}建立持续跟踪清单，及时识别产品、合作与投资窗口。`,
      `将${secondaryTopic}纳入内部评估，提前准备对应的工程与内容能力。`,
    );
  }
  const risks: string[] = [];
  if (confirmedCount < events.length) {
    risks.push(
      `${events.length - confirmedCount} 条事件尚未完全确认，关键判断应回看原文并交叉验证。`,
    );
  }
  if (confidenceScore < 80) {
    risks.push("当前来源的一致性仍有限，不宜仅依据单一媒体或摘要做重大决策。");
  }
  risks.push(
    `热点集中可能放大短期噪声，建议持续观察${dominantTopic}是否形成可量化结果。`,
  );

  const updatedAt =
    articles
      .map(
        (article) =>
          article.source?.published_at ?? article.event.event_time,
      )
      .sort(
        (left, right) =>
          new Date(right).getTime() - new Date(left).getTime(),
      )[0] ?? new Date(0).toISOString();

  return {
    id: `assessment-${industryName}-${category}`,
    industryName,
    accent,
    category,
    title,
    summary,
    conclusion,
    articleCount: articles.length,
    eventCount: events.length,
    sourceCount,
    confidenceScore,
    periodLabel: category === "全部" ? "本轮扫描" : `${category}专题`,
    updatedAt,
    signals: events.slice(0, 3).map(signalFromEvent),
    opportunities,
    risks: risks.slice(0, 3),
    supportingArticles: articles,
  };
}
