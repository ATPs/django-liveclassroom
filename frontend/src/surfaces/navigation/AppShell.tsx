import * as React from "react";
import { createRoot } from "react-dom/client";

import { preserveLocale, requestApplicationNavigation } from "../../navigation.js";
import { switchLocalePage } from "../../locales.js";
import { getJson } from "../../protocol.js";

type Context = {
  kind: "course" | "class";
  id: number;
  title: string;
  teaching_url?: string;
  learning_url?: string;
  results_url?: string;
};

type Bootstrap = {
  locale: "en" | "zh-Hans";
  mode: "guest" | "teaching" | "learning" | "student_preview";
  path: string;
  authenticated: boolean;
  teacher_allowed: boolean;
  user_label: string;
  preference_namespace: string;
  links: Record<string, string>;
  host_links: Record<string, string>;
  current_context: Context | null;
  current_ref: string;
};

type Destination = { key: string; label: string; href?: string; initial: string; ref?: string };
type Group = { key: string; label: string; destinations: Destination[] };
type Preferences = { version: 2; collapsed: boolean; pins: string[]; recent: string[] };
type ResolvedDestination = { ref: string; label: string; url: string; kind: string };
type NavigationPayload = { resolved: ResolvedDestination[] };

const MAX_PINS = 12;
const MAX_RECENT = 10;
const DRAWER_EVENT = "liveclassroom:shell-drawer";

function isMobileViewport(): boolean {
  return window.matchMedia("(max-width: 767px)").matches;
}

function publishDrawer(open: boolean): void {
  window.dispatchEvent(new CustomEvent<{ open: boolean }>(DRAWER_EVENT, { detail: { open } }));
}

function tr(bootstrap: Bootstrap, english: string, chinese: string): string {
  return bootstrap.locale === "zh-Hans" ? chinese : english;
}

function storageKey(bootstrap: Bootstrap): string {
  return `liveclassroom:shell:${bootstrap.preference_namespace}`;
}

function loadPreferences(bootstrap: Bootstrap): Preferences {
  const fallback: Preferences = { version: 2, collapsed: window.matchMedia("(max-width: 1199px)").matches, pins: [], recent: [] };
  try {
    const parsed = JSON.parse(window.localStorage.getItem(storageKey(bootstrap)) || "{}") as Partial<Preferences>;
    if (parsed.version !== 2) return fallback;
    return {
      version: 2,
      collapsed: Boolean(parsed.collapsed),
      pins: Array.isArray(parsed.pins) ? parsed.pins.filter((value): value is string => typeof value === "string").slice(0, MAX_PINS) : [],
      recent: Array.isArray(parsed.recent) ? parsed.recent.filter((value): value is string => typeof value === "string").slice(0, MAX_RECENT) : [],
    };
  } catch {
    return fallback;
  }
}

function savePreferences(bootstrap: Bootstrap, preferences: Preferences): void {
  try {
    window.localStorage.setItem(storageKey(bootstrap), JSON.stringify(preferences));
  } catch {
    // Navigation remains usable when storage is disabled or full.
  }
}

function publishPreferences(preferences: Preferences): void {
  window.dispatchEvent(new CustomEvent<Preferences>("liveclassroom:shell-preferences", { detail: preferences }));
}

function groups(bootstrap: Bootstrap): Group[] {
  const links = bootstrap.links;
  const teaching: Destination[] = [
    { key: "teacher", label: tr(bootstrap, "Teacher console", "教师工作台"), href: links.teacher, initial: "T", ref: "page:teacher" },
    { key: "courses", label: tr(bootstrap, "Teaching courses", "教学课程"), href: links.courses, initial: "C", ref: "page:teaching-courses" },
    { key: "classes", label: tr(bootstrap, "Classes", "班级"), href: links.classes, initial: "K", ref: "page:teaching-classes" },
    { key: "sessions", label: tr(bootstrap, "Sessions", "课堂"), href: links.sessions, initial: "S", ref: "page:teacher-sessions" },
    { key: "results", label: tr(bootstrap, "Results and grading", "成绩与评分"), href: links.results, initial: "R", ref: "page:teacher-results" },
  ];
  const materials: Destination[] = [
    { key: "lessons", label: tr(bootstrap, "Lessons", "教案"), href: links.lessons, initial: "L", ref: "page:lessons" },
    { key: "decks", label: tr(bootstrap, "Slide decks", "幻灯片"), href: links.decks, initial: "D", ref: "page:decks" },
    { key: "assessments", label: tr(bootstrap, "Assessments", "测验"), href: links.assessments, initial: "A", ref: "page:assessments" },
    { key: "questions", label: tr(bootstrap, "Question bank", "题库"), href: links.questions, initial: "Q", ref: "page:questions" },
    { key: "shared", label: tr(bootstrap, "Shared with me", "共享给我的内容"), href: links.shared, initial: "H", ref: "page:shared" },
  ];
  const learning: Destination[] = [
    { key: "learning", label: tr(bootstrap, "My courses", "我的课程"), href: links.learning, initial: "M", ref: "page:learning" },
    { key: "history", label: tr(bootstrap, "My attempts and results", "我的作答和结果"), href: links.history, initial: "Y", ref: "page:history" },
  ];
  const result: Group[] = [];
  if (bootstrap.teacher_allowed) {
    result.push({ key: "teaching", label: tr(bootstrap, "Teaching", "教学"), destinations: teaching.filter((item) => item.href) });
    result.push({ key: "materials", label: tr(bootstrap, "Materials", "教学材料"), destinations: materials.filter((item) => item.href) });
  }
  if (bootstrap.authenticated) result.push({ key: "learning", label: tr(bootstrap, "Learning", "学习"), destinations: learning.filter((item) => item.href) });
  if (bootstrap.current_context?.title) {
    const context = bootstrap.current_context;
    result.push({
      key: "context",
      label: context.title,
      destinations: [
        { key: "overview", label: tr(bootstrap, "Overview", "概览"), href: context.teaching_url || context.learning_url, initial: "O" },
        { key: "context-results", label: tr(bootstrap, "Results", "结果"), href: context.results_url, initial: "R" },
      ].filter((item) => item.href),
    });
  }
  return result;
}

function destinationForMode(bootstrap: Bootstrap, mode: string): string {
  const context = bootstrap.current_context;
  if (bootstrap.path === bootstrap.links.home && (mode === "teaching" || mode === "learning")) {
    const home = new URL(bootstrap.links.home, window.location.href);
    home.searchParams.set("mode", mode);
    return `${home.pathname}${home.search}`;
  }
  if (mode === "teaching") return context?.teaching_url || bootstrap.links.teacher || bootstrap.links.home;
  if (mode === "learning") return context?.learning_url || bootstrap.links.learning || bootstrap.links.home;
  return bootstrap.links.student_preview || bootstrap.links.teacher || bootstrap.links.home;
}

function recordRecent(bootstrap: Bootstrap, reference?: string): void {
  if (!reference || reference === bootstrap.current_ref) return;
  const preferences = loadPreferences(bootstrap);
  preferences.recent = [reference, ...preferences.recent.filter((item) => item !== reference)].slice(0, MAX_RECENT);
  savePreferences(bootstrap, preferences);
}

function navigateFromShell(
  event: React.MouseEvent<HTMLAnchorElement>,
  bootstrap: Bootstrap,
  href: string,
  reference?: string,
  onNavigate?: () => void,
): void {
  if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  event.preventDefault();
  requestApplicationNavigation(() => {
    onNavigate?.();
    recordRecent(bootstrap, reference);
    window.location.assign(preserveLocale(href));
  });
}

function ShellHeader({ bootstrap }: { bootstrap: Bootstrap }) {
  const [preferences, setPreferences] = React.useState(() => loadPreferences(bootstrap));
  const [mobile, setMobile] = React.useState(isMobileViewport);
  const [drawerOpen, setDrawerOpen] = React.useState(false);
  const root = document.querySelector<HTMLElement>("[data-classroom-shell]");
  React.useEffect(() => {
    const media = window.matchMedia("(max-width: 767px)");
    const update = () => {
      setMobile(media.matches);
      if (!media.matches) setDrawerOpen(false);
    };
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  React.useEffect(() => {
    const sync = (event: Event) => setDrawerOpen((event as CustomEvent<{ open: boolean }>).detail.open);
    window.addEventListener(DRAWER_EVENT, sync);
    return () => window.removeEventListener(DRAWER_EVENT, sync);
  }, []);
  React.useEffect(() => {
    if (root) root.dataset.sidebar = preferences.collapsed ? "collapsed" : "expanded";
    savePreferences(bootstrap, preferences);
    publishPreferences(preferences);
  }, [bootstrap, preferences, root]);
  React.useEffect(() => {
    if (root) root.dataset.drawer = drawerOpen ? "open" : "closed";
    publishDrawer(drawerOpen);
  }, [drawerOpen, root]);
  const modes = [
    ...(bootstrap.teacher_allowed ? [{ value: "teaching", label: tr(bootstrap, "Teaching", "教学") }] : []),
    ...(bootstrap.authenticated ? [{ value: "learning", label: tr(bootstrap, "Learning", "学习") }] : []),
    ...(bootstrap.teacher_allowed ? [{ value: "student_preview", label: tr(bootstrap, "Student preview", "学生预览") }] : []),
  ];
  const pinCurrent = () => {
    const reference = bootstrap.current_ref;
    if (!reference) return;
    setPreferences((current) => {
      const pins = current.pins.includes(reference)
        ? current.pins.filter((item) => item !== reference)
        : [reference, ...current.pins].slice(0, MAX_PINS);
      return { ...current, pins };
    });
  };
  const pinned = Boolean(bootstrap.current_ref && preferences.pins.includes(bootstrap.current_ref));
  return <>
    <div className="lc-shell-brand"><a href={preserveLocale(bootstrap.links.home)} onClick={(event) => navigateFromShell(event, bootstrap, bootstrap.links.home, "page:home", () => setDrawerOpen(false))}>LiveClassroom</a></div>
    <button type="button" className="lc-shell-toggle" aria-label={tr(bootstrap, "Toggle navigation", "切换导航")} aria-expanded={mobile ? drawerOpen : !preferences.collapsed} onClick={() => {
      if (mobile) setDrawerOpen((open) => !open);
      else setPreferences((value) => ({ ...value, collapsed: !value.collapsed }));
    }}>M</button>
    <div className="lc-shell-header-context">{bootstrap.current_context?.title || tr(bootstrap, "Workspace", "工作区")}</div>
    <div className="lc-shell-header-actions">
      {modes.length ? <label className="lc-shell-role"><span>{tr(bootstrap, "Role", "角色")}</span><select value={bootstrap.mode === "guest" ? "learning" : bootstrap.mode} onChange={(event) => {
        const destination = destinationForMode(bootstrap, event.target.value);
        requestApplicationNavigation(() => window.location.assign(preserveLocale(destination)));
      }}>{modes.map((item) => <option value={item.value} key={item.value}>{item.label}</option>)}</select></label> : null}
      <button type="button" className="lc-shell-icon-button" disabled={!bootstrap.current_ref} aria-label={pinned ? tr(bootstrap, "Unpin this page", "取消固定此页面") : tr(bootstrap, "Pin this page", "固定此页面")} title={pinned ? tr(bootstrap, "Unpin this page", "固定此页面") : tr(bootstrap, "Pin this page", "固定此页面")} onClick={pinCurrent}>P</button>
      <button type="button" className="lc-shell-icon-button" aria-label={tr(bootstrap, "Switch language", "切换语言")} title={tr(bootstrap, "Switch language", "切换语言")} onClick={() => switchLocalePage(bootstrap.locale === "zh-Hans" ? "en" : "zh-Hans")}>{bootstrap.locale === "zh-Hans" ? "EN" : "ZH"}</button>
      {bootstrap.authenticated && bootstrap.host_links.account_url ? <a className="lc-shell-user" href={bootstrap.host_links.account_url}>{bootstrap.user_label || tr(bootstrap, "Account", "账户")}</a> : null}
      {bootstrap.authenticated && bootstrap.host_links.logout_url ? <form method="post" action={logoutUrl(bootstrap.host_links.logout_url)} className="lc-shell-logout"><input type="hidden" name="csrfmiddlewaretoken" value={csrfToken()} /><button type="submit" className="lc-shell-icon-button" title={tr(bootstrap, "Sign out", "退出登录")} aria-label={tr(bootstrap, "Sign out", "退出登录")}>O</button></form> : null}
      {!bootstrap.authenticated && bootstrap.host_links.login_url ? <a className="lc-shell-user" href={bootstrap.host_links.login_url}>{tr(bootstrap, "Sign in", "登录")}</a> : null}
    </div>
  </>;
}

function csrfToken(): string {
  return document.querySelector<HTMLInputElement>("input[name='csrfmiddlewaretoken']")?.value || "";
}

function logoutUrl(value: string): string {
  const url = new URL(value, window.location.href);
  url.searchParams.set("next", `${window.location.pathname}${window.location.search}`);
  return `${url.pathname}${url.search}${url.hash}`;
}

function AppNavigation({ bootstrap }: { bootstrap: Bootstrap }) {
  const [filter, setFilter] = React.useState("");
  const [preferences, setPreferences] = React.useState(() => loadPreferences(bootstrap));
  const [resolved, setResolved] = React.useState<ResolvedDestination[]>([]);
  const [openGroup, setOpenGroup] = React.useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = React.useState(false);
  const navigationRef = React.useRef<HTMLElement>(null);
  const groupLaunchers = React.useRef(new Map<string, HTMLButtonElement>());
  const filterValue = filter.trim().toLocaleLowerCase();
  const visibleGroups = groups(bootstrap).map((group) => ({
    ...group,
    destinations: group.destinations.filter((item) => !filterValue || item.label.toLocaleLowerCase().includes(filterValue)),
  })).filter((group) => group.destinations.length);
  const closeDrawer = React.useCallback(() => publishDrawer(false), []);
  const link = (item: Destination) => <a key={item.key} className="lc-shell-link" href={preserveLocale(item.href || "")} data-current={bootstrap.path === item.href ? "true" : undefined} title={item.label} onClick={(event) => item.href && navigateFromShell(event, bootstrap, item.href, item.ref, closeDrawer)}><span aria-hidden="true" className="lc-shell-link-icon">{item.initial}</span><span className="lc-shell-link-label">{item.label}</span></a>;
  const removeReference = (reference: string) => setPreferences((current) => ({
    ...current,
    pins: current.pins.filter((item) => item !== reference),
    recent: current.recent.filter((item) => item !== reference),
  }));
  React.useEffect(() => savePreferences(bootstrap, preferences), [bootstrap, preferences]);
  React.useEffect(() => {
    const sync = (event: Event) => setPreferences((event as CustomEvent<Preferences>).detail);
    window.addEventListener("liveclassroom:shell-preferences", sync);
    return () => window.removeEventListener("liveclassroom:shell-preferences", sync);
  }, []);
  React.useEffect(() => {
    const sync = (event: Event) => setDrawerOpen((event as CustomEvent<{ open: boolean }>).detail.open);
    window.addEventListener(DRAWER_EVENT, sync);
    return () => window.removeEventListener(DRAWER_EVENT, sync);
  }, []);
  React.useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setFilter("");
      if (drawerOpen) {
        event.preventDefault();
        closeDrawer();
        window.requestAnimationFrame(() => document.querySelector<HTMLButtonElement>(".lc-shell-toggle")?.focus());
        return;
      }
      if (openGroup) {
        const launcher = groupLaunchers.current.get(openGroup);
        setOpenGroup(null);
        window.requestAnimationFrame(() => launcher?.focus());
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [closeDrawer, drawerOpen, openGroup]);
  React.useEffect(() => {
    if (!drawerOpen) return;
    const navigation = navigationRef.current;
    if (!navigation) return;
    const selector = "a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])";
    const focusable = () => Array.from(navigation.querySelectorAll<HTMLElement>(selector)).filter((element) => !element.hidden);
    window.requestAnimationFrame(() => focusable()[0]?.focus());
    const trapFocus = (event: KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const controls = focusable();
      if (!controls.length) return;
      const first = controls[0];
      const last = controls[controls.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", trapFocus);
    return () => window.removeEventListener("keydown", trapFocus);
  }, [drawerOpen]);
  React.useEffect(() => {
    const references = [...preferences.pins, ...preferences.recent].slice(0, MAX_PINS + MAX_RECENT);
    if (!bootstrap.authenticated || !bootstrap.links.navigation || !references.length) {
      setResolved([]);
      return;
    }
    const controller = new AbortController();
    const url = new URL(bootstrap.links.navigation, window.location.href);
    references.forEach((reference) => url.searchParams.append("ref", reference));
    void getJson<NavigationPayload>(url.toString(), { signal: controller.signal }).then((payload) => {
      if (controller.signal.aborted) return;
      const allowed = new Set(payload.resolved.map((item) => item.ref));
      setResolved(payload.resolved);
      setPreferences((current) => {
        const pins = current.pins.filter((reference) => allowed.has(reference));
        const recent = current.recent.filter((reference) => allowed.has(reference));
        if (pins.length === current.pins.length && recent.length === current.recent.length) return current;
        return { ...current, pins, recent };
      });
    }).catch(() => {
      if (!controller.signal.aborted) setResolved([]);
    });
    return () => controller.abort();
  }, [bootstrap.authenticated, bootstrap.links.navigation, preferences.pins, preferences.recent]);
  const resolvedByReference = new Map(resolved.map((item) => [item.ref, item]));
  const movePin = (reference: string, direction: -1 | 1) => setPreferences((current) => {
    const from = current.pins.indexOf(reference);
    const to = from + direction;
    if (from < 0 || to < 0 || to >= current.pins.length) return current;
    const pins = [...current.pins];
    [pins[from], pins[to]] = [pins[to], pins[from]];
    return { ...current, pins };
  });
  const savedLink = (reference: string, pinned: boolean) => {
    const item = resolvedByReference.get(reference);
    if (!item) return null;
    return <div className="lc-shell-saved-link" key={reference}>
      <a href={preserveLocale(item.url)} onClick={(event) => navigateFromShell(event, bootstrap, item.url, reference, closeDrawer)}>
        <span aria-hidden="true">{pinned ? "P" : "R"}</span><span>{item.label}</span>
      </a>
      {pinned ? <span className="lc-shell-saved-actions">
        <button type="button" aria-label={tr(bootstrap, "Move pin up", "上移固定项")} title={tr(bootstrap, "Move pin up", "上移固定项")} onClick={() => movePin(reference, -1)}>^</button>
        <button type="button" aria-label={tr(bootstrap, "Move pin down", "下移固定项")} title={tr(bootstrap, "Move pin down", "下移固定项")} onClick={() => movePin(reference, 1)}>v</button>
        <button type="button" aria-label={tr(bootstrap, "Remove pin", "取消固定")} title={tr(bootstrap, "Remove pin", "取消固定")} onClick={() => removeReference(reference)}>x</button>
      </span> : null}
    </div>;
  };
  const renderGroup = (group: Group, contents: React.ReactNode = group.destinations.map(link)) => {
    const expanded = !preferences.collapsed || openGroup === group.key;
    const closeIfLeaving = (event: React.FocusEvent<HTMLDivElement>) => {
      if (!preferences.collapsed || !openGroup || event.currentTarget.contains(event.relatedTarget as Node | null)) return;
      setOpenGroup(null);
    };
    return <div className="lc-shell-group" key={group.key} onBlur={closeIfLeaving}>
      <button
        type="button"
        className="lc-shell-group-toggle"
        data-initial={group.label.slice(0, 1)}
        aria-expanded={expanded}
        aria-controls={`lc-shell-group-${group.key}`}
        ref={(element) => {
          if (element) groupLaunchers.current.set(group.key, element);
          else groupLaunchers.current.delete(group.key);
        }}
        onClick={() => setOpenGroup((current) => current === group.key ? null : group.key)}
      >{group.label}</button>
      {expanded ? <div id={`lc-shell-group-${group.key}`} className="lc-shell-group-menu">{contents}</div> : null}
    </div>;
  };
  const visiblePins = preferences.pins.filter((reference) => {
    const item = resolvedByReference.get(reference);
    return item && (!filterValue || item.label.toLocaleLowerCase().includes(filterValue));
  });
  const visibleRecent = preferences.recent.filter((reference) => {
    const item = resolvedByReference.get(reference);
    return item && (!filterValue || item.label.toLocaleLowerCase().includes(filterValue));
  });
  return <nav ref={navigationRef} className="lc-shell-navigation" aria-label={tr(bootstrap, "Classroom navigation", "课堂导航")}>
    <div className="lc-shell-drawer-title"><span>{tr(bootstrap, "Navigation", "导航")}</span><button type="button" className="lc-shell-icon-button" aria-label={tr(bootstrap, "Close navigation", "关闭导航")} onClick={closeDrawer}>x</button></div>
    <label className="lc-shell-filter"><span>{tr(bootstrap, "Filter navigation", "筛选导航")}</span><input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder={tr(bootstrap, "Filter", "筛选")} /></label>
    <a className="lc-shell-link" href={preserveLocale(bootstrap.links.home)} data-current={bootstrap.path === bootstrap.links.home ? "true" : undefined} title={tr(bootstrap, "Home", "首页")} onClick={(event) => navigateFromShell(event, bootstrap, bootstrap.links.home, "page:home")}><span aria-hidden="true" className="lc-shell-link-icon">H</span><span className="lc-shell-link-label">{tr(bootstrap, "Home", "首页")}</span></a>
    {visibleGroups.map((group) => renderGroup(group))}
    {visiblePins.length ? renderGroup(
      { key: "pins", label: tr(bootstrap, "Pinned", "固定"), destinations: [] },
      visiblePins.map((reference) => savedLink(reference, true)),
    ) : null}
    {visibleRecent.length ? renderGroup(
      { key: "recent", label: tr(bootstrap, "Recent", "最近访问"), destinations: [] },
      visibleRecent.map((reference) => savedLink(reference, false)),
    ) : null}
    <div className="lc-shell-utility-links">
      {link({ key: "join", label: tr(bootstrap, "Join a session", "加入课堂"), href: bootstrap.links.join, initial: "J", ref: "page:join" })}
      {link({ key: "help", label: tr(bootstrap, "Help", "帮助"), href: bootstrap.links.help, initial: "?", ref: "page:help" })}
      {bootstrap.host_links.home_url ? link({ key: "site", label: tr(bootstrap, "Back to site", "返回网站"), href: bootstrap.host_links.home_url, initial: "B" }) : null}
    </div>
  </nav>;
}

function parseBootstrap(): Bootstrap | null {
  const element = document.getElementById("liveclassroom-navigation-bootstrap");
  if (!element?.textContent) return null;
  try {
    return JSON.parse(element.textContent) as Bootstrap;
  } catch {
    return null;
  }
}

function ShellDrawerOverlay({ bootstrap }: { bootstrap: Bootstrap }) {
  const [drawerOpen, setDrawerOpen] = React.useState(false);
  React.useEffect(() => {
    const sync = (event: Event) => setDrawerOpen((event as CustomEvent<{ open: boolean }>).detail.open);
    window.addEventListener(DRAWER_EVENT, sync);
    return () => window.removeEventListener(DRAWER_EVENT, sync);
  }, []);
  if (!drawerOpen) return null;
  return <button
    type="button"
    className="lc-shell-drawer-dismiss"
    aria-label={tr(bootstrap, "Close navigation", "关闭导航")}
    onClick={() => {
      publishDrawer(false);
      window.requestAnimationFrame(() => document.querySelector<HTMLButtonElement>(".lc-shell-toggle")?.focus());
    }}
  />;
}

export function mountAppShell(): void {
  const bootstrap = parseBootstrap();
  const header = document.querySelector<HTMLElement>("[data-liveclassroom-shell-header]");
  const navigation = document.querySelector<HTMLElement>("[data-liveclassroom-shell-navigation]");
  const overlay = document.querySelector<HTMLElement>("[data-liveclassroom-shell-overlay]");
  if (!bootstrap || !header || !navigation) return;
  createRoot(header).render(<ShellHeader bootstrap={bootstrap} />);
  createRoot(navigation).render(<AppNavigation bootstrap={bootstrap} />);
  if (overlay) createRoot(overlay).render(<ShellDrawerOverlay bootstrap={bootstrap} />);
}
