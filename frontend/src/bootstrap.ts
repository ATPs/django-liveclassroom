import type { Audience } from "./protocol.js";
import type { Locale } from "./locales.js";

/** Typed view of the bootstrap `data-*` attributes a page root carries. */
export type Bootstrap = {
  sessionId: number | null;
  audience: Audience;
  stateUrl: string | null;
  websocketUrl: string | null;
  pendingName: string;
  accessMode: string;
  authenticated: boolean;
  guestJoinUrl: string | null;
  accountJoinUrl: string | null;
  locale: Locale;
  preview: boolean;
};

export function readBootstrap(root: HTMLElement): Bootstrap {
  const d = root.dataset;
  return {
    sessionId: d.sessionId ? Number(d.sessionId) : null,
    audience: (d.audience as Audience | undefined) ?? "student",
    stateUrl: d.stateUrl ?? null,
    websocketUrl: d.websocketUrl ?? null,
    pendingName: d.pendingName ?? "",
    accessMode: d.accessMode ?? "guest",
    authenticated: d.authenticated === "true",
    guestJoinUrl: d.guestJoinUrl ?? null,
    accountJoinUrl: d.accountJoinUrl ?? null,
    locale: (d.locale as Locale | undefined) ?? "en",
    preview: d.preview === "true",
  };
}
