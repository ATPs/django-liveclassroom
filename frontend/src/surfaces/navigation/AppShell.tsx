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
  classes_url?: string;
  lessons_url?: string;
  sessions_url?: string;
  assessments_url?: string;
  students_url?: string;
  results_url?: string;
};

type Bootstrap = {
  locale: "en" | "zh-Hans";
  mode: "guest" | "teaching" | "learning" | "student_preview";
  path: string;
  authenticated: boolean;
  teacher_allowed: boolean;
  allowed_modes?: Array<"teaching" | "learning" | "student_preview">;
  user_label: string;
  preference_namespace: string;
  links: Record<string, string>;
  host_links: Record<string, string>;
  current_context: Context | null;
  current_ref: string;
};

type Destination = { key: string; label: string; href?: string; icon: string; ref?: string };
type Group = { key: string; label: string; destinations: Destination[] };
type Preferences = { version: 2; collapsed: boolean; rememberedMode?: "teaching" | "learning"; pins: string[]; recent: string[] };
type ResolvedDestination = { ref: string; label: string; url: string; kind: string };
type NavigationContext = Context;
type NavigationPayload = { resolved: ResolvedDestination[]; contexts?: NavigationContext[] };
type CurrentShellEvent = { path: string; reference: string; context: Context | null };
type PendingRecent = { namespace: string; reference: string; href: string };

const MAX_PINS = 12;
const MAX_RECENT = 10;
const DRAWER_EVENT = "liveclassroom:shell-drawer";
const CURRENT_EVENT = "liveclassroom:shell-current";
const PENDING_RECENT_KEY = "liveclassroom:shell-pending-recent";

function Icon({ name, size = 18 }: { name: string; size?: number }): React.ReactElement {
  const common = { fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  let content: React.ReactNode;
  switch (name) {
    case "menu": content = <><path {...common} d="M3 5h18M3 12h18M3 19h18" /></>; break;
    case "home": content = <><path {...common} d="m3 11 9-8 9 8v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z" /><path {...common} d="M9 21v-6h6v6" /></>; break;
    case "teacher": content = <><path {...common} d="M4 19V5h16v14M2 19h20" /><path {...common} d="m7 9 3 2 3-2 3 2-3 2-3-2-3 2z" /></>; break;
    case "course": content = <><path {...common} d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v15H6.5A2.5 2.5 0 0 0 4 20.5z" /><path {...common} d="M4 5.5v15M8 7h8M8 11h8" /></>; break;
    case "class": content = <><path {...common} d="M4 19h16M6 17V7h12v10M9 7V4h6v3" /><circle {...common} cx="12" cy="11" r="2" /></>; break;
    case "session": content = <><rect {...common} x="3" y="5" width="18" height="14" rx="2" /><path {...common} d="m10 9 5 3-5 3z" /></>; break;
    case "results": content = <><path {...common} d="M4 19V5M4 19h16" /><path {...common} d="m7 15 3-4 3 2 5-7" /></>; break;
    case "lesson": content = <><path {...common} d="M5 4h14v16H5z" /><path {...common} d="M8 8h8M8 12h8M8 16h5" /></>; break;
    case "deck": content = <><rect {...common} x="3" y="4" width="18" height="14" rx="1" /><path {...common} d="m8 14 3-4 2 2 2-2 3 4M8 21h8" /></>; break;
    case "assessment": content = <><path {...common} d="M6 3h12v18H6z" /><path {...common} d="m9 8 1.5 1.5L13 7M9 13h6M9 17h6" /></>; break;
    case "question": content = <><circle {...common} cx="12" cy="12" r="9" /><path {...common} d="M9.5 9a2.5 2.5 0 1 1 4.4 1.6c-.9 1-1.9 1.3-1.9 2.9M12 17h.01" /></>; break;
    case "shared": content = <><circle {...common} cx="8" cy="12" r="3" /><circle {...common} cx="17" cy="7" r="3" /><circle {...common} cx="17" cy="17" r="3" /><path {...common} d="m10.5 10.5 3.5-2M10.5 13.5l3.5 2" /></>; break;
    case "learning": content = <><path {...common} d="m3 7 9-4 9 4-9 4zM6 9v5c2 2 10 2 12 0V9" /><path {...common} d="M21 8v6" /></>; break;
    case "history": content = <><path {...common} d="M4 12a8 8 0 1 0 2.3-5.7L4 8.5M4 4v4.5h4.5" /><path {...common} d="M12 7v5l3 2" /></>; break;
    case "join": content = <><path {...common} d="M12 3v12M7 8l5-5 5 5M5 13v6h14v-6" /></>; break;
    case "help": content = <><circle {...common} cx="12" cy="12" r="9" /><path {...common} d="M9.5 9a2.5 2.5 0 1 1 4.4 1.6c-.9 1-1.9 1.3-1.9 2.9M12 17h.01" /></>; break;
    case "pin": content = <><path {...common} d="m15 4 5 5-3 1-3 5-2-2-5 3 3-5-2-2 5-3zM12 14l-4 7" /></>; break;
    case "recent": content = <><path {...common} d="M4 12a8 8 0 1 0 2-5.3M4 4v4h4" /><path {...common} d="M12 7v5l3 2" /></>; break;
    case "back": content = <><path {...common} d="M19 12H5M11 6l-6 6 6 6" /></>; break;
    case "close": content = <><path {...common} d="m5 5 14 14M19 5 5 19" /></>; break;
    case "up": content = <><path {...common} d="m6 14 6-6 6 6" /></>; break;
    case "down": content = <><path {...common} d="m6 10 6 6 6-6" /></>; break;
    case "account": content = <><circle {...common} cx="12" cy="8" r="3" /><path {...common} d="M5 20a7 7 0 0 1 14 0" /></>; break;
    case "logout": content = <><path {...common} d="M14 4H5v16h9M10 12h10M17 8l4 4-4 4" /></>; break;
    case "overview": content = <><path {...common} d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z" /></>; break;
    case "students": content = <><circle {...common} cx="9" cy="8" r="3" /><path {...common} d="M3 20a6 6 0 0 1 12 0M16 11a3 3 0 1 1 2.5-1.3M17 14a5 5 0 0 1 4 6" /></>; break;
    case "site": content = <><circle {...common} cx="12" cy="12" r="9" /><path {...common} d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18" /></>; break;
    default: content = <circle {...common} cx="12" cy="12" r="8" />;
  }
  return <svg className="lc-icon" aria-hidden="true" width={size} height={size} viewBox="0 0 24 24">{content}</svg>;
}

function isMobileViewport(): boolean {
  return window.matchMedia("(max-width: 767px)").matches;
}

function publishDrawer(open: boolean): void {
  window.dispatchEvent(new CustomEvent<{ open: boolean }>(DRAWER_EVENT, { detail: { open } }));
}

function tr(bootstrap: Bootstrap, english: string, chinese: string): string {
  return bootstrap.locale === "zh-Hans" ? chinese : english;
}

function pathReference(bootstrap: Bootstrap, pathname: string): string {
  for (const [key, href] of Object.entries(bootstrap.links)) {
    if (!href || !key) continue;
    try {
      if (new URL(href, window.location.href).pathname === pathname) {
        const pageByKey: Record<string, string> = { home: "page:home", help: "page:help", join: "page:join", learning: "page:learning", history: "page:history", teacher: "page:teacher", courses: "page:teaching-courses", classes: "page:teaching-classes", sessions: "page:teacher-sessions", results: "page:teacher-results", lessons: "page:lessons", decks: "page:decks", assessments: "page:assessments", questions: "page:questions", shared: "page:shared", student_preview: "page:student-preview" };
        const page = pageByKey[key];
        if (page) return page;
      }
    } catch {
      // Ignore malformed optional host links.
    }
  }
  const parts = pathname.split("/").filter(Boolean);
  const numberAfter = (name: string): string | null => {
    const index = parts.lastIndexOf(name);
    const value = index >= 0 ? parts[index + 1] : "";
    return value && /^\d+$/.test(value) ? value : null;
  };
  const teacherIndex = parts.lastIndexOf("teacher");
  if (teacherIndex >= 0) {
    const section = parts[teacherIndex + 1];
    const id = section ? parts[teacherIndex + 2] : "";
    if (section === "courses" && /^\d+$/.test(id || "")) {
      if (parts[teacherIndex + 3] === "classes" && /^\d+$/.test(parts[teacherIndex + 4] || "")) return `class:${parts[teacherIndex + 4]}:teaching`;
      return `course:${id}:teaching`;
    }
    if (section === "classes" && /^\d+$/.test(id || "")) return `class:${id}:teaching`;
    if (section === "sessions" && /^\d+$/.test(id || "")) return `session:${id}:${parts[teacherIndex + 3] === "student-view" ? "preview" : "teaching"}`;
    if (section === "flows" && /^\d+$/.test(id || "")) return `flow:${id}`;
    if (section === "decks" && /^\d+$/.test(id || "")) return `deck:${id}`;
    if (section === "assessments" && /^\d+$/.test(id || "")) return `assessment:${id}`;
  }
  const learnIndex = parts.lastIndexOf("learn");
  if (learnIndex >= 0) {
    const section = parts[learnIndex + 1];
    const id = parts[learnIndex + 2];
    if (section === "courses" && /^\d+$/.test(id || "")) return `course:${id}:learning`;
    if (section === "classes" && /^\d+$/.test(id || "")) return `class:${id}:learning`;
  }
  const sessionId = numberAfter("sessions");
  if (sessionId && teacherIndex < 0) return `session:${sessionId}:learning`;
  const attemptIndex = parts.lastIndexOf("attempts");
  if (attemptIndex >= 0 && parts[attemptIndex + 1]) return `attempt:${parts[attemptIndex + 1]}`;
  return "";
}

function contextForReference(contexts: NavigationContext[] | undefined, reference: string): Context | null {
  const [kind, id] = reference.split(":");
  const numericId = Number(id);
  if ((kind !== "course" && kind !== "class") || !Number.isInteger(numericId)) return null;
  return contexts?.find((context) => context.kind === kind && context.id === numericId) ?? null;
}

function storageKey(bootstrap: Bootstrap): string {
  return `liveclassroom:shell:${bootstrap.preference_namespace}`;
}

const memoryPreferences = new Map<string, Preferences>();

function loadPreferences(bootstrap: Bootstrap): Preferences {
  const fallback: Preferences = { version: 2, collapsed: window.matchMedia("(max-width: 1199px)").matches, pins: [], recent: [] };
  try {
    const parsed = JSON.parse(window.localStorage.getItem(storageKey(bootstrap)) || "{}") as Partial<Preferences>;
    if (parsed.version !== 2) return fallback;
    return {
      version: 2,
      collapsed: Boolean(parsed.collapsed),
      rememberedMode: parsed.rememberedMode === "teaching" || parsed.rememberedMode === "learning" ? parsed.rememberedMode : undefined,
      pins: Array.isArray(parsed.pins) ? parsed.pins.filter((value): value is string => typeof value === "string").slice(0, MAX_PINS) : [],
      recent: Array.isArray(parsed.recent) ? parsed.recent.filter((value): value is string => typeof value === "string").slice(0, MAX_RECENT) : [],
    };
  } catch {
    return memoryPreferences.get(storageKey(bootstrap)) ?? fallback;
  }
}

function savePreferences(bootstrap: Bootstrap, preferences: Preferences): void {
  memoryPreferences.set(storageKey(bootstrap), preferences);
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
    { key: "teacher", label: tr(bootstrap, "Teacher console", "教师工作台"), href: links.teacher, icon: "teacher", ref: "page:teacher" },
    { key: "courses", label: tr(bootstrap, "Teaching courses", "教学课程"), href: links.courses, icon: "course", ref: "page:teaching-courses" },
    { key: "classes", label: tr(bootstrap, "Classes", "班级"), href: links.classes, icon: "class", ref: "page:teaching-classes" },
    { key: "sessions", label: tr(bootstrap, "Sessions", "课堂"), href: links.sessions, icon: "session", ref: "page:teacher-sessions" },
    { key: "results", label: tr(bootstrap, "Results and grading", "成绩与评分"), href: links.results, icon: "results", ref: "page:teacher-results" },
  ];
  const materials: Destination[] = [
    { key: "lessons", label: tr(bootstrap, "Lessons", "教案"), href: links.lessons, icon: "lesson", ref: "page:lessons" },
    { key: "decks", label: tr(bootstrap, "Slide decks", "幻灯片"), href: links.decks, icon: "deck", ref: "page:decks" },
    { key: "assessments", label: tr(bootstrap, "Assessments", "测验"), href: links.assessments, icon: "assessment", ref: "page:assessments" },
    { key: "questions", label: tr(bootstrap, "Question bank", "题库"), href: links.questions, icon: "question", ref: "page:questions" },
    { key: "shared", label: tr(bootstrap, "Shared with me", "共享给我的内容"), href: links.shared, icon: "shared", ref: "page:shared" },
  ];
  const learning: Destination[] = [
    { key: "learning", label: tr(bootstrap, "My courses", "我的课程"), href: links.learning, icon: "learning", ref: "page:learning" },
    { key: "history", label: tr(bootstrap, "My attempts and results", "我的作答和结果"), href: links.history, icon: "history", ref: "page:history" },
  ];
  const result: Group[] = [];
  if (bootstrap.teacher_allowed && bootstrap.mode !== "learning") {
    result.push({ key: "teaching", label: tr(bootstrap, "Teaching", "教学"), destinations: teaching.filter((item) => item.href) });
    result.push({ key: "materials", label: tr(bootstrap, "Materials", "教学材料"), destinations: materials.filter((item) => item.href) });
  }
  if (bootstrap.authenticated && bootstrap.mode === "learning") result.push({ key: "learning", label: tr(bootstrap, "Learning", "学习"), destinations: learning.filter((item) => item.href) });
  if (bootstrap.current_context?.title) {
    const context = bootstrap.current_context;
    result.push({
      key: "context",
      label: context.title,
      destinations: [
        { key: "overview", label: tr(bootstrap, "Overview", "概览"), href: context.teaching_url || context.learning_url, icon: "overview" },
        { key: "classes", label: tr(bootstrap, "Classes", "班级"), href: context.classes_url, icon: "class" },
        { key: "lessons", label: tr(bootstrap, "Lessons", "教案"), href: context.lessons_url, icon: "lesson" },
        { key: "sessions", label: tr(bootstrap, "Sessions", "课堂"), href: context.sessions_url, icon: "session" },
        { key: "assessments", label: tr(bootstrap, "Assessments", "测验"), href: context.assessments_url, icon: "assessment" },
        { key: "students", label: tr(bootstrap, "Students", "学生"), href: context.students_url, icon: "students" },
        { key: "results", label: tr(bootstrap, "Results", "结果"), href: context.results_url, icon: "results" },
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
  if (mode === "teaching" || mode === "learning") {
    const matching = mode === "teaching" ? context?.teaching_url : context?.learning_url;
    if (matching) return matching;
    const home = new URL(bootstrap.links.home, window.location.href);
    home.searchParams.set("mode", mode);
    return `${home.pathname}${home.search}`;
  }
  return bootstrap.links.student_preview || bootstrap.links.teacher || bootstrap.links.home;
}

function queueRecent(bootstrap: Bootstrap, reference: string | undefined, href: string): void {
  if (!reference || reference === bootstrap.current_ref) return;
  try {
    const pending: PendingRecent = { namespace: bootstrap.preference_namespace, reference, href: preserveLocale(href) };
    window.sessionStorage.setItem(PENDING_RECENT_KEY, JSON.stringify(pending));
  } catch {
    // A disabled session store must never block navigation.
  }
}

function consumePendingRecent(bootstrap: Bootstrap): void {
  try {
    const raw = window.sessionStorage.getItem(PENDING_RECENT_KEY);
    if (!raw) return;
    const pending = JSON.parse(raw) as Partial<PendingRecent>;
    const reference = pending.reference;
    if (typeof reference !== "string") return;
    const target = typeof pending.href === "string" ? new URL(pending.href, window.location.href) : null;
    const arrived = pending.namespace === bootstrap.preference_namespace
      && reference === bootstrap.current_ref
      && target?.pathname === window.location.pathname;
    if (!arrived) return;
    const preferences = loadPreferences(bootstrap);
    preferences.recent = [reference, ...preferences.recent.filter((item) => item !== reference)].slice(0, MAX_RECENT);
    savePreferences(bootstrap, preferences);
    window.sessionStorage.removeItem(PENDING_RECENT_KEY);
  } catch {
    // Ignore malformed or unavailable session state.
  }
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
    queueRecent(bootstrap, reference, href);
    window.location.assign(preserveLocale(href));
  });
}

function ShellHeader({ bootstrap }: { bootstrap: Bootstrap }) {
  const [preferences, setPreferences] = React.useState(() => loadPreferences(bootstrap));
  const [current, setCurrent] = React.useState<CurrentShellEvent>({ path: bootstrap.path, reference: bootstrap.current_ref, context: bootstrap.current_context });
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
    const sync = (event: Event) => {
      const detail = (event as CustomEvent<CurrentShellEvent>).detail;
      if (detail?.path) setCurrent(detail);
    };
    window.addEventListener(CURRENT_EVENT, sync);
    return () => window.removeEventListener(CURRENT_EVENT, sync);
  }, []);
  const activeBootstrap = { ...bootstrap, path: current.path, current_ref: current.reference, current_context: current.context };
  React.useEffect(() => {
    const sync = (event: Event) => setDrawerOpen((event as CustomEvent<{ open: boolean }>).detail.open);
    window.addEventListener(DRAWER_EVENT, sync);
    return () => window.removeEventListener(DRAWER_EVENT, sync);
  }, []);
  React.useEffect(() => {
    if (root) root.dataset.sidebar = !mobile && preferences.collapsed ? "collapsed" : "expanded";
    savePreferences(bootstrap, preferences);
    publishPreferences(preferences);
  }, [bootstrap, preferences, root, mobile]);
  React.useEffect(() => {
    if (root) root.dataset.drawer = drawerOpen ? "open" : "closed";
    publishDrawer(drawerOpen);
  }, [drawerOpen, root]);
  const availableModes = activeBootstrap.allowed_modes ?? [
    ...(activeBootstrap.teacher_allowed ? ["teaching" as const] : []),
    ...(activeBootstrap.authenticated ? ["learning" as const] : []),
    ...(activeBootstrap.teacher_allowed ? ["student_preview" as const] : []),
  ];
  const modes = availableModes.map((value) => ({
    value,
    label: value === "teaching" ? tr(activeBootstrap, "Teaching", "教学") : value === "learning" ? tr(activeBootstrap, "Learning", "学习") : tr(activeBootstrap, "Student preview", "学生预览"),
  }));
  const selectedMode = availableModes.includes(activeBootstrap.mode as "teaching" | "learning" | "student_preview")
    ? activeBootstrap.mode
    : (preferences.rememberedMode && availableModes.includes(preferences.rememberedMode) ? preferences.rememberedMode : availableModes[0]);
  const pinCurrent = () => {
    const reference = activeBootstrap.current_ref;
    if (!reference) return;
    setPreferences((current) => {
      const pins = current.pins.includes(reference)
        ? current.pins.filter((item) => item !== reference)
        : [reference, ...current.pins].slice(0, MAX_PINS);
      return { ...current, pins };
    });
  };
  const pinned = Boolean(activeBootstrap.current_ref && preferences.pins.includes(activeBootstrap.current_ref));
  return <>
    <div className="lc-shell-brand"><a href={preserveLocale(bootstrap.links.home)} onClick={(event) => navigateFromShell(event, bootstrap, bootstrap.links.home, "page:home", () => setDrawerOpen(false))}>LiveClassroom</a></div>
    <button type="button" className="lc-shell-toggle" aria-label={tr(bootstrap, "Toggle navigation", "切换导航")} aria-expanded={mobile ? drawerOpen : !preferences.collapsed} onClick={() => {
      if (mobile) setDrawerOpen((open) => !open);
      else setPreferences((value) => ({ ...value, collapsed: !value.collapsed }));
    }}><Icon name="menu" /></button>
    <div className="lc-shell-header-context">{activeBootstrap.current_context?.title || tr(activeBootstrap, "Workspace", "工作区")}</div>
    <div className="lc-shell-header-actions">
      {modes.length ? <label className="lc-shell-role"><span>{tr(bootstrap, "Role", "角色")}</span><select value={selectedMode} onChange={(event) => {
        const nextMode = event.target.value as "teaching" | "learning" | "student_preview";
        const destination = destinationForMode(activeBootstrap, nextMode);
        const nextPreferences = { ...preferences, ...(nextMode === "teaching" || nextMode === "learning" ? { rememberedMode: nextMode } : {}) };
        requestApplicationNavigation(() => {
          setPreferences(nextPreferences);
          savePreferences(bootstrap, nextPreferences);
          window.location.assign(preserveLocale(destination));
        });
      }}>{modes.map((item) => <option value={item.value} key={item.value}>{item.label}</option>)}</select></label> : null}
      <button type="button" className="lc-shell-icon-button" disabled={!activeBootstrap.current_ref} aria-label={pinned ? tr(activeBootstrap, "Unpin this page", "取消固定此页面") : tr(activeBootstrap, "Pin this page", "固定此页面")} title={pinned ? tr(activeBootstrap, "Unpin this page", "固定此页面") : tr(activeBootstrap, "Pin this page", "固定此页面")} onClick={pinCurrent}><Icon name="pin" /></button>
      <button type="button" className="lc-shell-icon-button" aria-label={tr(bootstrap, "Switch language", "切换语言")} title={tr(bootstrap, "Switch language", "切换语言")} onClick={() => switchLocalePage(bootstrap.locale === "zh-Hans" ? "en" : "zh-Hans")}>{bootstrap.locale === "zh-Hans" ? "EN" : "ZH"}</button>
      {bootstrap.authenticated && bootstrap.host_links.account_url ? <a className="lc-shell-user" href={bootstrap.host_links.account_url}>{bootstrap.user_label || tr(bootstrap, "Account", "账户")}</a> : null}
      {bootstrap.authenticated && bootstrap.host_links.logout_url ? <form method="post" action={logoutUrl(bootstrap.host_links.logout_url)} className="lc-shell-logout"><input type="hidden" name="csrfmiddlewaretoken" value={csrfToken()} /><button type="submit" className="lc-shell-icon-button" title={tr(bootstrap, "Sign out", "退出登录")} aria-label={tr(bootstrap, "Sign out", "退出登录")}><Icon name="logout" /></button></form> : null}
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
  const [currentPath, setCurrentPath] = React.useState(() => window.location.pathname);
  const [currentRef, setCurrentRef] = React.useState(bootstrap.current_ref);
  const [currentContext, setCurrentContext] = React.useState<Context | null>(bootstrap.current_context);
  const navigationRef = React.useRef<HTMLElement>(null);
  const groupLaunchers = React.useRef(new Map<string, HTMLButtonElement>());
  const referencesKey = [...preferences.pins, ...preferences.recent].slice(0, MAX_PINS + MAX_RECENT).join("|");
  const activeBootstrap = { ...bootstrap, path: currentPath, current_ref: currentRef, current_context: currentContext };
  const filterValue = filter.trim().toLocaleLowerCase();
  const visibleGroups = groups(activeBootstrap).map((group) => ({
    ...group,
    destinations: group.destinations.filter((item) => !filterValue || item.label.toLocaleLowerCase().includes(filterValue)),
  })).filter((group) => group.destinations.length);
  const closeDrawer = React.useCallback(() => publishDrawer(false), []);
  const link = (item: Destination) => <a key={item.key} className="lc-shell-link" href={preserveLocale(item.href || "")} data-current={activeBootstrap.path === item.href ? "true" : undefined} title={item.label} onClick={(event) => item.href && navigateFromShell(event, activeBootstrap, item.href, item.ref, closeDrawer)}><span aria-hidden="true" className="lc-shell-link-icon"><Icon name={item.icon} /></span><span className="lc-shell-link-label">{item.label}</span></a>;
  const removeReference = (reference: string) => setPreferences((current) => ({
    ...current,
    pins: current.pins.filter((item) => item !== reference),
    recent: current.recent.filter((item) => item !== reference),
  }));
  React.useEffect(() => savePreferences(bootstrap, preferences), [bootstrap, preferences]);
  React.useEffect(() => {
    const sync = () => {
      const path = window.location.pathname;
      const reference = pathReference(bootstrap, path);
      setCurrentPath(path);
      setCurrentRef(reference);
      if (!reference.startsWith("course:") && !reference.startsWith("class:")) setCurrentContext(null);
    };
    window.addEventListener("liveclassroom:navigation", sync);
    return () => {
      window.removeEventListener("liveclassroom:navigation", sync);
    };
  }, [bootstrap]);
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
    const focusable = () => Array.from(navigation.querySelectorAll<HTMLElement>(selector)).filter((element) => !element.hidden && element.getClientRects().length > 0);
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
    if (!preferences.collapsed || !openGroup) return;
    const place = () => {
      const menu = document.getElementById(`lc-shell-group-${openGroup}`);
      const trigger = menu?.parentElement?.querySelector<HTMLElement>(".lc-shell-group-toggle");
      if (!menu || !trigger || isMobileViewport()) return;
      const rect = trigger.getBoundingClientRect();
      menu.style.top = `${Math.max(60, Math.min(rect.top, window.innerHeight - menu.offsetHeight - 12))}px`;
      menu.style.left = `${rect.right + 12}px`;
    };
    window.requestAnimationFrame(() => { place(); navigationRef.current?.querySelector<HTMLElement>(`#lc-shell-group-${openGroup} a, #lc-shell-group-${openGroup} button`)?.focus(); });
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => { window.removeEventListener("resize", place); window.removeEventListener("scroll", place, true); };
  }, [openGroup, preferences.collapsed]);
  React.useEffect(() => {
    const references = referencesKey ? referencesKey.split("|") : [];
    if (currentRef && !references.includes(currentRef)) references.push(currentRef);
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
      const context = contextForReference(payload.contexts, currentRef);
      if (currentRef.startsWith("course:") || currentRef.startsWith("class:")) setCurrentContext(context);
      window.dispatchEvent(new CustomEvent<CurrentShellEvent>(CURRENT_EVENT, { detail: { path: currentPath, reference: currentRef, context: (currentRef.startsWith("course:") || currentRef.startsWith("class:")) ? context : null } }));
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
  }, [bootstrap.authenticated, bootstrap.links.navigation, referencesKey, currentRef, currentPath]);
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
      <a href={preserveLocale(item.url)} onClick={(event) => navigateFromShell(event, activeBootstrap, item.url, reference, closeDrawer)}>
        <span aria-hidden="true" className="lc-shell-link-icon"><Icon name={pinned ? "pin" : "recent"} /></span><span className="lc-shell-link-label">{item.label}</span>
      </a>
      {pinned ? <span className="lc-shell-saved-actions">
        <button type="button" aria-label={tr(bootstrap, "Move pin up", "上移固定项")} title={tr(bootstrap, "Move pin up", "上移固定项")} onClick={() => movePin(reference, -1)}><Icon name="up" size={15} /></button>
        <button type="button" aria-label={tr(bootstrap, "Move pin down", "下移固定项")} title={tr(bootstrap, "Move pin down", "下移固定项")} onClick={() => movePin(reference, 1)}><Icon name="down" size={15} /></button>
        <button type="button" aria-label={tr(bootstrap, "Remove pin", "取消固定")} title={tr(bootstrap, "Remove pin", "取消固定")} onClick={() => removeReference(reference)}><Icon name="close" size={15} /></button>
      </span> : null}
    </div>;
  };
  const renderGroup = (group: Group, contents: React.ReactNode = group.destinations.map(link)) => {
    const expanded = isMobileViewport() || !preferences.collapsed || openGroup === group.key;
    const closeIfLeaving = (event: React.FocusEvent<HTMLDivElement>) => {
      if (!preferences.collapsed || !openGroup || event.currentTarget.contains(event.relatedTarget as Node | null)) return;
      setOpenGroup(null);
    };
    return <div className="lc-shell-group" key={group.key} onBlur={closeIfLeaving}>
      <button
        type="button"
        className="lc-shell-group-toggle"
        aria-expanded={expanded}
        aria-controls={`lc-shell-group-${group.key}`}
        ref={(element) => {
          if (element) groupLaunchers.current.set(group.key, element);
          else groupLaunchers.current.delete(group.key);
        }}
        onClick={() => setOpenGroup((current) => current === group.key ? null : group.key)}
      ><span aria-hidden="true" className="lc-shell-link-icon"><Icon name={group.key === "teaching" ? "teacher" : group.key === "materials" ? "lesson" : group.key === "learning" ? "learning" : group.key === "context" ? "course" : group.key === "pins" ? "pin" : "recent"} /></span><span className="lc-shell-link-label">{group.label}</span></button>
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
    <div className="lc-shell-drawer-title"><span>{tr(bootstrap, "Navigation", "导航")}</span><button type="button" className="lc-shell-icon-button" aria-label={tr(bootstrap, "Close navigation", "关闭导航")} onClick={closeDrawer}><Icon name="close" /></button></div>
    <label className="lc-shell-filter"><span>{tr(bootstrap, "Filter navigation", "筛选导航")}</span><input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder={tr(bootstrap, "Filter", "筛选")} /></label>
    <a className="lc-shell-link" href={preserveLocale(bootstrap.links.home)} data-current={activeBootstrap.path === bootstrap.links.home ? "true" : undefined} title={tr(bootstrap, "Home", "首页")} onClick={(event) => navigateFromShell(event, activeBootstrap, bootstrap.links.home, "page:home", closeDrawer)}><span aria-hidden="true" className="lc-shell-link-icon"><Icon name="home" /></span><span className="lc-shell-link-label">{tr(bootstrap, "Home", "首页")}</span></a>
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
      {link({ key: "join", label: tr(bootstrap, "Join a session", "加入课堂"), href: bootstrap.links.join, icon: "join", ref: "page:join" })}
      {link({ key: "help", label: tr(bootstrap, "Help", "帮助"), href: bootstrap.links.help, icon: "help", ref: "page:help" })}
      {bootstrap.host_links.home_url ? link({ key: "site", label: tr(bootstrap, "Back to site", "返回网站"), href: bootstrap.host_links.home_url, icon: "site" }) : null}
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
  if (!bootstrap || !header || !navigation) return;
  const current = new URL(window.location.href);
  const home = new URL(bootstrap.links.home, window.location.href);
  if (bootstrap.authenticated && current.pathname === home.pathname) {
    const explicit = current.searchParams.get("mode");
    const remembered = loadPreferences(bootstrap).rememberedMode;
    const selected = explicit === "teaching" || explicit === "learning" ? explicit : remembered;
    if (selected === "learning" || (selected === "teaching" && bootstrap.teacher_allowed)) {
      bootstrap.mode = selected;
      const workspace = document.querySelector<HTMLElement>("[data-home-workspace]");
      if (workspace) workspace.dataset.mode = selected;
    }
  }
  consumePendingRecent(bootstrap);
  let overlay = document.querySelector<HTMLElement>("[data-liveclassroom-shell-overlay]");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.dataset.liveclassroomShellOverlay = "";
    overlay.className = "lc-shell-drawer-overlay";
    navigation.parentElement?.insertBefore(overlay, navigation);
  }
  createRoot(header).render(<ShellHeader bootstrap={bootstrap} />);
  createRoot(navigation).render(<AppNavigation bootstrap={bootstrap} />);
  createRoot(overlay).render(<ShellDrawerOverlay bootstrap={bootstrap} />);
}
