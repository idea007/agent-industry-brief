import assert from "node:assert/strict";
import test from "node:test";
import { normalizeMixedTextSpacing } from "../../client/app/mixed-text-spacing.mjs";

test("adds spaces between Han text and Latin letters or numbers", () => {
  assert.equal(
    normalizeMixedTextSpacing("OpenAI发布了2个AI Agent功能"),
    "OpenAI 发布了 2 个 AI Agent 功能",
  );
  assert.equal(
    normalizeMixedTextSpacing("第3次扫描收录15条RSS新闻"),
    "第 3 次扫描收录 15 条 RSS 新闻",
  );
});

test("keeps already-spaced text and technical tokens stable", () => {
  assert.equal(
    normalizeMixedTextSpacing("UniVRM v0.131.0 版本"),
    "UniVRM v0.131.0 版本",
  );
  assert.equal(
    normalizeMixedTextSpacing("AI 摘要 · RSS 来源"),
    "AI 摘要 · RSS 来源",
  );
});
