import assert from "node:assert/strict";
import test from "node:test";

import {
  articleCategoryKey,
  categoryKey,
  displaySourceSearchTemplate,
  expandNewsArticles,
  sortNewsArticlesNewestFirst,
  storySourceInsight,
} from "../../client/app/radar-types.ts";

test("renders every source-search placeholder as user-facing text", () => {
  assert.equal(
    displaySourceSearchTemplate(
      "{focus} {related} 官方 OR 公司 OR 高管 OR 财报",
    ),
    "〔当前关注〕 〔一级关系〕 官方 OR 公司 OR 高管 OR 财报",
  );
  assert.doesNotMatch(
    displaySourceSearchTemplate("{query} {industry}"),
    /\{[^}]+\}/,
  );
});

test("maps the stable server taxonomy to the six visible categories", () => {
  assert.equal(categoryKey("news"), "新闻");
  assert.equal(categoryKey("content"), "内容");
  assert.equal(categoryKey("funding"), "融资");
  assert.equal(categoryKey("technology"), "技术");
  assert.equal(categoryKey("event"), "活动");
  assert.equal(categoryKey("interview"), "访谈");
});

test("uses the story event category for a multi-source card", () => {
  const article = {
    event: { category: "event" },
    source: { category: "interview" },
  };

  assert.equal(articleCategoryKey(article), "活动");
});

test("keeps compatibility with legacy model category values", () => {
  assert.equal(categoryKey("sdk_release"), "技术");
  assert.equal(categoryKey("conference"), "活动");
  assert.equal(categoryKey("podcast"), "访谈");
});

test("sorts cards by source publish time from newest to oldest", () => {
  const articles = [
    {
      id: "event-fallback",
      event: {
        event_time: "2026-07-24T08:00:00Z",
      },
      source: null,
    },
    {
      id: "newest-source",
      event: {
        event_time: "2026-07-20T08:00:00Z",
      },
      source: {
        published_at: "2026-07-26T08:00:00Z",
      },
    },
    {
      id: "oldest-source",
      event: {
        event_time: "2026-07-26T08:00:00Z",
      },
      source: {
        published_at: "2026-07-22T08:00:00Z",
      },
    },
  ];

  assert.deepEqual(
    sortNewsArticlesNewestFirst(articles).map((article) => article.id),
    ["newest-source", "event-fallback", "oldest-source"],
  );
  assert.deepEqual(
    articles.map((article) => article.id),
    ["event-fallback", "newest-source", "oldest-source"],
  );
});

function source(sourceId, publisher, publishedAt, title = `${publisher}报道`) {
  return {
    source_id: sourceId,
    title,
    url: `https://example.com/${sourceId}`,
    publisher,
    source_type: "aggregator",
    published_at: publishedAt,
    content: title,
    category: "news",
  };
}

function event(id, storyId, publishedAt, sources) {
  return {
    id,
    story_id: storyId,
    run_id: `run-${id}`,
    subscription_id: "robot",
    title: "小鹏 IRON 人形机器人开启试生产",
    summary: "小鹏 IRON 人形机器人进入试生产阶段。",
    category: "news",
    tags: ["小鹏", "IRON", "人形机器人"],
    event_time: publishedAt,
    importance_score: 8.5,
    importance_reason: "机器人进入量产准备阶段。",
    confidence_level: "medium",
    confidence_score: 0.8,
    confidence_reason: "多家媒体报道。",
    verification_status: "partially_confirmed",
    facts: [],
    inferences: [],
    source_ids: sources.map((item) => item.source_id),
    sources,
  };
}

test("renders one story card and merges reports collected across runs", () => {
  const articles = expandNewsArticles([
    event("second", "story-iron", "2026-07-26T08:00:00Z", [
      source("bjnews", "新京报", "2026-07-26T08:00:00Z"),
    ]),
    event("first", "story-iron", "2026-07-26T07:00:00Z", [
      source("sina", "手机新浪网", "2026-07-26T07:00:00Z"),
    ]),
  ]);

  assert.equal(articles.length, 1);
  assert.equal(articles[0].id, "story-iron");
  assert.equal(articles[0].story_event_count, 2);
  assert.deepEqual(
    articles[0].story_events.map((item) => item.id),
    ["first", "second"],
  );
  assert.equal(articles[0].event.sources.length, 2);
  assert.deepEqual(
    new Set(articles[0].event.sources.map((item) => item.publisher)),
    new Set(["手机新浪网", "新京报"]),
  );
});

test("reports source coverage and keeps title attribution as a clue", () => {
  const item = event("iron", "story-iron", "2026-07-26T08:00:00Z", [
    source(
      "sina-cnmo",
      "手机新浪网",
      "2026-07-26T08:00:00Z",
      "小鹏 IRON 开启试生产 - CNMO 科技 - 手机新浪网",
    ),
    source("bjnews", "新京报", "2026-07-26T07:00:00Z"),
  ]);

  const insight = storySourceInsight(item);

  assert.equal(insight.sourceCount, 2);
  assert.equal(insight.publisherCount, 2);
  assert.equal(insight.earliestSource.publisher, "新京报");
  assert.equal(insight.officialSource, null);
  assert.equal(insight.attributionHints[0].publisher, "CNMO 科技");
});
