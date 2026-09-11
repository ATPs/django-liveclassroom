import * as React from "react";
import { useCallback, useEffect, useState } from "react";

/**
 * Small URL-state helpers shared by the independently mounted React surfaces.
 * Django remains responsible for path routing; this module owns only optional
 * selection/filter state in the current, mount-safe URL.
 */
export type QueryValue = string | number | null | undefined;

export type HistoryEntryState = {
  liveclassroomScroll?: { x?: number; y?: number };
  liveclassroomFocusId?: string;
};

export type NavigationOptions = {
  replace?: boolean;
  focusId?: string;
};

export type NavigationLinkProps = Omit<React.AnchorHTMLAttributes<HTMLAnchorElement>, "href"> & {
  href: string;
  onNavigate?: (navigate: () => void) => void;
};

const NAVIGATION_EVENT = "liveclassroom:navigation";
const NAVIGATION_REQUEST_EVENT = "liveclassroom:request-navigation";
let skipNextBeforeUnload = false;

function allowControlledDeparture(): void {
  skipNextBeforeUnload = true;
  window.setTimeout(() => {
    skipNextBeforeUnload = false;
  }, 0);
}

function currentState(): HistoryEntryState {
  return (window.history.state ?? {}) as HistoryEntryState;
}

function notifyNavigation(): void {
  window.dispatchEvent(new Event(NAVIGATION_EVENT));
}

/** Ask an active editor to guard a controlled application navigation. */
export function requestApplicationNavigation(navigate: () => void): void {
  const event = new CustomEvent<{ navigate: () => void }>(NAVIGATION_REQUEST_EVENT, {
    cancelable: true,
    detail: { navigate },
  });
  window.dispatchEvent(event);
  if (!event.defaultPrevented) navigate();
}

export function queryValue(name: string): string | null {
  return new URL(window.location.href).searchParams.get(name);
}

/** Keep an explicit locale query while following a mount-safe server URL. */
export function preserveLocale(url: string): string {
  const target = new URL(url, window.location.href);
  const locale = new URL(window.location.href).searchParams.get("lang");
  if (locale) target.searchParams.set("lang", locale);
  return `${target.pathname}${target.search}${target.hash}`;
}

export function updateQuery(
  changes: Record<string, QueryValue>,
  { replace = false, focusId }: NavigationOptions = {},
): void {
  const url = new URL(window.location.href);
  for (const [name, value] of Object.entries(changes)) {
    if (value === null || value === undefined || value === "") url.searchParams.delete(name);
    else url.searchParams.set(name, String(value));
  }
  const next = `${url.pathname}${url.search}${url.hash}`;
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (next === current) return;
  const state: HistoryEntryState = {
    ...currentState(),
    liveclassroomScroll: { x: window.scrollX, y: window.scrollY },
    ...(focusId ? { liveclassroomFocusId: focusId } : {}),
  };
  if (replace) window.history.replaceState(state, "", next);
  else window.history.pushState({ liveclassroomScroll: { x: 0, y: 0 }, ...(focusId ? { liveclassroomFocusId: focusId } : {}) }, "", next);
  notifyNavigation();
}

/** Change a route within the mounted application without a document reload. */
export function updateLocation(destination: string, { replace = false, focusId }: NavigationOptions = {}): void {
  const target = new URL(destination, window.location.href);
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  const next = `${target.pathname}${target.search}${target.hash}`;
  if (next === current) return;
  window.history.replaceState(
    { ...currentState(), liveclassroomScroll: { x: window.scrollX, y: window.scrollY } },
    "",
    current,
  );
  const state: HistoryEntryState = { liveclassroomScroll: { x: 0, y: 0 }, ...(focusId ? { liveclassroomFocusId: focusId } : {}) };
  if (replace) window.history.replaceState(state, "", next);
  else window.history.pushState(state, "", next);
  notifyNavigation();
}

export function useLocationPath(): string {
  const [path, setPath] = useState(() => `${window.location.pathname}${window.location.search}${window.location.hash}`);
  useEffect(() => {
    const update = () => setPath(`${window.location.pathname}${window.location.search}${window.location.hash}`);
    window.addEventListener("popstate", update);
    window.addEventListener(NAVIGATION_EVENT, update);
    return () => {
      window.removeEventListener("popstate", update);
      window.removeEventListener(NAVIGATION_EVENT, update);
    };
  }, []);
  return path;
}

/** Build a mount-safe local path with only durable browsing state. */
export function routeUrl(pathname: string, query: Record<string, QueryValue> = {}): string {
  const url = new URL(pathname, window.location.href);
  const locale = query.lang ?? queryValue("lang");
  for (const [name, value] of Object.entries({ ...query, ...(locale ? { lang: locale } : {}) })) {
    if (value === null || value === undefined || value === "") url.searchParams.delete(name);
    else url.searchParams.set(name, String(value));
  }
  return `${url.pathname}${url.search}${url.hash}`;
}

/** A regular anchor keeps new-tab and modified-click behavior intact. */
export function NavigationLink({ href, onNavigate, onClick, ...props }: NavigationLinkProps): React.ReactElement {
  return <a {...props} href={preserveLocale(href)} onClick={(event) => {
    onClick?.(event);
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    const navigate = () => window.location.assign(preserveLocale(href));
    if (onNavigate) onNavigate(navigate);
    else requestApplicationNavigation(navigate);
  }} />;
}

export function Breadcrumbs({ items }: { items: Array<{ href?: string; label: string }> }): React.ReactElement {
  return <nav className="lc-breadcrumbs" aria-label="Breadcrumb">{items.map((item, index) => (
    <React.Fragment key={`${item.label}-${index}`}>
      {index ? <span aria-hidden="true"> / </span> : null}
      {item.href ? <NavigationLink href={item.href}>{item.label}</NavigationLink> : <span aria-current="page">{item.label}</span>}
    </React.Fragment>
  ))}</nav>;
}

/** Install once per document; each history entry keeps only its own scroll point. */
export function installHistoryRestoration(): void {
  if (typeof window === "undefined") return;
  const page = window as typeof window & { liveclassroomHistoryInstalled?: boolean };
  if (page.liveclassroomHistoryInstalled) return;
  page.liveclassroomHistoryInstalled = true;
  window.history.scrollRestoration = "manual";
  const save = () => window.history.replaceState(
    { ...currentState(), liveclassroomScroll: { x: window.scrollX, y: window.scrollY } },
    "",
    window.location.href,
  );
  save();
  window.addEventListener("pagehide", save);
  window.addEventListener("popstate", (event) => {
    const point = (event.state as { liveclassroomScroll?: { x?: number; y?: number } } | null)?.liveclassroomScroll;
    if (!point) return;
    window.requestAnimationFrame(() => window.scrollTo(point.x ?? 0, point.y ?? 0));
    notifyNavigation();
  });
}

/** Keep a deliberate selection addressable and restore it on Back/Forward. */
export function useQuerySelection(name: string, fallback = ""): [string, (value: string, options?: { replace?: boolean }) => void] {
  const [value, setValue] = useState(() => queryValue(name) ?? fallback);

  useEffect(() => {
    const onPopState = () => setValue(queryValue(name) ?? fallback);
    window.addEventListener("popstate", onPopState);
    window.addEventListener(NAVIGATION_EVENT, onPopState);
    return () => {
      window.removeEventListener("popstate", onPopState);
      window.removeEventListener(NAVIGATION_EVENT, onPopState);
    };
  }, [fallback, name]);

  const select = useCallback((next: string, options?: { replace?: boolean }) => {
    updateQuery({ [name]: next || null }, options);
  }, [name]);
  return [value, select];
}

/** Native navigation warning for changes that have not reached the server. */
export function useUnsavedChangesWarning(dirty: boolean): void {
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      if (skipNextBeforeUnload) {
        skipNextBeforeUnload = false;
        return;
      }
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
}

/** Focus the current page heading after direct navigation or history restoration. */
export function useNavigationHeading(id: string): void {
  useEffect(() => {
    const focus = () => {
      const requested = currentState().liveclassroomFocusId;
      if (requested && requested !== id) return;
      window.requestAnimationFrame(() => document.getElementById(id)?.focus({ preventScroll: true }));
    };
    window.addEventListener(NAVIGATION_EVENT, focus);
    return () => window.removeEventListener(NAVIGATION_EVENT, focus);
  }, [id]);
}

/**
 * Give editor-internal navigation an explicit save/discard/stay choice. Browser
 * reloads and departures still use the native warning because browsers do not
 * permit application-controlled prompts for those transitions.
 */
export function useUnsavedNavigationGuard({
  dirty,
  onSave,
  onBeforeLeave,
  labels = {},
}: {
  dirty: boolean;
  onSave: () => Promise<boolean>;
  onBeforeLeave?: () => void;
  labels?: Partial<{ title: string; body: string; save: string; discard: string; stay: string }>;
}): {
  requestNavigation: (navigate: () => void) => void;
  dialog: React.ReactNode;
} {
  const [pending, setPending] = useState<(() => void) | null>(null);
  const [saving, setSaving] = useState(false);
  const requestNavigation = useCallback((navigate: () => void) => {
    if (!dirty) navigate();
    else setPending(() => navigate);
  }, [dirty]);
  useEffect(() => {
    if (!dirty) return;
    const guard = (event: Event) => {
      if (event.defaultPrevented) return;
      event.preventDefault();
      requestNavigation((event as CustomEvent<{ navigate: () => void }>).detail.navigate);
    };
    window.addEventListener(NAVIGATION_REQUEST_EVENT, guard);
    return () => window.removeEventListener(NAVIGATION_REQUEST_EVENT, guard);
  }, [dirty, requestNavigation]);
  const leave = useCallback(() => {
    const navigate = pending;
    setPending(null);
    onBeforeLeave?.();
    allowControlledDeparture();
    navigate?.();
  }, [onBeforeLeave, pending]);
  const save = useCallback(async () => {
    setSaving(true);
    try {
      if (await onSave()) leave();
    } finally {
      setSaving(false);
    }
  }, [leave, onSave]);
  const text = {
    title: labels.title ?? "Unsaved changes",
    body: labels.body ?? "Save your changes before leaving this editor?",
    save: labels.save ?? "Save and leave",
    discard: labels.discard ?? "Discard and leave",
    stay: labels.stay ?? "Stay",
  };
  return {
    requestNavigation,
    dialog: pending ? <div className="lc-modal-overlay" role="presentation"><section className="lc-modal" role="dialog" aria-modal="true" aria-labelledby="lc-unsaved-title"><h2 id="lc-unsaved-title">{text.title}</h2><p>{text.body}</p><div className="lc-actions"><button type="button" className="lc-btn lc-btn-primary" disabled={saving} onClick={() => void save()}>{text.save}</button><button type="button" className="lc-btn lc-btn-danger" disabled={saving} onClick={leave}>{text.discard}</button><button type="button" className="lc-btn lc-btn-outline" disabled={saving} onClick={() => setPending(null)}>{text.stay}</button></div></section></div> : null,
  };
}
