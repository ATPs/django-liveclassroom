import * as React from "react";
import { createRoot } from "react-dom/client";

import { getJson } from "../../protocol.js";
import { preserveLocale } from "../../navigation.js";

type Item = { id?: string | number; key?: string; title: string; status?: string; url: string };
type Section = { key: string; title: string; items: Item[] };
type HomePayload = { mode: "guest" | "teaching" | "learning"; sections: Section[]; quick_actions: Item[] };

function HomeWorkspace({ homeUrl, mode, authenticated, joinUrl, helpUrl }: {
  homeUrl: string;
  mode: string;
  authenticated: boolean;
  joinUrl: string;
  helpUrl: string;
}) {
  const [payload, setPayload] = React.useState<HomePayload | null>(null);
  const [error, setError] = React.useState("");
  React.useEffect(() => {
    if (!authenticated) return;
    let active = true;
    const url = new URL(homeUrl, window.location.href);
    url.searchParams.set("mode", mode === "teaching" ? "teaching" : "learning");
    setPayload(null);
    setError("");
    void getJson<HomePayload>(url.toString())
      .then((value) => { if (active) setPayload(value); })
      .catch((reason: unknown) => {
        if (active) setError(reason instanceof Error ? reason.message : "Unable to load your workspace.");
      });
    return () => { active = false; };
  }, [authenticated, homeUrl, mode]);

  if (!authenticated) return <section className="lc-home-page">
    <header className="lc-page-heading"><div><p className="lc-kicker">LiveClassroom</p><h1>Teaching and learning, in one workspace</h1><p>Join an active classroom, learn from your courses, or sign in to prepare teaching material.</p></div></header>
    <div className="lc-home-guest-actions"><a className="lc-btn lc-btn-primary" href={preserveLocale(joinUrl)}>Join a session</a><a className="lc-btn lc-btn-outline" href={preserveLocale(helpUrl)}>Help</a></div>
  </section>;
  if (!payload && !error) return <section className="lc-home-page"><p role="status">Loading your workspace...</p></section>;
  if (error) return <section className="lc-home-page"><p className="lc-form-error" role="alert">{error}</p><button className="lc-btn lc-btn-outline" type="button" onClick={() => window.location.reload()}>Retry</button></section>;
  return <section className="lc-home-page">
    <header className="lc-page-heading"><div><p className="lc-kicker">{payload?.mode === "teaching" ? "Teaching" : "Learning"}</p><h1>{payload?.mode === "teaching" ? "Work to resume" : "Continue learning"}</h1></div></header>
    {payload?.quick_actions.length ? <section className="lc-home-actions" aria-label="Quick actions">{payload.quick_actions.map((item) => <a className="lc-btn lc-btn-primary" key={item.key || item.url} href={preserveLocale(item.url)}>{item.title}</a>)}</section> : null}
    <div className="lc-home-grid">{payload?.sections.map((section, index) => <section className={index === 0 ? "lc-home-section lc-home-section-primary" : "lc-home-section"} key={section.key}><h2>{section.title}</h2>{section.items.length ? <div className="lc-data-list">{section.items.map((item) => <a className="lc-data-list-row" href={preserveLocale(item.url)} key={String(item.id ?? item.url)}><span><strong>{item.title}</strong></span>{item.status ? <span className="lc-status-chip">{item.status.replaceAll("_", " ")}</span> : <span aria-hidden="true">Open</span>}</a>)}</div> : <p className="lc-empty-copy">Nothing to resume here yet.</p>}</section>)}</div>
  </section>;
}

export function mountHomeWorkspace(element: HTMLElement): void {
  const homeUrl = element.dataset.homeUrl;
  const joinUrl = element.dataset.joinUrl;
  const helpUrl = element.dataset.helpUrl;
  if (!homeUrl || !joinUrl || !helpUrl) return;
  createRoot(element).render(<HomeWorkspace homeUrl={homeUrl} mode={element.dataset.mode || "learning"} authenticated={element.dataset.authenticated === "true"} joinUrl={joinUrl} helpUrl={helpUrl} />);
}
