import * as React from "react";
import { useEffect, useRef, useState } from "react";
import { useT } from "../i18n.js";
import type { ActivityState } from "../protocol.js";
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
  const content = activityContent(activity);
  const mediaDisabled = content.media_disabled === true || activity.definition.media_disabled === true;
  if (mediaDisabled) return <p>This media is unavailable.</p>;
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
      {isImage ? <img src={url} alt={caption || "Media image"} /> : null}
      {isVideo ? <video src={url} controls /> : null}
      {isAudio ? <audio src={url} controls /> : null}
      {!isImage && !isVideo && !isAudio ? (
        <iframe
          src={url}
          sandbox={provider === "vaultpub" ? "allow-scripts allow-same-origin" : "allow-scripts"}
          referrerPolicy={provider === "vaultpub" ? "same-origin" : "no-referrer"}
          loading="lazy"
          title={caption || (provider === "vaultpub" ? "VaultPub presentation" : "Embedded content")}
        />
      ) : null}
      {caption ? <p className="lc-media-caption">{caption}</p> : null}
    </div>
  );
}
