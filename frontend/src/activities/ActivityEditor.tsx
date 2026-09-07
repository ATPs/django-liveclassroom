import * as React from "react";
import { useState } from "react";
import { useLocale } from "../i18n.js";

export type EditableSnapshot = { title?: string; type_key?: string; content?: Record<string, unknown>; [key: string]: unknown };

/** Ordinary teacher fields; full saved payloads survive edits to unrelated fields. */
export function ActivityEditor({ initial, onSave, onCancel }: {
  initial?: EditableSnapshot;
  onSave: (snapshot: EditableSnapshot) => Promise<void>;
  onCancel: () => void;
}) {
  const locale = useLocale();
  const tr = (en: string, zh: string) => locale.startsWith("zh") ? zh : en;
  const content = initial?.content ?? {};
  const [kind, setKind] = useState(String(initial?.type_key ?? "liveclassroom.short_text"));
  const [title, setTitle] = useState(initial?.title ?? "");
  const [prompt, setPrompt] = useState(String(content.prompt ?? ""));
  const [options, setOptions] = useState(((content.options ?? []) as Array<{id:string;text:string}>).map(o => `${o.id}: ${o.text}`).join("\n"));
  const [answer, setAnswer] = useState(Array.isArray(content.answer) ? content.answer.join(", ") : String(content.answer ?? ""));
  const [explanation, setExplanation] = useState(String(content.explanation_markdown ?? ""));
  const [markdown, setMarkdown] = useState(String(content.markdown ?? ""));
  const [url, setUrl] = useState(String(content.url ?? ""));
  const [vaultpub, setVaultpub] = useState(content.provider === "vaultpub");
  const [duration, setDuration] = useState(String(content.duration_seconds ?? 60));
  const [filesystem, setFilesystem] = useState(JSON.stringify(content.filesystem ?? {}, null, 2));
  const [initialDirectory, setInitialDirectory] = useState(String(content.initial_directory ?? "/"));
  const [completion, setCompletion] = useState(JSON.stringify(content.completion ?? {}, null, 2));
  const [minimum, setMinimum] = useState(String(content.minimum ?? ""));
  const [maximum, setMaximum] = useState(String(content.maximum ?? ""));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const choice = ["single_choice", "multiple_choice", "poll", "ranking", "true_false"].some(k => kind === `liveclassroom.${k}`);
  const numeric = ["liveclassroom.numeric", "liveclassroom.rating"].includes(kind);
  const bashSimulator = kind === "liveclassroom.bash_simulator";
  const kinds = [
    ["short_text", "Short text", "简答"], ["single_choice", "Single choice", "单选"],
    ["multiple_choice", "Multiple choice", "多选"], ["true_false", "True / false", "判断"],
    ["poll", "Poll", "投票"], ["numeric", "Numeric", "数值"], ["rating", "Rating", "评分"],
    ["ranking", "Ranking", "排序"], ["word_cloud", "Word cloud", "词云"],
    ["bash_simulator", "Bash simulator", "Bash 模拟器"],
    ["markdown", "Markdown", "Markdown"], ["media", "Media URL", "媒体链接"], ["timer", "Timer", "计时器"],
  ];
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setError("");
    try {
      const next: Record<string, unknown> = { ...content };
      if (prompt.trim()) next.prompt = prompt.trim();
      else delete next.prompt;
      if (choice) {
        next.options = options.split("\n").filter(s => s.trim()).map((line, index) => {
          const match = /^([^:]+):\s*(.*)$/.exec(line);
          return { id: match ? match[1].trim() : String.fromCharCode(65 + index), text: match ? match[2] : line.trim() };
        });
        if (kind === "liveclassroom.true_false" && !(next.options as unknown[]).length) next.options = [{id:"true",text:tr("True","正确")},{id:"false",text:tr("False","错误")}];
      }
      if (choice || numeric) {
        if (answer.trim()) next.answer = numeric ? Number(answer) : answer.split(",").map(v => v.trim()).filter(Boolean);
        else delete next.answer;
      }
      if (explanation.trim()) next.explanation_markdown = explanation.trim(); else delete next.explanation_markdown;
      if (kind === "liveclassroom.markdown") next.markdown = markdown;
      if (kind === "liveclassroom.media") {
        let mediaUrl = url.trim();
        if (vaultpub && mediaUrl) {
          try {
            const parsed = new URL(mediaUrl, window.location.href);
            if (parsed.origin === window.location.origin) mediaUrl = `${parsed.pathname}${parsed.search}`;
          } catch { /* server validation reports an invalid URL */ }
          next.provider = "vaultpub";
          next.media_type = "iframe";
        } else if (content.provider === "vaultpub") {
          delete next.provider;
        }
        next.url = mediaUrl;
      }
      if (kind === "liveclassroom.timer") next.duration_seconds = Number(duration);
      if (bashSimulator) {
        const parsedFilesystem = JSON.parse(filesystem);
        const parsedCompletion = JSON.parse(completion);
        if (!parsedFilesystem || typeof parsedFilesystem !== "object" || Array.isArray(parsedFilesystem)) {
          throw new Error(tr("Filesystem must be a JSON object", "文件系统必须是 JSON 对象"));
        }
        if (!parsedCompletion || typeof parsedCompletion !== "object" || Array.isArray(parsedCompletion)) {
          throw new Error(tr("Completion must be a JSON object", "完成条件必须是 JSON 对象"));
        }
        next.filesystem = parsedFilesystem;
        next.initial_directory = initialDirectory.trim() || "/";
        next.completion = parsedCompletion;
      }
      if (numeric) {
        if (minimum !== "") next.minimum = Number(minimum); else delete next.minimum;
        if (maximum !== "") next.maximum = Number(maximum); else delete next.maximum;
      }
      await onSave({ ...initial, type_key: kind, kind: kind.split(".").pop(), schema_version: 1, title: title.trim() || prompt.trim() || tr("Activity", "活动"), content: next });
    } catch (reason) { setError(reason instanceof Error ? reason.message : tr("Could not save", "保存失败")); }
    finally { setBusy(false); }
  };
  return <form className="lc-form" onSubmit={event => void submit(event)}>
    {!initial && <label>{tr("Activity type", "活动类型")}<select value={kind} onChange={e => setKind(e.target.value)}>{kinds.map(([key,en,zh]) => <option key={key} value={`liveclassroom.${key}`}>{tr(en,zh)}</option>)}</select></label>}
    <label>{tr("Title", "标题")}<input value={title} maxLength={200} onChange={e => setTitle(e.target.value)} /></label>
    <label>{tr("Prompt", "题干")}<textarea aria-label={tr("Prompt", "题干")} value={prompt} onChange={e => setPrompt(e.target.value)} /></label>
    {choice && <label>{tr("Options (one ID: text per line)", "选项（每行一个 编号: 内容）")}<textarea aria-label={tr("Options", "选项")} value={options} onChange={e => setOptions(e.target.value)} /></label>}
    {(choice || numeric) && <label>{tr("Correct answer (optional)", "正确答案（可选）")}<input value={answer} onChange={e => setAnswer(e.target.value)} /></label>}
    {numeric && <><label>{tr("Minimum", "最小值")}<input type="number" value={minimum} onChange={e => setMinimum(e.target.value)} /></label><label>{tr("Maximum", "最大值")}<input type="number" value={maximum} onChange={e => setMaximum(e.target.value)} /></label></>}
    {kind === "liveclassroom.markdown" && <label>Markdown<textarea aria-label="Markdown" rows={8} value={markdown} onChange={e => setMarkdown(e.target.value)} /></label>}
    {kind === "liveclassroom.media" && <><label>{tr("Media URL", "媒体链接")}<input type="text" value={url} onChange={e => setUrl(e.target.value)} /></label><label><input type="checkbox" checked={vaultpub} onChange={e => setVaultpub(e.target.checked)} /> {tr("VaultPub Slide View", "VaultPub 幻灯片视图")}</label></>}
    {kind === "liveclassroom.timer" && <label>{tr("Seconds", "秒")}<input type="number" min={1} value={duration} onChange={e => setDuration(e.target.value)} /></label>}
    {bashSimulator && <>
      <label>{tr("Virtual filesystem (JSON path to text)", "虚拟文件系统（JSON 路径到文本）")}<textarea rows={8} value={filesystem} onChange={e => setFilesystem(e.target.value)} /></label>
      <label>{tr("Initial directory", "初始目录")}<input value={initialDirectory} onChange={e => setInitialDirectory(e.target.value)} /></label>
      <label>{tr("Completion requirements (JSON)", "完成条件（JSON）")}<textarea rows={4} value={completion} onChange={e => setCompletion(e.target.value)} /></label>
    </>}
    <label>{tr("Explanation (optional)", "解析（可选）")}<textarea aria-label={tr("Explanation (optional)", "解析（可选）")} value={explanation} onChange={e => setExplanation(e.target.value)} /></label>
    {error && <p role="alert">{error}</p>}
    <div className="lc-actions"><button disabled={busy}>{tr("Save", "保存")}</button><button type="button" onClick={onCancel}>{tr("Cancel", "取消")}</button></div>
  </form>;
}
