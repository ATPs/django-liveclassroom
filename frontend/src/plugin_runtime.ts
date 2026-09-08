import { createElement, useEffect, useRef, useState } from "react";
import { createRoot, type Root } from "react-dom/client";

import type { ActivityState, AggregateState, Audience, SessionState } from "./protocol.js";
import type { Locale } from "./locales.js";

export type PluginRenderContext = {
  activity: ActivityState | null;
  audience: Audience;
  state?: SessionState;
  stateUrl?: string;
  aggregate?: AggregateState | null;
  locale: Locale;
  container: HTMLElement;
  fallback: () => void;
  readOnly?: boolean;
  submit?: (answer: Record<string, unknown>) => Promise<void>;
};

export type PluginMount = void | boolean | (() => void) | {
  dispose?: () => void;
  update?: (context: PluginRenderContext) => void;
};

type PluginModule = {
  pluginApiVersion?: number;
  render?: (context: PluginRenderContext) => PluginMount;
};

type PluginActivityOptions = Omit<PluginRenderContext, "container" | "fallback"> & {
  parent: HTMLElement;
  manifest?: Record<string, string>;
  fallback: (container: HTMLElement) => void | (() => void);
};

function rendererKey(audience: Audience): "student_renderer" | "display_renderer" {
  return audience === "student" ? "student_renderer" : "display_renderer";
}

function pluginUrl(path: string): string {
  const staticUrl = document.body.dataset.liveclassroomStaticUrl || "/static/";
  return new URL(path.replace(/^\/+/, ""), new URL(staticUrl, window.location.href)).toString();
}

function PluginActivity({ options }: { options: PluginActivityOptions }): ReturnType<typeof createElement> {
  const content = useRef<HTMLDivElement>(null);
  const latest = useRef(options);
  const update = useRef<((context: PluginRenderContext) => void) | undefined>(undefined);
  const [loadError, setLoadError] = useState(false);
  const [reload, setReload] = useState(0);
  latest.current = options;
  const target = options.manifest?.[rendererKey(options.audience)] ?? "";
  // Normal state polling must not recreate a plugin.  Eligibility changes are
  // intentionally part of the identity so an old writable surface cannot
  // survive a pause, token expiry, or participant switch.
  const eligibility = Boolean(options.submit);

  const contextFor = (current: PluginActivityOptions, container: HTMLElement, fallback: () => void): PluginRenderContext => ({
    activity: current.activity,
    audience: current.audience,
    state: current.state,
    stateUrl: current.stateUrl,
    aggregate: current.aggregate,
    locale: current.locale,
    container,
    fallback,
    readOnly: current.readOnly,
    submit: current.submit,
  });

  useEffect(() => {
    const container = content.current;
    if (!container) return undefined;
    let disposed = false;
    let cleanup: (() => void) | undefined;
    const fallback = () => {
      if (!disposed) {
        const result = options.fallback(container);
        if (typeof result === "function") cleanup = result;
      }
    };
    if (!target) {
      fallback();
      return undefined;
    }
    setLoadError(false);
    void import(/* @vite-ignore */ pluginUrl(target))
      .then((module: PluginModule) => {
        if (disposed) return;
        if (module.pluginApiVersion !== 1 || typeof module.render !== "function") {
          setLoadError(true);
          return;
        }
        const result = module.render(contextFor(latest.current, container, fallback));
        if (typeof result === "function") cleanup = result;
        else if (result && typeof result === "object") {
          cleanup = result.dispose;
          update.current = result.update;
        }
      })
      .catch(() => {
        if (!disposed) setLoadError(true);
      });
    return () => {
      disposed = true;
      update.current = undefined;
      cleanup?.();
    };
  }, [target, options.activity?.id, options.activity?.revision, options.audience, options.locale, eligibility, reload]);

  useEffect(() => {
    const container = content.current;
    if (!container || !update.current) return;
    update.current(contextFor(options, container, () => options.fallback(container)));
  }, [options.state, options.aggregate, options.stateUrl, options.submit]);

  const retryLabel = options.locale.startsWith("zh") ? "重试" : "Retry";
  const errorLabel = options.locale.startsWith("zh") ? "无法加载此活动。" : "This activity could not be loaded.";
  return createElement(
    "div",
    { className: "lc-plugin-activity", ref: content },
    loadError ? createElement("p", { className: "lc-plugin-error", role: "status" }, errorLabel, " ", createElement("button", { type: "button", onClick: () => setReload((value) => value + 1) }, retryLabel)) : null,
  );
}

export type MountedPluginActivity = {
  update: (options: PluginActivityOptions) => void;
  unmount: () => void;
};

export function mountPluginActivity(options: PluginActivityOptions): MountedPluginActivity {
  const host = document.createElement("div");
  host.className = "lc-plugin-island";
  options.parent.replaceChildren(host);
  const root: Root = createRoot(host);
  const render = (next: PluginActivityOptions) => root.render(createElement(PluginActivity, { options: next }));
  render(options);
  return { update: render, unmount: () => root.unmount() };
}
