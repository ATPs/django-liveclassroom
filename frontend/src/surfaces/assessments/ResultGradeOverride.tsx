import * as React from "react";
import { useLocale } from "../../i18n.js";
import { postJson } from "../../protocol.js";
import { useUnsavedChangesWarning, useUnsavedNavigationGuard } from "../../navigation.js";

export function ResultGradeOverride({ url, fingerprint, initialPoints, possible, initialComment, onSaved }: {
  url: string; fingerprint: string; initialPoints: string; possible: string; initialComment: string; onSaved: () => void;
}) {
  const zh = useLocale().startsWith("zh");
  const [points, setPoints] = React.useState(initialPoints);
  const [comment, setComment] = React.useState(initialComment);
  const [reason, setReason] = React.useState("");
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [saved, setSaved] = React.useState(false);
  const dirty = !saved && (points !== initialPoints || comment !== initialComment || Boolean(reason));
  useUnsavedChangesWarning(dirty);
  const save = React.useCallback(async (): Promise<boolean> => {
    if (busy) return false;
    const awarded = Number(points);
    const maximum = Number(possible);
    if (!points.trim() || !Number.isFinite(awarded) || !Number.isFinite(maximum) || maximum <= 0 || awarded < 0 || awarded > maximum || !reason.trim()) {
      setError(zh ? "请输入有效得分和更正理由。" : "Enter a valid score and a correction reason."); return false;
    }
    setBusy(true); setError("");
    try {
      await postJson(url, { normalized_score: (awarded / maximum).toFixed(10), comment, reason, expected_grade_fingerprint: fingerprint, idempotency_key: crypto.randomUUID() });
      setSaved(true);
      return true;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : (zh ? "保存失败，输入已保留。" : "Save failed. Your entry is retained."));
      return false;
    } finally { setBusy(false); }
  }, [busy, comment, fingerprint, points, possible, reason, url, zh]);
  const saveAndRefresh = React.useCallback(async (): Promise<boolean> => {
    const ok = await save();
    if (ok) onSaved();
    return ok;
  }, [onSaved, save]);
  const guard = useUnsavedNavigationGuard({ dirty, onSave: saveAndRefresh,
    onBeforeLeave: () => { setPoints(initialPoints); setComment(initialComment); setReason(""); },
    labels: zh ? { title: "未保存的评分", body: "离开前保存评分？", save: "保存并离开", discard: "放弃并离开", stay: "留在此页" } : {},
  });
  return <section className="lc-result-grade-override"><h3>{zh ? "更正评分" : "Correct grade"}</h3>
    {guard.dialog}
    <form className="lc-form" onSubmit={event => { event.preventDefault(); void saveAndRefresh(); }}>
      <label>{zh ? "得分" : "Awarded points"}<input className="lc-input" value={points} onChange={event => { setSaved(false); setPoints(event.target.value); }} inputMode="decimal" disabled={busy || saved} required /></label>
      <p>{zh ? "满分" : "Possible points"}: {possible}</p>
      <label>{zh ? "评语" : "Comment"}<textarea className="lc-textarea" value={comment} onChange={event => { setSaved(false); setComment(event.target.value); }} maxLength={4000} disabled={busy || saved} /></label>
      <label>{zh ? "更正理由" : "Correction reason"}<input className="lc-input" value={reason} onChange={event => { setSaved(false); setReason(event.target.value); }} maxLength={255} disabled={busy || saved} required /></label>
      {error ? <p className="lc-form-error" role="alert">{error}</p> : null}
      <button className="lc-btn lc-btn-primary" type="submit" disabled={busy || saved}>{zh ? "保存更正" : "Save correction"}</button>
    </form>
  </section>;
}
