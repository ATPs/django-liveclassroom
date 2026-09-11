import * as React from "react";
import { createRoot } from "react-dom/client";
import { LocaleProvider, useLocale } from "../../i18n.js";
import { ApiError, getJson } from "../../protocol.js";
import { Breadcrumbs, NavigationLink, routeUrl, updateQuery, useLocationPath, useNavigationHeading } from "../../navigation.js";
import { MarkdownView } from "../../activities/MarkdownView.js";
import { ManualGradingQueue } from "./ManualGradingQueue.js";
import { ResultGradeOverride } from "./ResultGradeOverride.js";

type Page<T> = { items: T[]; count: number; page: number; page_size: number; next: string | null; previous: string | null };
type Run = { public_id: string; title: string; attempts_url: string };
type Grade = { status: string; awarded_points: string | null; possible_points: string | null; feedback?: string };
type Item = { item_key: string; position: number; prompt: string; answer: unknown; possible_points: string; grade_fingerprint: string; override_url: string | null; current_grade: Grade | null; grade_decisions: Array<{ created_at: string; source: string; awarded_points: string | null; comment: string; reason: string }> };
type Attempt = { attempt_id: string; run_id: string; run_title: string; student_identifier: string; attempt_number: number; status: string; earned_points: string | null; possible_points: string | null; detail_url?: string | null; items?: Item[] };
type Summary = { scope: { title: string }; overall: { graded_count: number; pending_count: number; percent: string | null }; roster: { denominator: number } };
type Context = { kind: string; id: number; title: string; results_url?: string };

function useRead<T>(url: string | null) {
  const [state, setState] = React.useState<{ url: string | null; data: T | null; error: string; status?: number }>({ url: null, data: null, error: "" });
  const [revision, retry] = React.useReducer((value: number) => value + 1, 0);
  React.useEffect(() => {
    if (state.data) window.dispatchEvent(new Event("liveclassroom:content-ready"));
  }, [state.data]);
  React.useEffect(() => {
    let active = true;
    setState({ url, data: null, error: "" });
    if (url) void getJson<T>(url).then(data => {
      if (active) setState({ url, data, error: "" });
    }).catch((cause: unknown) => {
      if (active) setState({ url, data: null, error: cause instanceof Error ? cause.message : "Unavailable", status: cause instanceof ApiError ? cause.status : undefined });
    });
    return () => { active = false; };
  }, [url, revision]);
  return { data: state.url === url ? state.data : null, error: state.url === url ? state.error : "", status: state.url === url ? state.status : undefined, retry };
}

function apiUrl(root: string, path: string): string {
  const base = new URL(root, window.location.href);
  base.pathname = base.pathname.replace(/workspace\/?$/, "");
  if (!base.pathname.endsWith("/")) base.pathname += "/";
  base.search = "";
  base.hash = "";
  return new URL(path, base).toString();
}

function Pager({ page, name }: { page: Page<unknown>; name: string }) {
  const zh = useLocale().startsWith("zh");
  return <nav className="lc-actions" aria-label={zh ? "分页" : "Pagination"}>
    <button className="lc-btn lc-btn-outline" disabled={!page.previous} onClick={() => updateQuery({ [name]: page.page - 1 })}>{zh ? "上一页" : "Previous"}</button>
    <span>{page.page} / {Math.max(1, Math.ceil(page.count / page.page_size))} · {page.count}</span>
    <button className="lc-btn lc-btn-outline" disabled={!page.next} onClick={() => updateQuery({ [name]: page.page + 1 })}>{zh ? "下一页" : "Next"}</button>
  </nav>;
}

function ReadState({ error, retry }: { error: string; retry: () => void }) {
  const zh = useLocale().startsWith("zh");
  return error ? <div role="alert"><p>{zh ? "所选内容不可用。" : "The selected content is unavailable."}</p><button className="lc-btn lc-btn-outline" onClick={retry}>{zh ? "重试" : "Retry"}</button></div> : <p role="status">{zh ? "加载中…" : "Loading…"}</p>;
}

function Submission({ url, runId, itemKey, panel, onGradeSaved }: { url: string; runId: string; itemKey: string; panel: string; onGradeSaved: () => void }) {
  const zh = useLocale().startsWith("zh");
  const { data, error, retry, status } = useRead<Attempt>(url);
  const items = data?.run_id === runId ? data.items ?? [] : [];
  const selected = items.find(item => item.item_key === itemKey) ?? items[0];
  React.useEffect(() => {
    if (status === 404 || (data && data.run_id !== runId)) {
      updateQuery({ attempt: null, item: null }, { replace: true });
    }
  }, [data, runId, status]);
  React.useEffect(() => {
    if (data?.run_id === runId && itemKey && !items.some(item => item.item_key === itemKey)) updateQuery({ item: items[0]?.item_key ?? null }, { replace: true });
  }, [data, runId, itemKey]);
  if (!data) return status === 404 ? <p role="status">{zh ? "所选提交不可用。" : "The selected submission is unavailable."}</p> : <ReadState error={error} retry={retry} />;
  if (data.run_id !== runId) return <p role="alert">{zh ? "所选提交不可用。" : "The selected submission is unavailable."}</p>;
  return <aside className="lc-card lc-results-submission" aria-label={zh ? "提交详情" : "Submission detail"}>
    <h2>{data.student_identifier} · #{data.attempt_number}</h2>
    <p>{data.status} · {data.earned_points ?? "—"}/{data.possible_points ?? "—"}</p>
    <label>{zh ? "题目" : "Question"}<select className="lc-input" value={selected?.item_key ?? ""} onChange={event => updateQuery({ item: event.target.value })}>{items.map((item, index) => <option key={item.item_key} value={item.item_key}>{index + 1}</option>)}</select></label>
    <nav className="lc-actions" aria-label={zh ? "详情面板" : "Detail panels"}>{["answer", "history"].map(value => <button key={value} className="lc-btn lc-btn-outline" aria-pressed={panel === value} onClick={() => updateQuery({ panel: value })}>{value === "answer" ? (zh ? "答案与成绩" : "Answer and grade") : (zh ? "评分历史" : "Grade history")}</button>)}</nav>
    {selected ? <>
      <MarkdownView markdown={selected.prompt} />
      {panel === "history" ? <ol>{selected.grade_decisions.map((decision, index) => <li key={index}><p>{decision.created_at} · {decision.source} · {decision.awarded_points ?? "—"}</p><p>{decision.comment}</p><p>{decision.reason}</p></li>)}</ol> : <>
        <h3>{zh ? "学生答案" : "Student answer"}</h3><pre>{typeof selected.answer === "string" ? selected.answer : JSON.stringify(selected.answer, null, 2)}</pre>
        <p>{selected.current_grade?.awarded_points ?? "—"} / {selected.current_grade?.possible_points ?? "—"}</p>
        <p>{selected.current_grade?.feedback}</p>
        {selected.override_url ? <ResultGradeOverride key={`${selected.item_key}-${selected.grade_fingerprint}`} url={selected.override_url} fingerprint={selected.grade_fingerprint} initialPoints={selected.current_grade?.awarded_points ?? ""} possible={selected.possible_points} initialComment={selected.current_grade?.feedback ?? ""} onSaved={() => { retry(); onGradeSaved(); }} /> : null}
      </>}
    </> : <p>{zh ? "没有题目。" : "No questions."}</p>}
  </aside>;
}

function ResultsWorkspace({ apiRoot, runsUrl, summaryUrl, parentUrl, navigationUrl }: { apiRoot: string; runsUrl: string; summaryUrl?: string; parentUrl?: string; navigationUrl?: string }) {
  const locale = useLocale();
  const zh = locale.startsWith("zh");
  const location = useLocationPath();
  const params = new URL(location, window.location.origin).searchParams;
  const runId = params.get("run") ?? "";
  const attemptId = params.get("attempt") ?? "";
  const panel = params.get("panel") ?? "answer";
  const q = params.get("q") ?? "";
  const [search, setSearch] = React.useState(q);
  const searchPending = React.useRef(false);
  React.useEffect(() => { searchPending.current = false; setSearch(q); }, [location, q]);
  React.useEffect(() => {
    if (!searchPending.current) return;
    const timer = window.setTimeout(() => { searchPending.current = false; updateQuery({ q: search, page: null }, { replace: true }); }, 300);
    return () => window.clearTimeout(timer);
  }, [location, q, search]);
  React.useEffect(() => {
    if (!["answer", "history", "grading"].includes(panel)) updateQuery({ panel: "answer" }, { replace: true });
  }, [panel]);
  const runs = useRead<Page<Run>>(routeUrl(runsUrl, { q, page: params.get("page"), sort: params.get("sort") }));
  const scope = new URL(runsUrl, window.location.href).searchParams;
  const classId = scope.get("class_id") || undefined;
  const courseId = scope.get("course_id") || undefined;
  // The grading panel has its own run/attempt-filtered queue. Avoid fetching
  // the submission table there, which could clear a valid grading scope when a
  // stale attempt query happens to return 404.
  const attemptListUrl = runId && panel !== "grading" ? routeUrl(apiUrl(apiRoot, `browse/results/${encodeURIComponent(runId)}/attempts/`), { page: params.get("attempt_page"), status: params.get("status"), class_id: scope.get("class_id"), course_id: scope.get("course_id") }) : null;
  const attempts = useRead<Page<Attempt> & { run: { title: string } }>(attemptListUrl);
  const [unavailable, setUnavailable] = React.useState(false);
  React.useEffect(() => {
    setUnavailable(false);
  }, [runId]);
  React.useEffect(() => {
    if (runId && attempts.status === 404) {
      setUnavailable(true);
      updateQuery({ run: null, attempt: null, item: null, attempt_page: null }, { replace: true });
    }
  }, [runId, attempts.status]);
  const summary = useRead<Summary>(summaryUrl ?? null);
  const contexts = useRead<{ contexts: Context[] }>(navigationUrl ?? null);
  useNavigationHeading("lc-results-heading");
  return <div className="lc-results-root">
    {parentUrl ? <Breadcrumbs items={[{ href: parentUrl, label: zh ? "概览" : "Overview" }, { label: zh ? "结果" : "Results" }]} /> : null}
    <header className="lc-builder-topbar"><h1 id="lc-results-heading" tabIndex={-1}>{summary.data?.scope.title ?? (zh ? "结果与评分" : "Results and grading")}</h1>
      <button className="lc-btn lc-btn-outline" aria-pressed={panel === "grading"} onClick={() => updateQuery({ panel: panel === "grading" ? "answer" : "grading" })}>{zh ? "人工评分队列" : "Manual grading queue"}</button>
    </header>
    {unavailable ? <p role="status">{zh ? "之前选择的测验不可用，请选择其他测验。" : "The previous assessment is unavailable. Select another assessment."}</p> : null}
    {summaryUrl && !summary.data ? <ReadState error={summary.error} retry={summary.retry} /> : null}
    {summary.data ? <section className="lc-results-summary"><p>{zh ? "名册" : "Roster"}: {summary.data.roster.denominator}</p><p>{zh ? "已评分" : "Graded"}: {summary.data.overall.graded_count}</p><p>{zh ? "待处理" : "Pending"}: {summary.data.overall.pending_count}</p></section> : null}
    {contexts.data ? <details><summary>{zh ? "班级和课程汇总" : "Class and course summaries"}</summary><ul>{contexts.data.contexts.filter(context => context.results_url).map(context => <li key={`${context.kind}-${context.id}`}><NavigationLink href={context.results_url!}>{context.title}</NavigationLink></li>)}</ul></details> : null}
    {panel === "grading" ? <><button className="lc-btn lc-btn-outline" onClick={() => updateQuery({ run: null, attempt: null, item: null })}>{zh ? "所有待评分答案" : "All pending responses"}</button><ManualGradingQueue apiRoot={apiUrl(apiRoot, "")} runId={runId || undefined} attemptId={attemptId || undefined} itemKey={params.get("item") || undefined} classId={classId} courseId={courseId} /></> : <div className="lc-results-layout">
      <aside className="lc-results-filters"><h2>{zh ? "已发布测验" : "Published assessments"}</h2>
        <label>{zh ? "搜索测验" : "Search assessments"}<input className="lc-input" value={search} onChange={event => { searchPending.current = true; setSearch(event.target.value); }} /></label>
        <label>{zh ? "排序" : "Sort"}<select className="lc-input" value={params.get("sort") ?? "recent"} onChange={event => updateQuery({ sort: event.target.value, page: null }, { replace: true })}><option value="recent">{zh ? "最近" : "Recent"}</option><option value="title">{zh ? "标题" : "Title"}</option></select></label>
        {!runs.data ? <ReadState error={runs.error} retry={runs.retry} /> : <><ul className="lc-data-list">{runs.data.items.map(run => <li key={run.public_id}><a className="lc-data-list-row" aria-current={runId === run.public_id ? "true" : undefined} href={routeUrl(window.location.pathname, { run: run.public_id, lang: locale })} onClick={event => { if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return; event.preventDefault(); updateQuery({ run: run.public_id, attempt: null, item: null, attempt_page: null }); }}>{run.title}</a></li>)}</ul>{!runs.data.items.length ? <p>{zh ? "没有可用测验。" : "No assessments available."}</p> : null}<Pager page={runs.data} name="page" /></>}
      </aside>
      <section className="lc-results-table-region"><h2>{attempts.data?.run.title ?? (zh ? "提交" : "Submissions")}</h2>
        {!runId ? <p>{zh ? "选择测验以查看提交。" : "Select an assessment to view submissions."}</p> : !attempts.data ? <ReadState error={attempts.error} retry={attempts.retry} /> : <>
          <label>{zh ? "状态" : "Status"}<select className="lc-input" value={params.get("status") ?? ""} onChange={event => updateQuery({ status: event.target.value, attempt_page: null }, { replace: true })}><option value="">{zh ? "全部" : "All"}</option><option value="in_progress">{zh ? "进行中" : "In progress"}</option><option value="submitted">{zh ? "已提交" : "Submitted"}</option></select></label>
          <div className="lc-results-table-wrap"><table><thead><tr><th>{zh ? "学生" : "Student"}</th><th>{zh ? "次数" : "Attempt"}</th><th>{zh ? "状态" : "Status"}</th><th>{zh ? "成绩" : "Score"}</th></tr></thead><tbody>{attempts.data.items.map(attempt => <tr key={attempt.attempt_id} aria-selected={attemptId === attempt.attempt_id}><td>{attempt.detail_url ? <button className="lc-btn lc-btn-outline" onClick={() => updateQuery({ attempt: attempt.attempt_id, item: null })}>{attempt.student_identifier}</button> : attempt.student_identifier}</td><td>{attempt.attempt_number}</td><td>{attempt.status}</td><td>{attempt.earned_points ?? "—"}/{attempt.possible_points ?? "—"}</td></tr>)}</tbody></table></div>
          {!attempts.data.items.length ? <p>{zh ? "没有提交。" : "No submissions."}</p> : null}<Pager page={attempts.data} name="attempt_page" />
        </>}
      </section>
      {attemptId && runId && attempts.data ? <Submission key={attemptId} url={apiUrl(apiRoot, `browse/result-attempts/${encodeURIComponent(attemptId)}/`)} runId={runId} itemKey={params.get("item") ?? ""} panel={panel} onGradeSaved={() => { summary.retry(); attempts.retry(); }} /> : null}
    </div>}
  </div>;
}

export function mountResultsWorkspace(element: HTMLElement): void {
  const { apiRoot, runsUrl, summaryUrl, parentUrl, navigationUrl } = element.dataset;
  if (!apiRoot || !runsUrl) return;
  const root = createRoot(element);
  root.render(<LocaleProvider initial={element.dataset.locale?.startsWith("zh") ? "zh-Hans" : "en"} root={element}><ResultsWorkspace apiRoot={apiRoot} runsUrl={runsUrl} summaryUrl={summaryUrl} parentUrl={parentUrl} navigationUrl={navigationUrl} /></LocaleProvider>);
  element.addEventListener("liveclassroom:unmount", () => root.unmount(), { once: true });
}
