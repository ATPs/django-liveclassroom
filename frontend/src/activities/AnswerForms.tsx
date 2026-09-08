import * as React from "react";
import { useRef, useState } from "react";
import { postJson } from "../protocol.js";
import { useT } from "../i18n.js";
import type { ActivityState, SessionState } from "../protocol.js";
import {
  activityContent,
  activityKind,
  answerFor,
  answerText,
  choicesFor,
  numberValue,
  selectedChoices,
  stringValue,
  submitUrl,
} from "./activityData.js";

function SubmitButton({
  state,
  canSubmit,
  submitting,
}: {
  state: SessionState;
  canSubmit: boolean;
  submitting: boolean;
}) {
  const t = useT();
  const label = submitting
    ? t("saving")
    : state?.my_submission && !state.my_submission.is_stale
      ? t("saveChanges")
      : t("submit");
  return (
    <button type="submit" disabled={!canSubmit || submitting}>
      {label}
    </button>
  );
}

function AnswerStatus({ state }: { state: SessionState | undefined }) {
  const t = useT();
  if (!state?.my_submission) return null;
  return <p>{state.my_submission.is_stale ? t("stale") : t("saved")}</p>;
}

type FormProps = {
  activity: ActivityState;
  state: SessionState;
  stateUrl: string;
  onSubmitted: () => void;
};

type SubmissionIntent = {
  fingerprint: string;
  key: string;
};

function newIdempotencyKey(): string {
  const uuid = globalThis.crypto?.randomUUID?.();
  return uuid ? `submission-${uuid}` : `submission-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function submissionAllowed(activity: ActivityState, state: SessionState): boolean {
  return (
    activity.state === "open" &&
    state.session.status === "live" &&
    state.participant?.admission_state === "admitted" &&
    state.act_as_active !== false
  );
}

function useSubmit(activity: ActivityState, state: SessionState, stateUrl: string, onSubmitted: () => void) {
  const t = useT();
  const [notice, setNotice] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const submittingRef = useRef(false);
  const intentRef = useRef<SubmissionIntent | null>(null);
  const canSubmit = submissionAllowed(activity, state);

  const submit = async (answer: Record<string, unknown>): Promise<void> => {
    if (!canSubmit || submittingRef.current) return;
    const fingerprint = JSON.stringify({
      activity_id: activity.id,
      activity_revision_id: activity.revision_id,
      answer,
    });
    const intent = intentRef.current?.fingerprint === fingerprint
      ? intentRef.current
      : { fingerprint, key: newIdempotencyKey() };
    intentRef.current = intent;
    submittingRef.current = true;
    setSubmitting(true);
    setNotice("");
    try {
      await postJson(
        submitUrl(stateUrl, activity),
        { answer, activity_revision_id: activity.revision_id },
        intent.key,
      );
      intentRef.current = null;
      setNotice(t("saved"));
      onSubmitted();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : t("unavailable"));
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  };

  return { canSubmit, notice, setNotice, submitting, submit };
}

export function ChoiceAnswerForm({ activity, state, stateUrl, onSubmitted }: FormProps) {
  const t = useT();
  const kind = activityKind(activity);
  const multiple = kind === "multiple_choice";
  const selected = selectedChoices(answerFor(activity, state));
  const options = choicesFor(activity);
  const inputType = multiple ? "checkbox" : "radio";
  const inputName = multiple ? "choices" : "choice";
  const { canSubmit, notice, setNotice, submitting, submit } = useSubmit(activity, state, stateUrl, onSubmitted);

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSubmit || submitting) return;
    const values = [...new FormData(event.currentTarget).getAll(inputName)].map(String);
    if (!values.length) {
      setNotice(t("selectionRequired"));
      return;
    }
    void submit(multiple ? { choices: values } : { choice: values[0] });
  };

  return (
    <form onSubmit={handleSubmit}>
      <p className="lc-form-hint">{multiple ? t("chooseMany") : t("chooseOne")}</p>
      {options.map((option) => (
        <div key={option.id}>
          <label>
            <input
              type={inputType}
              name={inputName}
              value={option.id}
              defaultChecked={selected.includes(option.id)}
              disabled={!canSubmit || submitting}
            />{" "}
            {option.text}
          </label>
        </div>
      ))}
      {activity.state === "open" ? (
        <SubmitButton state={state} canSubmit={canSubmit} submitting={submitting} />
      ) : null}
      <AnswerStatus state={state} />
      {notice ? <p data-liveclassroom-form-status aria-live="polite">{notice}</p> : null}
    </form>
  );
}

export function TextAnswerForm({ activity, state, stateUrl, onSubmitted }: FormProps) {
  const t = useT();
  const kind = activityKind(activity);
  const content = activityContent(activity);
  const field = kind === "numeric" ? "value" : kind === "rating" ? "rating" : "text";
  const initial = answerText(answerFor(activity, state), field);
  const { canSubmit, notice, setNotice, submitting, submit } = useSubmit(activity, state, stateUrl, onSubmitted);
  const asTextarea = kind === "short_text" || kind === "word_cloud";
  const [rating, setRating] = useState(initial);
  const ratingMinimum = numberValue(content.minimum) ?? 1;
  const ratingMaximum = numberValue(content.maximum) ?? 5;
  const ratingOptions = Array.from(
    { length: Math.max(0, Math.floor(ratingMaximum) - Math.ceil(ratingMinimum) + 1) },
    (_, index) => Math.ceil(ratingMinimum) + index,
  );

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSubmit || submitting) return;
    const input = event.currentTarget.elements.namedItem(field) as HTMLInputElement | HTMLTextAreaElement;
    const raw = input.value.trim();
    if (!raw) {
      setNotice(t("answerRequired"));
      return;
    }
    const value = kind === "numeric" || kind === "rating" ? Number(raw) : raw;
    if (typeof value === "number" && !Number.isFinite(value)) {
      setNotice(t("numericAnswer"));
      return;
    }
    void submit({ [field]: value });
  };

  const numericProps =
    kind === "numeric" || kind === "rating"
      ? {
          type: "number",
          min: numberValue(content.minimum) ?? undefined,
          max: numberValue(content.maximum) ?? undefined,
          step: numberValue(content.step) ?? undefined,
        }
      : { type: "text" };

  return (
    <form onSubmit={handleSubmit}>
      {kind === "rating" ? (
        <fieldset className="lc-rating-control">
          <legend>{t("ratingValue")}</legend>
          <div className="lc-rating-endpoints"><span>{stringValue(content.minimum_label, t("notConfidentYet"))}</span><span>{stringValue(content.maximum_label, t("veryConfident"))}</span></div>
          <div className="lc-rating-options">
            {ratingOptions.map((value) => <button key={value} type="button" className={String(value) === rating ? "lc-rating-btn lc-rating-btn-selected" : "lc-rating-btn"} disabled={!canSubmit || submitting} aria-pressed={String(value) === rating} onClick={() => setRating(String(value))}>{value}</button>)}
          </div>
          <input type="hidden" name={field} value={rating} />
        </fieldset>
      ) : asTextarea ? (
        <label>{t("textAnswer")}<textarea name={field} defaultValue={initial} maxLength={numberValue(content.max_length) ?? undefined} disabled={!canSubmit || submitting} /></label>
      ) : (
        <label>{stringValue(content.label, t("numericAnswer"))}<input name={field} defaultValue={initial} disabled={!canSubmit || submitting} {...numericProps} /></label>
      )}
      {activity.state === "open" ? (
        <SubmitButton state={state} canSubmit={canSubmit} submitting={submitting} />
      ) : null}
      <AnswerStatus state={state} />
      {notice ? <p data-liveclassroom-form-status aria-live="polite">{notice}</p> : null}
    </form>
  );
}

export function RankingAnswerForm({ activity, state, stateUrl, onSubmitted }: FormProps) {
  const saved = selectedChoices(answerFor(activity, state));
  const choices = choicesFor(activity);
  const [ranking, setRanking] = React.useState(() => {
    const known = new Set(saved);
    return [...saved.filter((id) => choices.some((choice) => choice.id === id)), ...choices.map((choice) => choice.id).filter((id) => !known.has(id))];
  });
  const { canSubmit, notice, submitting, submit } = useSubmit(activity, state, stateUrl, onSubmitted);

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSubmit || submitting) return;
    void submit({ ranking });
  };

  const move = (index: number, delta: number) => {
    const destination = index + delta;
    if (destination < 0 || destination >= ranking.length) return;
    setRanking((current) => {
      const next = [...current];
      [next[index], next[destination]] = [next[destination], next[index]];
      return next;
    });
  };

  return (
    <form onSubmit={handleSubmit}>
      <ol className="lc-ranking-list" aria-label="Ranking order">
        {ranking.map((id, index) => {
          const option = choices.find((choice) => choice.id === id);
          if (!option) return null;
          return <li key={id} className="lc-ranking-item">
            <span>{index + 1}. {option.text}</span>
            <span className="lc-actions">
              <button type="button" disabled={!canSubmit || submitting || index === 0} aria-label={`Move ${option.text} up`} onClick={() => move(index, -1)}>↑</button>
              <button type="button" disabled={!canSubmit || submitting || index === ranking.length - 1} aria-label={`Move ${option.text} down`} onClick={() => move(index, 1)}>↓</button>
            </span>
          </li>;
        })}
      </ol>
      {activity.state === "open" ? (
        <SubmitButton state={state} canSubmit={canSubmit} submitting={submitting} />
      ) : null}
      <AnswerStatus state={state} />
      {notice ? <p data-liveclassroom-form-status aria-live="polite">{notice}</p> : null}
    </form>
  );
}
