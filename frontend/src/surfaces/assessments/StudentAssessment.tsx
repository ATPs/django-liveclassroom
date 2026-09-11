import * as React from "react";
import { createRoot } from "react-dom/client";
import { LanguageSwitcher, LocaleProvider, useLocale, useT } from "../../i18n.js";
import { ApiError, getJson, postJson } from "../../protocol.js";
import { MarkdownView, markdownFragmentFor } from "../../activities/MarkdownView.js";
import { updateQuery, useQuerySelection } from "../../navigation.js";

export type AssessmentAnswer = Record<string, unknown>;

export type AssessmentAttemptItem = {
  key: string;
  position: number;
  points: string;
  type_key: string;
  schema_version?: number;
  payload: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  asset_id?: string | null;
  answer_version: number;
  answer: AssessmentAnswer | null;
};

export type AssessmentAttempt = {
  id: string;
  run_id: string;
  attempt_number: number;
  status: "in_progress" | "submitted" | string;
  started_at: string;
  deadline_at?: string | null;
  submitted_at?: string | null;
  finalization_reason?: string | null;
  server_now?: string;
  navigation?: {
    mode: "free" | "forward_only";
    current_item_key: string;
    current_item_position: number;
    highest_accessible_item_position: number;
    locked_item_keys: string[];
    navigation_version: number;
    can_go_previous: boolean;
    can_go_next: boolean;
  };
  items: AssessmentAttemptItem[];
};

export type AssessmentRunEntry = {
  public_id: string;
  title: string;
  instructions: string;
  audience: string;
  course_id?: number | null;
  attempt_available?: boolean;
};

export type AnswerSaveRequest = {
  itemKey: string;
  expectedVersion: number;
  requestId: string;
  answer: AssessmentAnswer;
};

export type AnswerSaveResult = {
  item_key: string;
  version: number;
  answer: AssessmentAnswer;
  saved_at: string;
  server_now: string;
};

export type AutosaveStatus = "idle" | "saving" | "saved" | "offline" | "retry" | "conflict";

export type AutosaveEvent = {
  itemKey: string;
  status: AutosaveStatus;
  task?: AnswerSaveRequest;
  result?: AnswerSaveResult;
  error?: unknown;
};

type SaveAnswer = (request: AnswerSaveRequest) => Promise<AnswerSaveResult>;

function newRequestId(): string {
  const uuid = globalThis.crypto?.randomUUID?.();
  if (uuid) return uuid;
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (value) => {
    const random = Math.floor(Math.random() * 16);
    const nibble = value === "x" ? random : (random & 0x3) | 0x8;
    return nibble.toString(16);
  });
}

/**
 * Per-item serialized answer saves. A pending answer replaces only another
 * pending answer for that item; an in-flight request is always allowed to
 * finish first. A request id is kept with the pending body so a retry is an
 * idempotent replay of the same command.
 */
export class SerializedAutosaveController {
  private readonly pending = new Map<string, AnswerSaveRequest>();
  private readonly timers = new Map<string, ReturnType<typeof setTimeout>>();
  private readonly inFlight = new Map<string, Promise<boolean>>();
  private disposed = false;

  constructor(
    private readonly save: SaveAnswer,
    private readonly onEvent: (event: AutosaveEvent) => void,
    private readonly delayMs = 500,
  ) {}

  queue(itemKey: string, answer: AssessmentAnswer, expectedVersion: number): void {
    if (this.disposed) return;
    const prior = this.pending.get(itemKey);
    const sameBody = prior && prior.expectedVersion === expectedVersion
      && JSON.stringify(prior.answer) === JSON.stringify(answer);
    const request: AnswerSaveRequest = {
      itemKey,
      expectedVersion,
      requestId: sameBody ? prior.requestId : newRequestId(),
      answer,
    };
    this.pending.set(itemKey, request);
    this.onEvent({ itemKey, status: "saving", task: request });
    this.schedule(itemKey, this.delayMs);
  }

  retry(itemKey: string): void {
    if (this.disposed || !this.pending.has(itemKey)) return;
    this.schedule(itemKey, 0);
  }

  async flush(itemKey: string): Promise<boolean> {
    this.clearTimer(itemKey);
    return this.pump(itemKey);
  }

  async flushAll(): Promise<boolean> {
    for (const itemKey of this.pending.keys()) this.clearTimer(itemKey);
    const keys = new Set([...this.pending.keys(), ...this.inFlight.keys()]);
    const results = await Promise.all([...keys].map((itemKey) => this.pump(itemKey)));
    return results.every(Boolean) && !this.hasUnsaved();
  }

  hasUnsaved(): boolean {
    return this.pending.size > 0 || this.inFlight.size > 0;
  }

  dispose(): void {
    this.disposed = true;
    for (const timer of this.timers.values()) clearTimeout(timer);
    this.timers.clear();
  }

  private schedule(itemKey: string, delay: number): void {
    this.clearTimer(itemKey);
    this.timers.set(itemKey, setTimeout(() => {
      this.timers.delete(itemKey);
      void this.pump(itemKey);
    }, delay));
  }

  private clearTimer(itemKey: string): void {
    const timer = this.timers.get(itemKey);
    if (timer !== undefined) clearTimeout(timer);
    this.timers.delete(itemKey);
  }

  private pump(itemKey: string): Promise<boolean> {
    const existing = this.inFlight.get(itemKey);
    if (existing) return existing;
    const work = this.pumpLoop(itemKey);
    this.inFlight.set(itemKey, work);
    void work.finally(() => this.inFlight.delete(itemKey));
    return work;
  }

  private async pumpLoop(itemKey: string): Promise<boolean> {
    while (!this.disposed && this.pending.has(itemKey)) {
      const task = this.pending.get(itemKey) as AnswerSaveRequest;
      this.pending.delete(itemKey);
      this.onEvent({ itemKey, status: "saving", task });
      try {
        const result = await this.save(task);
        const newer = this.pending.get(itemKey);
        if (newer) newer.expectedVersion = result.version;
        else this.onEvent({ itemKey, status: "saved", task, result });
      } catch (error) {
        this.pending.set(itemKey, task);
        const status: AutosaveStatus = error instanceof ApiError && error.status === 409
          ? "conflict"
          : typeof navigator !== "undefined" && navigator.onLine === false ? "offline" : "retry";
        this.onEvent({ itemKey, status, task, error });
        return false;
      }
    }
    return !this.hasUnsaved();
  }
}

function endpoint(startUrl: string, attemptId: string, suffix = ""): string {
  const url = new URL(startUrl, window.location.href);
  // Starting an attempt and reading/saving it intentionally use separate
  // package routes. Preserve the mount prefix while moving from
  // assessment-runs/<run>/attempts/ to attempts/<attempt>/.
  const attemptPath = url.pathname.replace(/assessment-runs\/[^/]+\/attempts\/?$/, "attempts/");
  url.pathname = `${attemptPath.replace(/\/+$/, "")}/${encodeURIComponent(attemptId)}${suffix ? `/${suffix.replace(/^\/+|\/+$/g, "")}` : ""}/`;
  return url.toString();
}

export function assessmentAttemptUrl(startUrl: string, attemptId: string): string {
  return endpoint(startUrl, attemptId);
}

function text(value: unknown): string {
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

function object(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function itemPayload(item: AssessmentAttemptItem): Record<string, unknown> {
  const payload = object(item.payload);
  const content = object(payload.content);
  return Object.keys(content).length ? { ...payload, ...content } : payload;
}

function itemType(item: AssessmentAttemptItem): string {
  const raw = text(item.type_key || itemPayload(item).type_key);
  return raw.split(".").pop() || "unknown";
}

function itemPrompt(item: AssessmentAttemptItem): string {
  const payload = itemPayload(item);
  return text(payload.prompt || payload.stem_markdown || payload.markdown || object(payload.question).prompt);
}

function itemOptions(item: AssessmentAttemptItem): Array<{ id: string; text: string }> {
  const payload = itemPayload(item);
  const raw = Array.isArray(payload.options) ? payload.options : Array.isArray(payload.choices) ? payload.choices : [];
  return raw.flatMap((value, index): Array<{ id: string; text: string }> => {
    if (typeof value === "string") return [{ id: String.fromCharCode(65 + index), text: value }];
    const option = object(value);
    const label = text(option.text || option.label);
    return label ? [{ id: text(option.id) || String.fromCharCode(65 + index), text: label }] : [];
  });
}

function selectedValues(answer: AssessmentAnswer, key: string): string[] {
  const value = answer[key];
  return Array.isArray(value) ? value.map(String) : value === undefined || value === null ? [] : [String(value)];
}

function wireAnswer(kind: string, answer: AssessmentAnswer): AssessmentAnswer {
  if (kind === "single_choice" || kind === "true_false" || kind === "poll") {
    return text(answer.choice) ? { choice: text(answer.choice) } : {};
  }
  if (kind === "multiple_choice") {
    const choices = selectedValues(answer, "choices");
    return choices.length ? { choices } : {};
  }
  if (kind === "ranking") {
    const ranking = selectedValues(answer, "ranking");
    return ranking.length ? { ranking } : {};
  }
  if (kind === "numeric" || kind === "rating") {
    const raw = answer[kind === "numeric" ? "value" : "rating"];
    if (raw === undefined || raw === null || String(raw).trim() === "") return {};
    const value = Number(raw);
    return Number.isFinite(value) ? { [kind === "numeric" ? "value" : "rating"]: value } : answer;
  }
  const value = text(answer.text);
  return value.trim() ? { text: value } : {};
}

function answerText(answer: AssessmentAnswer, key: string): string {
  const value = answer[key];
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

function answerStatusLabel(status: AutosaveStatus, t: ReturnType<typeof useT>): string {
  switch (status) {
    case "saving": return t("assessmentSaving");
    case "saved": return t("assessmentSaved");
    case "offline": return t("assessmentOffline");
    case "retry": return t("assessmentRetry");
    case "conflict": return t("assessmentConflict");
    default: return "";
  }
}

function ResponseControl({
  item,
  answer,
  disabled,
  onChange,
}: {
  item: AssessmentAttemptItem;
  answer: AssessmentAnswer;
  disabled: boolean;
  onChange: (next: AssessmentAnswer) => void;
}) {
  const t = useT();
  const kind = itemType(item);
  const options = itemOptions(item);
  if (["single_choice", "true_false", "poll"].includes(kind)) {
    const current = answerText(answer, "choice");
    return (
      <fieldset className="lc-assessment-response-options">
        <legend>{kind === "multiple_choice" ? t("assessmentChooseMany") : t("assessmentChooseOne")}</legend>
        {options.map((option) => (
          <label key={option.id} className="lc-assessment-option">
            <input type="radio" name={`assessment-${item.key}`} value={option.id} checked={current === option.id} disabled={disabled} onChange={() => onChange({ choice: option.id })} />
            <span><strong>{option.id}</strong> {option.text}</span>
          </label>
        ))}
      </fieldset>
    );
  }
  if (kind === "multiple_choice") {
    const selected = new Set(selectedValues(answer, "choices"));
    return (
      <fieldset className="lc-assessment-response-options">
        <legend>{t("assessmentChooseMany")}</legend>
        {options.map((option) => (
          <label key={option.id} className="lc-assessment-option">
            <input type="checkbox" name={`assessment-${item.key}`} value={option.id} checked={selected.has(option.id)} disabled={disabled} onChange={(event) => {
              const next = new Set(selected);
              if (event.currentTarget.checked) next.add(option.id); else next.delete(option.id);
              onChange({ choices: [...next] });
            }} />
            <span><strong>{option.id}</strong> {option.text}</span>
          </label>
        ))}
      </fieldset>
    );
  }
  if (kind === "ranking") {
    const ranking = selectedValues(answer, "ranking");
    const ordered = [...ranking.filter((id) => options.some((option) => option.id === id)), ...options.map((option) => option.id).filter((id) => !ranking.includes(id))];
    const move = (index: number, delta: number) => {
      const nextIndex = index + delta;
      if (nextIndex < 0 || nextIndex >= ordered.length) return;
      const next = [...ordered];
      [next[index], next[nextIndex]] = [next[nextIndex], next[index]];
      onChange({ ranking: next });
    };
    return (
      <ol className="lc-assessment-ranking" aria-label={t("assessmentRanking")}>
        {ordered.map((id, index) => <li key={id}><span>{options.find((option) => option.id === id)?.text || id}</span><span className="lc-actions"><button type="button" disabled={disabled || index === 0} aria-label={`${t("assessmentMoveUp")} ${id}`} onClick={() => move(index, -1)}>↑</button><button type="button" disabled={disabled || index === ordered.length - 1} aria-label={`${t("assessmentMoveDown")} ${id}`} onClick={() => move(index, 1)}>↓</button></span></li>)}
      </ol>
    );
  }
  if (kind === "numeric" || kind === "rating") {
    const key = kind === "numeric" ? "value" : "rating";
    const payload = itemPayload(item);
    return <label className="lc-assessment-answer-label">{kind === "numeric" ? t("assessmentNumericAnswer") : t("assessmentRating")}<input type="number" inputMode="decimal" min={text(payload.minimum) || undefined} max={text(payload.maximum) || undefined} step={text(payload.step) || undefined} value={answerText(answer, key)} disabled={disabled} onChange={(event) => onChange({ [key]: event.currentTarget.value })} /></label>;
  }
  if (["short_text", "word_cloud", "essay"].includes(kind)) {
    const payload = itemPayload(item);
    const maxLength = Number(payload.max_length) || (kind === "essay" ? 50000 : 4000);
    return <label className="lc-assessment-answer-label">{kind === "essay" ? t("assessmentEssayResponse") : t("assessmentTextAnswer")}<textarea rows={kind === "essay" ? 9 : 4} maxLength={maxLength} value={answerText(answer, "text")} disabled={disabled} onChange={(event) => onChange({ text: event.currentTarget.value })} />{kind === "essay" ? <small>{answerText(answer, "text").length} / {maxLength} {t("characters")}</small> : null}</label>;
  }
  return <p className="lc-assessment-no-response">{t("assessmentNoResponse")}</p>;
}

function QuestionCard({
  item,
  answer,
  status,
  disabled,
  onChange,
  onRetry,
}: {
  item: AssessmentAttemptItem;
  answer: AssessmentAnswer;
  status: AutosaveStatus;
  disabled: boolean;
  onChange?: (next: AssessmentAnswer) => void;
  onRetry?: () => void;
}) {
  const t = useT();
  const prompt = itemPrompt(item);
  const fragment = markdownFragmentFor({ definition: itemPayload(item) }, "prompt");
  const label = answerStatusLabel(status, t);
  return (
    <article className="lc-card lc-student-assessment-question" data-assessment-item={item.key}>
      <header className="lc-student-assessment-question-heading"><span className="lc-assessment-item-number">{item.position}</span><div><h2>{t("assessmentQuestion")} {item.position}</h2><p className="lc-workspace-meta">{itemType(item)} · {item.points} {t("assessmentPoints")}</p></div></header>
      {prompt ? <MarkdownView markdown={prompt} fragment={fragment} /> : null}
      {onChange ? <ResponseControl item={item} answer={answer} disabled={disabled} onChange={onChange} /> : <p className="lc-assessment-readonly-answer">{t("assessmentAnswerRecorded")}</p>}
      {label ? <p className={`lc-assessment-save-status lc-assessment-save-${status}`} role="status">{label}{status === "retry" || status === "offline" || status === "conflict" ? <button type="button" className="lc-btn-sm lc-btn-outline" onClick={onRetry}>{t("assessmentRetryNow")}</button> : null}</p> : null}
    </article>
  );
}

function StudentAssessment({ runUrl, startUrl, historyUrl, initialAttemptId = "" }: { runUrl: string; startUrl: string; historyUrl?: string; initialAttemptId?: string }) {
  const t = useT();
  const locale = useLocale();
  const [run, setRun] = React.useState<AssessmentRunEntry | null>(null);
  const [attempt, setAttempt] = React.useState<AssessmentAttempt | null>(null);
  const [answers, setAnswers] = React.useState<Record<string, AssessmentAnswer>>({});
  const [versions, setVersions] = React.useState<Record<string, number>>({});
  const [statuses, setStatuses] = React.useState<Record<string, AutosaveStatus>>({});
  const [selected, setSelected] = React.useState(0);
  const [loading, setLoading] = React.useState(true);
  const [starting, setStarting] = React.useState(false);
  const [submitting, setSubmitting] = React.useState(false);
  const [confirming, setConfirming] = React.useState(false);
  const [error, setError] = React.useState("");
  const [notice, setNotice] = React.useState("");
  const [itemSelection, selectItemUrl] = useQuerySelection("item");
  const attemptRef = React.useRef<AssessmentAttempt | null>(null);
  const versionsRef = React.useRef<Record<string, number>>({});
  const storageKey = React.useMemo(() => `liveclassroom-assessment-attempt:${runUrl}`, [runUrl]);
  const controllerRef = React.useRef<SerializedAutosaveController | null>(null);

  const loadAttempt = React.useCallback((loaded: AssessmentAttempt) => {
    const normalizedItems = Array.isArray(loaded.items) ? [...loaded.items].sort((a, b) => a.position - b.position) : [];
    const normalized = { ...loaded, items: normalizedItems };
    const initialAnswers: Record<string, AssessmentAnswer> = {};
    const initialVersions: Record<string, number> = {};
    const initialStatuses: Record<string, AutosaveStatus> = {};
    for (const item of normalizedItems) {
      if (item.answer && typeof item.answer === "object") initialAnswers[item.key] = item.answer;
      initialVersions[item.key] = item.answer_version || 0;
      initialStatuses[item.key] = item.answer ? "saved" : "idle";
    }
    attemptRef.current = normalized;
    versionsRef.current = initialVersions;
    setAttempt(normalized);
    setAnswers(initialAnswers);
    setVersions(initialVersions);
    setStatuses(initialStatuses);
    // A URL is an untrusted navigation request. Start at the persisted server
    // cursor; the effect below asks the server before honoring ?item=.
    const selectedKey = normalized.navigation?.current_item_key;
    const selectedIndex = normalizedItems.findIndex((item) => item.key === selectedKey);
    setSelected(selectedIndex >= 0 ? selectedIndex : 0);
  }, []);

  const saveAnswer = React.useCallback((request: AnswerSaveRequest) => {
    const current = attemptRef.current;
    if (!current) return Promise.reject(new Error("An attempt has not been started."));
    return postJson<AnswerSaveResult>(endpoint(startUrl, current.id, "answers"), {
      item_key: request.itemKey,
      expected_version: request.expectedVersion,
      request_id: request.requestId,
      answer: request.answer,
    });
  }, [startUrl]);

  if (!controllerRef.current) {
    controllerRef.current = new SerializedAutosaveController(saveAnswer, (event) => {
      setStatuses((current) => ({ ...current, [event.itemKey]: event.status }));
      if (event.result) {
        versionsRef.current = { ...versionsRef.current, [event.itemKey]: event.result.version };
        setVersions(versionsRef.current);
        setAnswers((current) => ({ ...current, [event.itemKey]: event.result?.answer ?? current[event.itemKey] }));
      }
    });
  }
  const controller = controllerRef.current;

  React.useEffect(() => () => controller.dispose(), [controller]);

  React.useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    void getJson<AssessmentRunEntry>(runUrl).then((loadedRun) => {
      if (!active) return;
      setRun(loadedRun);
      // Persist only the server-issued attempt identity. Answers themselves
      // never enter browser storage, so unsaved text is not promised after a
      // browser closes and a different account cannot read another's attempt.
      const storedAttempt = initialAttemptId || window.localStorage.getItem(storageKey);
      if (!storedAttempt) return;
      return getJson<AssessmentAttempt>(assessmentAttemptUrl(startUrl, storedAttempt)).then((loadedAttempt) => {
        if (active) loadAttempt(loadedAttempt);
      }).catch(() => window.localStorage.removeItem(storageKey));
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : t("assessmentLoadFailed"));
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [initialAttemptId, loadAttempt, runUrl, startUrl, storageKey, t]);

  React.useEffect(() => {
    const beforeUnload = (event: BeforeUnloadEvent) => {
      if (!controller.hasUnsaved()) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [controller]);

  const start = async () => {
    if (starting) return;
    setStarting(true); setError(""); setNotice("");
    try {
      const loaded = await postJson<AssessmentAttempt>(startUrl, { request_id: newRequestId(), new_attempt: false });
      loadAttempt(loaded);
      window.localStorage.setItem(storageKey, loaded.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("assessmentStartFailed"));
    } finally { setStarting(false); }
  };

  const changeAnswer = (item: AssessmentAttemptItem, next: AssessmentAnswer) => {
    setAnswers((current) => ({ ...current, [item.key]: next }));
    const toSave = wireAnswer(itemType(item), next);
    if (!Object.keys(toSave).length) {
      setStatuses((current) => ({ ...current, [item.key]: "retry" }));
      return;
    }
    controller.queue(item.key, toSave, versionsRef.current[item.key] ?? item.answer_version ?? 0);
  };

  const applyNavigation = React.useCallback((navigation: NonNullable<AssessmentAttempt["navigation"]>) => {
    const current = attemptRef.current;
    if (!current) return;
    const next = { ...current, navigation };
    attemptRef.current = next;
    setAttempt(next);
    const index = next.items.findIndex((item) => item.key === navigation.current_item_key);
    if (index >= 0) setSelected(index);
  }, []);

  const navigateTo = React.useCallback(async (itemKey: string, writeHistory: boolean) => {
    const current = attemptRef.current;
    if (!current?.navigation || current.status !== "in_progress") return;
    setError("");
    try {
      const result = await postJson<NonNullable<AssessmentAttempt["navigation"]>>(
        endpoint(startUrl, current.id, "navigate"),
        { item_key: itemKey, expected_navigation_version: current.navigation.navigation_version },
      );
      applyNavigation(result);
      if (writeHistory) selectItemUrl(itemKey);
    } catch (reason) {
      const apiError = reason as ApiError & { body?: { current?: NonNullable<AssessmentAttempt["navigation"]> } };
      if (apiError.body?.current) {
        applyNavigation(apiError.body.current);
        updateQuery({ item: apiError.body.current.current_item_key }, { replace: true });
      }
      setError(reason instanceof Error ? reason.message : t("assessmentLoadFailed"));
    }
  }, [applyNavigation, selectItemUrl, startUrl, t]);

  React.useEffect(() => {
    if (!attempt || !itemSelection || itemSelection === attempt.navigation?.current_item_key) return;
    if (attempt.items.some((item) => item.key === itemSelection)) void navigateTo(itemSelection, false);
    else updateQuery({ item: attempt.navigation?.current_item_key ?? null }, { replace: true });
  }, [attempt, itemSelection, navigateTo]);

  const advance = async () => {
    const current = attemptRef.current;
    const item = current?.items[selected];
    if (!current || !item || !current.navigation || submitting) return;
    setSubmitting(true); setError("");
    try {
      const allSaved = await controller.flushAll();
      if (!allSaved) throw new Error(t("assessmentSaveBeforeSubmit"));
      const result = await postJson<NonNullable<AssessmentAttempt["navigation"]>>(
        endpoint(startUrl, current.id, "advance"),
        { item_key: item.key, expected_navigation_version: current.navigation.navigation_version },
      );
      applyNavigation(result);
      selectItemUrl(result.current_item_key);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("assessmentLoadFailed"));
    } finally { setSubmitting(false); }
  };

  const submit = async () => {
    if (!attempt || submitting || attempt.status !== "in_progress") return;
    setSubmitting(true); setError(""); setNotice("");
    try {
      const allSaved = await controller.flushAll();
      if (!allSaved) throw new Error(t("assessmentSaveBeforeSubmit"));
      const expectedVersions: Record<string, number> = {};
      for (const item of attempt.items) expectedVersions[item.key] = versionsRef.current[item.key] ?? item.answer_version ?? 0;
      const result = await postJson<AssessmentSubmissionResult>(endpoint(startUrl, attempt.id, "submit"), {
        request_id: newRequestId(),
        expected_versions: expectedVersions,
      });
      const finalItems = Array.isArray(result.items) ? result.items : [];
      const finalAnswers = new Map(finalItems.map((item) => [item.item_key, item]));
      const finalAttempt: AssessmentAttempt = {
        ...attempt,
        ...result,
        status: "submitted",
        items: attempt.items.map((item) => {
          const saved = finalAnswers.get(item.key);
          return saved ? { ...item, answer_version: saved.version, answer: saved.answer } : item;
        }),
      };
      loadAttempt(finalAttempt);
      setNotice(t("assessmentSubmitted"));
      setConfirming(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : t("assessmentSubmitFailed"));
    } finally { setSubmitting(false); }
  };

  if (loading) return <div className="lc-assessment-root"><LanguageSwitcher /><p role="status">{t("loading")}</p></div>;
  return (
    <div className="lc-assessment-root lc-student-assessment-root">
      <LanguageSwitcher />
      {error ? <p className="lc-form-error" role="alert">{error}</p> : null}
      {notice ? <p className="lc-builder-status lc-builder-status-success" role="status">{notice}</p> : null}
      {run ? <header className="lc-student-assessment-header"><p className="lc-kicker">{t("assessmentKicker")}</p><h1>{run.title}</h1>{run.instructions ? <MarkdownView markdown={run.instructions} /> : null}</header> : null}
      {!attempt ? (
        <section className="lc-card lc-student-assessment-landing">
          <p>{t("assessmentStartGuidance")}</p>
          <button type="button" className="lc-btn lc-btn-primary" onClick={() => void start()} disabled={starting}>{starting ? t("assessmentStarting") : t("assessmentStart")}</button>
        </section>
      ) : attempt.status === "submitted" ? (
        <section className="lc-card lc-student-assessment-submitted" data-assessment-submitted>
          <h2>{t("assessmentSubmittedHeading")}</h2>
          <p>{t("assessmentSubmittedDetails")}</p>
          <p className="lc-workspace-meta">{t("assessmentScoresHidden")}</p>
          {historyUrl ? <a className="lc-btn lc-btn-outline" href={historyUrl}>{locale.startsWith("zh") ? "查看作答" : "Review attempt"}</a> : null}
        </section>
      ) : (
        <>
          <div className="lc-student-assessment-layout">
            <nav className="lc-card lc-student-assessment-nav" aria-label={t("assessmentQuestionNavigation")}>
              <h2>{t("assessmentQuestions")}</h2>
              <ol>{attempt.items.map((item, index) => <li key={item.key}><button type="button" className={selected === index ? "lc-assessment-nav-current" : ""} onClick={() => void navigateTo(item.key, true)} disabled={submitting || Boolean(attempt.navigation?.mode === "forward_only" && item.position > attempt.navigation.highest_accessible_item_position)}><span>{item.position}</span>{answers[item.key] && Object.keys(answers[item.key]).length ? <small aria-label={t("assessmentAnswered")}>✓</small> : null}</button></li>)}</ol>
            </nav>
            <main className="lc-student-assessment-main">
              {attempt.items[selected] ? <QuestionCard item={attempt.items[selected]} answer={answers[attempt.items[selected].key] ?? {}} status={statuses[attempt.items[selected].key] ?? "idle"} disabled={submitting || Boolean(attempt.navigation?.mode === "forward_only" && attempt.navigation.locked_item_keys.includes(attempt.items[selected].key))} onChange={(next) => changeAnswer(attempt.items[selected], next)} onRetry={() => controller.retry(attempt.items[selected].key)} /> : <p>{t("assessmentNoQuestions")}</p>}
              <div className="lc-student-assessment-actions">
                <button type="button" className="lc-btn lc-btn-outline" onClick={() => { const prior = attempt.items[selected - 1]; if (prior) void navigateTo(prior.key, true); }} disabled={selected === 0 || submitting}>{t("assessmentPrevious")}</button>
                {selected < attempt.items.length - 1 ? <button type="button" className="lc-btn lc-btn-outline" onClick={() => void advance()} disabled={submitting}>{t("assessmentNext")}</button> : null}
                <button type="button" className="lc-btn lc-btn-primary" onClick={() => setConfirming(true)} disabled={submitting}>{t("assessmentSubmit")}</button>
              </div>
              {confirming ? <section className="lc-card lc-assessment-submit-confirm" role="dialog" aria-modal="false" aria-labelledby="assessment-submit-heading"><h2 id="assessment-submit-heading">{t("assessmentConfirmSubmit")}</h2><p>{t("assessmentConfirmSubmitDetails")}</p><div className="lc-actions"><button type="button" className="lc-btn lc-btn-primary" onClick={() => void submit()} disabled={submitting}>{submitting ? t("assessmentSubmitting") : t("assessmentSubmitNow")}</button><button type="button" className="lc-btn lc-btn-outline" onClick={() => setConfirming(false)} disabled={submitting}>{t("cancel")}</button></div></section> : null}
            </main>
          </div>
        </>
      )}
    </div>
  );
}

type AssessmentSubmissionResult = Omit<AssessmentAttempt, "items"> & {
  items: Array<{ item_key: string; version: number; answer: AssessmentAnswer | null }>;
};

export function mountStudentAssessment(el: HTMLElement): void {
  const runUrl = el.dataset.runUrl;
  const startUrl = el.dataset.startUrl;
  const historyUrl = el.dataset.historyUrl;
  const initialAttemptId = el.dataset.attemptId || "";
  if (!runUrl || !startUrl) return;
  const locale = el.dataset.locale?.startsWith("zh") ? "zh-Hans" : "en";
  const root = createRoot(el);
  root.render(<LocaleProvider initial={locale} root={el}><StudentAssessment runUrl={runUrl} startUrl={startUrl} historyUrl={historyUrl} initialAttemptId={initialAttemptId} /></LocaleProvider>);
  el.addEventListener("liveclassroom:unmount", () => root.unmount(), { once: true });
}
