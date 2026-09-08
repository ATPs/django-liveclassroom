import * as React from "react";
import { useEffect, useRef, useState } from "react";
import { useLocale, useT } from "../i18n.js";
import { apiEndpoint, postJson, type ActivityState, type AggregateState, type Audience, type SessionState } from "../protocol.js";
import { activityContent, choicesFor, numberValue, stringValue } from "./activityData.js";

export function TimerDisplay({ activity, state = null }: { activity: ActivityState; state?: SessionState | null }) {
  const t = useT();
  const content = activityContent(activity);
  const duration = numberValue(content.duration_seconds) ?? numberValue(activity.definition.duration_seconds) ?? 60;
  const label = stringValue(content.label, stringValue(activity.definition.label, t("timer")));
  const runtime = activity.runtime;
  const timerKey = `timer_${activity.id}_${activity.revision}:${runtime?.deadline ?? ""}:${runtime?.status ?? "idle"}`;
  const serverOffset = useRef(0);
  const [remaining, setRemaining] = useState(duration);

  useEffect(() => {
    if (typeof state?.server_time === "number") serverOffset.current = Date.now() / 1000 - state.server_time;

    const tick = (): boolean => {
      let rem = Math.max(0, runtime?.remaining_seconds ?? duration);
      if (runtime?.status === "running" && typeof runtime.deadline === "number") {
        rem = Math.max(0, runtime.deadline - (Date.now() / 1000 - serverOffset.current));
      }
      setRemaining(rem);
      return rem > 0;
    };

    const keep = tick();
    let interval: number | undefined;
    if (runtime?.status === "running" && keep) {
      interval = window.setInterval(() => {
        if (!tick()) window.clearInterval(interval);
      }, 1000);
    }
    return () => {
      if (interval !== undefined) window.clearInterval(interval);
    };
  }, [timerKey, duration, runtime?.remaining_seconds, runtime?.status, state?.server_time]);

  const mm = String(Math.floor(remaining / 60)).padStart(2, "0");
  const ss = String(remaining % 60).padStart(2, "0");
  const ended = runtime?.status === "expired" || (runtime?.status === "running" && remaining <= 0);
  return (
    <div className="lc-timer-display">
      {label ? <div className="lc-timer-label">{label}</div> : null}
      <div className={ended ? "lc-timer-countdown lc-timer-ended" : "lc-timer-countdown"}>
        {ended ? "00:00" : `${mm}:${ss}`}
      </div>
      <div className={ended ? "lc-timer-subtext lc-timer-ended-text" : "lc-timer-subtext"}>
        {ended ? t("timerFinished") : runtime?.status === "idle" ? t("startTimer") : `${t("timerRemaining")} (${duration}${t("seconds")})`}
      </div>
    </div>
  );
}

type MediaViewProps = {
  activity: ActivityState;
  state?: SessionState | null;
  stateUrl?: string | null;
  audience?: Audience;
};

function VaultPubFrame({ activity, url, caption, state, stateUrl, audience }: MediaViewProps & { url: string; caption: string }) {
  const t = useT();
  const frame = useRef<HTMLIFrameElement>(null);
  const lastReported = useRef<number | null>(null);
  const ready = useRef(false);
  const slideCount = useRef<number | null>(null);
  const channel = audience === "student" ? "participants" : "display";
  const page = Math.max(1, Math.floor(state?.channels?.[channel]?.presentation?.page ?? 1));
  const canControl = audience === "teacher" && Boolean(stateUrl) && state?.session.status === "live";
  const sameOnParticipants = state?.channels?.display?.activity?.id === activity.id
    && state?.channels?.display?.activity?.revision_id === activity.revision_id
    && state?.channels?.participants?.activity?.id === activity.id
    && state?.channels?.participants?.activity?.revision_id === activity.revision_id;
  const postFrame = (command: "previous" | "next" | "go_to", index?: number) => {
    frame.current?.contentWindow?.postMessage(
      { protocol: "vaultpub.slide", version: 1, type: "command", command, ...(index === undefined ? {} : { index }) },
      window.location.origin,
    );
  };
  useEffect(() => {
    ready.current = false;
    slideCount.current = null;
  }, [url]);
  useEffect(() => {
    const index = Math.min(page - 1, Math.max(0, (slideCount.current ?? page) - 1));
    lastReported.current = index;
    if (ready.current) postFrame("go_to", index);
  }, [page, url]);
  const savePage = (index: number) => {
    if (!canControl || !stateUrl || index < 0) return;
    const channels = sameOnParticipants ? ["display", "participants"] : ["display"];
    void postJson(apiEndpoint(stateUrl, "sessions/presentation"), { channels, page: index + 1 }).catch(() => undefined);
  };

  useEffect(() => {
    const onMessage = (event: MessageEvent<unknown>) => {
      if (event.origin !== window.location.origin || event.source !== frame.current?.contentWindow) return;
      if (!event.data || typeof event.data !== "object" || Array.isArray(event.data)) return;
      const message = event.data as Record<string, unknown>;
      if (message.protocol !== "vaultpub.slide" || message.version !== 1) return;
      if (message.type === "ready") {
        const deck = message.deck;
        if (!deck || typeof deck !== "object" || Array.isArray(deck)) return;
        const count = Math.floor(Number((deck as Record<string, unknown>).slideCount));
        if (!Number.isFinite(count) || count < 1) return;
        ready.current = true;
        slideCount.current = count;
        postFrame("go_to", Math.min(page - 1, count - 1));
        return;
      }
      if (message.type !== "slide-changed" || !canControl || typeof message.index !== "number") return;
      const index = Math.floor(message.index);
      if (index < 0 || index >= (slideCount.current ?? 0) || lastReported.current === index || index === page - 1) return;
      lastReported.current = index;
      savePage(index);
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [page, canControl, stateUrl, sameOnParticipants]);

  return <div className="lc-vaultpub-frame" data-vaultpub-presentation>
    {canControl ? <div className="lc-actions lc-vaultpub-controls"><button type="button" aria-label="Previous slide" onClick={() => postFrame("previous")}>←</button><button type="button" aria-label="Next slide" onClick={() => postFrame("next")}>→</button><span>{page}</span></div> : null}
    <iframe
      ref={frame}
      src={url}
      sandbox="allow-scripts allow-same-origin"
      referrerPolicy="same-origin"
      loading="lazy"
      onLoad={() => {
        ready.current = false;
        slideCount.current = null;
        frame.current?.contentWindow?.postMessage(
          { protocol: "vaultpub.slide", version: 1, type: "handshake" },
          window.location.origin,
        );
      }}
      title={caption || t("vaultpubPresentation")}
    />
  </div>;
}

export function MediaView({ activity, state = null, stateUrl = null, audience = "student" }: MediaViewProps) {
  const t = useT();
  const content = activityContent(activity);
  const mediaDisabled = content.media_disabled === true || activity.definition.media_disabled === true;
  if (mediaDisabled) return <p>{t("mediaUnavailable")}</p>;
  const url = stringValue(content.url, stringValue(activity.definition.url));
  if (!url) return null;

  const rawMediaType = stringValue(content.media_type, stringValue(activity.definition.media_type)).toLowerCase();
  const caption = stringValue(content.caption, stringValue(activity.definition.caption));
  const cleanUrl = url.split("?")[0].toLowerCase();
  let mediaType = rawMediaType;
  if (!mediaType) {
    if (cleanUrl.match(/\.(png|jpe?g|svg|webp|gif)$/i)) mediaType = "image";
    else if (cleanUrl.match(/\.(mp4|webm)$/i)) mediaType = "video";
    else if (cleanUrl.match(/\.(mp3|ogg|wav)$/i)) mediaType = "audio";
    else mediaType = "iframe";
  }

  const isImage = mediaType === "image" || cleanUrl.match(/\.(png|jpe?g|svg|webp|gif)$/i);
  const isVideo = mediaType === "video" || cleanUrl.match(/\.(mp4|webm)$/i);
  const isAudio = mediaType === "audio" || cleanUrl.match(/\.(mp3|ogg|wav)$/i);
  const provider = stringValue(content.provider, stringValue(activity.definition.provider)).toLowerCase();

  if (provider === "vaultpub" && !isImage && !isVideo && !isAudio) {
    return <><VaultPubFrame activity={activity} url={url} caption={caption} state={state} stateUrl={stateUrl} audience={audience} />{caption ? <p className="lc-media-caption">{caption}</p> : null}</>;
  }

  return (
    <div className="lc-media-container">
      {isImage ? <img src={url} alt={caption || t("mediaImage")} /> : null}
      {isVideo ? <video src={url} controls /> : null}
      {isAudio ? <audio src={url} controls /> : null}
      {!isImage && !isVideo && !isAudio ? (
        <iframe
          src={url}
          sandbox={provider === "vaultpub" ? "allow-scripts allow-same-origin" : "allow-scripts"}
          referrerPolicy={provider === "vaultpub" ? "same-origin" : "no-referrer"}
          loading="lazy"
          title={caption || (provider === "vaultpub" ? t("vaultpubPresentation") : t("embeddedContent"))}
        />
      ) : null}
      {caption ? <p className="lc-media-caption">{caption}</p> : null}
    </div>
  );
}

function displayValue(value: unknown): string {
  if (Array.isArray(value)) return value.map(String).join(", ");
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

export function WordCloud({ aggregate, isTeacher = false }: { aggregate: AggregateState | null; isTeacher?: boolean }) {
  const t = useT();
  const raw = ((aggregate?.word_frequencies ?? aggregate?.words) ?? {}) as Record<string, number>;
  const entries = Object.entries(raw);
  if (!entries.length) return <p>{t("noResponses")}</p>;

  let minCount = Infinity;
  let maxCount = -Infinity;
  for (const [, count] of entries) {
    const num = Number(count) || 1;
    if (num < minCount) minCount = num;
    if (num > maxCount) maxCount = num;
  }
  if (!Number.isFinite(minCount)) minCount = 1;
  if (!Number.isFinite(maxCount)) maxCount = 1;

  const sorted = [...entries].sort((a, b) => (Number(b[1]) || 0) - (Number(a[1]) || 0) || a[0].localeCompare(b[0]));
  const rawAnswers = (aggregate?.raw_answers ?? aggregate?.values ?? []) as Array<unknown>;

  return (
    <div className="lc-word-cloud">
      <div className="lc-word-cloud-tags">
        {sorted.map(([word, countVal]) => {
          const count = Number(countVal) || 1;
          const fontSize = maxCount === minCount ? 18 : Math.round(14 + ((count - minCount) / (maxCount - minCount)) * (36 - 14));
          return (
            <span key={word} className="lc-word-tag" style={{ fontSize: `${fontSize}px` }} title={`${word}: ${count}`}>
              {word} ({count})
            </span>
          );
        })}
      </div>
      {isTeacher && rawAnswers.length > 0 ? (
        <div className="lc-word-cloud-moderation">
          <h4>
            {t("moderation")} ({rawAnswers.length})
          </h4>
          <ul className="lc-moderation-list">
            {rawAnswers.map((item, index) => (
              <li key={index}>{displayValue(item)}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

export function AggregateView({ aggregate, activity }: { aggregate: AggregateState | null; activity?: ActivityState }) {
  const t = useT();
  const locale = useLocale();
  if (!aggregate) return null;
  const count = aggregate.submission_count;
  const summary =
    typeof count === "number"
      ? `${count} ${locale === "zh-Hans" ? "人作答" : count === 1 ? "response" : "responses"}`
      : t("results");

  return (
    <>
      <p>{summary}</p>
      {aggregate.choices ? <ChoiceBars choices={aggregate.choices} activity={activity} /> : null}
      {aggregate.words || aggregate.word_frequencies ? <WordCloud aggregate={aggregate} /> : null}
      {aggregate.values?.length && !aggregate.words && !aggregate.word_frequencies ? (
        <ul>
          {aggregate.values.map((value, index) => (
            <li key={index}>{displayValue(value)}</li>
          ))}
        </ul>
      ) : null}
    </>
  );
}

export function ChoiceBars({ choices, activity }: { choices: Record<string, number>; activity?: ActivityState }) {
  const t = useT();
  const locale = useLocale();
  const entries = Object.entries(choices);
  let totalVotes = 0;
  for (const [, v] of entries) totalVotes += Number(v) || 0;
  const labels = new Map<string, string>(activity ? choicesFor(activity).map((option) => [option.id, option.text]) : []);

  return (
    <div className="lc-choice-bars">
      {entries.map(([choice, value]) => {
        const voteCount = Number(value) || 0;
        const pct = totalVotes > 0 ? Math.round((voteCount / totalVotes) * 100) : 0;
        return (
          <div key={choice} className="lc-choice-bar-row">
            <div className="lc-choice-bar-header">
              <strong>{labels.get(choice) ?? choice}</strong>
              <span>
                {pct}% ({voteCount} {voteCount === 1 ? t("vote") : t("votes")})
              </span>
            </div>
            <div className="lc-bar-container">
              <div className="lc-bar" style={{ width: `${pct}%` }} />
              <span className="lc-bar-text">
                {pct}% ({voteCount} {locale === "zh-Hans" ? "票" : "votes"})
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
