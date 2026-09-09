import * as React from "react";
import { useCallback, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";

import { MarkdownView } from "../../activities/MarkdownView.js";
import { ApiError, getJson, postJson } from "../../protocol.js";
import { LocaleProvider, useLocale } from "../../i18n.js";

type ManualDecision = {
  status?: string;
  normalized_score?: string | null;
  awarded_points?: string | null;
  possible_points?: string | null;
  source?: string;
  comment?: string;
  reason?: string;
};

export type ManualGradingItem = {
  attempt_id: string;
  item_key: string;
  run_id: string;
  run_title: string;
  student_id: number;
  student_username: string;
  prompt: string;
  answer?: { text?: string } | string | null;
  possible_points: string;
  status: string;
  normalized_score?: string | null;
  awarded_points?: string | null;
  comment?: string;
  decision?: ManualDecision;
};

type ManualGradingQueueProps = { apiRoot: string };

function endpoint(apiRoot: string, path: string): string {
  const base = new URL(apiRoot, window.location.href);
  if (!base.pathname.endsWith("/")) base.pathname += "/";
  return new URL(path.replace(/^\/+/, ""), base).toString();
}

function normalizeApiRoot(value: string): string {
  const base = new URL(value, window.location.href);
  base.pathname = base.pathname.replace(/workspace\/?$/, "");
  if (!base.pathname.endsWith("/")) base.pathname += "/";
  base.search = "";
  base.hash = "";
  return base.toString();
}

function text(locale: string, en: string, zh: string): string {
  return locale.startsWith("zh") ? zh : en;
}

function requestKey(): string {
  const id = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `manual-grade-${id}`;
}

function answerText(answer: ManualGradingItem["answer"]): string {
  if (typeof answer === "string") return answer;
  if (answer && typeof answer === "object" && typeof answer.text === "string") return answer.text;
  if (answer === null || answer === undefined) return "";
  try {
    return JSON.stringify(answer);
  } catch {
    return "";
  }
}

function decimal(value: string): number | null {
  if (!value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function ManualGradingCard({
  item,
  apiRoot,
  locale,
  onSaved,
}: {
  item: ManualGradingItem;
  apiRoot: string;
  locale: string;
  onSaved: () => void;
}) {
  const possible = decimal(item.possible_points) ?? 0;
  const [awarded, setAwarded] = useState(item.awarded_points ?? "");
  const [comment, setComment] = useState(item.comment ?? "");
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const save = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const points = decimal(awarded);
    if (points === null || points < 0 || points > possible) {
      setError(text(locale, `Awarded points must be between 0 and ${item.possible_points}.`, `得分必须在 0 到 ${item.possible_points} 之间。`));
      return;
    }
    if (!reason.trim()) {
      setError(text(locale, "A grading reason is required.", "请填写评分理由。"));
      return;
    }
    if (comment.length > 4000) {
      setError(text(locale, "Comment is too long.", "评语过长。"));
      return;
    }
    setSaving(true);
    setError("");
    try {
      await postJson(
        endpoint(apiRoot, `attempts/${item.attempt_id}/items/${item.item_key}/manual-grade/`),
        { normalized_score: String(points / possible), comment, reason },
        requestKey(),
      );
      onSaved();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : text(locale, "Unable to save this grade. Your entry is still here.", "无法保存评分，当前输入仍保留。"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <article className="lc-card lc-manual-grade-card" data-manual-grade-item={item.item_key}>
      <header className="lc-manual-grade-heading">
        <div>
          <p className="lc-kicker">{item.run_title}</p>
          <h3>{item.student_username}</h3>
        </div>
        <span className="lc-badge">{text(locale, "Pending", "待评分")}</span>
      </header>
      <section className="lc-manual-grade-prompt" aria-label={text(locale, "Retained prompt", "保留题干")}>
        <h4>{text(locale, "Prompt", "题干")}</h4>
        <MarkdownView markdown={item.prompt} />
      </section>
      <section className="lc-manual-grade-answer" aria-label={text(locale, "Student answer", "学生答案")}>
        <h4>{text(locale, "Student answer", "学生答案")}</h4>
        <pre>{answerText(item.answer) || text(locale, "No answer submitted.", "未提交答案。")}</pre>
      </section>
      <form className="lc-manual-grade-form" onSubmit={save}>
        <div className="lc-manual-grade-points">
          <label>
            {text(locale, "Awarded points", "得分")}
            <input
              aria-label={text(locale, "Awarded points", "得分")}
              className="lc-input"
              inputMode="decimal"
              min="0"
              max={item.possible_points}
              step="0.01"
              value={awarded}
              onChange={(event) => setAwarded(event.currentTarget.value)}
              disabled={saving}
              required
            />
            <span>{text(locale, `of ${item.possible_points}`, `满分 ${item.possible_points}`)}</span>
          </label>
        </div>
        <label>
          {text(locale, "Comment", "评语")}
          <textarea className="lc-textarea" rows={3} maxLength={4000} value={comment} onChange={(event) => setComment(event.currentTarget.value)} disabled={saving} />
        </label>
        <label>
          {text(locale, "Reason", "评分理由")}
          <input className="lc-input" maxLength={255} value={reason} onChange={(event) => setReason(event.currentTarget.value)} disabled={saving} required />
        </label>
        {error ? <p className="lc-form-error" role="alert">{error}</p> : null}
        <button type="submit" className="lc-btn lc-btn-primary" disabled={saving}>
          {saving ? text(locale, "Saving…", "保存中…") : text(locale, "Save grade", "保存评分")}
        </button>
      </form>
    </article>
  );
}

export function ManualGradingQueue({ apiRoot }: ManualGradingQueueProps) {
  const locale = useLocale();
  const [items, setItems] = useState<ManualGradingItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setError("");
    try {
      const response = await getJson<{ items?: ManualGradingItem[] }>(endpoint(apiRoot, "grading/queue/"));
      setItems(response.items ?? []);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : text(locale, "Unable to load the grading queue.", "无法加载评分队列。"));
    } finally {
      setLoading(false);
    }
  }, [apiRoot, locale]);

  useEffect(() => {
    setLoading(true);
    void load();
  }, [load]);

  return (
    <section className="lc-manual-grading-queue" aria-labelledby="manual-grading-heading">
      <header className="lc-manual-grading-header">
        <div>
          <p className="lc-kicker">{text(locale, "Teacher grading", "教师评分")}</p>
          <h2 id="manual-grading-heading">{text(locale, "Manual grading queue", "人工评分队列")}</h2>
          <p>{text(locale, `${items.length} pending response${items.length === 1 ? "" : "s"}`, `待评分答案 ${items.length} 项`)}</p>
        </div>
        <button type="button" className="lc-btn lc-btn-outline" onClick={() => void load()} disabled={loading}>
          {text(locale, "Refresh", "刷新")}
        </button>
      </header>
      {error ? <p className="lc-form-error" role="alert">{error}</p> : null}
      {loading ? <p role="status">{text(locale, "Loading…", "加载中…")}</p> : null}
      {!loading && !error && !items.length ? <p className="lc-card lc-empty-notice">{text(locale, "No submitted responses need grading.", "没有待评分的已提交答案。")}</p> : null}
      <div className="lc-manual-grading-list">
        {items.map((item) => <ManualGradingCard key={`${item.attempt_id}-${item.item_key}`} item={item} apiRoot={apiRoot} locale={locale} onSaved={() => void load()} />)}
      </div>
    </section>
  );
}

export function mountManualGradingQueue(el: HTMLElement): void {
  const rawApiRoot = el.dataset.apiRoot;
  if (!rawApiRoot) return;
  const apiRoot = normalizeApiRoot(rawApiRoot);
  const locale = el.dataset.locale?.startsWith("zh") ? "zh-Hans" : "en";
  const root = createRoot(el);
  root.render(<LocaleProvider initial={locale} root={el}><ManualGradingQueue apiRoot={apiRoot} /></LocaleProvider>);
  el.addEventListener("liveclassroom:unmount", () => root.unmount(), { once: true });
}
