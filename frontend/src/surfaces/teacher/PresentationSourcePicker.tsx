import * as React from "react";
import { useEffect, useMemo, useState } from "react";
import { useLocale } from "../../i18n.js";
import { apiEndpoint, deleteJson, getJson, postJson } from "../../protocol.js";

type Snapshot = { id: number; title: string; slides?: unknown[] };
type PlanStep = { key?: string; id: number; position: number; title: string };
type Provider = { key: string; search_supported?: boolean; navigation_supported?: boolean };
type Source = Record<string, unknown> & { type?: string; provider?: string; title?: string };
type Cue = { id: string; step_key: string; source: Source; status?: string; valid?: boolean; error_code?: string };

function label(locale: string, en: string, zh: string): string {
  return locale.startsWith("zh") ? zh : en;
}

/** Small, bilingual teacher control for native/external sources and cues. */
export function PresentationSourcePicker({
  stateUrl,
  snapshots,
  steps,
  onRefresh,
}: {
  stateUrl: string;
  snapshots: Snapshot[];
  steps: PlanStep[];
  onRefresh: () => Promise<void>;
}) {
  const locale = useLocale();
  const tr = (en: string, zh: string) => label(locale, en, zh);
  const [providers, setProviders] = useState<Provider[]>([]);
  const [cues, setCues] = useState<Cue[]>([]);
  const [mode, setMode] = useState<"native" | "external">("native");
  const [provider, setProvider] = useState("");
  const [snapshotId, setSnapshotId] = useState("");
  const [stepKey, setStepKey] = useState(steps[0]?.key ?? "");
  const [slideIndex, setSlideIndex] = useState("0");
  const [url, setUrl] = useState("");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Source[]>([]);
  const [selectedSource, setSelectedSource] = useState<Source | null>(null);
  const [status, setStatus] = useState("");
  const [pending, setPending] = useState(false);
  const providerUrl = useMemo(() => apiEndpoint(stateUrl, "sessions/presentation/providers").replace(/\/+$/, ""), [stateUrl]);
  const cuesUrl = useMemo(() => apiEndpoint(stateUrl, "sessions/presentation/cues").replace(/\/+$/, ""), [stateUrl]);

  const refreshCues = () => getJson<{ cues: Cue[] }>(cuesUrl).then((data) => setCues(data.cues ?? []));
  useEffect(() => {
    void Promise.all([
      getJson<{ providers: Provider[] }>(`${providerUrl}/`).then((data) => {
        const next = data.providers ?? [];
        setProviders(next);
        setProvider((current) => current || next[0]?.key || "");
      }),
      refreshCues(),
    ]).catch((error: unknown) => setStatus(error instanceof Error ? error.message : tr("Sources are unavailable.", "来源不可用。")));
  }, [providerUrl, cuesUrl]);
  useEffect(() => {
    if (!steps.some((step) => step.key === stepKey)) setStepKey(steps[0]?.key ?? "");
  }, [steps, stepKey]);

  const search = async () => {
    if (!provider || !query.trim()) return;
    setPending(true);
    setStatus("");
    try {
      const endpoint = new URL(`${providerUrl}/${encodeURIComponent(provider)}/search/`, window.location.href);
      endpoint.searchParams.set("q", query.trim());
      const data = await getJson<{ results: Source[] }>(endpoint.toString());
      setResults(data.results ?? []);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : tr("Provider search is unavailable.", "提供者搜索不可用。"));
    } finally {
      setPending(false);
    }
  };

  const attach = async () => {
    if (!stepKey || pending) return;
    setPending(true);
    setStatus("");
    try {
      let source: Source;
      const index = Number(slideIndex);
      if (!Number.isInteger(index) || index < 0) throw new Error(tr("Slide position is invalid.", "页面位置无效。"));
      if (mode === "native") {
        if (!snapshotId) throw new Error(tr("Choose a native deck snapshot.", "请选择原生幻灯片快照。"));
        source = { type: "native", snapshot_id: Number(snapshotId), slide_index: index };
      } else {
        if (!provider) throw new Error(tr("Choose a content provider.", "请选择内容提供者。"));
        if (selectedSource) source = { ...selectedSource, slide_index: index };
        else {
          if (!url.trim()) throw new Error(tr("Paste a supported provider URL.", "请粘贴支持的提供者 URL。"));
          source = { type: "external", provider, url: url.trim(), slide_index: index };
        }
        if (typeof source.reference !== "object") {
          const resolved = await postJson<{ source: Source }>(`${providerUrl}/resolve/`, { provider, url: url.trim() }, crypto.randomUUID());
          source = { ...resolved.source, slide_index: index };
        }
      }
      await postJson(cuesUrl, { step_key: stepKey, source }, crypto.randomUUID());
      setStatus(tr("Cue attached.", "提示点已添加。"));
      setSelectedSource(null);
      setResults([]);
      await refreshCues();
      await onRefresh();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : tr("Unable to attach cue.", "无法添加提示点。"));
    } finally {
      setPending(false);
    }
  };

  const launch = async (cue: Cue) => {
    if (pending || cue.valid === false) return;
    setPending(true);
    setStatus("");
    try {
      await postJson(`${cuesUrl}/${cue.id}/launch/`, { channel: "display" }, crypto.randomUUID());
      setStatus(tr("Activity launched.", "活动已启动。"));
      await onRefresh();
      await refreshCues();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : tr("Unable to launch cue.", "无法启动提示点。"));
    } finally {
      setPending(false);
    }
  };

  const remove = async (cue: Cue) => {
    if (pending) return;
    setPending(true);
    try {
      await deleteJson(`${cuesUrl}/${cue.id}/`, crypto.randomUUID());
      await refreshCues();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : tr("Unable to remove cue.", "无法移除提示点。"));
    } finally {
      setPending(false);
    }
  };

  return <details className="lc-console-panel" data-presentation-source-picker>
    <summary>{tr("Presentation sources and cues", "演示来源和提示点")}</summary>
    <div className="lc-actions">
      <label>{tr("Source", "来源")} <select value={mode} onChange={(event) => { setMode(event.target.value as "native" | "external"); setSelectedSource(null); }}><option value="native">{tr("Native deck", "原生幻灯片")}</option><option value="external">{tr("Provider URL", "提供者 URL")}</option></select></label>
      <label>{tr("Lesson step", "教案步骤")} <select value={stepKey} onChange={(event) => setStepKey(event.target.value)}><option value="">{tr("Choose a step", "选择步骤")}</option>{steps.map((step) => <option key={step.key ?? step.id} value={step.key}>{step.position}. {step.title}</option>)}</select></label>
      <label>{tr("Slide", "页面")} <input type="number" min={1} value={Number(slideIndex) + 1} onChange={(event) => setSlideIndex(String(Math.max(0, Number(event.target.value) - 1)))} /></label>
    </div>
    {mode === "native" ? <label>{tr("Snapshot", "快照")} <select value={snapshotId} onChange={(event) => setSnapshotId(event.target.value)}><option value="">{tr("Choose a snapshot", "选择快照")}</option>{snapshots.map((snapshot) => <option key={snapshot.id} value={snapshot.id}>{snapshot.title} ({snapshot.slides?.length ?? "?"})</option>)}</select></label> : <>
      <label>{tr("Provider", "提供者")} <select value={provider} onChange={(event) => { setProvider(event.target.value); setResults([]); }}><option value="">{tr("Choose a provider", "选择提供者")}</option>{providers.map((item) => <option key={item.key} value={item.key}>{item.key}{item.search_supported ? " · search" : ""}</option>)}</select></label>
      <label>{tr("Supported URL", "支持的 URL")} <input type="url" value={url} onChange={(event) => { setUrl(event.target.value); setSelectedSource(null); }} placeholder="https://…" /></label>
      {providers.find((item) => item.key === provider)?.search_supported ? <div className="lc-actions"><label>{tr("Search", "搜索")} <input value={query} onChange={(event) => setQuery(event.target.value)} /></label><button type="button" disabled={pending || !query.trim()} onClick={() => void search()}>{tr("Search", "搜索")}</button></div> : <p role="status">{tr("Browse is unavailable; paste a supported URL.", "浏览不可用；请粘贴支持的 URL。")}</p>}
      {results.length ? <ul>{results.map((item, index) => <li key={`${String(item.title)}-${index}`}><button type="button" onClick={() => { setSelectedSource(item); setUrl(""); }}>{String(item.title || item.provider || tr("Source", "来源"))}</button></li>)}</ul> : null}
    </>}
    <button type="button" disabled={pending || !stepKey} onClick={() => void attach()}>{tr("Attach cue", "添加提示点")}</button>
    {cues.length ? <ul aria-label={tr("Attached cues", "已添加提示点")}>{cues.map((cue) => <li key={cue.id}><span>{String(cue.source.title || cue.source.type || tr("Source", "来源"))} · {steps.find((step) => step.key === cue.step_key)?.title || cue.step_key} · {Number(cue.source.slide_index ?? 0) + 1}</span>{cue.valid === false ? <strong role="status"> {cue.status === "reattach_required" ? tr("Reattach required", "需要重新关联") : tr("Unavailable", "不可用")}</strong> : <button type="button" disabled={pending} onClick={() => void launch(cue)}>{tr("Launch", "启动")}</button>}<button type="button" disabled={pending} onClick={() => void remove(cue)}>{tr("Remove", "移除")}</button></li>)}</ul> : <p>{tr("No cues attached yet.", "尚未添加提示点。")}</p>}
    {status ? <p role="status" className="lc-builder-status-error">{status}</p> : null}
  </details>;
}
