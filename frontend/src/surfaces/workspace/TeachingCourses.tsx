import * as React from "react";
import { createRoot } from "react-dom/client";

import { LocaleProvider, useLocale } from "../../i18n.js";
import { getJson } from "../../protocol.js";
import { preserveLocale, updateQuery, useLocationPath } from "../../navigation.js";

type Link = { id?: number; title: string; url: string; status?: string };
type BrowsePage<T> = { items: T[]; count: number; page: number; page_size: number; next: string | null; previous: string | null };
type ClassDetail = { class: Link; lessons?: Link[]; sessions: Link[]; assessments: Array<Link & { public_id: string }>; results_url?: string };
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

function Links({ title, rows, empty }: { title: string; rows: Link[]; empty: string }) {
  return <section className="lc-learning-section"><h2>{title}</h2>{rows.length ? <ul>{rows.map((row) => <li key={String(row.id ?? row.url)}><a href={preserveLocale(row.url)}>{row.title}</a>{row.status ? <span className="lc-workspace-meta"> {row.status}</span> : null}</li>)}</ul> : <p>{empty}</p>}</section>;
}

function PagedLinks({ title, page, empty, onPage, locale }: { title: string; page: BrowsePage<Link>; empty: string; onPage: (url: string | null) => void; locale: string }) {
  const tr = React.useCallback((en: string, zh: string) => text(locale, en, zh), [locale]);
  return <section className="lc-learning-section" data-browse-page={page.page}><div className="lc-home-section-heading"><h2>{title}</h2><span className="lc-workspace-meta">{page.count}</span></div>{page.items.length ? <ul>{page.items.map((row) => <li key={String(row.id ?? row.url)}><a href={preserveLocale(row.url)}>{row.title}</a></li>)}</ul> : <p>{empty}</p>}<div className="lc-actions"><button type="button" className="lc-btn-sm lc-btn-outline" disabled={!page.previous} onClick={() => onPage(page.previous)}>{tr("Previous", "上一页")}</button><span className="lc-workspace-meta">{tr(`Page ${page.page}`, `第 ${page.page} 页`)}</span><button type="button" className="lc-btn-sm lc-btn-outline" disabled={!page.next} onClick={() => onPage(page.next)}>{tr("Next", "下一页")}</button></div></section>;
}

function TeachingCourses({ browseUrl: detailUrl, teacherUrl, coursesUrl, classesUrl }: { browseUrl: string; teacherUrl: string; coursesUrl?: string; classesUrl?: string }) {
  const locale = useLocale();
  const tr = (en: string, zh: string) => text(locale, en, zh);
  const location = useLocationPath();
  const query = React.useMemo(() => new URL(location, window.location.origin).searchParams, [location]);
  const rawPage = query.get("page");
  const page = rawPage && /^[1-9]\d*$/.test(rawPage) ? rawPage : "1";
  const rawSort = query.get("sort");
  const sort = rawSort && SORTS.has(rawSort) ? rawSort : "title";
  const queryText = query.get("q") ?? "";
  const [search, setSearch] = React.useState(queryText);
  const [payload, setPayload] = React.useState<TeachingPayload | null>(null);
  const [pages, setPages] = React.useState<{ courses: BrowsePage<Link>; classes: BrowsePage<Link> } | null>(null);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    if (rawPage && rawPage !== page) updateQuery({ page }, { replace: true });
    if (rawSort && rawSort !== sort) updateQuery({ sort: sort === "title" ? null : sort }, { replace: true });
  }, [page, rawPage, rawSort, sort]);
  React.useEffect(() => setSearch(queryText), [queryText]);
  React.useEffect(() => {
    if (search === queryText) return;
    const timer = window.setTimeout(() => updateQuery({ q: search || null, page: "1" }, { replace: true }), 300);
    return () => window.clearTimeout(timer);
  }, [queryText, search]);
  React.useEffect(() => {
    const controller = new AbortController();
    setError("");
    if (coursesUrl && classesUrl) {
      void Promise.all([
        getJson<BrowsePage<Link>>(browseEndpoint(coursesUrl, location, page, sort), { signal: controller.signal }),
        getJson<BrowsePage<Link>>(browseEndpoint(classesUrl, location, page, sort), { signal: controller.signal }),
      ]).then(([courses, classes]) => {
        if (!controller.signal.aborted) setPages({ courses, classes });
      }).catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : tr("Unable to load teaching courses.", "无法加载教学课程。"));
      });
    } else {
      void getJson<TeachingPayload>(detailUrl, { signal: controller.signal }).then((value) => {
        if (!controller.signal.aborted) setPayload(value);
      }).catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : tr("Unable to load teaching courses.", "无法加载教学课程。"));
      });
    }
    return () => controller.abort();
  }, [classesUrl, coursesUrl, detailUrl, location, page, sort, tr]);
  const selectPage = React.useCallback((url: string | null) => {
    if (!url) return;
    const target = new URL(url, window.location.href);
    updateQuery({ page: target.searchParams.get("page") ?? "1" });
  }, []);
  const classSection = (section: ClassDetail) => <article className="lc-learning-class" key={String(section.class.id)}><h2><a href={preserveLocale(section.class.url)}>{section.class.title}</a></h2>{section.results_url ? <a className="lc-btn-sm lc-btn-outline" href={preserveLocale(section.results_url)}>{tr("Results", "结果")}</a> : null}<Links title={tr("Lessons", "教案")} rows={section.lessons ?? []} empty={tr("No linked lessons.", "没有关联教案。")}/><Links title={tr("Classrooms", "课堂")} rows={section.sessions} empty={tr("No classrooms yet.", "还没有课堂。")}/><Links title={tr("Published assessments", "已发布测验")} rows={section.assessments} empty={tr("No published assessments.", "没有已发布测验。")}/></article>;
  const heading = payload?.course?.title ?? payload?.class?.title ?? tr("Courses", "课程");
  if (!pages && !payload) return <div className="lc-learning-root"><p role="status">{error || tr("Loading…", "正在加载…")}</p></div>;
  return <div className="lc-learning-root lc-wide"><header className="lc-builder-topbar"><div><p className="lc-kicker">{tr("Teaching", "教学")}</p><h1>{heading}</h1></div><a className="lc-btn lc-btn-outline" href={preserveLocale(teacherUrl)}>{tr("Teacher home", "教师首页")}</a></header>{error ? <p role="alert" className="lc-form-error">{error}</p> : null}{pages ? <><label className="lc-field"><span>{tr("Search courses and classes", "搜索课程和班级")}</span><input value={search} onChange={(event) => setSearch(event.target.value)} /></label><label className="lc-field"><span>{tr("Sort", "排序")}</span><select value={sort} onChange={(event) => updateQuery({ sort: event.target.value === "title" ? null : event.target.value, page: "1" }, { replace: true })}><option value="title">{tr("Title", "标题")}</option><option value="recent">{tr("Recently updated", "最近更新")}</option></select></label><PagedLinks title={tr("Teaching courses", "教学课程")} page={pages.courses} empty={tr("No courses yet.", "还没有课程。")} onPage={selectPage} locale={locale}/><PagedLinks title={tr("Classes", "班级")} page={pages.classes} empty={tr("No classes yet.", "还没有班级。")} onPage={selectPage} locale={locale}/></> : <>{payload?.courses ? <Links title={tr("Courses", "课程")} rows={payload.courses} empty={tr("No courses yet.", "还没有课程。")}/> : null}{payload?.independent_classes ? <Links title={tr("Independent classes", "独立班级")} rows={payload.independent_classes} empty={tr("No independent classes.", "没有独立班级。")}/> : null}{(payload?.classes ?? []).map(classSection)}{payload?.class && payload.sessions && payload.assessments ? classSection({ class: payload.class, lessons: payload.lessons, sessions: payload.sessions, assessments: payload.assessments as Array<Link & { public_id: string }>, results_url: payload.results_url }) : null}</>}</div>;
}

export function mountTeachingCourses(element: HTMLElement): void {
  const browseUrl = element.dataset.browseUrl;
  const teacherUrl = element.dataset.teacherUrl;
  if (!browseUrl || !teacherUrl) return;
  const locale = element.dataset.locale?.startsWith("zh") ? "zh-Hans" : "en";
  createRoot(element).render(<LocaleProvider initial={locale} root={element}><TeachingCourses browseUrl={browseUrl} teacherUrl={teacherUrl} coursesUrl={element.dataset.coursesUrl} classesUrl={element.dataset.classesUrl} /></LocaleProvider>);
}
