import * as React from "react";
import { useEffect, useRef } from "react";
import { createRoot } from "react-dom/client";
import { useLocale, useT } from "../i18n.js";
import { postJson } from "../protocol.js";
import { mountPluginActivity } from "../plugin_runtime.js";
import type { ActivityState, Audience, SessionState } from "../protocol.js";
import {
  activityContent,
  activityKind,
  activityTitle,
  choicesFor,
  displayAnswer,
  questionPrompt,
  stringValue,
  submitUrl,
} from "./activityData.js";
import { MarkdownView } from "./MarkdownView.js";
import { FileActivity } from "./FileActivity.js";
import { MediaView, TimerDisplay } from "./renderers.js";
import { ChoiceAnswerForm, RankingAnswerForm, TextAnswerForm } from "./AnswerForms.js";

const RESPONSE_KINDS = [
  "single_choice",
  "multiple_choice",
  "true_false",
  "poll",
  "short_text",
  "word_cloud",
  "numeric",
  "rating",
  "ranking",
];

const BUILTIN_KINDS = new Set([
  ...RESPONSE_KINDS,
  "timer",
  "media",
  "markdown",
  "file",
]);

export function isBuiltinActivity(activity: ActivityState | null): boolean {
  return activity === null || BUILTIN_KINDS.has(activityKind(activity));
}

export function Prompt({ activity }: { activity: ActivityState }) {
  const prompt = questionPrompt(activity);
  const content = activityContent(activity);
  const markdown = stringValue(content.markdown, stringValue(activity.definition.markdown));
  return (
    <>
      {prompt ? <p>{prompt}</p> : null}
      {markdown && markdown !== prompt ? <MarkdownView markdown={markdown} /> : null}
    </>
  );
}

export function RevealedFeedback({ activity }: { activity: ActivityState }) {
  const t = useT();
  const content = activityContent(activity);
  const answer = displayAnswer(content.answer ?? content.correct_answer ?? activity.definition.answer);
  const explanation = stringValue(content.explanation_markdown, stringValue(content.explanation));
  return (
    <>
      {answer ? (
        <p>
          {t("correctAnswer")}: {answer}
        </p>
      ) : null}
      {explanation ? <MarkdownView markdown={explanation} /> : null}
    </>
  );
}

function ResponseForm({
  activity,
  state,
  stateUrl,
  refresh,
}: {
  activity: ActivityState;
  state: SessionState;
  stateUrl: string;
  refresh: () => void;
}) {
  const t = useT();
  const kind = activityKind(activity);
  const content = activityContent(activity);
  const hasVisibleContent =
    questionPrompt(activity) !== "" ||
    choicesFor(activity).length > 0 ||
    stringValue(content.markdown, stringValue(activity.definition.markdown)) !== "";
  if (!hasVisibleContent) return <p>{t("notShownYet")}</p>;
  if (["single_choice", "multiple_choice", "true_false", "poll"].includes(kind)) {
    return <ChoiceAnswerForm activity={activity} state={state} stateUrl={stateUrl} onSubmitted={refresh} />;
  }
  if (["short_text", "word_cloud", "numeric", "rating"].includes(kind)) {
    return <TextAnswerForm activity={activity} state={state} stateUrl={stateUrl} onSubmitted={refresh} />;
  }
  if (kind === "ranking") {
    return <RankingAnswerForm activity={activity} state={state} stateUrl={stateUrl} onSubmitted={refresh} />;
  }
  return <p>{t("noAnswer")}</p>;
}

function BuiltinActivityView({
  activity,
  state,
  stateUrl,
  refresh,
}: {
  activity: ActivityState | null;
  state: SessionState | null;
  stateUrl: string | null;
  refresh: () => void;
}) {
  const t = useT();
  if (!activity) return <p>{t("waiting")}</p>;
  const kind = activityKind(activity);
  const admitted = state?.participant?.admission_state === "admitted";
  const actAsActive = state?.act_as_active !== false;

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
        <MediaView activity={activity} state={state} stateUrl={stateUrl} audience="student" />
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
        <FileActivity activity={activity} audience="student" state={state} stateUrl={stateUrl} />
      </>
    );
  }

  return (
    <>
      {heading}
      <Prompt activity={activity} />
      {admitted && actAsActive && state && stateUrl ? (
        <ResponseForm
          key={`${activity.id}:${activity.revision}:${activity.revision_id}`}
          activity={activity}
          state={state}
          stateUrl={stateUrl}
          refresh={refresh}
        />
      ) : admitted && choicesFor(activity).length ? (
        <ul data-liveclassroom-readonly-choices>
          {choicesFor(activity).map((choice) => <li key={choice.id}>{choice.text}</li>)}
        </ul>
      ) : null}
      {admitted ? <RevealedFeedback activity={activity} /> : null}
    </>
  );
}

export function PluginActivityView({
  activity,
  state,
  stateUrl,
  audience,
  refresh,
  fallback,
}: {
  activity: ActivityState;
  state: SessionState | null;
  stateUrl: string | null;
  audience: Audience;
  refresh?: () => void;
  fallback: React.ReactNode;
}) {
  const locale = useLocale();
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = host.current;
    if (!container) return undefined;
    let innerRoot: ReturnType<typeof createRoot> | undefined;
    const unmount = mountPluginActivity({
      parent: container,
      activity,
      audience,
      state: state ?? undefined,
      stateUrl: stateUrl ?? undefined,
      aggregate: state?.aggregate ?? null,
      locale,
      manifest: activity.frontend_manifest,
      submit: audience === "student" && stateUrl && refresh
        ? async (answer) => {
            const key = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;
            await postJson(
              submitUrl(stateUrl, activity),
              { answer, activity_revision_id: activity.revision_id },
              `submission-${key}`,
            );
            refresh?.();
          }
        : undefined,
      fallback: (el) => {
        innerRoot = createRoot(el);
        innerRoot.render(fallback);
      },
    });
    return () => {
      unmount();
      innerRoot?.unmount();
    };
  }, [activity.id, activity.revision, activity.frontend_manifest, audience, fallback, locale, refresh, state?.state_version, stateUrl]);

  return <div ref={host} />;
}

/**
 * Delegate third-party activity types to their registered renderer while
 * keeping built-ins in the React tree so polling cannot discard form input.
 */
export function ActivityView({
  activity,
  state,
  stateUrl,
  refresh,
}: {
  activity: ActivityState | null;
  state: SessionState | null;
  stateUrl: string | null;
  refresh: () => void;
}) {
  if (!activity || isBuiltinActivity(activity)) {
    return <BuiltinActivityView activity={activity} state={state} stateUrl={stateUrl} refresh={refresh} />;
  }
  return (
    <PluginActivityView
      activity={activity}
      state={state}
      stateUrl={stateUrl}
      audience="student"
      refresh={refresh}
      fallback={<BuiltinActivityView activity={activity} state={state} stateUrl={stateUrl} refresh={refresh} />}
    />
  );
}
