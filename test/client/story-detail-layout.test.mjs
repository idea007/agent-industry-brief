import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const componentUrl = new URL(
  "../../client/app/components/IntelDetailDialog.tsx",
  import.meta.url,
);

test("keeps the story detail sections in the action-first order", async () => {
  const source = await readFile(componentUrl, "utf8");
  const hero = source.indexOf('className="story-hub-hero"');
  const judgement = source.indexOf('className="story-ai-judgement"');
  const workspace = source.indexOf('className="story-content-workspace"');
  const relatedReports = source.indexOf(
    'className="markdown-news-document story-related-reports"',
  );
  const feedback = source.indexOf('className="detail-feedback"');

  assert.ok(hero >= 0, "missing action-first hero");
  assert.ok(hero < judgement, "AI judgement must follow the hero");
  assert.ok(judgement < workspace, "content tabs must follow AI judgement");
  assert.ok(workspace < relatedReports, "related reports must stay below content tabs");
  assert.ok(relatedReports < feedback, "feedback must stay below related reports");
});

test("keeps the summary and adds untouched source fulltext directly below it", async () => {
  const source = await readFile(componentUrl, "utf8");
  const summary = source.indexOf("<p>{item.summary}</p>");
  const original = source.indexOf('className="story-original-copy"');
  const timeline = source.indexOf(
    "storyContextTimeline && storyContextTimeline.items.length > 1",
  );

  assert.ok(summary >= 0, "missing the existing story summary");
  assert.ok(summary < original, "original source body must follow the summary");
  assert.ok(original < timeline, "original source body must remain in the hero");
  assert.match(source, /\{originalArticleSource\.content\}/);
  assert.doesNotMatch(
    source.slice(original, timeline),
    /translated_content|ReactMarkdown/,
  );
});

test("shows only real multi-event timelines and exposes five content tabs", async () => {
  const source = await readFile(componentUrl, "utf8");

  assert.match(source, /const showTimeline = article\.story_event_count > 1/);
  assert.match(source, /: showTimeline \? \(/);
  assert.match(source, /orderedTimeline\.slice\(0, 3\)/);
  assert.match(source, /展开全部 \$\{orderedTimeline\.length\} 条进展/);
  assert.match(
    source,
    /\["content", "事件内容"\][\s\S]*\["importance", "为什么值得关注"\][\s\S]*\["facts", "关键事实"\][\s\S]*\["assessment", "判断依据"\][\s\S]*\["sources", "来源追溯"\]/,
  );
  assert.match(
    source,
    /<h2 id="story-ai-judgement-title">AI 判断<\/h2>[\s\S]*className="story-ai-conclusion-copy"/,
  );
  assert.doesNotMatch(source, /className="story-ai-conclusions"/);
  assert.doesNotMatch(source, /<span>判断结论<\/span>/);
  assert.match(source, /story-content-panel story-assessment-evidence/);
  assert.match(source, /role="tablist"/);
  assert.match(source, /event\.key !== "ArrowLeft"/);
  assert.match(source, /event\.key !== "ArrowRight"/);
});

test("places the evidence boundary directly before the event information", async () => {
  const source = await readFile(componentUrl, "utf8");
  const original = source.indexOf('className="story-original-copy"');
  const boundary = source.indexOf("story-evidence-boundary");
  const deepDive = source.indexOf('className="story-deep-dive"');
  const judgement = source.indexOf('className="story-ai-judgement"');
  const workspace = source.indexOf('className="story-content-workspace"');

  assert.ok(original >= 0, "missing the original source snapshot");
  assert.ok(deepDive > original, "deep dive must follow the source snapshot");
  assert.ok(boundary > judgement, "evidence boundary must follow AI judgement");
  assert.ok(workspace > boundary, "event information must follow the evidence boundary");
  assert.match(source, /本条信息的证据边界/);
  assert.match(source, /当前可以确认到什么程度/);
  assert.match(source, /深挖并补齐证据/);
  assert.match(source, /已确认事实、背景脉络、来源观点与待确认问题/);
});
