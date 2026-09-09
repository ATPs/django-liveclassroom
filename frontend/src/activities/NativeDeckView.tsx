import * as React from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useT } from "../i18n.js";
import { apiEndpoint, getJson, postJson, type Audience, type DeckPresentationState, type SessionState } from "../protocol.js";
import { MarkdownView } from "./MarkdownView.js";

type DeckPayload = DeckPresentationState & {
  slides?: Array<{ key?: string; position?: number; markdown?: string }>;
};

/** Render an immutable deck slide from the authorized snapshot payload.
 *
 * The optional VaultPub Slide View remains available at ``slides_url`` for
 * host integrations. The package fallback is deliberately safe and keeps the
 * current position when that optional renderer is unavailable.
 */
export function NativeDeckView({
  deck,
  state,
  audience,
  stateUrl,
}: {
  deck: DeckPresentationState;
  state: SessionState | null;
  audience: Audience;
  stateUrl?: string;
}) {
  const t = useT();
  const [payload, setPayload] = useState<DeckPayload | null>(null);
  const [error, setError] = useState("");
  const [reviewIndex, setReviewIndex] = useState<number | null>(null);
  const [richUrl, setRichUrl] = useState<string | null>(null);
  const frame = useRef<HTMLIFrameElement>(null);
  const frameReady = useRef(false);
  const payloadUrl = useMemo(() => deck.payload_url ?? "", [deck.payload_url]);
  const channel = audience === "student" ? "participants" : "display";

  useEffect(() => {
    let active = true;
    setError("");
    setPayload(null);
    setReviewIndex(null);
    setRichUrl(null);
    frameReady.current = false;
    if (!payloadUrl) return undefined;
    const url = new URL(payloadUrl, window.location.href);
    url.searchParams.set("channel", channel);
    void getJson<DeckPayload>(url.toString())
      .then((next) => {
        if (active) setPayload(next);
      })
      .catch((reason) => {
        if (active) setError(reason instanceof Error ? reason.message : t("unavailable"));
      });
    return () => {
      active = false;
    };
  }, [channel, payloadUrl, t]);

  useEffect(() => {
    let active = true;
    const raw = deck.slides_url;
    if (!raw) return undefined;
    const url = new URL(raw, window.location.href);
    if (url.origin !== window.location.origin) return undefined;
    url.searchParams.set("channel", channel);
    url.searchParams.set("embed", "1");
    void fetch(url.toString(), { credentials: "same-origin", method: "GET" })
      .then((response) => {
        if (!response.ok || !response.headers.get("content-type")?.toLowerCase().includes("text/html")) return;
        if (active) setRichUrl(url.toString());
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [channel, deck.slides_url]);

  useEffect(() => {
    if (frameReady.current && frame.current?.contentWindow) {
      frame.current.contentWindow.postMessage(
        { protocol: "vaultpub.slide", version: 1, type: "command", command: "go_to", index: deck.slide_index },
        window.location.origin,
      );
    }
  }, [deck.slide_index, richUrl]);

  useEffect(() => {
    const onMessage = (event: MessageEvent<unknown>) => {
      if (!frame.current || event.origin !== window.location.origin || event.source !== frame.current.contentWindow) return;
      if (!event.data || typeof event.data !== "object" || Array.isArray(event.data)) return;
      const message = event.data as Record<string, unknown>;
      if (message.protocol !== "vaultpub.slide" || message.version !== 1) return;
      if (message.type === "ready") {
        frameReady.current = true;
        frame.current.contentWindow?.postMessage(
          { protocol: "vaultpub.slide", version: 1, type: "command", command: "go_to", index: deck.slide_index },
          window.location.origin,
        );
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [deck.slide_index, richUrl]);

  const slides = payload?.slides ?? [];
  const serverIndex = Math.max(0, Math.min(deck.slide_index, Math.max(0, slides.length - 1)));
  const index = reviewIndex === null ? serverIndex : Math.max(0, Math.min(reviewIndex, Math.max(0, slides.length - 1)));
  const slide = slides[index];
  const navigation = state?.channels?.[channel]?.presentation?.navigation_mode ?? "follow";
  const canReview = audience === "student" && deck.allow_review && navigation === "paged";

  if (error) return <p role="status">{error || t("unavailable")}</p>;
  if (!payload) return <p role="status">{t("loading")}</p>;
  return (
    <section className="lc-native-deck" data-deck-snapshot={deck.snapshot_id}>
      <header className="lc-native-deck-header">
        <h2>{payload.title}</h2>
        <span>{index + 1} / {slides.length || deck.slide_count}</span>
      </header>
      {richUrl ? <iframe className="lc-native-deck-frame" ref={frame} src={richUrl} sandbox="allow-scripts allow-same-origin" referrerPolicy="same-origin" title={payload.title} onLoad={() => {
        frameReady.current = false;
        frame.current?.contentWindow?.postMessage({ protocol: "vaultpub.slide", version: 1, type: "handshake" }, window.location.origin);
      }} /> : slide ? <MarkdownView markdown={typeof slide.markdown === "string" ? slide.markdown : ""} /> : <p>{t("unavailable")}</p>}
      {audience === "teacher" && stateUrl ? <nav className="lc-native-deck-controls" aria-label={t("filePresentationControls")}>
        <button type="button" disabled={deck.slide_index <= 0} onClick={() => void postJson(apiEndpoint(stateUrl, "sessions/presentation"), { channels: ["display"], deck_action: "previous", expected_revision: deck.revision }, `deck-prev-${deck.revision}-${crypto.randomUUID()}`)}>{t("filePreviousPage")}</button>
        <button type="button" disabled={deck.slide_index >= deck.slide_count - 1} onClick={() => void postJson(apiEndpoint(stateUrl, "sessions/presentation"), { channels: ["display"], deck_action: "next", expected_revision: deck.revision }, `deck-next-${deck.revision}-${crypto.randomUUID()}`)}>{t("fileNextPage")}</button>
      </nav> : null}
      {canReview ? (
        <nav className="lc-native-deck-review" aria-label={t("filePresentationControls")}>
          <button type="button" disabled={index <= 0} onClick={() => setReviewIndex(index - 1)}>{t("filePreviousPage")}</button>
          <button type="button" disabled={index >= slides.length - 1} onClick={() => setReviewIndex(index + 1)}>{t("fileNextPage")}</button>
        </nav>
      ) : null}
    </section>
  );
}
