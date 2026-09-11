import * as React from "react";
import { createRoot } from "react-dom/client";

import { LocaleProvider, useLocale } from "../../i18n.js";
import { getJson } from "../../protocol.js";
import { preserveLocale, updateQuery, useLocationPath } from "../../navigation.js";

type Link = { id?: number; public_id?: string; title: string; url: string; status?: string };
type BrowsePage<T> = { items: T[]; count: number; page: number; page_size: number; next: string | null; previous: string | null };
type ClassSection = { class: Link & { description?: string }; sessions: Link[]; assessments: Link[] };
type LearningPayload = { courses?: Link[]; independent_classes?: Link[]; attempts?: Array<Link & { id: string; run_id: string }>; course?: Link; classes?: ClassSection[]; class?: Link; sessions?: Link[]; assessments?: Link[] };

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
  return <section className="lc-learning-section"><h2>{title}</h2>{rows.length ? <ul>{rows.map((row) => <li key={String(row.id ?? row.public_id ?? row.url)}><a href={preserveLocale(row.url)}>{row.title}</a>{row.status ? <span className="lc-workspace-meta"> {row.status}</span> : null}</li>)}</ul> : <p>{empty}</p>}</section>;
}

function PagedLinks({ title, page, empty, onPage, locale }: { title: string; page: BrowsePage<Link>; empty: string; onPage: (url: string | null) => void; locale: string }) {
  const tr = (en: string, zh: string) => text(locale, en, zh);
  return <section className="lc-learning-section" data-browse-page={page.page}><div className="lc-home-section-heading"><h2>{title}</h2><span className="lc-workspace-meta">{page.count}</span></div>{page.items.length ? <ul>{page.items.map((row) => <li key={String(row.id ?? row.public_id ?? row.url)}><a href={preserveLocale(row.url)}>{row.title}</a></li>)}</ul> : <p>{empty}</p>}<div className="lc-actions"><button type="button" className="lc-btn-sm lc-btn-outline" disabled={!page.previous} onClick={() => onPage(page.previous)}>{tr("Previous", "上一页")}</button><span className="lc-workspace-meta">{tr(`Page ${page.page}`, `第 ${page.page} 页`)}</span><button type="button" className="lc-btn-sm lc-btn-outline" disabled={!page.next} onClick={() => onPage(page.next)}>{tr("Next", "下一页")}</button></div></section>;
}

function LearningWorkspace({ browseUrl: detailUrl, joinUrl, coursesUrl, classesUrl }: { browseUrl: string; joinUrl: string; coursesUrl?: string; classesUrl?: string }) {
  const locale = useLocale();
  const tr = React.useCallback((en: string, zh: string) => text(locale, en, zh), [locale]);
  const location = useLocationPath();
  const query = React.useMemo(() => new URL(location, window.location.origin).searchParams, [location]);
  const rawPage = query.get("page");
  const page = rawPage && /^[1-9]\d*$/.test(rawPage) ? rawPage : "1";
  const rawSort = query.get("sort");
  const sort = rawSort && SORTS.has(rawSort) ? rawSort : "title";
  const queryText = query.get("q") ?? "";
  const [search, setSearch] = React.useState(queryText);
  const [payload, setPayload] = React.useState<LearningPayload | null>(null);
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
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : tr("Unable to load your learning spaces.", "无法加载学习空间。"));
      });
    } else {
      void getJson<LearningPayload>(detailUrl, { signal: controller.signal }).then((value) => {
        if (!controller.signal.aborted) setPayload(value);
      }).catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : tr("Unable to load your learning spaces.", "无法加载学习空间。"));
      });
    }
    return () => controller.abort();
  }, [classesUrl, coursesUrl, detailUrl, location, page, sort, tr]);
  const selectPage = React.useCallback((url: string | null) => {
    if (!url) return;
    const target = new URL(url, window.location.href);
    updateQuery({ page: target.searchParams.get("page") ?? "1" });
  }, []);
  const heading = payload?.course?.title ?? payload?.class?.title ?? tr("My courses", "我的课程");
  if (!pages && !payload) return <div className="lc-learning-root"><p role="status">{error || tr("Loading…", "正在加载…")}</p></div>;
  return <div className="lc-learning-root lc-wide"><header className="lc-builder-topbar"><div><p className="lc-kicker">{tr("Learning", "学习")}</p><h1>{heading}</h1></div><a className="lc-btn lc-btn-outline" href={preserveLocale(joinUrl)}>{tr("Join classroom", "加入课堂")}</a></header>{error ? <p role="alert" className="lc-form-error">{error}</p> : null}{pages ? <><label className="lc-field"><span>{tr("Search courses and classes", "搜索课程和班级")}</span><input value={search} onChange={(event) => setSearch(event.target.value)} /></label><label className="lc-field"><span>{tr("Sort", "排序")}</span><select value={sort} onChange={(event) => updateQuery({ sort: event.target.value === "title" ? null : event.target.value, page: "1" }, { replace: true })}><option value="title">{tr("Title", "标题")}</option><option value="recent">{tr("Recently updated", "最近更新")}</option></select></label><PagedLinks title={tr("Courses", "课程")} page={pages.courses} empty={tr("You are not enrolled in a course yet.", "你尚未加入课程。")} onPage={selectPage} locale={locale}/><PagedLinks title={tr("Classes", "班级")} page={pages.classes} empty={tr("No classes.", "没有班级。")} onPage={selectPage} locale={locale}/></> : <>{payload?.courses ? <Links title={tr("Courses", "课程")} rows={payload.courses} empty={tr("You are not enrolled in a course yet.", "你尚未加入课程。")}/> : null}{payload?.independent_classes ? <Links title={tr("Independent classes", "独立班级")} rows={payload.independent_classes} empty={tr("No independent classes.", "没有独立班级。")}/> : null}{payload?.attempts ? <Links title={tr("My attempts and results", "我的作答和结果")} rows={payload.attempts} empty={tr("No assessment attempts yet.", "还没有测验作答。")}/> : null}{(payload?.classes ?? []).map((section) => <article className="lc-learning-class" key={String(section.class.id)}><h2><a href={preserveLocale(section.class.url)}>{section.class.title}</a></h2><Links title={tr("Classrooms", "课堂")} rows={section.sessions} empty={tr("No released classrooms.", "没有已发布课堂。")}/><Links title={tr("Assessments", "测验")} rows={section.assessments} empty={tr("No available assessments.", "没有可用测验。")}/></article>)}{payload?.class ? <><Links title={tr("Classrooms", "课堂")} rows={payload.sessions ?? []} empty={tr("No released classrooms.", "没有已发布课堂。")}/><Links title={tr("Assessments", "测验")} rows={payload.assessments ?? []} empty={tr("No available assessments.", "没有可用测验。")}/></> : null}</>}</div>;
}

export function mountLearningWorkspace(element: HTMLElement): void {
  const browseUrl = element.dataset.browseUrl;
  const joinUrl = element.dataset.joinUrl;
  if (!browseUrl || !joinUrl) return;
  const locale = element.dataset.locale?.startsWith("zh") ? "zh-Hans" : "en";
  createRoot(element).render(<LocaleProvider initial={locale} root={element}><LearningWorkspace browseUrl={browseUrl} joinUrl={joinUrl} coursesUrl={element.dataset.coursesUrl} classesUrl={element.dataset.classesUrl} /></LocaleProvider>);
}
