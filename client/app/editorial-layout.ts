import {
  articleCategoryKey,
  type NewsArticle,
} from "./radar-types";

export type EditorialTemplateId =
  | "image-led"
  | "rail-led"
  | "modular-mosaic"
  | "feature-dashboard"
  | "three-rail";

export type EditorialContentType =
  | "technology"
  | "business"
  | "design"
  | "research"
  | "general";

export type EditorialSlot = {
  x: number;
  y: number;
  w: number;
  h: number;
};

export type EditorialShape = {
  id: string;
  kind: "circle" | "ring" | "bar" | "square" | "blob";
  x: number;
  y: number;
  w: number;
  h: number;
  rotation: number;
  tone: number;
};

export type EditorialLayoutPlan = {
  templateId: EditorialTemplateId;
  templateLabel: string;
  contentType: EditorialContentType;
  contentTypeLabel: string;
  rationale: string;
  visualMode: "source-image" | "generative-shapes";
  visualPrompt: string;
  density: "airy" | "balanced" | "dense";
  storyColumns: 2 | 3;
  score: number;
  seed: number;
  shapes: EditorialShape[];
  slots: {
    masthead: EditorialSlot;
    headline: EditorialSlot;
    visual: EditorialSlot;
    story: EditorialSlot;
    brief: EditorialSlot;
    facts: EditorialSlot;
    quote: EditorialSlot;
    source: EditorialSlot;
  };
};

type TemplateDefinition = {
  label: string;
  rationale: string;
  slots: EditorialLayoutPlan["slots"];
};

const TEMPLATE_LIBRARY: Record<EditorialTemplateId, TemplateDefinition> = {
  "image-led": {
    label: "Image-led Feature",
    rationale: "用大幅视觉建立第一层注意力，再以正文、事实和来源完成阅读闭环。",
    slots: {
      masthead: { x: 0, y: 0, w: 12, h: 3 },
      headline: { x: 0, y: 3, w: 5, h: 8 },
      visual: { x: 5, y: 3, w: 7, h: 8 },
      story: { x: 0, y: 11, w: 8, h: 8 },
      brief: { x: 8, y: 11, w: 4, h: 8 },
      facts: { x: 0, y: 19, w: 5, h: 5 },
      quote: { x: 5, y: 19, w: 4, h: 5 },
      source: { x: 9, y: 19, w: 3, h: 5 },
    },
  },
  "rail-led": {
    label: "Rail-led News",
    rationale: "用窄栏承载高密度元数据，让主报道与核验信息保持并行。",
    slots: {
      masthead: { x: 0, y: 0, w: 12, h: 3 },
      headline: { x: 0, y: 3, w: 7, h: 7 },
      visual: { x: 7, y: 3, w: 3, h: 7 },
      brief: { x: 10, y: 3, w: 2, h: 7 },
      story: { x: 0, y: 10, w: 7, h: 8 },
      facts: { x: 7, y: 10, w: 5, h: 8 },
      quote: { x: 0, y: 18, w: 5, h: 6 },
      source: { x: 5, y: 18, w: 7, h: 6 },
    },
  },
  "modular-mosaic": {
    label: "Modular Mosaic",
    rationale: "用等宽主稿和横向观点带拆解复杂技术信息，适合多层概念阅读。",
    slots: {
      masthead: { x: 0, y: 0, w: 12, h: 3 },
      headline: { x: 0, y: 3, w: 6, h: 6 },
      visual: { x: 6, y: 3, w: 6, h: 6 },
      quote: { x: 0, y: 9, w: 12, h: 3 },
      story: { x: 0, y: 12, w: 6, h: 12 },
      facts: { x: 6, y: 12, w: 3, h: 5 },
      brief: { x: 9, y: 12, w: 3, h: 5 },
      source: { x: 6, y: 17, w: 6, h: 7 },
    },
  },
  "feature-dashboard": {
    label: "Feature Dashboard",
    rationale: "把核心叙事、主视觉和关键指标并置，突出数据与商业信号。",
    slots: {
      masthead: { x: 0, y: 0, w: 12, h: 3 },
      headline: { x: 0, y: 3, w: 4, h: 8 },
      visual: { x: 4, y: 3, w: 4, h: 8 },
      brief: { x: 8, y: 3, w: 4, h: 8 },
      story: { x: 0, y: 11, w: 7, h: 8 },
      facts: { x: 7, y: 11, w: 5, h: 8 },
      quote: { x: 0, y: 19, w: 8, h: 5 },
      source: { x: 8, y: 19, w: 4, h: 5 },
    },
  },
  "three-rail": {
    label: "Three-rail Editorial",
    rationale: "以 6/4/2 的报纸式节奏组织长短信息，兼顾主稿、视觉和来源。",
    slots: {
      masthead: { x: 0, y: 0, w: 12, h: 3 },
      headline: { x: 0, y: 3, w: 6, h: 8 },
      visual: { x: 6, y: 3, w: 4, h: 8 },
      brief: { x: 10, y: 3, w: 2, h: 8 },
      story: { x: 0, y: 11, w: 6, h: 8 },
      facts: { x: 6, y: 11, w: 4, h: 8 },
      source: { x: 10, y: 11, w: 2, h: 13 },
      quote: { x: 0, y: 19, w: 10, h: 5 },
    },
  },
};

function hashText(value: string): number {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function createRandom(seed: number): () => number {
  let state = seed || 1;
  return () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 4294967296;
  };
}

function createShapes(seed: number, density: EditorialLayoutPlan["density"]) {
  const random = createRandom(seed);
  const shapeCount = density === "dense" ? 14 : density === "airy" ? 8 : 11;
  const kinds: EditorialShape["kind"][] = [
    "circle",
    "ring",
    "bar",
    "square",
    "blob",
  ];

  return Array.from({ length: shapeCount }, (_, index) => {
    const kind = kinds[Math.floor(random() * kinds.length)];
    const baseWidth = kind === "bar" ? 30 + random() * 34 : 12 + random() * 28;
    const baseHeight = kind === "bar" ? 3 + random() * 8 : 12 + random() * 30;
    return {
      id: `${seed}-${index}`,
      kind,
      x: Math.round(random() * 82),
      y: Math.round(random() * 82),
      w: Math.round(baseWidth),
      h: Math.round(baseHeight),
      rotation: Math.round(random() * 110 - 55),
      tone: Math.floor(random() * 4),
    };
  });
}

function classifyContent(article: NewsArticle): EditorialContentType {
  const combined = [
    article.event.category,
    article.event.title,
    article.event.summary,
    article.event.tags.join(" "),
    article.source?.content ?? "",
  ]
    .join(" ")
    .toLocaleLowerCase();

  if (
    /design|设计|视觉|品牌|创意|交互|ui|ux|live2d/.test(combined)
  ) {
    return "design";
  }
  if (
    /fund|融资|资本|商业|市场|营收|量产|company|business/.test(combined)
  ) {
    return "business";
  }
  if (
    /research|研究|评估|报告|论文|实验|benchmark|eval/.test(combined)
  ) {
    return "research";
  }
  if (
    /ai|agent|模型|sdk|代码|技术|工程|芯片|机器人|technology/.test(
      combined,
    )
  ) {
    return "technology";
  }
  return "general";
}

const CONTENT_TYPE_LABELS: Record<EditorialContentType, string> = {
  technology: "科技深读",
  business: "商业观察",
  design: "设计专题",
  research: "研究解读",
  general: "综合报道",
};

function templateCandidates(
  article: NewsArticle,
  contentType: EditorialContentType,
): EditorialTemplateId[] {
  const category = articleCategoryKey(article);

  if (contentType === "business" || category === "融资") {
    return ["feature-dashboard", "rail-led", "three-rail"];
  }
  if (contentType === "design") {
    return ["image-led", "modular-mosaic", "three-rail"];
  }
  if (contentType === "research") {
    return ["rail-led", "three-rail", "modular-mosaic"];
  }
  if (contentType === "technology") {
    return ["modular-mosaic", "image-led", "rail-led"];
  }
  return ["three-rail", "image-led", "feature-dashboard"];
}

export function createEditorialLayoutPlan(
  article: NewsArticle,
  revision = 0,
): EditorialLayoutPlan {
  const sourceText = article.source?.content ?? "";
  const contentLength =
    sourceText.length +
    article.event.summary.length +
    article.event.facts.reduce((total, fact) => total + fact.text.length, 0);
  const density =
    contentLength > 1600 ? "dense" : contentLength < 520 ? "airy" : "balanced";
  const contentType = classifyContent(article);
  const seed = hashText(
    [
      article.id,
      article.event.title,
      article.event.tags.join("|"),
      String(revision),
    ].join("::"),
  );
  const candidates = templateCandidates(article, contentType);
  const templateId = candidates[revision % candidates.length];
  const template = TEMPLATE_LIBRARY[templateId];
  const visualMode = article.source?.image_url
    ? "source-image"
    : "generative-shapes";
  const storyColumns = contentLength > 900 ? 3 : 2;
  const score = 82 + (seed % 14);

  return {
    templateId,
    templateLabel: template.label,
    contentType,
    contentTypeLabel: CONTENT_TYPE_LABELS[contentType],
    rationale: template.rationale,
    visualMode,
    visualPrompt: `${CONTENT_TYPE_LABELS[contentType]} · 主体偏右 · 为标题保留负空间`,
    density,
    storyColumns,
    score,
    seed,
    shapes: createShapes(seed, density),
    slots: template.slots,
  };
}
