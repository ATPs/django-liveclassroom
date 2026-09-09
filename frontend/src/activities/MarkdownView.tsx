import * as React from "react";
import { useEffect, useMemo, useState } from "react";
import { escapeHtml } from "./activityData.js";

export type MarkdownFragmentField =
  | "prompt"
  | "explanation"
  | "feedback_correct"
  | "feedback_incorrect";

export type MarkdownFragmentContext = {
  url: string;
  revisionKey?: string;
};

type FragmentPayload = {
  html?: unknown;
  revision_key?: unknown;
};

/** Read only server-issued fragment URLs from an activity payload. */
export function markdownFragmentFor(value: unknown, field: MarkdownFragmentField): MarkdownFragmentContext | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return null;
  const root = value as Record<string, unknown>;
  const definition = root.definition && typeof root.definition === "object" && !Array.isArray(root.definition)
    ? root.definition as Record<string, unknown>
    : root;
  const content = definition.content && typeof definition.content === "object" && !Array.isArray(definition.content)
    ? definition.content as Record<string, unknown>
    : {};
  for (const source of [root, definition, content]) {
    const urls = source.fragment_urls ?? source.fragmentUrls ?? source.fragments;
    if (urls === null || typeof urls !== "object" || Array.isArray(urls)) continue;
    const raw = (urls as Record<string, unknown>)[field];
    if (typeof raw === "string") return { url: raw };
    if (raw !== null && typeof raw === "object" && !Array.isArray(raw)) {
      const item = raw as Record<string, unknown>;
      if (typeof item.url === "string") {
        return {
          url: item.url,
          revisionKey: typeof item.revision_key === "string"
            ? item.revision_key
            : typeof item.revisionKey === "string" ? item.revisionKey : undefined,
        };
      }
    }
  }
  return null;
}

function sameOriginUrl(raw: string): string | null {
  try {
    const parsed = new URL(raw, window.location.href);
    if (parsed.origin !== window.location.origin || parsed.username || parsed.password) return null;
    return parsed.toString();
  } catch {
    return null;
  }
}

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

export function MarkdownView({
  markdown,
  fragment,
}: {
  markdown: string;
  fragment?: MarkdownFragmentContext | null;
}) {
  const fragmentUrl = useMemo(() => fragment?.url ? sameOriginUrl(fragment.url) : null, [fragment?.url]);
  const [remoteHtml, setRemoteHtml] = useState<string | null>(null);

  useEffect(() => {
    setRemoteHtml(null);
    if (!fragmentUrl) return undefined;
    const controller = new AbortController();
    let current = true;
    void fetch(fragmentUrl, { credentials: "same-origin", signal: controller.signal })
      .then(async (response) => {
        const payload = await response.json().catch(() => ({})) as FragmentPayload;
        if (!response.ok || typeof payload.html !== "string") throw new Error("Fragment unavailable");
        if (fragment?.revisionKey && payload.revision_key !== fragment.revisionKey) {
          throw new Error("Stale fragment");
        }
        return payload.html;
      })
      .then((html) => {
        if (current) setRemoteHtml(html);
      })
      .catch(() => {
        // VaultPub is optional. The existing safe renderer remains visible when
        // an optional request is denied, stale, or temporarily unavailable.
      });
    return () => {
      current = false;
      controller.abort();
    };
  }, [fragment?.revisionKey, fragmentUrl]);

  return (
    <div
      className={`lc-markdown-body${remoteHtml !== null ? " lc-markdown-vaultpub" : ""}`}
      data-markdown-renderer={remoteHtml !== null ? "vaultpub" : "fallback"}
      dangerouslySetInnerHTML={{ __html: remoteHtml ?? markdownToHtml(markdown) }}
    />
  );
}
