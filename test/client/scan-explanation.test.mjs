import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  buildScanExplanation,
  sourceDecisionReason,
} from "../../client/app/scan-explanation.mjs";

function document(overrides = {}) {
  return {
    id: "document-1",
    subscription_id: "subscription-1",
    source_id: "source-1",
    canonical_url: "https://example.com/story",
    latest_url: "https://example.com/story",
    title: "示例新闻",
    publisher: "示例媒体",
    source_type: "industry_media",
    published_at: "2026-08-05T00:00:00Z",
    content_excerpt: "示例正文",
    content_hash: "hash",
    content_origin: "feed",
    word_count: 120,
    reliability: 0.7,
    safety_flags: [],
    ranking_reasons: [],
    focus_tier: "core",
    focus_relation_score: 1,
    relevance_score: 0.8,
    novelty_score: 0.7,
    first_seen_at: "2026-08-05T00:00:00Z",
    last_seen_at: "2026-08-05T00:00:00Z",
    last_run_id: "run-1",
    seen_count: 1,
    last_outcome: "selected",
    ...overrides,
  };
}

test("explains selected, reviewed, duplicate, weak-context and blocked sources", () => {
  const documents = [
    document({
      id: "selected",
      content_origin: "fulltext",
      evidence_chain_id: "chain-1",
    }),
    document({ id: "reviewed", last_outcome: "reviewed" }),
    document({
      id: "duplicate",
      last_outcome: "deferred",
      cluster_relation: "duplicate",
      duplicate_of_document_id: "selected",
    }),
    document({
      id: "context",
      last_outcome: "deferred",
      focus_tier: "context",
      ranking_reasons: ["deferred:context_threshold"],
    }),
    document({
      id: "blocked",
      last_outcome: "blocked",
      safety_flags: ["prompt_injection"],
    }),
  ];

  const explanation = buildScanExplanation(documents);

  assert.deepEqual(explanation.outcomeCounts, {
    selected: 1,
    reviewed: 1,
    deferred: 2,
    blocked: 1,
    discovered: 0,
  });
  assert.equal(explanation.publisherCount, 1);
  assert.equal(explanation.evidenceChainCount, 1);
  assert.equal(
    sourceDecisionReason(documents[1]),
    "已进入证据复核，用于交叉验证但未单独形成情报",
  );
  assert.equal(
    sourceDecisionReason(documents[2]),
    "与已收录报道重复，已合并到同一事件",
  );
  assert.equal(
    sourceDecisionReason(documents[3]),
    "属于周边背景，但来源可靠性或直接关联不足",
  );
  assert.equal(
    sourceDecisionReason(documents[4]),
    "内容触发安全检查，不能进入事实整理",
  );
});

test("keeps source diagnostics and evidence boundaries visible in the UI", async () => {
  const coverage = await readFile(
    new URL(
      "../../client/app/components/ScanCoveragePanel.tsx",
      import.meta.url,
    ),
    "utf8",
  );
  const sources = await readFile(
    new URL(
      "../../client/app/components/CustomSourcesDialog.tsx",
      import.meta.url,
    ),
    "utf8",
  );

  const summary = coverage.match(/<summary>([\s\S]*?)<\/summary>/)?.[1] ?? "";
  assert.match(summary, /最近扫描/);
  assert.match(summary, /查看筛选与来源覆盖/);
  assert.match(coverage, /AI 检索累计发现/);
  assert.ok(
    sources.includes("连续 ${item.consecutive_failures} 次失败"),
    "source health should explain consecutive failures",
  );
  assert.match(sources, /完整正文/);
});
