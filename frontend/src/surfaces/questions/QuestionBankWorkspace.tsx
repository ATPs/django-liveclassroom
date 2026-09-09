import * as React from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ActivityEditor, type EditableSnapshot } from "../../activities/ActivityEditor.js";
import { MarkdownView } from "../../activities/MarkdownView.js";
import { deleteJson, getJson, patchJson, postJson } from "../../protocol.js";
import { useLocale } from "../../i18n.js";

type QuestionBank = {
  id: number;
  title: string;
  description: string;
  course_id?: number | null;
  question_count: number;
  updated_at: string;
};

type QuestionSummary = {
  id: number;
  title: string;
  type_key: string;
  metadata: Record<string, unknown>;
  current_revision_id?: number | null;
  updated_at: string;
};

type QuestionDetail = QuestionSummary & {
  definition: Record<string, unknown>;
  asset_id?: number | null;
  status?: string;
  schema_version?: number;
  revisions?: Array<{ id: number; revision: number; payload: Record<string, unknown>; metadata: Record<string, unknown> }>;
};

export type QuestionPickerSelection = QuestionDetail;

type QuestionBankWorkspaceProps = {
  apiRoot: string;
  picker?: boolean;
  onPick?: (definitionId: number, currentRevisionId?: number | null, question?: QuestionPickerSelection) => void | Promise<void>;
  pickerLabel?: { en: string; zh: string };
};

type Panel = "bank" | "question" | "edit" | null;

function endpoint(apiRoot: string, path: string): string {
  const base = new URL(apiRoot, window.location.href);
  if (!base.pathname.endsWith("/")) base.pathname += "/";
  return new URL(path.replace(/^\/+/, ""), base).toString();
}

function metadataText(value: unknown): string {
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

function tagsOf(question: QuestionSummary): string[] {
  const value = question.metadata?.tags;
  return Array.isArray(value) ? value.map(String) : [];
}

function questionPrompt(question: QuestionDetail): string {
  const prompt = question.definition?.prompt ?? question.definition?.stem_markdown ?? question.definition?.markdown;
  return typeof prompt === "string" ? prompt : "";
}

function localText(locale: string, en: string, zh: string): string {
  return locale.startsWith("zh") ? zh : en;
}

function QuestionPreview({ question }: { question: QuestionDetail }) {
  const locale = useLocale();
  const type = question.type_key.split(".").pop() ?? question.type_key;
  const prompt = questionPrompt(question);
  const options = Array.isArray(question.definition?.options)
    ? question.definition.options as Array<Record<string, unknown>>
    : [];
  const answer = question.definition?.answer;
  const markdown = type === "markdown" ? String(question.definition?.markdown ?? prompt) : "";

  return (
    <section className="lc-card lc-question-preview" aria-labelledby="lc-question-preview-heading">
      <div className="lc-question-preview-heading">
        <h3 id="lc-question-preview-heading">{question.title}</h3>
        <span className="lc-badge">{localText(locale, "Private preview", "私有预览")}</span>
      </div>
      <p className="lc-workspace-meta">{type}</p>
      {markdown ? <MarkdownView markdown={markdown} /> : prompt ? <p className="lc-question-prompt">{prompt}</p> : null}
      {options.length ? (
        <ul className="lc-question-options">
          {options.map((option, index) => (
            <li key={`${String(option.id ?? index)}-${index}`}>
              <span>{String(option.id ?? String.fromCharCode(65 + index))}</span> {String(option.text ?? option.label ?? "")}
            </li>
          ))}
        </ul>
      ) : null}
      {answer !== undefined ? (
        <p className="lc-question-answer">
          <strong>{localText(locale, "Answer (teacher only)", "答案（仅教师可见）")}:</strong> {Array.isArray(answer) ? answer.join(", ") : String(answer)}
        </p>
      ) : (
        <p className="lc-workspace-meta">{localText(locale, "No answer key; ungraded", "没有答案；不评分")}</p>
      )}
      {question.metadata && Object.keys(question.metadata).length ? (
        <dl className="lc-question-metadata">
          {question.metadata.topic ? <><dt>{localText(locale, "Topic", "主题")}</dt><dd>{metadataText(question.metadata.topic)}</dd></> : null}
          {question.metadata.difficulty ? <><dt>{localText(locale, "Difficulty", "难度")}</dt><dd>{metadataText(question.metadata.difficulty)}</dd></> : null}
          {tagsOf(question).length ? <><dt>{localText(locale, "Tags", "标签")}</dt><dd>{tagsOf(question).join(", ")}</dd></> : null}
        </dl>
      ) : null}
    </section>
  );
}

function MetadataFields({
  metadata,
  onChange,
}: {
  metadata: { topic: string; difficulty: string; tags: string };
  onChange: (next: { topic: string; difficulty: string; tags: string }) => void;
}) {
  const locale = useLocale();
  const tr = (en: string, zh: string) => localText(locale, en, zh);
  return (
    <div className="lc-question-metadata-form">
      <label>{tr("Topic", "主题")}<input className="lc-input" value={metadata.topic} onChange={(event) => onChange({ ...metadata, topic: event.target.value })} maxLength={200} /></label>
      <label>{tr("Difficulty", "难度")}<select className="lc-select" value={metadata.difficulty} onChange={(event) => onChange({ ...metadata, difficulty: event.target.value })}>
        <option value="">{tr("Any", "不限")}</option><option value="easy">{tr("Easy", "简单")}</option><option value="medium">{tr("Medium", "中等")}</option><option value="hard">{tr("Hard", "困难")}</option>
      </select></label>
      <label>{tr("Tags (comma separated)", "标签（用逗号分隔）")}<input className="lc-input" value={metadata.tags} onChange={(event) => onChange({ ...metadata, tags: event.target.value })} /></label>
    </div>
  );
}

function normalizedMetadata(metadata: { topic: string; difficulty: string; tags: string }): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  if (metadata.topic.trim()) result.topic = metadata.topic.trim();
  if (metadata.difficulty) result.difficulty = metadata.difficulty;
  const tags = metadata.tags.split(",").map((tag) => tag.trim()).filter(Boolean);
  if (tags.length) result.tags = [...new Set(tags)];
  return result;
}

function metadataFrom(question?: QuestionDetail | null): { topic: string; difficulty: string; tags: string } {
  const metadata = question?.metadata ?? {};
  return {
    topic: metadataText(metadata.topic),
    difficulty: metadataText(metadata.difficulty),
    tags: Array.isArray(metadata.tags) ? metadata.tags.map(String).join(", ") : "",
  };
}

export function QuestionBankWorkspace({ apiRoot, picker = false, onPick, pickerLabel }: QuestionBankWorkspaceProps) {
  const locale = useLocale();
  const tr = useCallback((en: string, zh: string) => localText(locale, en, zh), [locale]);
  const [banks, setBanks] = useState<QuestionBank[]>([]);
  const [selectedBankId, setSelectedBankId] = useState<number | null>(null);
  const [questions, setQuestions] = useState<QuestionSummary[]>([]);
  const [selectedQuestion, setSelectedQuestion] = useState<QuestionDetail | null>(null);
  const [panel, setPanel] = useState<Panel>(null);
  const [query, setQuery] = useState("");
  const [tag, setTag] = useState("");
  const [topic, setTopic] = useState("");
  const [difficulty, setDifficulty] = useState("");
  const [typeKey, setTypeKey] = useState("");
  const [bankTitle, setBankTitle] = useState("");
  const [metadata, setMetadata] = useState(metadataFrom());
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const loadBanks = useCallback(async (preferredId?: number) => {
    const data = await getJson<{ question_banks: QuestionBank[] }>(endpoint(apiRoot, "question-banks/"));
    const nextBanks = data.question_banks ?? [];
    setBanks(nextBanks);
    setSelectedBankId((previous) => {
      const candidate = preferredId ?? previous;
      return candidate && nextBanks.some((bank) => bank.id === candidate) ? candidate : nextBanks[0]?.id ?? null;
    });
  }, [apiRoot]);

  const loadQuestions = useCallback(async () => {
    if (!selectedBankId) {
      setQuestions([]);
      setSelectedQuestion(null);
      return;
    }
    const search = new URLSearchParams();
    if (query.trim()) search.set("q", query.trim());
    if (tag.trim()) search.set("tag", tag.trim());
    if (topic.trim()) search.set("topic", topic.trim());
    if (difficulty) search.set("difficulty", difficulty);
    if (typeKey.trim()) search.set("type_key", typeKey.trim());
    const data = await getJson<{ questions: QuestionSummary[] }>(endpoint(apiRoot, `question-banks/${selectedBankId}/questions/?${search.toString()}`));
    setQuestions(data.questions ?? []);
  }, [apiRoot, difficulty, query, selectedBankId, tag, topic, typeKey]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    void loadBanks().catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : tr("Unable to load question banks.", "无法加载题库。")); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [loadBanks, tr]);

  useEffect(() => {
    let active = true;
    void loadQuestions().catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : tr("Unable to load questions.", "无法加载题目。")); });
    return () => { active = false; };
  }, [loadQuestions, tr]);

  const selectQuestion = async (question: QuestionSummary) => {
    if (!selectedBankId) return;
    setError("");
    try {
      const detail = await getJson<QuestionDetail>(endpoint(apiRoot, `question-banks/${selectedBankId}/questions/${question.id}/`));
      setSelectedQuestion(detail);
      setMetadata(metadataFrom(detail));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : tr("Unable to preview question.", "无法预览题目。"));
    }
  };

  const pickQuestion = async (question: QuestionSummary) => {
    if (!onPick) return;
    setError("");
    try {
      // Resolve the private detail before handing it to a builder. This keeps
      // the selected revision and preview content together at the moment of
      // pinning instead of making callers guess which bank is active.
      const detail = selectedBankId
        ? await getJson<QuestionDetail>(endpoint(apiRoot, `question-banks/${selectedBankId}/questions/${question.id}/`))
        : undefined;
      await onPick(question.id, question.current_revision_id, detail ?? question as QuestionPickerSelection);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : tr("Unable to select question.", "无法选择题目。"));
    }
  };

  const createBank = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!bankTitle.trim() || busy) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const created = await postJson<QuestionBank>(endpoint(apiRoot, "question-banks/"), { title: bankTitle.trim() }, globalThis.crypto?.randomUUID?.());
      setBankTitle(""); setPanel(null); await loadBanks(created.id); setNotice(tr("Bank created.", "题库已创建。"));
    } catch (reason) { setError(reason instanceof Error ? reason.message : tr("Unable to create bank.", "无法创建题库。")); }
    finally { setBusy(false); }
  };

  const createQuestion = async (snapshot: EditableSnapshot) => {
    if (busy) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const created = await postJson<{ id: number }>(endpoint(apiRoot, "activity-definitions/create/"), {
        title: snapshot.title,
        type_key: snapshot.type_key,
        definition: snapshot.content ?? {},
        metadata: normalizedMetadata(metadata),
      }, globalThis.crypto?.randomUUID?.());
      if (selectedBankId) await postJson(endpoint(apiRoot, `question-banks/${selectedBankId}/questions/`), { definition_id: created.id }, globalThis.crypto?.randomUUID?.());
      setPanel(null); await loadQuestions(); await loadBanks(); setNotice(tr("Question created.", "题目已创建。"));
    } catch (reason) { setError(reason instanceof Error ? reason.message : tr("Unable to create question.", "无法创建题目。")); }
    finally { setBusy(false); }
  };

  const editQuestion = async (snapshot: EditableSnapshot) => {
    if (!selectedBankId || !selectedQuestion || busy) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const updated = await patchJson<QuestionDetail>(endpoint(apiRoot, `question-banks/${selectedBankId}/questions/${selectedQuestion.id}/`), {
        title: snapshot.title,
        definition: snapshot.content ?? {},
        metadata: normalizedMetadata(metadata),
      }, globalThis.crypto?.randomUUID?.());
      setSelectedQuestion(updated); setPanel(null); await loadQuestions(); await loadBanks(); setNotice(tr("Question updated.", "题目已更新。"));
    } catch (reason) { setError(reason instanceof Error ? reason.message : tr("Unable to update question.", "无法更新题目。")); }
    finally { setBusy(false); }
  };

  const copyQuestion = async (question: QuestionSummary) => {
    if (!selectedBankId || busy) return;
    const title = window.prompt(tr("Title for the copy", "副本标题"), `${tr("Copy of", "副本：")} ${question.title}`);
    if (title === null) return;
    setBusy(true); setError(""); setNotice("");
    try {
      await postJson(endpoint(apiRoot, `question-banks/${selectedBankId}/questions/${question.id}/copy/`), { title: title.trim() || question.title, target_bank_id: selectedBankId }, globalThis.crypto?.randomUUID?.());
      await loadQuestions(); await loadBanks(); setNotice(tr("Question copied. The source remains unchanged.", "题目已复制，来源保持不变。"));
    } catch (reason) { setError(reason instanceof Error ? reason.message : tr("Unable to copy question.", "无法复制题目。")); }
    finally { setBusy(false); }
  };

  const removeBank = async () => {
    if (!selectedBankId || busy) return;
    const bank = banks.find((item) => item.id === selectedBankId);
    if (!bank || !window.confirm(tr(`Delete “${bank.title}”? Questions will remain reusable.`, `删除“${bank.title}”吗？题目仍会保留。`))) return;
    setBusy(true); setError("");
    try { await deleteJson(endpoint(apiRoot, `question-banks/${selectedBankId}/`), globalThis.crypto?.randomUUID?.()); await loadBanks(); setSelectedQuestion(null); setNotice(tr("Bank deleted; questions remain.", "题库已删除，题目仍然保留。")); }
    catch (reason) { setError(reason instanceof Error ? reason.message : tr("Unable to delete bank.", "无法删除题库。")); }
    finally { setBusy(false); }
  };

  const editorInitial = selectedQuestion ? { title: selectedQuestion.title, type_key: selectedQuestion.type_key, content: selectedQuestion.definition } : undefined;
  const selectedBank = useMemo(() => banks.find((bank) => bank.id === selectedBankId) ?? null, [banks, selectedBankId]);

  return (
    <section className="lc-question-bank-workspace" aria-label={tr("Question bank workspace", "题库工作区")}>
      <header className="lc-question-bank-header">
        <div><p className="lc-kicker">{tr("Reusable questions", "可复用题目")}</p><h2>{tr("Question bank workspace", "题库工作区")}</h2></div>
        <div className="lc-actions"><button type="button" className="lc-btn-sm lc-btn-primary" onClick={() => { setPanel("question"); setMetadata(metadataFrom()); }}>{tr("Create question", "创建题目")}</button><button type="button" className="lc-btn-sm lc-btn-outline" onClick={() => setPanel("bank")}>{tr("Create bank", "创建题库")}</button></div>
      </header>
      {error ? <p className="lc-form-error" role="alert">{error}</p> : null}
      {notice ? <p className="lc-builder-status lc-builder-status-success" role="status">{notice}</p> : null}
      <div className="lc-question-bank-layout">
        <aside className="lc-card lc-question-bank-list" aria-label={tr("Question banks", "题库列表")}>
          <h3>{tr("Question banks", "题库")}</h3>
          {loading ? <p>{tr("Loading…", "加载中…")}</p> : banks.length ? <ul>{banks.map((bank) => <li key={bank.id}><button type="button" className={bank.id === selectedBankId ? "lc-question-bank-item lc-question-bank-item-selected" : "lc-question-bank-item"} onClick={() => { setSelectedBankId(bank.id); setSelectedQuestion(null); }}>{bank.title}<span>{bank.question_count}</span></button></li>)}</ul> : <p className="lc-empty-notice">{tr("No banks yet. Create one or create an independent question.", "还没有题库。可以创建题库或独立题目。")}</p>}
          {selectedBank ? <button type="button" className="lc-btn-sm lc-btn-danger" onClick={() => void removeBank()} disabled={busy}>{tr("Delete bank", "删除题库")}</button> : null}
        </aside>
        <div className="lc-question-bank-main">
          {selectedBankId ? <div className="lc-card lc-question-filters"><div className="lc-form-row"><label>{tr("Search", "搜索")}<input className="lc-input" value={query} onChange={(event) => setQuery(event.target.value)} placeholder={tr("Title or prompt", "标题或题干")} /></label><label>{tr("Tag", "标签")}<input className="lc-input" value={tag} onChange={(event) => setTag(event.target.value)} /></label><label>{tr("Topic", "主题")}<input className="lc-input" value={topic} onChange={(event) => setTopic(event.target.value)} /></label><label>{tr("Difficulty", "难度")}<select className="lc-select" value={difficulty} onChange={(event) => setDifficulty(event.target.value)}><option value="">{tr("Any", "不限")}</option><option value="easy">{tr("Easy", "简单")}</option><option value="medium">{tr("Medium", "中等")}</option><option value="hard">{tr("Hard", "困难")}</option></select></label><label>{tr("Type", "类型")}<input className="lc-input" value={typeKey} onChange={(event) => setTypeKey(event.target.value)} placeholder="short_text" /></label></div></div> : null}
          {!selectedBankId ? <div className="lc-card lc-empty-notice"><p>{tr("Choose a bank to find questions, or create a question to begin.", "选择题库查找题目，或创建题目开始。")}</p></div> : questions.length ? <div className="lc-question-list">{questions.map((question) => <article className="lc-card lc-question-card" key={question.id}><div><h3>{question.title}</h3><p className="lc-workspace-meta">{question.type_key} · {metadataText(question.metadata.topic)} {tagsOf(question).map((item) => <span className="lc-badge" key={item}>{item}</span>)}</p></div><div className="lc-actions"><button type="button" className="lc-btn-sm lc-btn-outline" onClick={() => void selectQuestion(question)}>{tr("Preview", "预览")}</button>{picker && onPick ? <button type="button" className="lc-btn-sm lc-btn-primary" onClick={() => void pickQuestion(question)}>{pickerLabel ? tr(pickerLabel.en, pickerLabel.zh) : tr("Use in lesson", "用于教案")}</button> : null}<button type="button" className="lc-btn-sm lc-btn-outline" onClick={() => { void selectQuestion(question); setPanel("edit"); setMetadata(metadataFrom()); }}>{tr("Edit", "编辑")}</button><button type="button" className="lc-btn-sm lc-btn-outline" onClick={() => void copyQuestion(question)} disabled={busy}>{tr("Copy", "复制")}</button></div></article>)}</div> : <div className="lc-card lc-empty-notice"><p>{tr("No questions match these filters.", "没有符合筛选条件的题目。")}</p></div>}
          {selectedQuestion && panel !== "edit" ? <QuestionPreview question={selectedQuestion} /> : null}
          {panel === "bank" ? <section className="lc-card lc-question-editor"><h3>{tr("Create question bank", "创建题库")}</h3><form className="lc-form" onSubmit={(event) => void createBank(event)}><label>{tr("Title", "标题")}<input className="lc-input" required maxLength={200} value={bankTitle} onChange={(event) => setBankTitle(event.target.value)} /></label><div className="lc-actions"><button className="lc-btn-sm lc-btn-primary" disabled={busy}>{tr("Save", "保存")}</button><button type="button" className="lc-btn-sm lc-btn-outline" onClick={() => setPanel(null)}>{tr("Cancel", "取消")}</button></div></form></section> : null}
          {panel === "question" ? <section className="lc-card lc-question-editor"><h3>{tr("Create question", "创建题目")}</h3><MetadataFields metadata={metadata} onChange={setMetadata} /><ActivityEditor onSave={createQuestion} onCancel={() => setPanel(null)} /></section> : null}
          {panel === "edit" && selectedQuestion ? <section className="lc-card lc-question-editor"><h3>{tr("Edit question", "编辑题目")}</h3><MetadataFields metadata={metadata} onChange={setMetadata} /><ActivityEditor key={selectedQuestion.id} initial={editorInitial} onSave={editQuestion} onCancel={() => setPanel(null)} /></section> : null}
        </div>
      </div>
    </section>
  );
}
