import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import test from "node:test";

const PROJECT_URL = new URL("../../client/", import.meta.url);
const GENERATED_DIRECTORY =
  /(?:^|\/)(?:node_modules|dist|\.vinext|\.next|\.wrangler|coverage)(?:\/|$)/;
const STYLESHEET = /\.(?:css|scss|sass|less)$/i;
const UI_SOURCE = /\.(?:js|jsx|mjs|ts|tsx)$/i;
const SPATIAL_PROPERTY =
  /^(?:margin(?:-.+)?|padding(?:-.+)?|gap|row-gap|column-gap|width|min-width|max-width|height|min-height|max-height|(?:min-|max-)?(?:block|inline)-size|top|right|bottom|left|inset(?:-.+)?|border|border-(?:top|right|bottom|left|block(?:-start|-end)?|inline(?:-start|-end)?)(?:-width)?|border-.*-radius|border-radius|border-spacing|outline(?:-width|-offset)?|scroll-(?:margin|padding)(?:-.+)?|grid-template-(?:columns|rows)|grid-auto-(?:columns|rows)|flex-basis|transform|translate|transform-origin|text-indent|vertical-align|background-size|background-position|mask-size|mask-position|object-position|perspective|column-width|column-rule-width|shape-margin|stroke-width)$/;

function isSpatialVariable(property) {
  return (
    property.startsWith("--") &&
    !/(?:font|line|letter)/.test(property) &&
    /(?:space|spacing|gap|width|height|radius|inset|offset|size)/.test(property)
  );
}

function lineNumberAt(source, offset) {
  return source.slice(0, offset).split("\n").length;
}

async function projectFiles(pattern) {
  return (await readdir(PROJECT_URL, { recursive: true }))
    .filter((file) => !GENERATED_DIRECTORY.test(file) && pattern.test(file))
    .sort();
}

function stylesheetViolations(source, file) {
  const declaration =
    /(?:^|[;{}\n])\s*([\w-]+)\s*:\s*([^;{}]+);/g;
  const violations = [];

  for (const match of source.matchAll(declaration)) {
    const property = match[1];
    if (!SPATIAL_PROPERTY.test(property) && !isSpatialVariable(property)) {
      continue;
    }

    for (const valueMatch of match[2].matchAll(/(-?\d*\.?\d+)px\b/g)) {
      const value = Math.abs(Number(valueMatch[1]));
      if (value > 4 && value % 4 !== 0) {
        violations.push(
          `${file}:${lineNumberAt(source, match.index)}: ${property}: ${valueMatch[0]}`,
        );
      }
    }
  }

  return violations;
}

function inlineStyleViolations(source, file) {
  const violations = [];

  for (const styleMatch of source.matchAll(
    /style\s*=\s*\{\s*\{([\s\S]*?)\}\s*(?:as\s+CSSProperties)?\s*\}/g,
  )) {
    for (const valueMatch of styleMatch[1].matchAll(
      /([\w-]+)\s*:\s*(?:["'`])?(-?\d*\.?\d+)(px)?(?:["'`])?/g,
    )) {
      const property = valueMatch[1];
      if (!SPATIAL_PROPERTY.test(property) && !isSpatialVariable(property)) {
        continue;
      }
      const value = Math.abs(Number(valueMatch[2]));
      if (value > 4 && value % 4 !== 0) {
        violations.push(
          `${file}:${lineNumberAt(source, styleMatch.index)}: ${property}: ${valueMatch[2]}${valueMatch[3] ?? "px"}`,
        );
      }
    }
  }

  return violations;
}

test("keeps spatial values in every source stylesheet on the 4px grid", async () => {
  const violations = [];

  for (const file of await projectFiles(STYLESHEET)) {
    const source = await readFile(new URL(file, PROJECT_URL), "utf8");
    violations.push(...stylesheetViolations(source, file));
  }

  assert.deepEqual(
    violations,
    [],
    `Spatial values greater than 4px must use the 4px grid:\n${violations.join("\n")}`,
  );
});

test("keeps inline spatial styles across UI source on the 4px grid", async () => {
  const violations = [];

  for (const file of await projectFiles(UI_SOURCE)) {
    const source = await readFile(new URL(file, PROJECT_URL), "utf8");
    violations.push(...inlineStyleViolations(source, file));
  }

  assert.deepEqual(
    violations,
    [],
    `Inline spatial values greater than 4px must use the 4px grid:\n${violations.join("\n")}`,
  );
});

test("treats 1px–4px as exceptions and rejects larger off-grid values", () => {
  const css = `
    .valid {
      border: 3px solid;
      gap: 4px;
      width: 8px;
      font-size: 15px;
    }
    .invalid {
      border-top: 5px solid;
      gap: 6px;
      border-start-start-radius: 10px;
    }
  `;

  assert.deepEqual(stylesheetViolations(css, "fixture.css"), [
    "fixture.css:8: border-top: 5px",
    "fixture.css:9: gap: 6px",
    "fixture.css:10: border-start-start-radius: 10px",
  ]);
});
