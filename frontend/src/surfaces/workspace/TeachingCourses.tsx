import * as React from "react";
import { createRoot } from "react-dom/client";

import { LanguageSwitcher, LocaleProvider, useLocale } from "../../i18n.js";
import { getJson } from "../../protocol.js";
import { preserveLocale } from "../../navigation.js";

type Link = { id?: number; title: string; url: string; status?: string };
type ClassDetail = { class: Link; lessons?: Link[]; sessions: Link[]; assessments: Array<Link & { public_id: string }>; results_url?: string };
type TeachingPayload = { courses?: Link[]; independent_classes?: Link[]; course?: Link; classes?: ClassDetail[]; class?: Link; lessons?: Link[]; sessions?: Link[]; assessments?: Link[]; results_url?: string };

const text = (locale: string, en: string, zh: string) => locale.startsWith("zh") ? zh : en;

function Links({ title, rows, empty }: { title: string; rows: Link[]; empty: string }) {
  return <section className="lc-learning-section"><h2>{title}</h2>{rows.length ? <ul>{rows.map((row) => <li key={String(row.id ?? row.url)}><a href={preserveLocale(row.url)}>{row.title}</a>{row.status ? <span className="lc-workspace-meta"> {row.status}</span> : null}</li>)}</ul> : <p>{empty}</p>}</section>;
}

function TeachingCourses({ browseUrl, teacherUrl }: { browseUrl: string; teacherUrl: string }) {
  const locale = useLocale();
  const tr = (en: string, zh: string) => text(locale, en, zh);
  const [payload, setPayload] = React.useState<TeachingPayload | null>(null);
  const [error, setError] = React.useState("");
  React.useEffect(() => {
    let active = true;
    void getJson<TeachingPayload>(browseUrl).then((value) => { if (active) setPayload(value); }).catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : tr("Unable to load teaching courses.", "无法加载教学课程。")); });
    return () => { active = false; };
  }, [browseUrl, tr]);
  if (!payload) return <div className="lc-learning-root"><LanguageSwitcher /><p role="status">{error || tr("Loading…", "正在加载…")}</p></div>;
  const classSection = (section: ClassDetail) => <article className="lc-learning-class" key={String(section.class.id)}><h2><a href={preserveLocale(section.class.url)}>{section.class.title}</a></h2>{section.results_url ? <a className="lc-btn-sm lc-btn-outline" href={preserveLocale(section.results_url)}>{tr("Results", "结果")}</a> : null}<Links title={tr("Lessons", "教案")} rows={section.lessons ?? []} empty={tr("No linked lessons.", "没有关联教案。")}/><Links title={tr("Classrooms", "课堂")} rows={section.sessions} empty={tr("No classrooms yet.", "还没有课堂。")}/><Links title={tr("Published assessments", "已发布测验")} rows={section.assessments} empty={tr("No published assessments.", "没有已发布测验。")}/></article>;
  return <div className="lc-learning-root lc-wide"><LanguageSwitcher /><header className="lc-builder-topbar"><div><p className="lc-kicker">{tr("Teaching", "教学")}</p><h1>{payload.course?.title ?? payload.class?.title ?? tr("Courses", "课程")}</h1></div><a className="lc-btn lc-btn-outline" href={preserveLocale(teacherUrl)}>{tr("Teacher home", "教师首页")}</a></header>{error ? <p role="alert" className="lc-form-error">{error}</p> : null}{payload.courses ? <Links title={tr("Courses", "课程")} rows={payload.courses} empty={tr("No courses yet.", "还没有课程。")}/> : null}{payload.independent_classes ? <Links title={tr("Independent classes", "独立班级")} rows={payload.independent_classes} empty={tr("No independent classes.", "没有独立班级。")}/> : null}{(payload.classes ?? []).map(classSection)}{payload.class && payload.sessions && payload.assessments ? classSection({ class: payload.class, lessons: payload.lessons, sessions: payload.sessions, assessments: payload.assessments as Array<Link & { public_id: string }>, results_url: payload.results_url }) : null}</div>;
}

export function mountTeachingCourses(element: HTMLElement): void {
  const browseUrl = element.dataset.browseUrl;
  const teacherUrl = element.dataset.teacherUrl;
  if (!browseUrl || !teacherUrl) return;
  const locale = element.dataset.locale?.startsWith("zh") ? "zh-Hans" : "en";
  createRoot(element).render(<LocaleProvider initial={locale} root={element}><TeachingCourses browseUrl={browseUrl} teacherUrl={teacherUrl} /></LocaleProvider>);
}
