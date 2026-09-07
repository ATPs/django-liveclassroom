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
  const label = state?.my_submission && !state.my_submission.is_stale ? t("update") : t("submit");
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

  return { canSubmit, notice, submitting, submit };
}

export function ChoiceAnswerForm({ activity, state, stateUrl, onSubmitted }: FormProps) {
  const kind = activityKind(activity);
  const multiple = kind === "multiple_choice";
  const selected = selectedChoices(answerFor(activity, state));
  const options = choicesFor(activity);
  const inputType = multiple ? "checkbox" : "radio";
  const inputName = multiple ? "choices" : "choice";
  const { canSubmit, notice, submitting, submit } = useSubmit(activity, state, stateUrl, onSubmitted);

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSubmit || submitting) return;
    const values = [...new FormData(event.currentTarget).getAll(inputName)].map(String);
    if (!values.length) return;
    void submit(multiple ? { choices: values } : { choice: values[0] });
  };

  return (
    <form onSubmit={handleSubmit}>
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
  const kind = activityKind(activity);
  const content = activityContent(activity);
  const field = kind === "numeric" ? "value" : kind === "rating" ? "rating" : "text";
  const initial = answerText(answerFor(activity, state), field);
  const { canSubmit, notice, submitting, submit } = useSubmit(activity, state, stateUrl, onSubmitted);
  const asTextarea = kind === "short_text" || kind === "word_cloud";

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSubmit || submitting) return;
    const input = event.currentTarget.elements.namedItem(field) as HTMLInputElement | HTMLTextAreaElement;
    const raw = input.value.trim();
    if (!raw) return;
    const value = kind === "numeric" || kind === "rating" ? Number(raw) : raw;
    if (typeof value === "number" && !Number.isFinite(value)) return;
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
      {asTextarea ? (
        <textarea name={field} defaultValue={initial} disabled={!canSubmit || submitting} />
      ) : (
        <input name={field} defaultValue={initial} disabled={!canSubmit || submitting} {...numericProps} />
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
  const selected = selectedChoices(answerFor(activity, state));
  const { canSubmit, notice, submitting, submit } = useSubmit(activity, state, stateUrl, onSubmitted);

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!canSubmit || submitting) return;
    const select = event.currentTarget.elements.namedItem("ranking") as HTMLSelectElement;
    const values = [...select.selectedOptions].map((option) => option.value);
    if (!values.length) return;
    void submit({ ranking: values });
  };

  return (
    <form onSubmit={handleSubmit}>
      <select name="ranking" multiple defaultValue={selected} disabled={!canSubmit || submitting}>
        {choicesFor(activity).map((option) => (
          <option key={option.id} value={option.id}>
            {option.text}
          </option>
        ))}
      </select>
      {activity.state === "open" ? (
        <SubmitButton state={state} canSubmit={canSubmit} submitting={submitting} />
      ) : null}
      <AnswerStatus state={state} />
      {notice ? <p data-liveclassroom-form-status aria-live="polite">{notice}</p> : null}
    </form>
  );
}
