import type { IntelEvent, IntelSource } from "./radar-types";

export type ResolvedNewsContent = {
  body: string;
  mode: "fulltext" | "translated" | "digest" | "unavailable";
  note?: string;
  source: IntelSource | null;
};

function containsChinese(value: string): boolean {
  return /[\u3400-\u4dbf\u4e00-\u9fff]/u.test(value);
}

function needsChineseTranslation(value: string): boolean {
  const sample = value.slice(0, 4000);
  const chineseCount =
    sample.match(/[\u3400-\u4dbf\u4e00-\u9fff]/gu)?.length ?? 0;
  const kanaOrHangulCount =
    sample.match(/[\u3040-\u30ff\uac00-\ud7af]/gu)?.length ?? 0;
  const latinCount = sample.match(/[A-Za-z]/g)?.length ?? 0;
  if (kanaOrHangulCount >= 4) return true;
  return latinCount >= 12 && chineseCount < Math.max(8, latinCount / 8);
}

function normalizedText(value: string): string {
  return value
    .normalize("NFKC")
    .toLocaleLowerCase()
    .replace(/[\s，。！？、：；,.!?:;'"“”‘’（）()[\]【】《》<>·—_-]+/gu, "");
}

function isTitleOnlyContent(source: IntelSource): boolean {
  const content = normalizedText(source.content);
  const title = normalizedText(source.title);
  if (!content) return true;
  return (
    content === title ||
    (content.length < 120 &&
      (title.includes(content) || content.includes(title)))
  );
}

export function hasSubstantiveNewsContent(source: IntelSource): boolean {
  const content = source.content.trim();
  if (!content || isTitleOnlyContent(source)) return false;
  if (source.content_origin === "fulltext") {
    return content.length >= 160 || (source.word_count ?? 0) >= 80;
  }
  return content.length >= 240 || (source.word_count ?? 0) >= 120;
}

function contentSourceScore(source: IntelSource): number {
  const contentLength = source.translated_content?.trim().length
    ? source.translated_content.trim().length
    : source.content.trim().length;
  return (
    (hasSubstantiveNewsContent(source) ? 2_000 : 0) +
    (source.content_origin === "fulltext" ? 1_000 : 0) +
    (source.translated_content?.trim() ? 400 : 0) +
    Math.min(contentLength, 1_000) +
    Math.round((source.reliability ?? 0.5) * 100)
  );
}

export function selectNewsContentSource(
  sources: IntelSource[],
  preferredSource: IntelSource | null,
): IntelSource | null {
  const candidates = [...sources];
  if (
    preferredSource &&
    !candidates.some(
      (source) => source.source_id === preferredSource.source_id,
    )
  ) {
    candidates.push(preferredSource);
  }
  return (
    candidates.sort(
      (left, right) =>
        contentSourceScore(right) - contentSourceScore(left),
    )[0] ?? null
  );
}

export function selectOriginalArticleSource(
  sources: IntelSource[],
  preferredSource: IntelSource | null,
): IntelSource | null {
  const candidates = [...sources];
  if (
    preferredSource &&
    !candidates.some(
      (source) => source.source_id === preferredSource.source_id,
    )
  ) {
    candidates.push(preferredSource);
  }
  return (
    candidates
      .filter((source) => hasSubstantiveNewsContent(source))
      .sort((left, right) => {
        const fulltextDifference =
          Number(right.content_origin === "fulltext") -
          Number(left.content_origin === "fulltext");
        if (fulltextDifference) return fulltextDifference;
        const preferredDifference =
          Number(right.source_id === preferredSource?.source_id) -
          Number(left.source_id === preferredSource?.source_id);
        if (preferredDifference) return preferredDifference;
        return contentSourceScore(right) - contentSourceScore(left);
      })[0] ?? null
  );
}

function uniqueChineseEvidence(item: IntelEvent): string[] {
  const candidates = [
    item.summary,
    ...item.facts.map((fact) => fact.text),
  ];
  const values: string[] = [];
  for (const candidate of candidates) {
    const value = candidate.trim();
    const normalized = normalizedText(value);
    if (!value || !containsChinese(value) || !normalized) continue;
    const duplicated = values.some((existing) => {
      const normalizedExisting = normalizedText(existing);
      return (
        normalizedExisting === normalized ||
        normalizedExisting.includes(normalized) ||
        normalized.includes(normalizedExisting)
      );
    });
    if (!duplicated) values.push(value);
  }
  return values;
}

function buildEvidenceDigest(item: IntelEvent): string {
  const evidence = uniqueChineseEvidence(item);
  if (!evidence.length) return "";
  const paragraphs = evidence.map((value, index) =>
    index === 0 ? value : `已确认信息：${value}`,
  );
  const publisherCount = new Set(
    item.sources.map((source) => source.publisher.trim()).filter(Boolean),
  ).size;
  if (item.sources.length > 1) {
    paragraphs.push(
      `本次扫描共关联 ${item.sources.length} 篇报道，来自 ${publisherCount || item.sources.length} 家媒体；以上内容仅整理多源报道中可以相互印证的事实。`,
    );
  }
  return paragraphs.join("\n\n");
}

export function resolveNewsContent(
  item: IntelEvent,
  preferredSource: IntelSource | null,
): ResolvedNewsContent {
  const source = selectNewsContentSource(item.sources, preferredSource);
  const original = source?.content.trim() ?? "";
  const translated = source?.translated_content?.trim();

  if (source && hasSubstantiveNewsContent(source) && translated) {
    return {
      body: translated,
      mode: "translated",
      note: "AI 中文译文（基于本次扫描提取的新闻原文）",
      source,
    };
  }
  if (
    source &&
    hasSubstantiveNewsContent(source) &&
    !needsChineseTranslation(original)
  ) {
    return { body: original, mode: "fulltext", source };
  }

  const digest = buildEvidenceDigest(item);
  if (digest) {
    return {
      body: digest,
      mode: "digest",
      note:
        source && needsChineseTranslation(original)
          ? "暂未保存逐段中文译文，当前展示基于本次扫描证据的中文整理。"
          : "暂未获取到足够完整的新闻原文，当前展示基于本次扫描证据的多源内容整理。",
      source: null,
    };
  }
  return {
    body: "暂未获取到足够完整的新闻原文，请通过下方“相关报道”打开来源页面查看。",
    mode: "unavailable",
    note: "当前记录只有标题或过短的 Feed 摘要，系统不会将其标记为完整正文。",
    source: null,
  };
}
