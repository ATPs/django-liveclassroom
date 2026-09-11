import * as React from "react";
import { useState } from "react";
import { useLocale } from "../i18n.js";

export type EditableSnapshot = { title?: string; type_key?: string; content?: Record<string, unknown>; [key: string]: unknown };

/** Ordinary teacher fields; full saved payloads survive edits to unrelated fields. */
export function ActivityEditor({ initial, onSave, onCancel, onSaveResult }: {
  initial?: EditableSnapshot;
  onSave: (snapshot: EditableSnapshot) => Promise<void | boolean>;
  onCancel: () => void;
  onSaveResult?: (saved: boolean) => void;
}) {
  const locale = useLocale();
  const tr = (en: string, zh: string) => locale.startsWith("zh") ? zh : en;
  const content = initial?.content ?? {};
  const [kind, setKind] = useState(String(initial?.type_key ?? "liveclassroom.short_text"));
  const [title, setTitle] = useState(initial?.title ?? "");
  const [prompt, setPrompt] = useState(String(content.prompt ?? ""));
  const [options, setOptions] = useState(((content.options ?? []) as Array<{id:string;text:string}>).map(o => `${o.id}: ${o.text}`).join("\n"));
  const storedAnswer = content.answer ?? content.correct_answer;
  const initialKind = String(initial?.type_key ?? "liveclassroom.short_text");
  const [answer, setAnswer] = useState(
    Array.isArray(storedAnswer)
      ? storedAnswer.join(initialKind === "liveclassroom.short_text" ? "\n" : ", ")
      : String(storedAnswer ?? ""),
  );
  const [partialCredit, setPartialCredit] = useState(content.partial_credit === true);
  const [tolerance, setTolerance] = useState(String(content.tolerance ?? ""));
  const [caseSensitive, setCaseSensitive] = useState(content.case_sensitive === true);
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
  const [essayMaxLength, setEssayMaxLength] = useState(String(content.max_length ?? 10000));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const choice = ["single_choice", "multiple_choice", "poll", "ranking", "true_false"].some(k => kind === `liveclassroom.${k}`);
  const numeric = ["liveclassroom.numeric", "liveclassroom.rating"].includes(kind);
  const gradedChoice = ["liveclassroom.single_choice", "liveclassroom.multiple_choice", "liveclassroom.true_false"].includes(kind);
  const shortText = kind === "liveclassroom.short_text";
  const essay = kind === "liveclassroom.essay";
  const optionIds = options.split("\n").map((line, index) => {
    const match = /^([^:]+):/.exec(line.trim());
    return match ? match[1].trim() : line.trim() ? String.fromCharCode(65 + index) : "";
  }).filter(Boolean);
  const selectedAnswers = answer.split(",").map(value => value.trim()).filter(Boolean);
  const toggleAnswer = (id: string, checked: boolean) => {
    const next = checked
      ? [...selectedAnswers, id].filter((value, index, values) => values.indexOf(value) === index)
      : selectedAnswers.filter(value => value !== id);
    setAnswer(next.join(", "));
  };
  const bashSimulator = kind === "liveclassroom.bash_simulator";
  const kinds = [
    ["short_text", "Short text", "简答"], ["single_choice", "Single choice", "单选"],
    ["multiple_choice", "Multiple choice", "多选"], ["true_false", "True / false", "判断"],
    ["essay", "Essay response", "长文本回答"],
    ["poll", "Poll", "投票"], ["numeric", "Numeric", "数值"], ["rating", "Rating", "评分"],
    ["ranking", "Ranking", "排序"], ["word_cloud", "Word cloud", "词云"],
    ["bash_simulator", "Bash simulator", "Bash 模拟器"],
    ["markdown", "Markdown", "Markdown"], ["media", "Media URL", "媒体链接"], ["timer", "Timer", "计时器"],
  ];
  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (busy) {
      // A guarded parent may request a save while an earlier submission is in
      // flight. Resolve that request instead of leaving its departure promise
      // pending forever.
      onSaveResult?.(false);
      return;
    }
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
      delete next.answer;
      delete next.correct_answer;
      delete next.partial_credit;
      delete next.tolerance;
      delete next.case_sensitive;
      delete next.auto_grade;
      delete next.automatic_grading;
      delete next.automatic_grading_enabled;
      if (gradedChoice && answer.trim()) {
        const values = answer.split(",").map(v => v.trim()).filter(Boolean);
        next.answer = kind === "liveclassroom.multiple_choice" ? values : values[0];
        if (kind === "liveclassroom.multiple_choice") next.partial_credit = partialCredit;
      }
      if (kind === "liveclassroom.numeric" && answer.trim()) {
        next.answer = answer.trim();
        if (tolerance.trim()) next.tolerance = tolerance.trim();
      }
      if (shortText && answer.trim()) {
        next.answer = [...new Map(answer.split("\n").map(value => value.trim()).filter(Boolean).map(value => [value, value])).values()];
        next.case_sensitive = caseSensitive;
      }
      if (essay) {
        const parsedMaxLength = Number(essayMaxLength);
        if (!Number.isInteger(parsedMaxLength) || parsedMaxLength < 1 || parsedMaxLength > 50000) {
          throw new Error(tr("Essay maximum length must be an integer from 1 to 50000", "长文本最大长度必须是 1 到 50000 之间的整数"));
        }
        next.max_length = parsedMaxLength;
        delete next.answer;
        delete next.correct_answer;
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
      const result = await onSave({ ...initial, type_key: kind, kind: kind.split(".").pop(), schema_version: 1, title: title.trim() || prompt.trim() || tr("Activity", "活动"), content: next });
      onSaveResult?.(result !== false);
    } catch (reason) {
      onSaveResult?.(false);
      setError(reason instanceof Error ? reason.message : tr("Could not save", "保存失败"));
    }
    finally { setBusy(false); }
  };
  return <form className="lc-form" onSubmit={event => void submit(event)}>
    {!initial && <label>{tr("Activity type", "活动类型")}<select value={kind} onChange={e => setKind(e.target.value)}>{kinds.map(([key,en,zh]) => <option key={key} value={`liveclassroom.${key}`}>{tr(en,zh)}</option>)}</select></label>}
    <label>{tr("Title", "标题")}<input aria-label={tr("Title", "标题")} value={title} maxLength={200} onChange={e => setTitle(e.target.value)} /></label>
    <label>{tr("Prompt", "题干")}<textarea aria-label={tr("Prompt", "题干")} value={prompt} onChange={e => setPrompt(e.target.value)} /></label>
    {choice && <label>{tr("Options (one ID: text per line)", "选项（每行一个 编号: 内容）")}<textarea aria-label={tr("Options", "选项")} value={options} onChange={e => setOptions(e.target.value)} /></label>}
    {kind === "liveclassroom.single_choice" && <label>{tr("Correct answer (optional)", "正确答案（可选）")}<select aria-label={tr("Correct answer", "正确答案")} value={answer} onChange={e => setAnswer(e.target.value)}><option value="">{tr("Not graded", "不评分")}</option>{optionIds.map(id => <option key={id} value={id}>{id}</option>)}</select></label>}
    {kind === "liveclassroom.multiple_choice" && <fieldset><legend>{tr("Correct answers (optional)", "正确答案（可选）")}</legend>{optionIds.map(id => <label key={id}><input type="checkbox" checked={selectedAnswers.includes(id)} onChange={e => toggleAnswer(id, e.target.checked)} /> {id}</label>)}</fieldset>}
    {kind === "liveclassroom.true_false" && <label>{tr("Correct answer (optional)", "正确答案（可选）")}<select aria-label={tr("Correct answer", "正确答案")} value={answer} onChange={e => setAnswer(e.target.value)}><option value="">{tr("Not graded", "不评分")}</option><option value="true">{tr("True", "正确")}</option><option value="false">{tr("False", "错误")}</option></select></label>}
    {kind === "liveclassroom.multiple_choice" && <label><input type="checkbox" checked={partialCredit} onChange={e => setPartialCredit(e.target.checked)} /> {tr("Allow partial credit", "允许部分得分")}</label>}
    {kind === "liveclassroom.numeric" && <><label>{tr("Correct number (optional)", "正确数值（可选）")}<input aria-label={tr("Correct number", "正确数值")} inputMode="decimal" value={answer} onChange={e => setAnswer(e.target.value)} /></label><label>{tr("Tolerance (optional)", "误差范围（可选）")}<input aria-label={tr("Tolerance", "误差范围")} type="number" min={0} step="any" value={tolerance} onChange={e => setTolerance(e.target.value)} disabled={!answer.trim()} /></label></>}
    {shortText && <><label>{tr("Accepted answers (one per line, optional)", "可接受答案（每行一个，可选）")}<textarea aria-label={tr("Accepted answers", "可接受答案")} rows={4} value={answer} onChange={e => setAnswer(e.target.value)} /></label><label><input type="checkbox" checked={caseSensitive} onChange={e => setCaseSensitive(e.target.checked)} disabled={!answer.trim()} /> {tr("Case sensitive", "区分大小写")}</label></>}
    {essay && <label>{tr("Maximum response length", "回答最大长度")}<input aria-label={tr("Maximum response length", "回答最大长度")} type="number" min={1} max={50000} step={1} value={essayMaxLength} onChange={e => setEssayMaxLength(e.target.value)} /><small>{tr("Essay answers are reviewed manually.", "长文本回答需要教师手动评分。")}</small></label>}
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
