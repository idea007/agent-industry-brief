import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  groupArticlesByRun,
  preferenceTargets,
} from "../../client/app/feed-view.mjs";

function article(id, storyEvents) {
  return {
    id,
    event: storyEvents.at(-1),
    story_events: storyEvents,
  };
}

test("groups a completed scan into new stories, progress, and history", () => {
  const articles = [
    article("new", [{ id: "event-new", run_id: "run-latest" }]),
    article("progress", [
      { id: "event-old", run_id: "run-old" },
      { id: "event-progress", run_id: "run-latest" },
    ]),
    article("history", [{ id: "event-history", run_id: "run-old" }]),
  ];
  const result = groupArticlesByRun(articles, {
    id: "run-latest",
    status: "completed",
    result: { item_ids: ["event-new", "event-progress"] },
  });

  assert.equal(result.hasSnapshot, true);
  assert.equal(result.newCount, 1);
  assert.equal(result.progressCount, 1);
  assert.deepEqual(
    result.changes.map((item) => [item.article.id, item.kind]),
    [
      ["new", "new"],
      ["progress", "progress"],
    ],
  );
  assert.deepEqual(result.history.map((item) => item.id), ["history"]);
});

test("does not pretend an unfinished run is a change snapshot", () => {
  const articles = [
    article("current", [{ id: "event-current", run_id: "run-current" }]),
  ];
  const result = groupArticlesByRun(articles, {
    id: "run-current",
    status: "running",
    result: null,
  });

  assert.equal(result.hasSnapshot, false);
  assert.deepEqual(result.changes, []);
  assert.deepEqual(result.history.map((item) => item.id), ["current"]);
});

test("uses specific story tags to explain preference feedback", () => {
  assert.deepEqual(
    preferenceTargets(["新闻", "小米 SU7", "雷军", "小米 SU7", "公司"]),
    ["小米 SU7", "雷军"],
  );
});

test("keeps the full feed and moves preference feedback into story detail", async () => {
  const [dashboard, card, detail, sources, timeline] = await Promise.all([
    readFile(
      new URL("../../client/app/RadarDashboard.tsx", import.meta.url),
      "utf8",
    ),
    readFile(
      new URL("../../client/app/components/IntelCard.tsx", import.meta.url),
      "utf8",
    ),
    readFile(
      new URL(
        "../../client/app/components/IntelDetailDialog.tsx",
        import.meta.url,
      ),
      "utf8",
    ),
    readFile(
      new URL(
        "../../client/app/components/CustomSourcesDialog.tsx",
        import.meta.url,
      ),
      "utf8",
    ),
    readFile(
      new URL(
        "../../client/app/components/FocusTimeline.tsx",
        import.meta.url,
      ),
      "utf8",
    ),
  ]);

  assert.match(dashboard, /baseArticles\.map\(\(article\) =>/);
  assert.doesNotMatch(dashboard, /变化优先/);
  assert.doesNotMatch(dashboard, /全部动态/);
  assert.doesNotMatch(dashboard, /feed-view-toolbar/);
  assert.doesNotMatch(dashboard, /\/api\/intel-feedback\?subscription_id=/);
  assert.doesNotMatch(card, /card-preference/);
  assert.doesNotMatch(card, /多看这类/);
  assert.match(detail, /调整后续动态/);
  assert.match(detail, /多看这类/);
  assert.match(detail, /少看这类/);
  assert.match(sources, /来源试用结果/);
  assert.match(sources, /确认加入来源/);
  assert.match(sources, /后续扫描会继续记录新增、入选、正文率与健康状态/);
  assert.match(timeline, /前情 · 已更新/);
  assert.match(timeline, /这不是最新状态/);
  assert.match(timeline, /查看后续事实/);
});
