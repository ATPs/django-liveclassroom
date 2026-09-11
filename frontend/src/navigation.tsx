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
  /** Internal same-document traversal bookkeeping; never contains product data. */
  liveclassroomHistoryIndex?: number;
};

export type NavigationOptions = {
  replace?: boolean;
  focusId?: string;
  /** Internal escape hatch for a navigation already accepted by a guard. */
  guard?: boolean;
};

export type NavigationLinkProps = Omit<React.AnchorHTMLAttributes<HTMLAnchorElement>, "href"> & {
  href: string;
  onNavigate?: (navigate: () => void) => void;
};

const NAVIGATION_EVENT = "liveclassroom:navigation";
const NAVIGATION_REQUEST_EVENT = "liveclassroom:request-navigation";
const CONTENT_READY_EVENT = "liveclassroom:content-ready";
let skipNextBeforeUnload = false;
let skipNextNavigationGuard = false;
let guardTransactionDepth = 0;

type UnsavedGuardRecord = {
  dirty: boolean;
  request: (navigate: () => void) => void;
  onSave: () => Promise<boolean>;
  onBeforeLeave?: () => void;
};

const unsavedGuards = new Set<UnsavedGuardRecord>();
let historyIndex: number | null = null;
let pendingHistoryTraversal: { targetIndex: number } | null = null;
let restoringHistoryTraversal = false;
let approvedHistoryTraversal = false;
let pendingContentRestore: HistoryEntryState | null = null;
let contentRestoreTimer: number | null = null;
let contentRestoreStartedAt = 0;
let contentRestoreScrollDone = false;
let contentRestoreFocusDone = false;

function dirtyGuards(): UnsavedGuardRecord[] {
  return [...unsavedGuards].filter((record) => record.dirty);
}

async function saveDirtyGuards(): Promise<boolean> {
  guardTransactionDepth += 1;
  // Read the set on each step: a successful save can remove its own dirty bit,
  // while an unrelated draft must remain part of the same departure decision.
  try {
    for (const record of [...unsavedGuards]) {
      if (!record.dirty) continue;
      try {
        if (!(await record.onSave())) return false;
      } catch {
        return false;
      }
    }
    return true;
  } finally {
    guardTransactionDepth -= 1;
  }
}

function beforeLeavingDirtyGuards(): void {
  for (const record of [...unsavedGuards]) {
    if (record.dirty) record.onBeforeLeave?.();
  }
}

function requestFromDirtyGuard(navigate: () => void): boolean {
  const record = dirtyGuards()[0];
  if (!record) return false;
  record.request(navigate);
  return true;
}

if (typeof window !== "undefined") {
  window.addEventListener(NAVIGATION_REQUEST_EVENT, (event) => {
    if (guardTransactionDepth > 0 || event.defaultPrevented || !requestFromDirtyGuard((event as CustomEvent<{ navigate: () => void }>).detail.navigate)) return;
    event.preventDefault();
  });
}

function allowControlledDeparture(): void {
  skipNextBeforeUnload = true;
  skipNextNavigationGuard = true;
  window.setTimeout(() => {
    skipNextBeforeUnload = false;
    skipNextNavigationGuard = false;
  }, 0);
}

function currentState(): HistoryEntryState {
  return (window.history.state ?? {}) as HistoryEntryState;
}

function notifyNavigation(focusId?: string): void {
  window.dispatchEvent(new CustomEvent(NAVIGATION_EVENT, { detail: { focusId } }));
}

export function notifyContentReady(): void {
  if (typeof window !== "undefined") window.dispatchEvent(new Event(CONTENT_READY_EVENT));
}

function activeElementId(): string | undefined {
  const active = document.activeElement;
  return active instanceof HTMLElement && active.id ? active.id : undefined;
}

function navigationState(focusId?: string): HistoryEntryState {
  const state: HistoryEntryState = {
    ...currentState(),
    liveclassroomHistoryIndex: historyIndex ?? currentState().liveclassroomHistoryIndex ?? 0,
    liveclassroomScroll: { x: window.scrollX, y: window.scrollY },
  };
  const focused = activeElementId();
  if (focused) state.liveclassroomFocusId = focused;
  else delete state.liveclassroomFocusId;
  if (focusId) state.liveclassroomFocusId = focusId;
  return state;
}

function restoreAfterContentReady(): void {
  const state = pendingContentRestore;
  if (!state) return;
  if (contentRestoreTimer !== null) window.clearTimeout(contentRestoreTimer);
  contentRestoreTimer = null;
  const point = state.liveclassroomScroll;
  const focusId = state.liveclassroomFocusId;
  const elapsed = Date.now() - contentRestoreStartedAt;
  window.requestAnimationFrame(() => {
    if (pendingContentRestore !== state) return;
    if (point && !contentRestoreScrollDone) {
      window.scrollTo(point.x ?? 0, point.y ?? 0);
      // A late content-ready event can arrive after the bounded fallback. Keep
      // the requested position pending when the document is still too short;
      // a later event can then restore it once the async surface has grown.
      const maxY = Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
      contentRestoreScrollDone = (point.y ?? 0) <= maxY + 2;
    } else if (!point) {
      contentRestoreScrollDone = true;
    }

    if (!contentRestoreFocusDone) {
      const focused = focusId ? document.getElementById(focusId) : null;
      const fallback = document.querySelector<HTMLElement>("h1[tabindex='-1'], h2[tabindex='-1'], [data-liveclassroom-heading]");
      const target = focused || fallback;
      if (target) {
        target.focus({ preventScroll: true });
        contentRestoreFocusDone = true;
      }
    }

    if (contentRestoreScrollDone && contentRestoreFocusDone) {
      pendingContentRestore = null;
      return;
    }
    // Retry briefly while the current response is laying out. After the
    // fallback deadline, leave the state queued for a future content-ready
    // notification instead of losing the user's requested scroll position.
    if (elapsed < 1200) {
      contentRestoreTimer = window.setTimeout(restoreAfterContentReady, 50);
    }
  });
}

function queueContentRestore(state: HistoryEntryState): void {
  pendingContentRestore = state;
  contentRestoreStartedAt = Date.now();
  contentRestoreScrollDone = !state.liveclassroomScroll;
  contentRestoreFocusDone = !state.liveclassroomFocusId;
  if (contentRestoreTimer !== null) window.clearTimeout(contentRestoreTimer);
  contentRestoreTimer = window.setTimeout(restoreAfterContentReady, 1200);
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
  { replace = false, focusId, guard = true }: NavigationOptions = {},
): void {
  const url = new URL(window.location.href);
  for (const [name, value] of Object.entries(changes)) {
    if (value === null || value === undefined || value === "") url.searchParams.delete(name);
    else url.searchParams.set(name, String(value));
  }
  const next = `${url.pathname}${url.search}${url.hash}`;
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (next === current) return;
  if (!replace && guard && guardTransactionDepth === 0 && !skipNextNavigationGuard && dirtyGuards().length) {
    requestApplicationNavigation(() => updateQuery(changes, { replace, focusId, guard: false }));
    return;
  }
  const currentIndex = currentState().liveclassroomHistoryIndex ?? historyIndex ?? 0;
  const outgoingState = navigationState();
  outgoingState.liveclassroomHistoryIndex = currentIndex;
  window.history.replaceState(outgoingState, "", current);
  const state: HistoryEntryState = {
    ...outgoingState,
    liveclassroomScroll: { x: window.scrollX, y: window.scrollY },
    ...(focusId ? { liveclassroomFocusId: focusId } : {}),
  };
  if (replace) {
    window.history.replaceState(state, "", next);
  } else {
    window.history.pushState({ ...state, liveclassroomHistoryIndex: currentIndex + 1, liveclassroomScroll: { x: 0, y: 0 } }, "", next);
    historyIndex = currentIndex + 1;
  }
  if (replace) historyIndex = currentIndex;
  notifyNavigation(focusId);
}

/** Change a route within the mounted application without a document reload. */
export function updateLocation(destination: string, { replace = false, focusId, guard = true }: NavigationOptions = {}): void {
  const target = new URL(destination, window.location.href);
  const current = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  const next = `${target.pathname}${target.search}${target.hash}`;
  if (next === current) return;
  if (!replace && guard && guardTransactionDepth === 0 && !skipNextNavigationGuard && dirtyGuards().length) {
    requestApplicationNavigation(() => updateLocation(destination, { replace, focusId, guard: false }));
    return;
  }
  const currentIndex = currentState().liveclassroomHistoryIndex ?? historyIndex ?? 0;
  const outgoingState = navigationState();
  outgoingState.liveclassroomHistoryIndex = currentIndex;
  window.history.replaceState(outgoingState, "", current);
  const state: HistoryEntryState = {
    ...outgoingState,
    liveclassroomScroll: { x: 0, y: 0 },
    ...(focusId ? { liveclassroomFocusId: focusId } : {}),
  };
  if (replace) {
    window.history.replaceState(state, "", next);
    historyIndex = currentIndex;
  } else {
    window.history.pushState({ ...state, liveclassroomHistoryIndex: currentIndex + 1 }, "", next);
    historyIndex = currentIndex + 1;
  }
  notifyNavigation(focusId);
}

export function useLocationPath(): string {
  const [path, setPath] = useState(() => `${window.location.pathname}${window.location.search}${window.location.hash}`);
  useEffect(() => {
    const update = () => setPath(`${window.location.pathname}${window.location.search}${window.location.hash}`);
    window.addEventListener(NAVIGATION_EVENT, update);
    return () => {
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
    const anchor = event.currentTarget;
    if (anchor.hasAttribute("download")) return;
    const target = (anchor.getAttribute("target") || "").toLowerCase();
    if (target && target !== "_self") return;
    const destination = new URL(anchor.href, window.location.href);
    if (destination.origin !== window.location.origin) return;
    if (`${destination.pathname}${destination.search}` === `${window.location.pathname}${window.location.search}`) return;
    event.preventDefault();
    const navigate = () => window.location.assign(preserveLocale(anchor.href));
    if (onNavigate) onNavigate(navigate);
    else requestApplicationNavigation(navigate);
  }} />;
}

function classroomMountPath(): string | null {
  const bootstrap = document.getElementById("liveclassroom-navigation-bootstrap");
  if (!bootstrap?.textContent) return null;
  try {
    const parsed = JSON.parse(bootstrap.textContent) as { links?: { home?: string } };
    const home = parsed.links?.home;
    if (!home) return null;
    const path = new URL(home, window.location.href).pathname;
    return path.endsWith("/") ? path : `${path}/`;
  } catch {
    return null;
  }
}

function isInClassroomMount(pathname: string, mountPath: string): boolean {
  return pathname === mountPath.slice(0, -1) || pathname.startsWith(mountPath);
}

/**
 * Guard ordinary server-rendered anchors as well as React NavigationLink.
 * React's delegated handler runs before this document bubble listener, so a
 * link that already made an application decision is left alone.
 */
function installDirtyAnchorGuard(): void {
  const root = document.getElementById("liveclassroom-root");
  const mountPath = classroomMountPath();
  if (!root || !mountPath) return;
  document.addEventListener("click", (event) => {
    if (event.defaultPrevented || guardTransactionDepth > 0 || skipNextNavigationGuard) return;
    if (!(event.target instanceof Element)) return;
    const anchor = event.target.closest<HTMLAnchorElement>("a[href]");
    if (!anchor || !root.contains(anchor) || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    if (anchor.hasAttribute("download")) return;
    const target = (anchor.getAttribute("target") || "").toLowerCase();
    if (target && target !== "_self") return;
    const destination = new URL(anchor.href, window.location.href);
    if (destination.origin !== window.location.origin || !isInClassroomMount(destination.pathname, mountPath)) return;
    const currentDocument = `${window.location.pathname}${window.location.search}`;
    const targetDocument = `${destination.pathname}${destination.search}`;
    // Let the browser perform native same-document hash scrolling.
    if (currentDocument === targetDocument) return;
    if (!dirtyGuards().length) return;
    event.preventDefault();
    requestApplicationNavigation(() => window.location.assign(preserveLocale(anchor.href)));
  });
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
  const initial = currentState();
  historyIndex = initial.liveclassroomHistoryIndex ?? 0;
  if (initial.liveclassroomScroll || initial.liveclassroomFocusId) queueContentRestore(initial);
  const save = () => window.history.replaceState(
    { ...navigationState(), liveclassroomHistoryIndex: historyIndex },
    "",
    window.location.href,
  );
  save();
  installDirtyAnchorGuard();
  window.addEventListener("pagehide", save);
  window.addEventListener(CONTENT_READY_EVENT, restoreAfterContentReady);
  window.addEventListener("popstate", (event) => {
    const state = (event.state ?? {}) as HistoryEntryState;
    const targetIndex = state.liveclassroomHistoryIndex;
    const currentIndex = historyIndex ?? 0;

    if (restoringHistoryTraversal) {
      restoringHistoryTraversal = false;
      if (targetIndex === currentIndex && pendingHistoryTraversal) {
        const pending = pendingHistoryTraversal;
        const accepted = requestFromDirtyGuard(() => {
          pendingHistoryTraversal = null;
          approvedHistoryTraversal = true;
          window.history.go(pending.targetIndex - currentIndex);
        });
        if (!accepted) {
          pendingHistoryTraversal = null;
          approvedHistoryTraversal = true;
          window.history.go(pending.targetIndex - currentIndex);
        }
      }
      return;
    }

    if (approvedHistoryTraversal) {
      approvedHistoryTraversal = false;
      pendingHistoryTraversal = null;
      historyIndex = targetIndex ?? currentIndex;
      queueContentRestore(state);
      notifyNavigation();
      return;
    }

    if (targetIndex !== undefined && targetIndex !== currentIndex && dirtyGuards().length) {
      pendingHistoryTraversal = { targetIndex };
      restoringHistoryTraversal = true;
      window.history.go(currentIndex - targetIndex);
      return;
    }

    historyIndex = targetIndex ?? currentIndex;
    queueContentRestore(state);
    notifyNavigation();
  });
}

/** Keep a deliberate selection addressable and restore it on Back/Forward. */
export function useQuerySelection(name: string, fallback = ""): [string, (value: string, options?: { replace?: boolean }) => void] {
  const [value, setValue] = useState(() => queryValue(name) ?? fallback);

  useEffect(() => {
    const onPopState = () => setValue(queryValue(name) ?? fallback);
    window.addEventListener(NAVIGATION_EVENT, onPopState);
    return () => {
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
    const focus = (event: Event) => {
      const requested = (event as CustomEvent<{ focusId?: string }>).detail?.focusId;
      if (requested !== id) return;
      const started = Date.now();
      let observer: MutationObserver | null = null;
      const tryFocus = () => {
        const heading = document.getElementById(id);
        if (heading) {
          observer?.disconnect();
          heading.focus({ preventScroll: true });
          return;
        }
        if (Date.now() - started > 1500) observer?.disconnect();
      };
      observer = new MutationObserver(tryFocus);
      observer.observe(document.body, { childList: true, subtree: true });
      window.setTimeout(() => observer?.disconnect(), 1500);
      window.requestAnimationFrame(tryFocus);
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
  const dialogRef = React.useRef<HTMLElement>(null);
  const returnFocusRef = React.useRef<HTMLElement | null>(null);
  const requestNavigation = useCallback((navigate: () => void) => {
    if (!dirty) navigate();
    else setPending((current) => {
      if (!current) {
        const active = document.activeElement;
        returnFocusRef.current = active instanceof HTMLElement ? active : null;
      }
      return current ?? navigate;
    });
  }, [dirty]);
  useEffect(() => {
    const record: UnsavedGuardRecord = {
      dirty,
      request: requestNavigation,
      onSave,
      onBeforeLeave,
    };
    unsavedGuards.add(record);
    return () => {
      unsavedGuards.delete(record);
    };
  }, [dirty, onBeforeLeave, onSave, requestNavigation]);
  const leave = useCallback(() => {
    const navigate = pending;
    setPending(null);
    returnFocusRef.current = null;
    beforeLeavingDirtyGuards();
    allowControlledDeparture();
    navigate?.();
  }, [pending]);
  const save = useCallback(async () => {
    setSaving(true);
    try {
      if (await saveDirtyGuards()) leave();
    } finally {
      setSaving(false);
    }
  }, [leave]);
  const restoreFocus = useCallback(() => {
    const target = returnFocusRef.current;
    returnFocusRef.current = null;
    if (!target) return;
    window.requestAnimationFrame(() => {
      if (target.isConnected) target.focus({ preventScroll: true });
    });
  }, []);
  const stay = useCallback(() => {
    setPending(null);
    pendingHistoryTraversal = null;
    restoreFocus();
  }, [restoreFocus]);
  const dialogOpen = Boolean(pending);
  useEffect(() => {
    if (!dialogOpen) return;
    const dialog = dialogRef.current;
    if (!dialog) return;
    const selector = "button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])";
    const focusable = () => Array.from(dialog.querySelectorAll<HTMLElement>(selector)).filter((element) => !element.hidden);
    window.requestAnimationFrame(() => {
      const first = focusable()[0];
      (first ?? dialog).focus();
    });
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        if (!saving) {
          event.preventDefault();
          stay();
        }
        return;
      }
      if (event.key !== "Tab") return;
      const controls = focusable();
      if (!controls.length) {
        event.preventDefault();
        dialog.focus();
        return;
      }
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
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [dialogOpen, saving, stay]);
  const text = {
    title: labels.title ?? "Unsaved changes",
    body: labels.body ?? "Save your changes before leaving this editor?",
    save: labels.save ?? "Save and leave",
    discard: labels.discard ?? "Discard and leave",
    stay: labels.stay ?? "Stay",
  };
  return {
    requestNavigation,
    dialog: pending ? <div className="lc-modal-overlay" role="presentation"><section ref={dialogRef} className="lc-modal" role="dialog" aria-modal="true" aria-labelledby="lc-unsaved-title" tabIndex={-1}><h2 id="lc-unsaved-title">{text.title}</h2><p>{text.body}</p><div className="lc-actions"><button type="button" className="lc-btn lc-btn-primary" disabled={saving} onClick={() => void save()}>{text.save}</button><button type="button" className="lc-btn lc-btn-danger" disabled={saving} onClick={leave}>{text.discard}</button><button type="button" className="lc-btn lc-btn-outline" disabled={saving} onClick={stay}>{text.stay}</button></div></section></div> : null,
  };
}
