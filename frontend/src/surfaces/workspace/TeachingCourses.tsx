import * as React from "react";
import { createRoot } from "react-dom/client";

import { LocaleProvider, useLocale } from "../../i18n.js";
import { getJson } from "../../protocol.js";
import { notifyContentReady, preserveLocale, updateQuery, useLocationPath, useNavigationHeading } from "../../navigation.js";

type Link = { id?: number; title: string; url: string; status?: string; description?: string };
type BrowsePage<T> = { items: T[]; count: number; page: number; page_size: number; next: string | null; previous: string | null };
type ClassLink = Link & { browse_url?: string; results_url?: string };
type ClassDetail = { class: ClassLink; lessons?: Link[]; sessions?: Link[]; assessments?: Array<Link & { public_id: string }>; results_url?: string };
type TeachingPayload = { courses?: Link[]; independent_classes?: Link[]; course?: Link; classes?: ClassDetail[]; class?: Link; lessons?: Link[]; sessions?: Link[]; assessments?: Link[]; results_url?: string };

const SORTS = new Set(["title", "-title", "updated", "-updated", "recent", "-recent"]);
const text = (locale: string, en: string, zh: string) => locale.startsWith("zh") ? zh : en;

function browseEndpoint(endpoint: string, path: string, page: string, sort: string): string {
  const target = new URL(endpoint, window.location.href);
  const source = new URL(path, window.location.origin);
  const query = source.searchParams.get("q");
  const locale = source.searchParams.get("lang");
  if (query) target.searchParams.set("q", query); else target.searchParams.delete("q");
  if (sort !== "title") target.searchParams.set("sort", sort); else target.searchParams.delete("sort");
  target.searchParams.set("page", page);
  if (locale) target.searchParams.set("lang", locale); else target.searchParams.delete("lang");
  return target.toString();
}

function detailEndpoint(endpoint: string, summary: boolean): string {
  const target = new URL(endpoint, window.location.href);
  if (summary) target.searchParams.set("summary", "1");
  return target.toString();
}

function Links({ title, rows, empty }: { title: string; rows: Link[]; empty: string }) {
  return <section className="lc-learning-section"><h2>{title}</h2>{rows.length ? <ul>{rows.map((row) => <li key={String(row.id ?? row.url)}><a href={preserveLocale(row.url)}>{row.title}</a>{row.status ? <span className="lc-workspace-meta"> {row.status}</span> : null}</li>)}</ul> : <p>{empty}</p>}</section>;
}

function PagedLinks({ title, page, empty, onPage, pageName, locale }: { title: string; page: BrowsePage<Link>; empty: string; onPage: (url: string | null, pageName: string) => void; pageName: string; locale: string }) {
  const tr = React.useCallback((en: string, zh: string) => text(locale, en, zh), [locale]);
  return <section className="lc-learning-section" data-browse-page={pageName} data-page={page.page}><div className="lc-home-section-heading"><h2>{title}</h2><span className="lc-workspace-meta">{page.count}</span></div>{page.items.length ? <ul>{page.items.map((row) => <li key={String(row.id ?? row.url)}><a href={preserveLocale(row.url)}>{row.title}</a></li>)}</ul> : <p>{empty}</p>}<div className="lc-actions"><button type="button" className="lc-btn-sm lc-btn-outline" disabled={!page.previous} onClick={() => onPage(page.previous, pageName)}>{tr("Previous", "上一页")}</button><span className="lc-workspace-meta">{tr(`Page ${page.page}`, `第 ${page.page} 页`)}</span><button type="button" className="lc-btn-sm lc-btn-outline" disabled={!page.next} onClick={() => onPage(page.next, pageName)}>{tr("Next", "下一页")}</button></div></section>;
}

function validPage(value: string | null): string {
  return value && /^[1-9]\d*$/.test(value) ? value : "1";
}

function TeachingCourses({ browseUrl: detailUrl, teacherUrl, coursesUrl, classesUrl }: { browseUrl: string; teacherUrl: string; coursesUrl?: string; classesUrl?: string }) {
  const locale = useLocale();
  const tr = React.useCallback((en: string, zh: string) => text(locale, en, zh), [locale]);
  const location = useLocationPath();
  useNavigationHeading("lc-teaching-heading");
  const query = React.useMemo(() => new URL(location, window.location.origin).searchParams, [location]);
  const pathname = React.useMemo(() => new URL(location, window.location.origin).pathname, [location]);
  const classesIndex = pathname.endsWith("/teacher/classes/");
  const listEndpoint = classesIndex ? classesUrl : coursesUrl;
  const listTitle = classesIndex ? tr("Classes", "班级") : tr("Teaching courses", "教学课程");
  const listEmpty = classesIndex ? tr("No classes yet.", "还没有班级。") : tr("No courses yet.", "还没有课程。");
  const rawPage = query.get("page") ?? query.get(classesIndex ? "class_page" : "course_page");
  const page = validPage(rawPage);
  const rawSort = query.get("sort");
  const sort = rawSort && SORTS.has(rawSort) ? rawSort : "title";
  const queryText = query.get("q") ?? "";
  const [search, setSearch] = React.useState(queryText);
  const [payload, setPayload] = React.useState<TeachingPayload | null>(null);
  const [selectedClassPayload, setSelectedClassPayload] = React.useState<ClassDetail | null>(null);
  const [pageData, setPageData] = React.useState<BrowsePage<Link> | null>(null);
  const [error, setError] = React.useState("");
  const [retry, setRetry] = React.useState(0);
  const typing = React.useRef(false);
  const listMode = Boolean(listEndpoint);
  const courseDetail = !listMode && pathname.includes("/teacher/courses/");

  React.useEffect(() => {
    const changes: Record<string, string | null> = {};
    if ((rawPage && rawPage !== page) || query.has("class_page") || query.has("course_page")) changes.page = page;
    if (query.get("course_page")) changes.course_page = null;
    if (query.get("class_page")) changes.class_page = null;
    if (rawSort && rawSort !== sort) changes.sort = sort === "title" ? null : sort;
    if (Object.keys(changes).length) updateQuery(changes, { replace: true });
  }, [page, rawPage, rawSort, sort, query]);
  React.useEffect(() => { typing.current = false; setSearch(queryText); }, [queryText, location]);
  React.useEffect(() => {
    if (!typing.current || search === queryText || !listMode) return;
    const timer = window.setTimeout(() => updateQuery({ q: search || null, page: "1", course_page: null, class_page: null }, { replace: true }), 300);
    return () => window.clearTimeout(timer);
  }, [listMode, queryText, search, location]);
  React.useEffect(() => {
    if (!listMode || !listEndpoint) return;
    setPageData(null);
    const controller = new AbortController();
    setError("");
    void getJson<BrowsePage<Link>>(browseEndpoint(listEndpoint, location, page, sort), { signal: controller.signal }).then((value) => {
      if (!controller.signal.aborted) setPageData(value);
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : tr("Unable to load teaching courses.", "无法加载教学课程。"));
    });
    return () => controller.abort();
  }, [listEndpoint, location, page, sort, tr, listMode, retry]);
  React.useEffect(() => {
    if (listMode) return;
    const controller = new AbortController();
    setPayload(null);
    setSelectedClassPayload(null);
    setError("");
    void getJson<TeachingPayload>(detailEndpoint(detailUrl, courseDetail), { signal: controller.signal }).then((value) => {
      if (!controller.signal.aborted) setPayload(value);
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : tr("Unable to load teaching courses.", "无法加载教学课程。"));
    });
    return () => controller.abort();
  }, [courseDetail, detailUrl, listMode, tr, retry]);
  const selectPage = React.useCallback((url: string | null) => {
    if (!url) return;
    const target = new URL(url, window.location.href);
    updateQuery({ page: target.searchParams.get("page") ?? "1", course_page: null, class_page: null });
  }, []);
  const pages = pageData;
  const classRows = payload?.classes ?? [];
  const selectedClassId = query.get("class") ?? "";
  const selectedClass = classRows.find((section) => String(section.class.id) === selectedClassId);
  const selectedClassBrowseUrl = selectedClass?.class.browse_url ?? "";
  const selectedTab = query.get("tab") ?? "overview";
  const sectionTab = selectedTab === "lessons" || selectedTab === "sessions" || selectedTab === "assessments" ? selectedTab : "overview";
  React.useEffect(() => {
    if (!courseDetail || !payload?.course || !selectedClassId || selectedClass) return;
    updateQuery({ tab: "overview", class: null }, { replace: true });
  }, [courseDetail, payload, selectedClass, selectedClassId]);
  React.useEffect(() => {
    if (!courseDetail || !selectedClassBrowseUrl) {
      setSelectedClassPayload(null);
      return;
    }
    const controller = new AbortController();
    setSelectedClassPayload(null);
    setError("");
    void getJson<ClassDetail>(selectedClassBrowseUrl, { signal: controller.signal }).then((value) => {
      if (!controller.signal.aborted) setSelectedClassPayload(value);
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : tr("Unable to load this class.", "无法加载此班级。"));
    });
    return () => controller.abort();
  }, [courseDetail, selectedClassBrowseUrl, tr, retry]);
  const classSection = (section: ClassDetail, activeTab = "overview") => {
    const resultsUrl = section.results_url ?? section.class.results_url;
    return <article className="lc-learning-class" key={String(section.class.id)}><h2><a href={preserveLocale(section.class.url)}>{section.class.title}</a></h2>{resultsUrl ? <a className="lc-btn-sm lc-btn-outline" href={preserveLocale(resultsUrl)}>{tr("Results", "结果")}</a> : null}<nav className="lc-actions" aria-label={tr("Class sections", "班级内容")}><button type="button" className="lc-btn-sm lc-btn-outline" aria-pressed={activeTab === "overview"} onClick={() => updateQuery({ tab: "overview" })}>{tr("Overview", "概览")}</button><button type="button" className="lc-btn-sm lc-btn-outline" aria-pressed={activeTab === "lessons"} onClick={() => updateQuery({ tab: "lessons" })}>{tr("Lessons", "教案")}</button><button type="button" className="lc-btn-sm lc-btn-outline" aria-pressed={activeTab === "sessions"} onClick={() => updateQuery({ tab: "sessions" })}>{tr("Classrooms", "课堂")}</button><button type="button" className="lc-btn-sm lc-btn-outline" aria-pressed={activeTab === "assessments"} onClick={() => updateQuery({ tab: "assessments" })}>{tr("Assessments", "测验")}</button></nav>{activeTab === "overview" || activeTab === "lessons" ? <Links title={tr("Lessons", "教案")} rows={section.lessons ?? []} empty={tr("No linked lessons.", "没有关联教案。")} /> : null}{activeTab === "overview" || activeTab === "sessions" ? <Links title={tr("Classrooms", "课堂")} rows={section.sessions ?? []} empty={tr("No classrooms yet.", "还没有课堂。")} /> : null}{activeTab === "overview" || activeTab === "assessments" ? <Links title={tr("Published assessments", "已发布测验")} rows={section.assessments ?? []} empty={tr("No published assessments.", "没有已发布测验。")} /> : null}</article>;
  };
  React.useEffect(() => { if (payload || pageData || selectedClassPayload || error) notifyContentReady(); }, [payload, pageData, selectedClassPayload, error]);
  const heading = payload?.course?.title ?? payload?.class?.title ?? listTitle;
  if (!pages && !payload) return <div className="lc-learning-root"><p role="status">{error || tr("Loading…", "正在加载…")}</p>{error ? <button onClick={() => setRetry(value => value + 1)}>{tr("Retry", "重试")}</button> : null}</div>;
  return <div className="lc-learning-root lc-wide"><header className="lc-builder-topbar"><div><p className="lc-kicker">{tr("Teaching", "教学")}</p><h1 id="lc-teaching-heading" tabIndex={-1}>{heading}</h1></div><a className="lc-btn lc-btn-outline" href={preserveLocale(teacherUrl)}>{tr("Teacher home", "教师首页")}</a></header>{error ? <div role="alert"><p className="lc-form-error">{error}</p><button onClick={() => setRetry(value => value + 1)}>{tr("Retry", "重试")}</button></div> : null}{pages ? <><label className="lc-field"><span>{tr("Search courses and classes", "搜索课程和班级")}</span><input value={search} onChange={(event) => { typing.current = true; setSearch(event.target.value); }} /></label><label className="lc-field"><span>{tr("Sort", "排序")}</span><select value={sort} onChange={(event) => updateQuery({ sort: event.target.value === "title" ? null : event.target.value, page: "1", course_page: null, class_page: null }, { replace: true })}><option value="title">{tr("Title", "标题")}</option><option value="recent">{tr("Recently updated", "最近更新")}</option></select></label><PagedLinks title={listTitle} page={pages} empty={listEmpty} onPage={(url) => selectPage(url)} pageName="page" locale={locale}/></> : <>{payload?.course ? <header className="lc-page-heading"><div><p className="lc-kicker">{tr("Course", "课程")}</p><p>{payload.course.description}</p></div></header> : null}{payload?.course ? <nav className="lc-actions" aria-label={tr("Course classes", "课程班级")}><button type="button" className="lc-btn-sm lc-btn-outline" aria-pressed={!selectedClass && sectionTab === "overview"} onClick={() => updateQuery({ tab: "overview", class: null })}>{tr("Overview", "概览")}</button><button type="button" className="lc-btn-sm lc-btn-outline" aria-pressed={selectedTab === "classes"} onClick={() => updateQuery({ tab: "classes", class: null })}>{tr("Classes", "班级")}</button>{classRows.map((section) => <button key={String(section.class.id)} type="button" className="lc-btn-sm lc-btn-outline" aria-pressed={selectedClass?.class.id === section.class.id} onClick={() => updateQuery({ tab: sectionTab === "overview" ? null : sectionTab, class: section.class.id })}>{section.class.title}</button>)}</nav> : null}{payload?.course && !selectedClass && ["lessons", "sessions", "assessments"].includes(selectedTab) ? <p role="status">{tr("Choose a class to view this section.", "选择班级以查看此栏目。")}</p> : null}{selectedClass ? (selectedClassPayload ? classSection(selectedClassPayload, sectionTab) : <article className="lc-learning-class"><h2><a href={preserveLocale(selectedClass.class.url)}>{selectedClass.class.title}</a></h2>{selectedClass.class.results_url ? <a className="lc-btn-sm lc-btn-outline" href={preserveLocale(selectedClass.class.results_url)}>{tr("Results", "结果")}</a> : null}<p role="status">{error || tr("Loading class…", "正在加载班级…")}</p></article>) : payload?.course ? <Links title={tr("Classes", "班级")} rows={classRows.map((section) => section.class)} empty={tr("No classes yet.", "还没有班级。")}/> : null}{payload?.independent_classes ? <Links title={tr("Independent classes", "独立班级")} rows={payload.independent_classes} empty={tr("No independent classes.", "没有课堂。")}/> : null}{payload?.class && payload.sessions && payload.assessments ? classSection({ class: payload.class, lessons: payload.lessons, sessions: payload.sessions, assessments: payload.assessments as Array<Link & { public_id: string }>, results_url: payload.results_url }, sectionTab) : null}</>}</div>;
}

export function mountTeachingCourses(element: HTMLElement): void {
  const browseUrl = element.dataset.browseUrl;
  const teacherUrl = element.dataset.teacherUrl;
  if (!browseUrl || !teacherUrl) return;
  const locale = element.dataset.locale?.startsWith("zh") ? "zh-Hans" : "en";
  const root = createRoot(element);
  root.render(<LocaleProvider initial={locale} root={element}><TeachingCourses browseUrl={browseUrl} teacherUrl={teacherUrl} coursesUrl={element.dataset.coursesUrl} classesUrl={element.dataset.classesUrl} /></LocaleProvider>);
  element.addEventListener("liveclassroom:unmount", () => root.unmount(), { once: true });
}
