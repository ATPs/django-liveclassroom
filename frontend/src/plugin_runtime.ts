import { createElement, useEffect, useRef } from "react";
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
};

type PluginModule = {
  pluginApiVersion?: number;
  render?: (context: PluginRenderContext) => void | boolean | (() => void);
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
    const target = options.manifest?.[rendererKey(options.audience)];
    if (!target) {
      fallback();
      return undefined;
    }
    void import(/* @vite-ignore */ pluginUrl(target))
      .then((module: PluginModule) => {
        if (disposed || module.pluginApiVersion !== 1 || typeof module.render !== "function") {
          fallback();
          return;
        }
        const result = module.render({
          activity: options.activity,
          audience: options.audience,
          state: options.state,
          stateUrl: options.stateUrl,
          aggregate: options.aggregate,
          locale: options.locale,
          container,
          fallback,
        });
        if (typeof result === "function") cleanup = result;
      })
      .catch(fallback);
    return () => {
      disposed = true;
      cleanup?.();
    };
  }, [options]);

  return createElement("div", { className: "lc-plugin-activity", ref: content });
}

export function mountPluginActivity(options: PluginActivityOptions): () => void {
  const host = document.createElement("div");
  host.className = "lc-plugin-island";
  options.parent.replaceChildren(host);
  const root: Root = createRoot(host);
  root.render(createElement(PluginActivity, { options }));
  return () => root.unmount();
}
