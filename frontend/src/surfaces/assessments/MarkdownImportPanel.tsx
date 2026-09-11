import * as React from "react";
import { useState } from "react";

import { ApiError, postJson } from "../../protocol.js";
import { useLocale } from "../../i18n.js";

type Preview = {
  valid: boolean;
  filename: string;
  fingerprint: string;
  kind: string | null;
  errors: Array<{ path: string; message: string; line?: number }>;
};

function endpoint(apiRoot: string, path: string): string {
  const base = new URL(apiRoot, window.location.href);
  base.pathname = base.pathname.replace(/workspace\/?$/, "");
  if (!base.pathname.endsWith("/")) base.pathname += "/";
  return new URL(path, base).toString();
}

function label(locale: string, en: string, zh: string): string {
  return locale.startsWith("zh") ? zh : en;
}

export function MarkdownImportPanel({ apiRoot, onImported }: { apiRoot: string; onImported: () => void }) {
  const locale = useLocale();
  const [filename, setFilename] = useState("import.yaml");
  const [content, setContent] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState("");
  const [working, setWorking] = useState(false);

  const previewSource = async () => {
    setWorking(true); setError("");
    try {
      const value = await postJson<Preview>(endpoint(apiRoot, "imports/markdown/preview/"), { filename, content });
      setPreview(value);
    } catch (cause) {
      setPreview(null);
      setError(cause instanceof ApiError ? cause.message : label(locale, "Unable to preview this import.", "无法预览此导入。"));
    } finally { setWorking(false); }
  };
  const commit = async () => {
    if (!preview?.valid) return;
    setWorking(true); setError("");
    try {
      await postJson(
        endpoint(apiRoot, "imports/markdown/commit/"),
        { filename, content, fingerprint: preview.fingerprint, idempotency_key: crypto.randomUUID() },
      );
      setPreview(null); setContent(""); onImported();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : label(locale, "Import was not saved; your source is still here.", "导入未保存，原始内容仍在此处。"));
    } finally { setWorking(false); }
  };
  const chooseFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.currentTarget.files?.[0];
    if (!file) return;
    setFilename(file.name); setContent(await file.text()); setPreview(null); setError("");
  };
  return <section className="lc-card lc-markdown-import" aria-labelledby="markdown-import-heading">
    <h2 id="markdown-import-heading">{label(locale, "Import Markdown or YAML", "导入 Markdown 或 YAML")}</h2>
    <p>{label(locale, "Preview a question, deck, lesson, or assessment before creating an independent copy.", "先预览题目、幻灯片、课程或测验，再创建独立副本。")}</p>
    <label>{label(locale, "File name", "文件名")}<input className="lc-input" value={filename} onChange={(event) => { setFilename(event.target.value); setPreview(null); }} /></label>
    <label>{label(locale, "Choose file", "选择文件")}<input type="file" accept=".md,.yaml,.yml,text/markdown,text/yaml" onChange={(event) => void chooseFile(event)} /></label>
    <label>{label(locale, "Source", "源内容")}<textarea className="lc-textarea" rows={8} value={content} onChange={(event) => { setContent(event.target.value); setPreview(null); }} /></label>
    <div className="lc-actions">
      <button type="button" className="lc-btn lc-btn-outline" onClick={() => void previewSource()} disabled={working || !filename || !content}>{label(locale, "Preview import", "预览导入")}</button>
      <button type="button" className="lc-btn lc-btn-primary" onClick={() => void commit()} disabled={working || !preview?.valid}>{label(locale, "Create copy", "创建副本")}</button>
    </div>
    {preview ? <div role="status"><p>{preview.valid ? label(locale, `Ready to import ${preview.kind ?? "content"}.`, `可导入 ${preview.kind ?? "内容"}。`) : label(locale, "Fix the listed errors before importing.", "请先修复列出的错误。")}</p>{preview.errors.map((item, index) => <p className="lc-form-error" key={`${item.path}-${index}`}>{item.path}{item.line ? `:${item.line}` : ""}: {item.message}</p>)}</div> : null}
    {error ? <p className="lc-form-error" role="alert">{error}</p> : null}
  </section>;
}
