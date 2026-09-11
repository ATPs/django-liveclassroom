import * as React from "react";
import { createRoot } from "react-dom/client";
import { LocaleProvider, useLocale } from "../../i18n.js";
import { getJson } from "../../protocol.js";
import { NavigationLink, notifyContentReady, preserveLocale, updateQuery, useLocationPath, useNavigationHeading } from "../../navigation.js";

type Link = { id?: number; public_id?: string; title: string; url: string; status?: string; description?: string };
type Page = { items: Link[]; count: number; page: number; next: string | null; previous: string | null };
type Overview = { course?: Link; class?: Link; classes?: Array<{ class: Link }> };
type Props = { browseUrl: string; joinUrl: string; historyUrl: string; coursesUrl?: string; classesUrl?: string; sessionsUrl: string; assessmentsUrl: string };

function LearningWorkspace(props: Props) {
  const locale = useLocale();
  const tr = React.useCallback((en: string, zh: string) => locale.startsWith("zh") ? zh : en, [locale]);
  const location = useLocationPath();
  useNavigationHeading("lc-learning-heading");
  const query = React.useMemo(() => new URL(location, window.location.origin).searchParams, [location]);
  const index = Boolean(props.coursesUrl);
  const tabs = index ? ["courses", "classes", "sessions", "assessments"] : ["overview", ...(props.classesUrl ? ["classes"] : []), "sessions", "assessments"];
  const rawTab = query.get("tab");
  const tab = rawTab && tabs.includes(rawTab) ? rawTab : tabs[0];
  const rawPage = query.get("page") ?? query.get(tab === "classes" ? "class_page" : "course_page");
  const page = rawPage && /^[1-9]\d*$/.test(rawPage) ? rawPage : "1";
  const sort = ["title", "-title", "recent"].includes(query.get("sort") ?? "") ? query.get("sort")! : "title";
  const q = query.get("q") ?? "";
  const [search, setSearch] = React.useState(q);
  const typing = React.useRef(false);
  const [overview, setOverview] = React.useState<Overview | null>(null);
  const [rows, setRows] = React.useState<Page | null>(null);
  const [error, setError] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [retry, setRetry] = React.useState(0);
  const labels: Record<string, string> = { overview: tr("Overview", "概览"), courses: tr("Courses", "课程"), classes: tr("Classes", "班级"), sessions: tr("Sessions", "课堂"), assessments: tr("Assessments", "测验") };
  const label = (key: string) => labels[key] ?? key;
  React.useEffect(() => {
    const changes: Record<string, string | null> = {};
    if (rawTab && rawTab !== tab) changes.tab = tab;
    if (rawPage && rawPage !== page) changes.page = page;
    if (query.has("course_page") || query.has("class_page")) Object.assign(changes, { page, course_page: null, class_page: null });
    if (query.has("sort") && query.get("sort") !== sort) changes.sort = null;
    if (Object.keys(changes).length) updateQuery(changes, { replace: true });
  }, [location, tab, page, sort]);
  React.useEffect(() => { typing.current = false; setSearch(q); }, [location, q]);
  React.useEffect(() => {
    if (!typing.current || search === q) return;
    const timer = window.setTimeout(() => {
      typing.current = false;
      updateQuery({ q: search || null, page: null }, { replace: true });
    }, 300);
    return () => window.clearTimeout(timer);
  }, [search, q, location]);
  React.useEffect(() => {
    if (index) return;
    const controller = new AbortController();
    const target = new URL(props.browseUrl, window.location.href);
    target.searchParams.set("tab", "overview");
    void getJson<Overview>(target.toString(), { signal: controller.signal }).then(value => {
      if (!controller.signal.aborted) setOverview(value);
    }).catch(reason => { if (!controller.signal.aborted) setError(String(reason)); });
    return () => controller.abort();
  }, [props.browseUrl, index, retry]);
  const endpoint = tab === "courses" ? props.coursesUrl : tab === "classes" ? props.classesUrl : tab === "sessions" ? props.sessionsUrl : tab === "assessments" ? props.assessmentsUrl : undefined;
  React.useEffect(() => {
    setError(""); setRows(null);
    if (!endpoint) { setLoading(false); return; }
    const controller = new AbortController();
    const target = new URL(endpoint, window.location.href);
    target.searchParams.set("q", q); target.searchParams.set("page", page); target.searchParams.set("sort", sort); target.searchParams.set("lang", locale);
    setLoading(true);
    void getJson<Page>(target.toString(), { signal: controller.signal }).then(value => {
      if (!controller.signal.aborted) { setRows(value); setLoading(false); }
    }).catch(reason => {
      if (!controller.signal.aborted) { setError(reason instanceof Error ? reason.message : String(reason)); setLoading(false); }
    });
    return () => controller.abort();
  }, [endpoint, q, page, sort, locale, retry]);
  React.useEffect(() => { if (!loading && (rows || overview || error)) notifyContentReady(); }, [loading, rows, overview, error]);
  const heading = overview?.course?.title ?? overview?.class?.title ?? tr("My courses", "我的课程");
  const turnPage = (url: string | null) => { if (url) updateQuery({ page: new URL(url, window.location.href).searchParams.get("page") ?? "1" }); };
  return <div className="lc-learning-root lc-wide">
    <header className="lc-builder-topbar"><div><p className="lc-kicker">{tr("Learning", "学习")}</p><h1 id="lc-learning-heading" tabIndex={-1}>{heading}</h1></div><div className="lc-actions"><NavigationLink href={preserveLocale(props.historyUrl)}>{tr("My attempts and results", "我的作答和结果")}</NavigationLink><NavigationLink className="lc-btn lc-btn-outline" href={preserveLocale(props.joinUrl)}>{tr("Join a session", "加入课堂")}</NavigationLink></div></header>
    <nav className="lc-actions" aria-label={tr("Learning sections", "学习栏目")}>{tabs.map(key => <button key={key} type="button" aria-current={tab === key ? "page" : undefined} className={tab === key ? "lc-btn-sm" : "lc-btn-sm lc-btn-outline"} onClick={() => updateQuery({ tab: key, page: null, q: null })}>{label(key)}</button>)}</nav>
    {error ? <div role="alert"><p className="lc-form-error">{error}</p><button type="button" onClick={() => setRetry(value => value + 1)}>{tr("Retry", "重试")}</button></div> : null}
    {tab === "overview" ? overview ? <section className="lc-learning-section"><h2>{label(tab)}</h2><p>{overview.course?.description ?? overview.class?.description}</p><p>{tr("Use the sections above to browse available classes, sessions, and assessments.", "使用上方栏目浏览可访问的班级、课堂和测验。")}</p>{overview.classes?.length ? <ul>{overview.classes.map(section => <li key={section.class.id}><NavigationLink href={preserveLocale(section.class.url)}>{section.class.title}</NavigationLink></li>)}</ul> : null}</section> : !error ? <p role="status">{tr("Loading…", "正在加载…")}</p> : null : <>
    <div className="lc-actions"><label className="lc-field"><span>{tr("Search", "搜索")}</span><input value={search} onChange={event => { typing.current = true; setSearch(event.target.value); }} /></label><label className="lc-field"><span>{tr("Sort", "排序")}</span><select value={sort} onChange={event => updateQuery({ sort: event.target.value, page: null }, { replace: true })}><option value="title">{tr("Title", "标题")}</option><option value="-title">{tr("Title descending", "标题降序")}</option><option value="recent">{tr("Recently updated", "最近更新")}</option></select></label></div>
    {loading ? <p role="status">{tr("Loading…", "正在加载…")}</p> : rows ? <section className="lc-learning-section"><h2>{label(tab)} <span className="lc-workspace-meta">({rows.count})</span></h2>{rows.items.length ? <ul>{rows.items.map(row => <li key={row.id ?? row.public_id ?? row.url}><NavigationLink href={preserveLocale(row.url)}>{row.title}</NavigationLink>{row.status ? <span className="lc-workspace-meta"> {row.status}</span> : null}</li>)}</ul> : <p>{tr("No available items match this view.", "此视图中没有可用的内容。")}</p>}<nav className="lc-actions" aria-label={tr("Pagination", "分页")}><button type="button" disabled={!rows.previous} onClick={() => turnPage(rows.previous)}>{tr("Previous", "上一页")}</button><span>{tr("Page", "页")} {rows.page}</span><button type="button" disabled={!rows.next} onClick={() => turnPage(rows.next)}>{tr("Next", "下一页")}</button></nav></section> : null}</>}
  </div>;
}
export function mountLearningWorkspace(element: HTMLElement): void {
  const { browseUrl, joinUrl, historyUrl, coursesUrl, classesUrl, sessionsUrl, assessmentsUrl } = element.dataset;
  if (!browseUrl || !joinUrl || !historyUrl || !sessionsUrl || !assessmentsUrl) return;
  const root = createRoot(element);
  root.render(<LocaleProvider initial={element.dataset.locale?.startsWith("zh") ? "zh-Hans" : "en"} root={element}><LearningWorkspace {...{ browseUrl, joinUrl, historyUrl, coursesUrl, classesUrl, sessionsUrl, assessmentsUrl }} /></LocaleProvider>);
  element.addEventListener("liveclassroom:unmount", () => root.unmount(), { once: true });
}
