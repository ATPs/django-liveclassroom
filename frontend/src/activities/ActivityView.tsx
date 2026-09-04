import * as React from "react";
import { useLocale, useT } from "../i18n.js";
import type { ActivityState, SessionState } from "../protocol.js";
import {
  activityContent,
  activityKind,
  activityTitle,
  choicesFor,
  displayAnswer,
  questionPrompt,
  stringValue,
} from "./activityData.js";
import { MarkdownView } from "./MarkdownView.js";
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
  const locale = useLocale();
  const content = activityContent(activity);
  const answer = displayAnswer(content.answer ?? content.correct_answer ?? activity.definition.answer);
  const explanation = stringValue(content.explanation_markdown, stringValue(content.explanation));
  return (
    <>
      {answer ? (
        <p>
          {locale === "zh-Hans" ? "正确答案" : "Answer"}: {answer}
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

  return (
    <>
      {heading}
      <Prompt activity={activity} />
      {admitted && actAsActive && state && stateUrl ? (
        <ResponseForm activity={activity} state={state} stateUrl={stateUrl} refresh={refresh} />
      ) : null}
      {admitted ? <RevealedFeedback activity={activity} /> : null}
    </>
  );
}
