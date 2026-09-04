import * as React from "react";
import { escapeHtml } from "./activityData.js";

function formatInline(escaped: string): string {
  return escaped
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/__([^_]+)__/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/_([^_]+)_/g, "<em>$1</em>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
}

/** Port of the legacy line-by-line markdown renderer, producing the same HTML. */
export function markdownToHtml(markdown: string): string {
  const lines = markdown.split("\n");
  let out = "";
  let inCodeBlock = false;
  let codeBuffer: string[] = [];
  let listOpen = false;
  let listType = "";
  let blockquoteOpen = false;

  const flushList = (): void => {
    if (listOpen) {
      out += `</${listType}>`;
      listOpen = false;
      listType = "";
    }
  };
  const flushBlockquote = (): void => {
    if (blockquoteOpen) {
      out += "</blockquote>";
      blockquoteOpen = false;
    }
  };
  const flushCode = (): void => {
    out += `<pre><code>${escapeHtml(codeBuffer.join("\n"))}</code></pre>`;
    codeBuffer = [];
    inCodeBlock = false;
  };

  for (const line of lines) {
    const trimmed = line.trim();

    if (trimmed.startsWith("```")) {
      flushList();
      flushBlockquote();
      if (inCodeBlock) {
        flushCode();
      } else {
        inCodeBlock = true;
        codeBuffer = [];
      }
      continue;
    }

    if (inCodeBlock) {
      codeBuffer.push(line);
      continue;
    }

    if (!trimmed) {
      flushList();
      flushBlockquote();
      continue;
    }

    const heading = trimmed.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      flushList();
      flushBlockquote();
      const level = Math.min(heading[1].length, 6);
      out += `<h${level}>${formatInline(escapeHtml(heading[2]))}</h${level}>`;
      continue;
    }

    if (trimmed.startsWith(">")) {
      flushList();
      const quoteText = trimmed.replace(/^>\s*/, "");
      if (!blockquoteOpen) {
        out += "<blockquote>";
        blockquoteOpen = true;
      }
      out += `<p>${formatInline(escapeHtml(quoteText))}</p>`;
      continue;
    }
    flushBlockquote();

    const ul = trimmed.match(/^[-*+]\s+(.*)$/);
    if (ul) {
      if (listType !== "ul") {
        flushList();
        out += "<ul>";
        listOpen = true;
        listType = "ul";
      }
      out += `<li>${formatInline(escapeHtml(ul[1]))}</li>`;
      continue;
    }

    const ol = trimmed.match(/^\d+\.\s+(.*)$/);
    if (ol) {
      if (listType !== "ol") {
        flushList();
        out += "<ol>";
        listOpen = true;
        listType = "ol";
      }
      out += `<li>${formatInline(escapeHtml(ol[1]))}</li>`;
      continue;
    }

    flushList();
    out += `<p>${formatInline(escapeHtml(trimmed))}</p>`;
  }

  flushList();
  flushBlockquote();
  if (inCodeBlock && codeBuffer.length) flushCode();
  return out;
}

export function MarkdownView({ markdown }: { markdown: string }) {
  return <div className="lc-markdown-body" dangerouslySetInnerHTML={{ __html: markdownToHtml(markdown) }} />;
}
