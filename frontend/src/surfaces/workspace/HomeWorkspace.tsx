import * as React from "react";
import { createRoot } from "react-dom/client";

import { getJson } from "../../protocol.js";
import { preserveLocale } from "../../navigation.js";

type Item = { id?: string | number; key?: string; title: string; status?: string; url: string };
type Section = { key: string; title: string; items: Item[]; view_all_url?: string };
type HomePayload = { mode: "guest" | "teaching" | "learning"; sections: Section[]; quick_actions: Item[] };

function text(english: string, chinese: string): string {
  return document.documentElement.lang.toLowerCase().startsWith("zh") ? chinese : english;
}

function sectionTitle(key: string, fallback: string, mode: HomePayload["mode"] | undefined): string {
  const labels: Record<string, [string, string]> = {
    sessions: ["Current sessions", "当前课堂"],
    recent: ["Recent teaching work", "最近教学工作"],
    classes: ["Courses and classes", "课程和班级"],
    resume: ["Continue learning", "继续学习"],
    assessments: ["Available assessments", "可参加的测验"],
    submitted: ["Recent submitted attempts", "最近提交的作答"],
  };
  if (key === "classes" && mode === "learning") return text("My courses", "我的课程");
  const value = labels[key];
  return value ? text(...value) : fallback;
}

function HomeWorkspace({ homeUrl, mode, authenticated, joinUrl, helpUrl, loginUrl }: {
  homeUrl: string;
  mode: string;
  authenticated: boolean;
  joinUrl: string;
  helpUrl: string;
  loginUrl?: string;
}) {
  const [payload, setPayload] = React.useState<HomePayload | null>(null);
  const [error, setError] = React.useState("");
  const [requestVersion, setRequestVersion] = React.useState(0);
  React.useEffect(() => {
    if (!authenticated) return;
    const controller = new AbortController();
    const url = new URL(homeUrl, window.location.href);
    url.searchParams.set("mode", mode === "teaching" ? "teaching" : "learning");
    setPayload(null);
    setError("");
    void getJson<HomePayload>(url.toString(), { signal: controller.signal })
      .then((value) => { if (!controller.signal.aborted) setPayload(value); })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : text("Unable to load your workspace.", "无法加载工作区。"));
      });
    return () => controller.abort();
  }, [authenticated, homeUrl, mode, requestVersion]);

  if (!authenticated) return <section className="lc-home-page">
    <header className="lc-page-heading"><div><p className="lc-kicker">LiveClassroom</p><h1>{text("Teaching and learning, in one workspace", "在一个工作区中教学和学习")}</h1><p>{text("Join an active classroom, learn from your courses, or sign in to prepare teaching material.", "加入正在进行的课堂、学习课程内容，或登录后准备教学材料。")}</p></div></header>
    <div className="lc-home-guest-actions"><a className="lc-btn lc-btn-primary" href={preserveLocale(joinUrl)}>{text("Join a session", "加入课堂")}</a><a className="lc-btn lc-btn-outline" href={preserveLocale(helpUrl)}>{text("Help", "帮助")}</a>{loginUrl ? <a className="lc-btn lc-btn-outline" href={preserveLocale(loginUrl)}>{text("Sign in", "登录")}</a> : null}</div>
  </section>;
  if (!payload && !error) return <section className="lc-home-page"><p role="status">{text("Loading your workspace...", "正在加载工作区...")}</p></section>;
  if (error) return <section className="lc-home-page"><p className="lc-form-error" role="alert">{error}</p><button className="lc-btn lc-btn-outline" type="button" onClick={() => setRequestVersion((value) => value + 1)}>{text("Retry", "重试")}</button></section>;
  return <section className="lc-home-page">
    <header className="lc-page-heading"><div><p className="lc-kicker">{payload?.mode === "teaching" ? text("Teaching", "教学") : text("Learning", "学习")}</p><h1>{payload?.mode === "teaching" ? text("Work to resume", "继续进行的工作") : text("Continue learning", "继续学习")}</h1></div></header>
    {payload?.quick_actions.length ? <section className="lc-home-actions" aria-label={text("Quick actions", "快捷操作")}>{payload.quick_actions.map((item) => <a className="lc-btn lc-btn-primary" key={item.key || item.url} href={preserveLocale(item.url)}>{item.title}</a>)}</section> : null}
    <div className="lc-home-grid">{payload?.sections.map((section, index) => <section className={index === 0 ? "lc-home-section lc-home-section-primary" : "lc-home-section"} key={section.key}><header className="lc-home-section-heading"><h2>{sectionTitle(section.key, section.title, payload?.mode)}</h2>{section.view_all_url ? <a href={preserveLocale(section.view_all_url)}>{text("View all", "查看全部")}</a> : null}</header>{section.items.length ? <div className="lc-data-list">{section.items.map((item) => <a className="lc-data-list-row" href={preserveLocale(item.url)} key={String(item.id ?? item.url)}><span><strong>{item.title}</strong></span>{item.status ? <span className="lc-status-chip">{item.status.replaceAll("_", " ")}</span> : <span aria-hidden="true">{text("Open", "打开")}</span>}</a>)}</div> : <p className="lc-empty-copy">{text("Nothing to resume here yet.", "这里还没有可继续进行的内容。")}</p>}</section>)}</div>
  </section>;
}

export function mountHomeWorkspace(element: HTMLElement): void {
  const homeUrl = element.dataset.homeUrl;
  const joinUrl = element.dataset.joinUrl;
  const helpUrl = element.dataset.helpUrl;
  if (!homeUrl || !joinUrl || !helpUrl) return;
  createRoot(element).render(<HomeWorkspace homeUrl={homeUrl} mode={element.dataset.mode || "learning"} authenticated={element.dataset.authenticated === "true"} joinUrl={joinUrl} helpUrl={helpUrl} loginUrl={element.dataset.loginUrl} />);
}
