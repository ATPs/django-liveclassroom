import * as React from "react";
import { useCallback, useEffect, useState } from "react";

import { ApiError, deleteJson, getJson, postJson } from "../../protocol.js";
import { useLocale } from "../../i18n.js";

type Share = {
  id: number;
  kind_label: string;
  source_title: string | null;
  owner: { display_name: string };
  recipient: { display_name: string };
  active: boolean;
  viewer_role: "owner" | "recipient";
};

function endpoint(apiRoot: string, path: string): string {
  const base = new URL(apiRoot, window.location.href);
  if (!base.pathname.endsWith("/")) base.pathname += "/";
  return new URL(path, base).toString();
}

function words(locale: string, en: string, zh: string): string { return locale.startsWith("zh") ? zh : en; }

export function ContentSharingPanel({ apiRoot, kind, objectId }: { apiRoot: string; kind?: string; objectId?: number | null }) {
  const locale = useLocale();
  const [owned, setOwned] = useState<Share[]>([]);
  const [received, setReceived] = useState<Share[]>([]);
  const [recipientId, setRecipientId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await getJson<{ owned_shares?: Share[]; received_shares?: Share[] }>(endpoint(apiRoot, "content-shares/"));
      setOwned(result.owned_shares ?? []); setReceived(result.received_shares ?? []); setError("");
    } catch (cause) { setError(cause instanceof ApiError ? cause.message : words(locale, "Unable to load content shares.", "无法加载内容共享。")); }
    finally { setLoading(false); }
  }, [apiRoot, locale]);
  useEffect(() => { void load(); }, [load]);
  const share = async () => {
    const parsed = Number(recipientId);
    if (!kind || !objectId || !Number.isInteger(parsed) || parsed < 1) { setError(words(locale, "Enter the recipient's account ID.", "请输入接收者账号 ID。")); return; }
    try {
      await postJson(endpoint(apiRoot, "content-shares/"), { kind, object_id: objectId, recipient_id: parsed }, crypto.randomUUID());
      setRecipientId(""); await load();
    } catch (cause) { setError(cause instanceof ApiError ? cause.message : words(locale, "Unable to create this share.", "无法创建此共享。")); }
  };
  const revoke = async (shareId: number) => {
    try { await deleteJson(endpoint(apiRoot, `content-shares/${shareId}/`), crypto.randomUUID()); await load(); }
    catch (cause) { setError(cause instanceof ApiError ? cause.message : words(locale, "Unable to revoke this share.", "无法撤销此共享。")); }
  };
  const copy = async (shareId: number) => {
    try { await postJson(endpoint(apiRoot, `content-shares/${shareId}/copy/`), {}, crypto.randomUUID()); await load(); }
    catch (cause) { setError(cause instanceof ApiError ? cause.message : words(locale, "Unable to copy this content.", "无法复制此内容。")); }
  };
  return <section className="lc-card lc-content-sharing" aria-labelledby="content-sharing-heading">
    <h2 id="content-sharing-heading">{words(locale, "Content sharing", "内容共享")}</h2>
    {kind && objectId ? <div className="lc-actions"><label>{words(locale, "Recipient account ID", "接收者账号 ID")}<input className="lc-input" inputMode="numeric" value={recipientId} onChange={(event) => setRecipientId(event.target.value)} /></label><button type="button" className="lc-btn lc-btn-primary" onClick={() => void share()}>{words(locale, "Share this assessment", "共享此测验")}</button></div> : <p>{words(locale, "Select saved content to share it with a named teacher.", "选择已保存内容后，可与指定教师共享。")}</p>}
    <button type="button" className="lc-btn lc-btn-outline" onClick={() => void load()} disabled={loading}>{words(locale, "Refresh shares", "刷新共享")}</button>
    {error ? <p className="lc-form-error" role="alert">{error}</p> : null}
    <h3>{words(locale, "Your grants", "我发出的共享")}</h3>
    {owned.length ? <ul>{owned.map((share) => <li key={share.id}>{share.kind_label}: {share.source_title ?? words(locale, "Unavailable source", "来源不可用")} → {share.recipient.display_name} {share.active ? <button type="button" className="lc-btn-sm lc-btn-danger" onClick={() => void revoke(share.id)}>{words(locale, "Revoke", "撤销")}</button> : <span>{words(locale, "Revoked", "已撤销")}</span>}</li>)}</ul> : <p>{words(locale, "No grants yet.", "尚无共享。")}</p>}
    <h3>{words(locale, "Shared with you", "分享给我的内容")}</h3>
    {received.length ? <ul>{received.map((share) => <li key={share.id}>{share.kind_label}: {share.source_title ?? words(locale, "Unavailable source", "来源不可用")} · {share.owner.display_name} <button type="button" className="lc-btn-sm lc-btn-primary" onClick={() => void copy(share.id)}>{words(locale, "Copy to my workspace", "复制到我的工作区")}</button></li>)}</ul> : <p>{words(locale, "No shared content available.", "暂无可用共享内容。")}</p>}
  </section>;
}
