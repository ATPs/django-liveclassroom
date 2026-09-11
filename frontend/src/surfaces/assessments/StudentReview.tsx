import * as React from "react";
import { createRoot } from "react-dom/client";
import { LanguageSwitcher, LocaleProvider, useLocale } from "../../i18n.js";
import { ApiError, getJson, postJson } from "../../protocol.js";
import { MarkdownView } from "../../activities/MarkdownView.js";
import { routeUrl, updateLocation, useLocationPath, useNavigationHeading, useQuerySelection } from "../../navigation.js";

type ReleaseDimensions = {
  scores: boolean;
  answers: boolean;
  explanations: boolean;
  comments: boolean;
};

export type StudentHistoryRow = {
  id: string;
  run_id: string;
  run_title: string;
  attempt_number: number;
  status: string;
  started_at: string | null;
  submitted_at: string | null;
  deadline_at: string | null;
  can_resume: boolean;
};

type HistoryPayload = {
  items: StudentHistoryRow[];
  total: number;
  next_offset: number | null;
};

type ReviewItem = {
  key: string;
  position: number;
  points: string;
  type_key: string | null;
  content: Record<string, unknown>;
  saved_answer: Record<string, unknown> | null;
  answer_version: number;
  released: ReleaseDimensions;
  result: Record<string, unknown>;
};

export type StudentReviewPayload = {
  id: string;
  run_id: string;
  run_title: string;
  attempt_number: number;
  status: string;
  started_at: string | null;
  submitted_at: string | null;
  released: ReleaseDimensions;
  score?: Record<string, unknown> | null;
  items: ReviewItem[];
};

type AvailablePayload = {
  attempt_available?: boolean;
};

type Copy = {
  history: string;
  review: string;
  back: string;
  historyIntro: string;
  noAttempts: string;
  loading: string;
  unavailable: string;
  retry: string;
  resume: string;
  newAttempt: string;
  starting: string;
  submitted: string;
  inProgress: string;
  attempt: string;
  started: string;
  submittedAt: string;
  answers: string;
  yourAnswer: string;
  answerKey: string;
  score: string;
  explanation: string;
  comments: string;
  notReleased: string;
  notGraded: string;
  awaitingGrading: string;
  noAnswer: string;
  reviewTitle: string;
  reviewUnavailable: string;
  attemptStarted: string;
  requestFailed: string;
};

const COPY: Record<"en" | "zh-Hans", Copy> = {
  en: {
    history: "Assessment history",
    review: "Review attempt",
    back: "Back to history",
    historyIntro: "Resume an active attempt or review work you submitted earlier.",
    noAttempts: "You do not have any assessment attempts yet.",
    loading: "Loading…",
    unavailable: "Assessment history is unavailable.",
    retry: "Retry",
    resume: "Resume",
    newAttempt: "Start a new attempt",
    starting: "Starting…",
    submitted: "Submitted",
    inProgress: "In progress",
    attempt: "Attempt",
    started: "Started",
    submittedAt: "Submitted",
    answers: "Answers",
    yourAnswer: "Your answer",
    answerKey: "Answer key",
    score: "Score",
    explanation: "Explanation",
    comments: "Teacher comments",
    notReleased: "Not released yet.",
    notGraded: "Not graded yet.",
    awaitingGrading: "Awaiting grading.",
    noAnswer: "No answer recorded.",
    reviewTitle: "Retained review",
    reviewUnavailable: "This review is unavailable.",
    attemptStarted: "Attempt started.",
    requestFailed: "The request failed.",
  },
  "zh-Hans": {
    history: "测验历史",
    review: "查看作答",
    back: "返回历史",
    historyIntro: "继续未完成的作答，或查看之前提交的内容。",
    noAttempts: "你还没有测验记录。",
    loading: "加载中…",
    unavailable: "测验历史暂时不可用。",
    retry: "重试",
    resume: "继续作答",
    newAttempt: "开始新的作答",
    starting: "正在开始…",
    submitted: "已提交",
    inProgress: "进行中",
    attempt: "第几次作答",
    started: "开始时间",
    submittedAt: "提交时间",
    answers: "答案",
    yourAnswer: "你的答案",
    answerKey: "参考答案",
    score: "得分",
    explanation: "解析",
    comments: "教师评语",
    notReleased: "教师尚未发布。",
    notGraded: "尚未评分。",
    awaitingGrading: "等待评分。",
    noAnswer: "没有记录答案。",
    reviewTitle: "保留的作答记录",
    reviewUnavailable: "该作答记录不可用。",
    attemptStarted: "已开始新的作答。",
    requestFailed: "请求失败。",
  },
};

function copyFor(locale: string): Copy {
  return COPY[locale.startsWith("zh") ? "zh-Hans" : "en"];
}

function object(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function text(value: unknown): string {
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

function displayDate(value: string | null, locale: string): string {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return new Intl.DateTimeFormat(locale.startsWith("zh") ? "zh-CN" : "en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(parsed);
}

function displayAnswer(value: unknown, content: Record<string, unknown>): string {
  if (value === null || value === undefined || value === "") return "";
  const answer = object(value);
  const options = Array.isArray(content.options) ? content.options : [];
  const labels = new Map(options.flatMap((option) => {
    const row = object(option);
    const id = text(row.id || row.value);
    const label = text(row.text || row.label || row.value);
    return id ? [[id, label || id] as [string, string]] : [];
  }));
  const labelValue = (raw: unknown): string => {
    const key = text(raw);
    return labels.get(key) || key;
  };
  if (typeof answer.choice === "string" || typeof answer.choice === "number") return labelValue(answer.choice);
  if (Array.isArray(answer.choices)) return answer.choices.map(labelValue).join(", ");
  if (Array.isArray(answer.ranking)) return answer.ranking.map(labelValue).join(" → ");
  if (typeof answer.text === "string" || typeof answer.text === "number") return String(answer.text);
  if (answer.value !== undefined && answer.value !== null) return String(answer.value);
  if (answer.rating !== undefined && answer.rating !== null) return String(answer.rating);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function answerKeyText(value: unknown, content: Record<string, unknown>): string {
  if (Array.isArray(value)) return value.map((entry) => displayAnswer(entry, content)).join(", ");
  return displayAnswer(value, content);
}

function itemMarkdown(content: Record<string, unknown>): string {
  for (const key of ["prompt", "stem_markdown", "stem", "markdown"]) {
    const value = content[key];
    if (typeof value === "string") return value;
  }
  const question = object(content.question);
  return text(question.prompt || question.text);
}

function itemType(typeKey: string | null): string {
  return text(typeKey).split(".").pop() || "";
}

function urlFor(template: string, id: string): string {
  const encoded = encodeURIComponent(id);
  if (template.includes("__id__")) return template.replace("__id__", encoded);
  // The view supplies a UUID placeholder, but retaining this fallback keeps
  // the component usable from a host template that uses a different marker.
  return template.replace(/[0-9a-f]{8}-[0-9a-f-]{27,}/i, encoded);
}

function requestId(): string {
  return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function ReleasedValue({
  label,
  value,
  children,
}: {
  label: string;
  value: unknown;
  children?: React.ReactNode;
}) {
  return (
    <div className="lc-review-value">
      <dt>{label}</dt>
      <dd>{children ?? (value === null || value === undefined || value === "" ? "—" : String(value))}</dd>
    </div>
  );
}

function ReviewCard({ item, copy, locale, selected, onSelect }: { item: ReviewItem; copy: Copy; locale: string; selected: boolean; onSelect: (key: string) => void }) {
  const content = object(item.content);
  const result = object(item.result);
  const hasScore = Object.prototype.hasOwnProperty.call(result, "score");
  const hasAnswerKey = Object.prototype.hasOwnProperty.call(result, "answer_key");
  const hasExplanation = Object.prototype.hasOwnProperty.call(result, "explanation");
  const hasComment = Object.prototype.hasOwnProperty.call(result, "comment");
  const markdown = itemMarkdown(content);
  const score = object(result.score);
  const ownAnswer = displayAnswer(item.saved_answer, content);
  return (
    <article className={`lc-card lc-student-review-item${selected ? " lc-assessment-selected" : ""}`} data-review-item={item.key}>
      <header className="lc-student-review-item-heading">
        <button type="button" className="lc-assessment-item-number" aria-label={`${copy.answers} ${item.position}`} aria-current={selected ? "true" : undefined} onClick={() => onSelect(item.key)}>{item.position}</button>
        <div>
          <h2>{copy.answers} {item.position}</h2>
          <p className="lc-workspace-meta">{itemType(item.type_key)} · {item.points}</p>
        </div>
      </header>
      {markdown ? <MarkdownView markdown={markdown} /> : null}
      <dl className="lc-student-review-details">
        <ReleasedValue label={copy.yourAnswer} value={ownAnswer || copy.noAnswer} />
        {item.released.answers && hasAnswerKey ? (
          <ReleasedValue label={copy.answerKey} value={answerKeyText(result.answer_key, content)} />
        ) : null}
        {item.released.scores && hasScore ? (
          <ReleasedValue label={copy.score} value={null}>
            <span>{text(score.awarded_points) || "0"} / {text(score.possible_points) || item.points}</span>
          </ReleasedValue>
        ) : null}
        {item.released.explanations && hasExplanation ? (
          <ReleasedValue label={copy.explanation} value={null}>
            <MarkdownView markdown={text(result.explanation)} />
          </ReleasedValue>
        ) : null}
        {item.released.comments && hasComment ? (
          <ReleasedValue label={copy.comments} value={text(result.comment) || "—"} />
        ) : null}
      </dl>
      <p className="lc-workspace-meta" aria-live="polite">
        {item.released.scores && !hasScore ? copy.awaitingGrading : !item.released.scores ? copy.notGraded : ""}
      </p>
    </article>
  );
}

function StudentReview({
  historyUrl,
  reviewUrlTemplate,
  startUrlTemplate,
  availableUrlTemplate,
  assessmentUrlTemplate,
  exportUrlTemplate,
  reviewPageUrlTemplate,
  historyPageUrl,
}: {
  historyUrl: string;
  reviewUrlTemplate: string;
  startUrlTemplate: string;
  availableUrlTemplate: string;
  assessmentUrlTemplate: string;
  exportUrlTemplate: string;
  reviewPageUrlTemplate: string;
  historyPageUrl: string;
}) {
  const locale = useLocale();
  const copy = copyFor(locale);
  const [history, setHistory] = React.useState<StudentHistoryRow[]>([]);
  const [selected, setSelected] = React.useState<StudentReviewPayload | null>(null);
  const [availability, setAvailability] = React.useState<Record<string, boolean>>({});
  const [loading, setLoading] = React.useState(true);
  const [busy, setBusy] = React.useState<string | null>(null);
  const [error, setError] = React.useState("");
  const [notice, setNotice] = React.useState("");
  const [itemSelection, selectItemUrl] = useQuerySelection("item");
  const locationPath = useLocationPath();
  useNavigationHeading("lc-student-review-heading");
  const routeAttemptId = React.useMemo(() => {
    const match = new URL(locationPath, window.location.href).pathname.match(/\/learn\/attempts\/([0-9a-f-]+)\/review\/?$/i);
    return match ? match[1] : null;
  }, [locationPath]);

  const assessmentUrl = React.useCallback((runId: string) => urlFor(assessmentUrlTemplate, runId), [assessmentUrlTemplate]);
  const exportUrl = React.useCallback((attemptId: string) => urlFor(exportUrlTemplate, attemptId), [exportUrlTemplate]);
  const availableUrl = React.useCallback((runId: string) => urlFor(availableUrlTemplate, runId), [availableUrlTemplate]);

  const loadHistory = React.useCallback(() => {
    setLoading(true);
    setError("");
    void getJson<HistoryPayload>(historyUrl)
      .then((payload) => {
        const rows = Array.isArray(payload.items) ? payload.items : [];
        setHistory(rows);
        const runIds = [...new Set(rows.map((row) => row.run_id))];
        return Promise.all(runIds.map(async (runId) => {
          try {
            const metadata = await getJson<AvailablePayload>(availableUrl(runId));
            return [runId, metadata.attempt_available !== false] as const;
          } catch {
            // A history row remains reviewable even when availability metadata
            // is temporarily unavailable. Starting still rechecks server-side.
            return [runId, false] as const;
          }
        }));
      })
      .then((rows) => setAvailability(Object.fromEntries(rows)))
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : copy.unavailable))
      .finally(() => setLoading(false));
  }, [availableUrl, copy.unavailable, historyUrl]);

  React.useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  const openAttempt = (row: StudentHistoryRow) => {
    window.localStorage.setItem(`liveclassroom-assessment-attempt:${availableUrl(row.run_id)}`, row.id);
    window.location.assign(assessmentUrl(row.run_id));
  };

  const loadReview = React.useCallback((attemptId: string) => {
    setBusy(attemptId);
    setError("");
    void getJson<StudentReviewPayload>(urlFor(reviewUrlTemplate, attemptId))
      .then((payload) => setSelected(payload))
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : copy.reviewUnavailable))
      .finally(() => setBusy(null));
  }, [copy.reviewUnavailable, reviewUrlTemplate]);

  React.useEffect(() => {
    if (!routeAttemptId) { setSelected(null); return; }
    if (selected?.id !== routeAttemptId) loadReview(routeAttemptId);
  }, [loadReview, routeAttemptId, selected?.id]);

  React.useEffect(() => {
    if (!selected || !itemSelection || !selected.items.some((item) => item.key === itemSelection)) return;
    window.requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-review-item="${itemSelection}"]`)?.scrollIntoView({ block: "nearest" }));
  }, [itemSelection, selected]);

  const openReview = (row: StudentHistoryRow) => {
    updateLocation(routeUrl(urlFor(reviewPageUrlTemplate, row.id), { item: null }), { focusId: "lc-student-review-heading" });
  };

  const startNewAttempt = (row: StudentHistoryRow) => {
    setBusy(row.id);
    setError("");
    void postJson<{ id: string }>(urlFor(startUrlTemplate, row.run_id), { request_id: requestId(), new_attempt: true }, requestId())
      .then((payload) => {
        setNotice(copy.attemptStarted);
        window.localStorage.setItem(`liveclassroom-assessment-attempt:${availableUrl(row.run_id)}`, payload.id);
        window.location.assign(assessmentUrl(row.run_id));
      })
      .catch((reason: unknown) => {
        setError(reason instanceof ApiError ? reason.message : reason instanceof Error ? reason.message : copy.requestFailed);
      })
      .finally(() => setBusy(null));
  };

  if (selected) {
    const released = selected.released;
    return (
      <div className="lc-assessment-root lc-student-review-root">
        <LanguageSwitcher />
        <div className="lc-actions lc-student-review-toolbar">
          <button type="button" className="lc-btn lc-btn-outline" onClick={() => updateLocation(routeUrl(historyPageUrl, { item: null }), { focusId: "lc-student-review-heading" })}>{copy.back}</button>
          <a href={assessmentUrl(selected.run_id)}>{copy.resume}</a>
        </div>
        <header className="lc-student-assessment-header">
          <p className="lc-kicker">{copy.review}</p>
          <h1 id="lc-student-review-heading" tabIndex={-1}>{selected.run_title}</h1>
          <p className="lc-workspace-meta">{copy.attempt} {selected.attempt_number} · {selected.status === "submitted" ? copy.submitted : copy.inProgress}</p>
          {selected.submitted_at ? <p className="lc-workspace-meta">{copy.submittedAt}: {displayDate(selected.submitted_at, locale)}</p> : null}
          {selected.status === "submitted" ? <a className="lc-btn lc-btn-outline" href={`${exportUrl(selected.id)}?format=csv`}>{locale.startsWith("zh") ? "下载作答记录" : "Download my result"}</a> : null}
          {released.scores && selected.score ? <p className="lc-student-review-summary">{copy.score}: {text(selected.score.awarded_points) || "0"} / {text(selected.score.possible_points) || "—"}</p> : null}
        </header>
        <section className="lc-student-review-list" aria-label={copy.reviewTitle}>
          <h2>{copy.reviewTitle}</h2>
          {selected.items.slice().sort((a, b) => a.position - b.position).map((item) => <ReviewCard key={item.key} item={item} copy={copy} locale={locale} selected={itemSelection === item.key} onSelect={selectItemUrl} />)}
        </section>
      </div>
    );
  }

  return (
    <div className="lc-assessment-root lc-student-review-root">
      <LanguageSwitcher />
      <header className="lc-student-assessment-header">
        <p className="lc-kicker">{copy.history}</p>
        <h1 id="lc-student-review-heading" tabIndex={-1}>{copy.history}</h1>
        <p>{copy.historyIntro}</p>
      </header>
      {notice ? <p className="lc-builder-status lc-builder-status-success" role="status">{notice}</p> : null}
      {error ? <p className="lc-form-error" role="alert">{error} <button type="button" className="lc-btn-sm lc-btn-outline" onClick={loadHistory}>{copy.retry}</button></p> : null}
      {loading ? <p role="status">{copy.loading}</p> : history.length === 0 ? <section className="lc-card"><p>{copy.noAttempts}</p></section> : (
        <section className="lc-student-review-history" aria-label={copy.history}>
          {history.map((row) => {
            const isBusy = busy === row.id;
            const canStart = availability[row.run_id] !== false;
            return (
              <article className="lc-card lc-student-review-history-row" key={row.id} data-attempt-id={row.id}>
                <div>
                  <h2>{row.run_title}</h2>
                  <p className="lc-workspace-meta">{copy.attempt} {row.attempt_number} · {row.can_resume ? copy.inProgress : copy.submitted}</p>
                  <p className="lc-workspace-meta">{copy.started}: {displayDate(row.started_at, locale)}{row.submitted_at ? ` · ${copy.submittedAt}: ${displayDate(row.submitted_at, locale)}` : ""}</p>
                </div>
                <div className="lc-actions">
                  {row.can_resume ? <button type="button" className="lc-btn lc-btn-primary" onClick={() => openAttempt(row)} disabled={isBusy}>{copy.resume}</button> : <button type="button" className="lc-btn lc-btn-outline" onClick={() => openReview(row)} disabled={isBusy}>{isBusy ? copy.loading : copy.review}</button>}
                  {!row.can_resume && canStart ? <button type="button" className="lc-btn lc-btn-outline" onClick={() => startNewAttempt(row)} disabled={isBusy}>{isBusy ? copy.starting : copy.newAttempt}</button> : null}
                </div>
              </article>
            );
          })}
        </section>
      )}
    </div>
  );
}

export function mountStudentReview(el: HTMLElement): void {
  const historyUrl = el.dataset.historyUrl;
  const reviewUrlTemplate = el.dataset.reviewUrlTemplate;
  const startUrlTemplate = el.dataset.startUrlTemplate;
  const availableUrlTemplate = el.dataset.availableUrlTemplate;
  const assessmentUrlTemplate = el.dataset.assessmentUrlTemplate;
  const exportUrlTemplate = el.dataset.exportUrlTemplate;
  const reviewPageUrlTemplate = el.dataset.reviewPageUrlTemplate;
  const historyPageUrl = el.dataset.historyPageUrl;
  if (!historyUrl || !reviewUrlTemplate || !startUrlTemplate || !availableUrlTemplate || !assessmentUrlTemplate || !exportUrlTemplate || !reviewPageUrlTemplate || !historyPageUrl) return;
  const locale = el.dataset.locale?.startsWith("zh") ? "zh-Hans" : "en";
  const root = createRoot(el);
  root.render(
    <LocaleProvider initial={locale} root={el}>
      <StudentReview
        historyUrl={historyUrl}
        reviewUrlTemplate={reviewUrlTemplate}
        startUrlTemplate={startUrlTemplate}
        availableUrlTemplate={availableUrlTemplate}
        assessmentUrlTemplate={assessmentUrlTemplate}
        exportUrlTemplate={exportUrlTemplate}
        reviewPageUrlTemplate={reviewPageUrlTemplate}
        historyPageUrl={historyPageUrl}
      />
    </LocaleProvider>,
  );
  el.addEventListener("liveclassroom:unmount", () => root.unmount(), { once: true });
}
