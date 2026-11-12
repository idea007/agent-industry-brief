import assert from "node:assert/strict";
import { once } from "node:events";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";

const clientDir = new URL("../../client/", import.meta.url);
const require = createRequire(new URL("package.json", clientDir));
const next = require("next");

let app;
let server;

before(async () => {
  app = next({ dir: fileURLToPath(clientDir), dev: false });
  await app.prepare();
  server = createServer(app.getRequestHandler());
  const listening = once(server, "listening");
  server.listen(0, "127.0.0.1");
  await listening;
});

after(async () => {
  if (server?.listening) {
    const closed = once(server, "close");
    server.close();
    await closed;
  }
  await app?.close();
});

function render() {
  return fetch(`http://127.0.0.1:${server.address().port}/`, {
    headers: { accept: "text/html" },
  });
}

test("server-renders the industry news brief product", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>Industry Brief｜行业新闻简报<\/title>/i);
  assert.match(html, /行业新闻简报/);
  assert.match(html, /运行信息/);
  assert.match(html, /更换关注/);
  assert.match(html, /立即扫描/);
  assert.match(
    html,
    /name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"/,
  );
  assert.match(html, /og\.png/);
  assert.doesNotMatch(html, /codex-preview|react-loading-skeleton/i);
});

test("renders an honest empty state and accessible controls", async () => {
  const response = await render();
  const html = await response.text();
  assert.match(html, /AI Agent/);
  assert.match(html, /机器人/);
  assert.doesNotMatch(html, /游戏研发观察/);
  assert.match(html, /来源策略/);
  assert.match(html, /补充当前关注的来源/);
  assert.match(html, /data-testid="run-radar"/);
  assert.match(html, /class="result-summary"/);
  assert.match(html, /正在更新内容/);
  assert.doesNotMatch(html, /aria-label="情报分类"|class="category-tabs"/);
  assert.match(html, /aria-label="管理关注"/);
  assert.match(
    html,
    /aria-pressed="true"[^>]*title="查看 AI Agent 动态并设为扫描目标"/,
  );
  assert.doesNotMatch(html, /data-testid="ai-assessment-card"/);
  assert.match(html, /正在连接情报服务/);
  assert.doesNotMatch(html, /（演示）|example\.test/);
  assert.doesNotMatch(html, /class="intel-card-button"/);
});
