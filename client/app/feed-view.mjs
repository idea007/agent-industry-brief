const GENERIC_TAGS = new Set([
  "新闻",
  "动态",
  "行业",
  "技术",
  "产品",
  "公司",
  "人物",
  "事件",
  "活动",
]);

export function preferenceTargets(tags = []) {
  return [...new Set(tags)]
    .filter((tag) => tag && !GENERIC_TAGS.has(tag))
    .slice(0, 2);
}

export function groupArticlesByRun(articles, run) {
  if (!run || run.status !== "completed") {
    return {
      hasSnapshot: false,
      changes: [],
      history: [...articles],
      newCount: 0,
      progressCount: 0,
    };
  }

  const itemIds = new Set(
    Array.isArray(run.result?.item_ids) ? run.result.item_ids : [],
  );
  const belongsToRun = (event) =>
    itemIds.size ? itemIds.has(event.id) : event.run_id === run.id;
  const changes = [];
  const history = [];

  for (const article of articles) {
    const storyEvents = article.story_events?.length
      ? article.story_events
      : [article.event];
    const runEvents = storyEvents.filter(belongsToRun);
    if (!runEvents.length) {
      history.push(article);
      continue;
    }
    const hasEarlierEvent = storyEvents.some((event) => !belongsToRun(event));
    /** @type {"progress" | "new"} */
    const kind = hasEarlierEvent ? "progress" : "new";
    changes.push({ article, kind });
  }

  return {
    hasSnapshot: true,
    changes,
    history,
    newCount: changes.filter((item) => item.kind === "new").length,
    progressCount: changes.filter((item) => item.kind === "progress").length,
  };
}
