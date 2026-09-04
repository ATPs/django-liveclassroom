import * as React from "react";
import { useEffect, useRef } from "react";
import { mountFileActivity } from "../file_renderer.js";
import { useLocale } from "../i18n.js";
import { apiEndpoint, type ActivityState, type Audience, type SessionState } from "../protocol.js";
import { markdownToHtml } from "./MarkdownView.js";

function renderMarkdown(markdown: string): HTMLElement {
  const element = document.createElement("div");
  element.className = "lc-markdown-body";
  element.innerHTML = markdownToHtml(markdown);
  return element;
}

function presentationKey(audience: Audience, state: SessionState | null): string {
  const channel = audience === "student" ? "participants" : "display";
  const presentation = state?.channels?.[channel]?.presentation;
  return `${presentation?.page ?? 1}:${presentation?.navigation_mode ?? "follow"}`;
}

/** Bridge the established protected-file renderer into the React activity surfaces. */
export function FileActivity({
  activity,
  audience,
  state,
  stateUrl,
}: {
  activity: ActivityState;
  audience: Audience;
  state: SessionState | null;
  stateUrl: string | null;
}) {
  const host = useRef<HTMLDivElement>(null);
  const locale = useLocale();
  const content = activity.definition.content as Record<string, unknown> | undefined;
  const asset = content?.asset as Record<string, unknown> | undefined;
  const contentUrl = typeof asset?.content_url === "string" ? asset.content_url : "";
  const presentation = presentationKey(audience, state);

  useEffect(() => {
    const container = host.current;
    if (!container) return undefined;
    container.replaceChildren();
    const dispose = mountFileActivity({
      parent: container,
      activity,
      audience,
      state: state ?? undefined,
      stateUrl: stateUrl ?? undefined,
      locale,
      renderMarkdown,
      presentationEndpoint: audience === "teacher" && stateUrl ? apiEndpoint(stateUrl, "sessions/presentation") : undefined,
    });
    return () => {
      dispose();
      container.replaceChildren();
    };
  }, [activity.id, activity.revision, audience, contentUrl, locale, presentation, stateUrl]);

  return <div ref={host} />;
}
