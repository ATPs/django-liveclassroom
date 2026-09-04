import * as React from "react";
import { useEffect, useRef, useState } from "react";
import { useLocale, useT } from "../i18n.js";
import type { ActivityState, AggregateState } from "../protocol.js";
import { activityContent, numberValue, stringValue } from "./activityData.js";

const activeTimerStartTimes = new Map<string, number>();

export function TimerDisplay({ activity }: { activity: ActivityState }) {
  const t = useT();
  const content = activityContent(activity);
  const duration = numberValue(content.duration_seconds) ?? numberValue(activity.definition.duration_seconds) ?? 60;
  const label = stringValue(content.label, stringValue(activity.definition.label, t("timer")));
  const timerKey = `timer_${activity.id}_${activity.revision}`;
  const startRef = useRef<number>(0);
  const [remaining, setRemaining] = useState(duration);

  useEffect(() => {
    let startTime = activeTimerStartTimes.get(timerKey);
    if (!startTime) {
      startTime = Date.now();
      activeTimerStartTimes.set(timerKey, startTime);
    }
    startRef.current = startTime;

    const tick = (): boolean => {
      let rem = 0;
      if (activity.state === "open") {
        rem = Math.max(0, duration - Math.floor((Date.now() - startRef.current) / 1000));
      } else if (activity.state === "closed") {
        rem = 0;
      } else {
        rem = duration;
      }
      setRemaining(rem);
      return rem > 0;
    };

    const keep = tick();
    let interval: number | undefined;
    if (activity.state === "open" && keep) {
      interval = window.setInterval(() => {
        if (!tick()) window.clearInterval(interval);
      }, 1000);
    }
    return () => {
      if (interval !== undefined) window.clearInterval(interval);
    };
  }, [timerKey, duration, activity.state]);

  const mm = String(Math.floor(remaining / 60)).padStart(2, "0");
  const ss = String(remaining % 60).padStart(2, "0");
  const ended = remaining <= 0;
  return (
    <div className="lc-timer-display">
      {label ? <div className="lc-timer-label">{label}</div> : null}
      <div className={ended ? "lc-timer-countdown lc-timer-ended" : "lc-timer-countdown"}>
        {ended ? "00:00" : `${mm}:${ss}`}
      </div>
      <div className={ended ? "lc-timer-subtext lc-timer-ended-text" : "lc-timer-subtext"}>
        {ended ? t("timerFinished") : `${t("timerRemaining")} (${duration}${t("seconds")})`}
      </div>
    </div>
  );
}

export function MediaView({ activity }: { activity: ActivityState }) {
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

export function AggregateView({ aggregate }: { aggregate: AggregateState | null }) {
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
      {aggregate.choices ? <ChoiceBars choices={aggregate.choices} /> : null}
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

export function ChoiceBars({ choices }: { choices: Record<string, number> }) {
  const t = useT();
  const locale = useLocale();
  const entries = Object.entries(choices);
  let totalVotes = 0;
  for (const [, v] of entries) totalVotes += Number(v) || 0;

  return (
    <div className="lc-choice-bars">
      {entries.map(([choice, value]) => {
        const voteCount = Number(value) || 0;
        const pct = totalVotes > 0 ? Math.round((voteCount / totalVotes) * 100) : 0;
        return (
          <div key={choice} className="lc-choice-bar-row">
            <div className="lc-choice-bar-header">
              <strong>{choice}</strong>
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
