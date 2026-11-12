"use client";

import { useEffect } from "react";
import { normalizeMixedTextSpacing } from "../mixed-text-spacing.mjs";

const SKIP_SELECTOR = [
  "code",
  "pre",
  "kbd",
  "samp",
  "script",
  "style",
  "textarea",
  "input",
  "[data-no-mixed-spacing]",
].join(",");

function normalizeTextNode(node: Node) {
  if (
    node.nodeType !== Node.TEXT_NODE ||
    !node.parentElement ||
    node.parentElement.closest(SKIP_SELECTOR)
  ) {
    return;
  }
  const current = node.nodeValue ?? "";
  const normalized = normalizeMixedTextSpacing(current);
  if (normalized !== current) node.nodeValue = normalized;
}

function normalizeSubtree(root: Node) {
  if (root.nodeType === Node.TEXT_NODE) {
    normalizeTextNode(root);
    return;
  }
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let node = walker.nextNode();
  while (node) {
    normalizeTextNode(node);
    node = walker.nextNode();
  }
}

export default function MixedTextSpacing() {
  useEffect(() => {
    normalizeSubtree(document.body);
    const observer = new MutationObserver((records) => {
      for (const record of records) {
        if (record.type === "characterData") {
          normalizeTextNode(record.target);
          continue;
        }
        for (const node of record.addedNodes) normalizeSubtree(node);
      }
    });
    observer.observe(document.body, {
      childList: true,
      characterData: true,
      subtree: true,
    });
    return () => observer.disconnect();
  }, []);

  return null;
}
