import * as React from "react";
import { createRoot } from "react-dom/client";

import { LanguageSwitcher, LocaleProvider, useLocale } from "../../i18n.js";
import { getJson } from "../../protocol.js";
import { preserveLocale } from "../../navigation.js";

type Link = { id?: number; public_id?: string; title: string; url: string; status?: string };
type ClassSection = { class: Link & { description?: string }; sessions: Link[]; assessments: Link[] };
type LearningPayload = { courses?: Link[]; independent_classes?: Link[]; attempts?: Array<Link & { id: string; run_id: string }>; course?: Link; classes?: ClassSection[]; class?: Link; sessions?: Link[]; assessments?: Link[] };
const text = (locale: string, en: string, zh: string) => locale.startsWith("zh") ? zh : en;

function Links({ title, rows, empty }: { title: string; rows: Link[]; empty: string }) {
  return <section className="lc-learning-section"><h2>{title}</h2>{rows.length ? <ul>{rows.map((row) => <li key={String(row.id ?? row.public_id ?? row.url)}><a href={preserveLocale(row.url)}>{row.title}</a>{row.status ? <span className="lc-workspace-meta"> {row.status}</span> : null}</li>)}</ul> : <p>{empty}</p>}</section>;
}

function LearningWorkspace({ browseUrl, joinUrl }: { browseUrl: string; joinUrl: string }) {
  const locale = useLocale();
  const tr = (en: string, zh: string) => text(locale, en, zh);
  const [payload, setPayload] = React.useState<LearningPayload | null>(null);
  const [error, setError] = React.useState("");
  React.useEffect(() => {
    let active = true;
    void getJson<LearningPayload>(browseUrl).then((value) => { if (active) setPayload(value); }).catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : tr("Unable to load your learning spaces.", "无法加载学习空间。")); });
    return () => { active = false; };
  }, [browseUrl, tr]);
  if (!payload) return <div className="lc-learning-root"><LanguageSwitcher /><p role="status">{error || tr("Loading…", "正在加载…")}</p></div>;
  return <div className="lc-learning-root lc-wide"><LanguageSwitcher /><header className="lc-builder-topbar"><div><p className="lc-kicker">{tr("Learning", "学习")}</p><h1>{payload.course?.title ?? payload.class?.title ?? tr("My courses", "我的课程")}</h1></div><a className="lc-btn lc-btn-outline" href={preserveLocale(joinUrl)}>{tr("Join classroom", "加入课堂")}</a></header>{error ? <p role="alert" className="lc-form-error">{error}</p> : null}{payload.courses ? <Links title={tr("Courses", "课程")} rows={payload.courses} empty={tr("You are not enrolled in a course yet.", "你尚未加入课程。")}/> : null}{payload.independent_classes ? <Links title={tr("Independent classes", "独立班级")} rows={payload.independent_classes} empty={tr("No independent classes.", "没有独立班级。")}/> : null}{payload.attempts ? <Links title={tr("My attempts and results", "我的作答和结果")} rows={payload.attempts} empty={tr("No assessment attempts yet.", "还没有测验作答。")}/> : null}{(payload.classes ?? []).map((section) => <article className="lc-learning-class" key={String(section.class.id)}><h2><a href={preserveLocale(section.class.url)}>{section.class.title}</a></h2><Links title={tr("Classrooms", "课堂")} rows={section.sessions} empty={tr("No released classrooms.", "没有已发布课堂。")}/><Links title={tr("Assessments", "测验")} rows={section.assessments} empty={tr("No available assessments.", "没有可用测验。")}/></article>)}{payload.class ? <><Links title={tr("Classrooms", "课堂")} rows={payload.sessions ?? []} empty={tr("No released classrooms.", "没有已发布课堂。")}/><Links title={tr("Assessments", "测验")} rows={payload.assessments ?? []} empty={tr("No available assessments.", "没有可用测验。")}/></> : null}</div>;
}

export function mountLearningWorkspace(element: HTMLElement): void {
  const browseUrl = element.dataset.browseUrl;
  const joinUrl = element.dataset.joinUrl;
  if (!browseUrl || !joinUrl) return;
  const locale = element.dataset.locale?.startsWith("zh") ? "zh-Hans" : "en";
  createRoot(element).render(<LocaleProvider initial={locale} root={element}><LearningWorkspace browseUrl={browseUrl} joinUrl={joinUrl} /></LocaleProvider>);
}
