import * as React from "react";
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { readBootstrap, type Bootstrap } from "../../bootstrap.js";
import { LanguageSwitcher, LocaleProvider, useT } from "../../i18n.js";
import { useSessionState } from "../../hooks/useSessionState.js";
import { isBuiltinActivity, PluginActivityView, Prompt, RevealedFeedback } from "../../activities/ActivityView.js";
import { AggregateView, MediaView, TimerDisplay, WordCloud } from "../../activities/renderers.js";
import { MarkdownView } from "../../activities/MarkdownView.js";
import { FileActivity } from "../../activities/FileActivity.js";
import {
  activityContent,
  activityKind,
  activityTitle,
  choicesFor,
  questionPrompt,
  stringValue,
} from "../../activities/activityData.js";
import type { ActivityState, AggregateState, SessionState } from "../../protocol.js";

function ChoiceList({ activity }: { activity: ActivityState }) {
  const choices = choicesFor(activity);
  if (!choices.length) return null;
  return (
    <ul>
      {choices.map((option) => (
        <li key={option.id}>
          {option.id}. {option.text}
        </li>
      ))}
    </ul>
  );
}

function DisplayActivity({
  activity,
  aggregate,
  state,
  stateUrl,
}: {
  activity: ActivityState | null;
  aggregate: AggregateState | null;
  state: SessionState | null;
  stateUrl: string;
}) {
  const t = useT();
  if (!activity) return <p>{t("noActivityPublished")}</p>;
  if (!isBuiltinActivity(activity)) {
    return (
      <PluginActivityView
        activity={activity}
        state={state}
        stateUrl={stateUrl}
        audience="display"
        fallback={<BuiltinDisplayActivity activity={activity} aggregate={aggregate} state={state} stateUrl={stateUrl} />}
      />
    );
  }
  return <BuiltinDisplayActivity activity={activity} aggregate={aggregate} state={state} stateUrl={stateUrl} />;
}

function BuiltinDisplayActivity({
  activity,
  aggregate,
  state,
  stateUrl,
}: {
  activity: ActivityState;
  aggregate: AggregateState | null;
  state: SessionState | null;
  stateUrl: string;
}) {
  const t = useT();
  const kind = activityKind(activity);
  const heading = <h2>{activityTitle(activity, t("activity"))}</h2>;

  if (kind === "timer") {
    return (
      <>
        {heading}
        <TimerDisplay activity={activity} />
      </>
    );
  }
  if (kind === "media") {
    return (
      <>
        {heading}
        <Prompt activity={activity} />
        <MediaView activity={activity} />
      </>
    );
  }
  if (kind === "markdown") {
    const content = activityContent(activity);
    const md = stringValue(content.markdown, stringValue(activity.definition.markdown, questionPrompt(activity)));
    return (
      <>
        {heading}
        {md ? <MarkdownView markdown={md} /> : <Prompt activity={activity} />}
      </>
    );
  }
  if (kind === "file") {
    return (
      <>
        {heading}
        <FileActivity activity={activity} audience="display" state={state} stateUrl={stateUrl} />
      </>
    );
  }

  return (
    <>
      {heading}
      <Prompt activity={activity} />
      {kind === "word_cloud" ? <WordCloud aggregate={aggregate} /> : <ChoiceList activity={activity} />}
      <RevealedFeedback activity={activity} />
      {kind !== "word_cloud" ? <AggregateView aggregate={aggregate} /> : null}
    </>
  );
}

function ClassroomDisplay({ bootstrap }: { bootstrap: Bootstrap }) {
  const t = useT();
  const stateUrl = bootstrap.stateUrl!;
  const [fullscreen, setFullscreen] = useState(false);
  const sync = useSessionState({
    stateUrl,
    websocketPath: bootstrap.websocketUrl,
    channel: "display",
    enabled: true,
  });
  const state = sync.state;
  const activity = state?.current_activity ?? null;

  const toggleFullscreen = () => {
    if (document.fullscreenElement) {
      void document.exitFullscreen();
    } else {
      void document.documentElement.requestFullscreen();
    }
    setFullscreen(!fullscreen);
  };

  return (
    <>
      <LanguageSwitcher />
      <div className="lc-display-toolbar">
        <button type="button" onClick={toggleFullscreen}>
          {fullscreen ? t("exitFullscreen") : t("fullscreen")}
        </button>
      </div>
      <h1 id="display-title">{activity ? activityTitle(activity, state?.session.title ?? "") : state?.session.title ?? "…"}</h1>
      <div id="display-content" data-liveclassroom-content>
        <DisplayActivity activity={activity} aggregate={state?.aggregate ?? null} state={state} stateUrl={stateUrl} />
      </div>
      <p id="display-status" data-liveclassroom-status aria-live="polite">
        {sync.error || (state ? state.session.status : "")}
      </p>
    </>
  );
}

export function mountClassroomDisplay(el: HTMLElement): void {
  const bootstrap = readBootstrap(el);
  if (!bootstrap.stateUrl) return;
  const root = createRoot(el);
  root.render(
    <LocaleProvider initial={bootstrap.locale} root={el}>
      <ClassroomDisplay bootstrap={bootstrap} />
    </LocaleProvider>,
  );
  el.addEventListener("liveclassroom:unmount", () => root.unmount(), { once: true });
}
