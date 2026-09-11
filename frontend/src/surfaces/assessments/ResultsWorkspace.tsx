import * as React from "react";
import { createRoot } from "react-dom/client";

import { LocaleProvider, useLocale } from "../../i18n.js";
import { getJson } from "../../protocol.js";
import { Breadcrumbs, preserveLocale, useNavigationHeading, useQuerySelection } from "../../navigation.js";
import { ManualGradingQueue } from "./ManualGradingQueue.js";

type Run = { public_id: string; title: string; counts: Record<string, number>; completion: { completed: number; denominator: number } };
type Student = { student_id: number; student_username: string; cells: Record<string, { state: string; earned_points?: string | null; possible_points?: string | null }> };
type Summary = { scope: { title: string }; overall: { graded_count: number; pending_count: number; percent?: string | null }; runs: Run[]; students: Student[]; roster: { denominator: number } };
type NavigationContext = { kind: string; id: number; title: string; results_url?: string };
type NavigationPayload = { contexts?: NavigationContext[] };
const text = (locale: string, en: string, zh: string) => locale.startsWith("zh") ? zh : en;

function GlobalResultsWorkspace({ apiRoot, navigationUrl }: { apiRoot: string; navigationUrl: string }) {
  const locale = useLocale();
  const tr = (en: string, zh: string) => text(locale, en, zh);
  const [contexts, setContexts] = React.useState<NavigationContext[] | null>(null);
  const [error, setError] = React.useState("");
  useNavigationHeading("lc-results-heading");

  React.useEffect(() => {
    let active = true;
    setError("");
    void getJson<NavigationPayload>(navigationUrl).then((payload) => {
      if (active) setContexts(Array.isArray(payload.contexts) ? payload.contexts : []);
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : text(locale, "Results are unavailable.", "结果不可用。"));
    });
    return () => { active = false; };
  }, [navigationUrl, locale]);

  const resultContexts = (contexts ?? []).filter((context) => Boolean(context.results_url));
  return <div className="lc-results-root lc-global-results-root">
    <header className="lc-builder-topbar">
      <div>
        <p className="lc-kicker">{tr("Teaching", "教学")}</p>
        <h1 id="lc-results-heading" tabIndex={-1}>{tr("Results and grading", "结果与评分")}</h1>
        <p>{tr("Review class outcomes and finish responses that need manual grading.", "查看班级结果，并完成需要人工评分的答案。")}</p>
      </div>
    </header>
    {error ? <p className="lc-form-error" role="alert">{error}</p> : null}
    <section className="lc-results-destinations" aria-labelledby="lc-results-destinations-heading">
      <header className="lc-manual-grading-header">
        <div>
          <p className="lc-kicker">{tr("Authorized spaces", "已授权空间")}</p>
          <h2 id="lc-results-destinations-heading">{tr("Class results", "班级结果")}</h2>
        </div>
      </header>
      {contexts === null && !error ? <p role="status">{tr("Loading classes…", "正在加载班级…")}</p> : null}
      {contexts !== null && !resultContexts.length ? <p className="lc-card lc-empty-notice">{tr("No class result summaries are available yet.", "目前没有可用的班级结果摘要。")}</p> : null}
      {resultContexts.length ? <ul className="lc-data-list">{resultContexts.map((context) => <li key={`${context.kind}-${context.id}`}><a className="lc-data-list-row" href={context.results_url}>{context.title}<span aria-hidden="true">→</span></a></li>)}</ul> : null}
    </section>
    <ManualGradingQueue apiRoot={apiRoot} />
  </div>;
}

function ResultsWorkspace({ summaryUrl, parentUrl }: { summaryUrl: string; parentUrl: string }) {
  const locale = useLocale();
  const tr = (en: string, zh: string) => text(locale, en, zh);
  const [summary, setSummary] = React.useState<Summary | null>(null);
  const [error, setError] = React.useState("");
  const [runSelection, selectRunUrl] = useQuerySelection("run");
  useNavigationHeading("lc-results-heading");
  React.useEffect(() => {
    let active = true;
    void getJson<Summary>(summaryUrl).then((payload) => { if (active) setSummary(payload); }).catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : tr("Results are unavailable.", "结果不可用。")); });
    return () => { active = false; };
  }, [summaryUrl, tr]);
  if (!summary) return <div className="lc-results-root"><p role="status">{error || tr("Loading results…", "正在加载结果…")}</p></div>;
  const selectedRun = summary.runs.find((run) => run.public_id === runSelection) ?? null;
  const visibleRuns = selectedRun ? [selectedRun] : summary.runs;
  return <div className="lc-results-root"><Breadcrumbs items={[{ href: parentUrl, label: tr("Class", "班级") }, { label: tr("Results", "结果") }]} />
    <header className="lc-builder-topbar"><div><p className="lc-kicker">{tr("Assessment results", "测验结果")}</p><h1 id="lc-results-heading" tabIndex={-1}>{summary.scope.title}</h1><p>{tr(`${summary.overall.graded_count} graded, ${summary.overall.pending_count} pending`, `已评分 ${summary.overall.graded_count}，待处理 ${summary.overall.pending_count}`)}</p></div><a className="lc-btn lc-btn-outline" href={preserveLocale(parentUrl)}>{tr("Back to class", "返回班级")}</a></header>
    {error ? <p className="lc-form-error" role="alert">{error}</p> : null}
    <section className="lc-card lc-results-summary"><p>{tr("Roster", "名册")}: {summary.roster.denominator}</p><p>{tr("Overall graded score", "已评分总成绩")}: {summary.overall.percent ?? "—"}%</p></section>
    <section className="lc-results-runs" aria-label={tr("Published assessments", "已发布测验")}><h2>{tr("Published assessments", "已发布测验")}</h2>{summary.runs.length ? <div className="lc-actions">{summary.runs.map((run) => <button key={run.public_id} type="button" className={run.public_id === selectedRun?.public_id ? "lc-btn lc-btn-primary" : "lc-btn lc-btn-outline"} onClick={() => selectRunUrl(run.public_id)}>{run.title}</button>)}{selectedRun ? <button type="button" className="lc-btn lc-btn-outline" onClick={() => selectRunUrl("")}>{tr("All assessments", "全部测验")}</button> : null}</div> : <p>{tr("No published assessments yet.", "尚无已发布测验。")}</p>}</section>
    {visibleRuns.map((run) => <section className="lc-card lc-results-run" key={run.public_id} data-result-run={run.public_id}><h2>{run.title}</h2><p>{tr("Completed", "已完成")}: {run.completion.completed}/{run.completion.denominator} · {tr("Graded", "已评分")}: {run.counts.graded ?? 0} · {tr("Pending", "待处理")}: {run.counts.pending ?? 0}</p><div className="lc-results-table-wrap"><table><thead><tr><th>{tr("Student", "学生")}</th><th>{tr("Status", "状态")}</th><th>{tr("Score", "成绩")}</th></tr></thead><tbody>{summary.students.map((student) => { const cell = student.cells[run.public_id]; return <tr key={student.student_id}><td>{student.student_username}</td><td>{cell?.state ?? "not_started"}</td><td>{cell?.earned_points == null ? "—" : `${cell.earned_points}/${cell.possible_points ?? "—"}`}</td></tr>; })}</tbody></table></div></section>)}
  </div>;
}

export function mountResultsWorkspace(element: HTMLElement): void {
  const mode = element.dataset.mode;
  if (mode === "global") {
    const apiRoot = element.dataset.apiRoot;
    const navigationUrl = element.dataset.navigationUrl;
    if (!apiRoot || !navigationUrl) return;
    const locale = element.dataset.locale?.startsWith("zh") ? "zh-Hans" : "en";
    createRoot(element).render(<LocaleProvider initial={locale} root={element}><GlobalResultsWorkspace apiRoot={apiRoot} navigationUrl={navigationUrl} /></LocaleProvider>);
    return;
  }
  const summaryUrl = element.dataset.summaryUrl;
  const parentUrl = element.dataset.parentUrl;
  if (!summaryUrl || !parentUrl) return;
  const locale = element.dataset.locale?.startsWith("zh") ? "zh-Hans" : "en";
  createRoot(element).render(<LocaleProvider initial={locale} root={element}><ResultsWorkspace summaryUrl={summaryUrl} parentUrl={parentUrl} /></LocaleProvider>);
}
