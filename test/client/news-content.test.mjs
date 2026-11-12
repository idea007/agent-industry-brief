import assert from "node:assert/strict";
import test from "node:test";

import {
  hasSubstantiveNewsContent,
  resolveNewsContent,
  selectOriginalArticleSource,
} from "../../client/app/news-content.ts";

function source(overrides = {}) {
  return {
    source_id: "source_short",
    title: "小鹏人形机器人 IRON 量产在即，门店店员明年上岗",
    url: "https://news.example.com/iron",
    publisher: "聚合媒体",
    source_type: "aggregator",
    published_at: "2026-07-26T10:00:00+08:00",
    content: "小鹏人形机器人 IRON 量产在即，门店店员明年上岗",
    category: "news",
    content_origin: "feed",
    word_count: 24,
    reliability: 0.72,
    ...overrides,
  };
}

function event(sources) {
  return {
    id: "intel_iron",
    story_id: "story_iron",
    run_id: "run_iron",
    subscription_id: "sub_robot",
    title: "小鹏 IRON 人形机器人开启试生产",
    summary:
      "小鹏汽车旗下人形机器人 IRON 已进入广州工厂小批量试生产阶段，计划在 2027 年进入门店。",
    category: "news",
    tags: ["机器人"],
    event_time: "2026-07-26T10:00:00+08:00",
    importance_score: 8.5,
    importance_reason: "人形机器人从研发走向规模化生产。",
    confidence_level: "high",
    confidence_score: 0.86,
    confidence_reason: "多家媒体报道。",
    verification_status: "confirmed",
    facts: [
      {
        text: "小鹏 IRON 已在广州工厂开启小批量试生产。",
        source_ids: ["source_short"],
      },
      {
        text: "量产目标指向 2026 年底，门店应用计划在 2027 年推进。",
        source_ids: ["source_short"],
      },
    ],
    inferences: [],
    source_ids: sources.map((item) => item.source_id),
    sources,
  };
}

test("does not present a feed title as complete news content", () => {
  const shortSource = source();
  const item = event([
    shortSource,
    source({
      source_id: "source_second",
      publisher: "行业媒体",
      url: "https://industry.example.com/iron",
    }),
  ]);

  assert.equal(hasSubstantiveNewsContent(shortSource), false);
  const content = resolveNewsContent(item, shortSource);
  assert.equal(content.mode, "digest");
  assert.equal(content.source, null);
  assert.match(content.body, /已确认信息/);
  assert.match(content.body, /2 篇报道，来自 2 家媒体/);
  assert.ok(content.body.length > shortSource.content.length * 2);
});

test("prefers an extracted article over a short primary feed source", () => {
  const shortSource = source({
    source_id: "source_official",
    publisher: "官方动态",
    source_type: "official",
  });
  const fulltextSource = source({
    source_id: "source_fulltext",
    publisher: "原始媒体",
    source_type: "industry",
    content_origin: "fulltext",
    content:
      "小鹏汽车介绍了 IRON 人形机器人的试生产进度。" +
      "该机器人正在广州工厂进行小批量生产验证，现场流程覆盖装配、测试与质量检查。" +
      "报道同时说明了后续量产目标、门店应用计划以及产品在人机交互方面的定位。" +
      "这些信息显示项目已从研发验证进入生产准备阶段。",
    word_count: 180,
  });
  const item = event([shortSource, fulltextSource]);

  const content = resolveNewsContent(item, shortSource);
  assert.equal(content.mode, "fulltext");
  assert.equal(content.source?.source_id, "source_fulltext");
  assert.match(content.body, /生产准备阶段/);
});

test("selects only an extracted original body and never the AI translation", () => {
  const shortSource = source();
  const fulltextSource = source({
    source_id: "source_original",
    publisher: "原始媒体",
    content_origin: "fulltext",
    content: "This is the untouched original article body from the publisher.",
    translated_content: "这是 AI 生成的中文译文，不应出现在原始正文区域。",
    word_count: 120,
  });

  assert.equal(
    selectOriginalArticleSource([shortSource], shortSource),
    null,
  );
  const selected = selectOriginalArticleSource(
    [shortSource, fulltextSource],
    shortSource,
  );
  assert.equal(selected?.source_id, "source_original");
  assert.equal(
    selected?.content,
    "This is the untouched original article body from the publisher.",
  );
});

test("accepts a substantive raw feed body without treating a short feed summary as full text", () => {
  const shortSource = source();
  const completeFeedSource = source({
    source_id: "source_complete_feed",
    publisher: "社区原帖",
    content_origin: "feed",
    content: "这是来源直接保存的完整原帖正文。".repeat(24),
    word_count: 180,
  });

  assert.equal(selectOriginalArticleSource([shortSource], shortSource), null);
  assert.equal(
    selectOriginalArticleSource([shortSource, completeFeedSource], shortSource)
      ?.source_id,
    "source_complete_feed",
  );
});
