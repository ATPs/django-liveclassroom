import * as React from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";

import { MarkdownView } from "../../activities/MarkdownView.js";
import { LanguageSwitcher, LocaleProvider, useLocale } from "../../i18n.js";
import { ApiError, getJson, patchJson, postJson, putJson } from "../../protocol.js";
import { QuestionBankWorkspace, type QuestionPickerSelection } from "../questions/QuestionBankWorkspace.js";
import { ManualGradingQueue } from "./ManualGradingQueue.js";
import { MarkdownImportPanel } from "./MarkdownImportPanel.js";
import { AssessmentResults } from "./AssessmentResults.js";
import { ContentSharingPanel } from "../sharing/ContentSharingPanel.js";

type AssessmentItem = {
  key: string;
  position: number;
  points: string;
  question_revision_id: number;
  definition_id: number;
  type_key: string;
  schema_version?: number;
  definition?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
};

type Assessment = {
  id: number;
  title: string;
  instructions: string;
  course_id?: number | null;
  version: number;
  settings: Record<string, unknown>;
  sections?: AssessmentSection[];
  items: AssessmentItem[];
  total_points: string;
  updated_at?: string;
};

type PresetMode = "practice" | "assignment" | "quiz" | "exam";

const PRESET_MODES: PresetMode[] = ["practice", "assignment", "quiz", "exam"];
const DEFAULT_RELEASE_POLICY = { scores: "manual", answers: "manual", explanations: "manual", comments: "manual" };

function localPresetSettings(mode: PresetMode, current: Record<string, unknown>): Record<string, unknown> {
  const next: Record<string, unknown> = { ...current, mode };
  if (mode === "practice") {
    Object.assign(next, { max_attempts: null, navigation: "free", scoring: false, release_policy: { scores: "after_submit", answers: "after_submit", explanations: "after_submit", comments: "after_submit" } });
    delete next.due_at; delete next.opens_at; delete next.closes_at; delete next.duration_seconds;
  } else if (mode === "assignment") {
    Object.assign(next, { max_attempts: 1, navigation: "free", scoring: true, release_policy: next.closes_at ? { scores: "after_close", answers: "after_close", explanations: "after_close", comments: "after_close" } : DEFAULT_RELEASE_POLICY });
    delete next.duration_seconds; delete next.opens_at;
  } else if (mode === "quiz") {
    Object.assign(next, { max_attempts: 1, navigation: "free", scoring: true, release_policy: DEFAULT_RELEASE_POLICY });
    delete next.due_at; delete next.opens_at; delete next.closes_at;
  } else {
    Object.assign(next, { max_attempts: 1, audience: "authenticated_link", navigation: "forward_only", scoring: true, release_policy: DEFAULT_RELEASE_POLICY });
  }
  return next;
}

function presetLabel(locale: string, mode: PresetMode): string {
  const labels: Record<PresetMode, [string, string]> = {
    practice: ["Practice", "练习"], assignment: ["Assignment", "作业"], quiz: ["Quiz", "测验"], exam: ["Exam", "考试"],
  };
  return locale.startsWith("zh") ? labels[mode][1] : labels[mode][0];
}

function dateInputValue(value: unknown): string {
  if (typeof value !== "string" || !value) return "";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "" : date.toISOString().slice(0, 16);
}

type Course = { id: number; title: string; can_manage?: boolean };
type QuestionBankSummary = { id: number; title: string };
type AssessmentSection = {
  key: string; title: string; position: number; shuffle_questions: boolean;
  entries: Array<{ key: string; kind: "fixed" | "pool"; item_key?: string; bank_id?: number; sample_size?: number; points?: string | null; shuffle_options?: boolean }>;
};
type CurrentQuestion = {
  id: number;
  title: string;
  type_key: string;
  definition: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  current_revision_id?: number | null;
};

type AssessmentBuilderProps = { apiRoot: string };

function endpoint(apiRoot: string, path: string): string {
  const base = new URL(apiRoot, window.location.href);
  if (!base.pathname.endsWith("/")) base.pathname += "/";
  return new URL(path.replace(/^\/+/, ""), base).toString();
}

function normalizeApiRoot(value: string): string {
  const base = new URL(value, window.location.href);
  base.pathname = base.pathname.replace(/workspace\/?$/, "");
  if (!base.pathname.endsWith("/")) base.pathname += "/";
  base.search = "";
  base.hash = "";
  return base.toString();
}

function tr(locale: string, en: string, zh: string): string {
  return locale.startsWith("zh") ? zh : en;
}

function requestKey(prefix: string): string {
  const id = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return `assessment-${prefix}-${id}`;
}

function asText(value: unknown): string {
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

function promptFor(item: AssessmentItem): string {
  const definition = item.definition ?? {};
  const value = definition.prompt ?? definition.stem_markdown ?? definition.markdown;
  return typeof value === "string" ? value : "";
}

function choicesFor(item: AssessmentItem): Array<{ id: string; text: string }> {
  const options = item.definition?.options;
  if (!Array.isArray(options)) return [];
  return options.map((option, index) => {
    if (option && typeof option === "object" && !Array.isArray(option)) {
      const value = option as Record<string, unknown>;
      return { id: asText(value.id) || String.fromCharCode(65 + index), text: asText(value.text ?? value.label) };
    }
    return { id: String.fromCharCode(65 + index), text: asText(option) };
  });
}

function fragmentUrl(apiRoot: string, revisionId: number, field = "prompt"): string {
  return endpoint(apiRoot, `activity-definitions/${revisionId}/fragments/${field}/`);
}

function itemFromQuestion(question: QuestionPickerSelection, revisionId?: number | null): AssessmentItem | null {
  const revision = revisionId ?? question.current_revision_id;
  if (!revision) return null;
  return {
    key: globalThis.crypto?.randomUUID?.() ?? `item-${Date.now()}-${Math.random().toString(36).slice(2)}`,
    position: 0,
    points: asText(question.metadata?.default_points) || "1",
    question_revision_id: revision,
    definition_id: question.id,
    type_key: question.type_key,
    schema_version: question.schema_version,
    definition: question.definition,
    metadata: question.metadata,
  };
}

function normalizeItems(items: AssessmentItem[]): AssessmentItem[] {
  return items.map((item, index) => ({ ...item, position: index + 1 }));
}

function QuestionPinnedPreview({ item, apiRoot, locale }: { item: AssessmentItem; apiRoot: string; locale: string }) {
  const prompt = promptFor(item);
  const choices = choicesFor(item);
  const answer = item.definition?.answer ?? item.definition?.correct_answer;
  const explanation = asText(item.definition?.explanation_markdown ?? item.definition?.explanation);
  const title = asText(item.definition?.title) || `${tr(locale, "Question", "题目")} ${item.position}`;
  return (
    <article className="lc-card lc-assessment-question-preview" data-pinned-revision={String(item.question_revision_id)}>
      <header className="lc-assessment-preview-heading">
        <div>
          <p className="lc-kicker">{tr(locale, "Pinned preview", "固定版本预览")}</p>
          <h3>{title}</h3>
        </div>
        <span className="lc-badge">v{item.question_revision_id}</span>
      </header>
      {prompt ? <MarkdownView markdown={prompt} fragment={{ url: fragmentUrl(apiRoot, item.question_revision_id) }} /> : null}
      {choices.length ? (
        <ol className="lc-assessment-choice-preview">
          {choices.map((choice) => <li key={choice.id}><strong>{choice.id}</strong> {choice.text}</li>)}
        </ol>
      ) : null}
      {answer !== undefined ? (
        <p className="lc-assessment-answer"><strong>{tr(locale, "Answer (teacher only)", "答案（仅教师可见）")}:</strong> {Array.isArray(answer) ? answer.map(String).join(", ") : String(answer)}</p>
      ) : <p className="lc-workspace-meta">{tr(locale, "No answer key; this item will be graded manually.", "没有答案；此题将由教师手动评分。")}</p>}
      {explanation ? <details><summary>{tr(locale, "Teacher explanation", "教师解释")}</summary><MarkdownView markdown={explanation} fragment={{ url: fragmentUrl(apiRoot, item.question_revision_id, "explanation") }} /></details> : null}
    </article>
  );
}

function AssessmentQuestionRow({
  item,
  index,
  itemCount,
  apiRoot,
  locale,
  current,
  onMove,
  onPoints,
  onRemove,
  onReplace,
}: {
  item: AssessmentItem;
  index: number;
  itemCount: number;
  apiRoot: string;
  locale: string;
  current?: CurrentQuestion;
  onMove: (index: number, offset: number) => void;
  onPoints: (key: string, points: string) => void;
  onRemove: (key: string) => void;
  onReplace: (key: string, question: CurrentQuestion) => void;
}) {
  const prompt = promptFor(item);
  const title = current?.title || `${tr(locale, "Question", "题目")} ${index + 1}`;
  const hasNewer = Boolean(current?.current_revision_id && current.current_revision_id !== item.question_revision_id);
  return (
    <li className="lc-card lc-assessment-item" data-assessment-item={item.key}>
      <div className="lc-assessment-item-heading">
        <span className="lc-assessment-item-number">{index + 1}</span>
        <div><h3>{title}</h3><p className="lc-workspace-meta">{item.type_key} · {tr(locale, "Pinned revision", "固定版本")} {item.question_revision_id}</p></div>
      </div>
      {prompt ? <p className="lc-assessment-item-prompt">{prompt}</p> : null}
      <div className="lc-assessment-item-controls">
        <label>{tr(locale, "Points", "分值")} <input aria-label={`${tr(locale, "Points for", "分值")} ${index + 1}`} className="lc-input lc-assessment-points" inputMode="decimal" min="0.000001" max="1000" step="any" value={item.points} onChange={(event) => onPoints(item.key, event.target.value)} /></label>
        <div className="lc-actions">
          <button type="button" className="lc-btn-sm lc-btn-outline" onClick={() => onMove(index, -1)} disabled={index === 0}>{tr(locale, "Move up", "上移")}</button>
          <button type="button" className="lc-btn-sm lc-btn-outline" onClick={() => onMove(index, 1)} disabled={index === itemCount - 1}>{tr(locale, "Move down", "下移")}</button>
          {hasNewer && current ? <button type="button" className="lc-btn-sm lc-btn-outline" onClick={() => onReplace(item.key, current)}>{tr(locale, "Replace with current", "替换为当前版本")}</button> : null}
          <button type="button" className="lc-btn-sm lc-btn-danger" onClick={() => onRemove(item.key)}>{tr(locale, "Remove", "移除")}</button>
        </div>
      </div>
    </li>
  );
}

function AssessmentBuilder({ apiRoot }: AssessmentBuilderProps) {
  const locale = useLocale();
  const text = useCallback((en: string, zh: string) => tr(locale, en, zh), [locale]);
  const [assessments, setAssessments] = useState<Assessment[]>([]);
  const [courses, setCourses] = useState<Course[]>([]);
  const [banks, setBanks] = useState<QuestionBankSummary[]>([]);
  const [sections, setSections] = useState<AssessmentSection[]>([]);
  const [sectionsSaving, setSectionsSaving] = useState(false);
  const [currentQuestions, setCurrentQuestions] = useState<Record<number, CurrentQuestion>>({});
  const [draft, setDraft] = useState<Assessment | null>(null);
  const [showPicker, setShowPicker] = useState(false);
  const [showPreview, setShowPreview] = useState(false);
  const [itemsDirty, setItemsDirty] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [conflict, setConflict] = useState(false);
  const [presetSaving, setPresetSaving] = useState(false);
  const [publishing, setPublishing] = useState(false);

  const load = useCallback(async () => {
    const [assessmentData, workspaceData, questionData, bankData] = await Promise.all([
      getJson<{ assessments: Assessment[] }>(endpoint(apiRoot, "assessments/")),
      getJson<{ courses?: Course[] }>(endpoint(apiRoot, "workspace/")),
      getJson<{ activities?: CurrentQuestion[] }>(endpoint(apiRoot, "activity-definitions/")),
      getJson<{ question_banks?: QuestionBankSummary[] }>(endpoint(apiRoot, "question-banks/")),
    ]);
    setAssessments(assessmentData.assessments ?? []);
    setCourses(workspaceData.courses ?? []);
    setBanks(bankData.question_banks ?? []);
    const questionMap: Record<number, CurrentQuestion> = {};
    for (const question of questionData.activities ?? []) questionMap[question.id] = question;
    setCurrentQuestions(questionMap);
  }, [apiRoot]);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    void load().catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : text("Unable to load assessments.", "无法加载测验。")); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [load, text]);

  const open = async (assessment: Assessment) => {
    setError(""); setNotice(""); setConflict(false); setShowPreview(false); setShowPicker(false);
    try {
      const detail = await getJson<Assessment>(endpoint(apiRoot, `assessments/${assessment.id}/`));
      setDraft({ ...detail, items: normalizeItems(detail.items ?? []) });
      const sectionData = await getJson<{ sections: AssessmentSection[] }>(endpoint(apiRoot, `assessments/${assessment.id}/sections/`));
      setSections(sectionData.sections ?? []);
      setItemsDirty(false);
    } catch (reason) { setError(reason instanceof Error ? reason.message : text("Unable to open assessment.", "无法打开测验。")); }
  };

  const create = () => {
    setDraft({ id: 0, title: "", instructions: "", course_id: null, version: 1, settings: localPresetSettings("quiz", { max_attempts: 1 }), items: [], total_points: "0" });
    setSections([]); setItemsDirty(true); setShowPreview(false); setShowPicker(false); setError(""); setNotice(""); setConflict(false);
  };

  const savedMode = draft?.settings.mode;
  const selectedMode: PresetMode = typeof savedMode === "string" && PRESET_MODES.includes(savedMode as PresetMode) ? savedMode as PresetMode : "quiz";

  const choosePreset = async (mode: PresetMode) => {
    if (!draft || presetSaving || mode === selectedMode) return;
    if (!draft.id) {
      setDraft({ ...draft, settings: localPresetSettings(mode, draft.settings) });
      return;
    }
    setPresetSaving(true); setError(""); setNotice("");
    try {
      const saved = await postJson<Assessment>(endpoint(apiRoot, `assessments/${draft.id}/preset/`), { mode, expected_version: draft.version }, requestKey("preset"));
      setDraft({ ...saved, items: normalizeItems(saved.items ?? []) });
      setAssessments((previous) => [saved, ...previous.filter((item) => item.id !== saved.id)]);
      setNotice(text(`${presetLabel(locale, mode)} preset saved.`, `${presetLabel(locale, mode)}模式已保存。`));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : text("Preset could not be saved.", "无法保存模式。"));
    } finally { setPresetSaving(false); }
  };

  const updateSetting = (key: string, value: unknown) => {
    if (!draft) return;
    setDraft({ ...draft, settings: { ...draft.settings, [key]: value } });
  };

  const saveSections = async () => {
    if (!draft?.id || sectionsSaving) return;
    setSectionsSaving(true); setError("");
    try {
      const saved = await putJson<Assessment>(endpoint(apiRoot, `assessments/${draft.id}/sections/`), {
        expected_version: draft.version, sections,
      }, requestKey("sections"));
      setDraft({ ...saved, items: normalizeItems(saved.items ?? []) });
      setSections((saved as Assessment & { sections?: AssessmentSection[] }).sections ?? sections);
      setAssessments((previous) => [saved, ...previous.filter((item) => item.id !== saved.id)]);
      setNotice(text("Section plan saved.", "题目分组已保存。"));
    } catch (reason) { setError(reason instanceof Error ? reason.message : text("Section plan could not be saved.", "无法保存题目分组。")); }
    finally { setSectionsSaving(false); }
  };

  const addPool = () => {
    if (!sections.length || !banks.length) { setError(text("Create a question bank before adding a random pool.", "请先创建题库，再添加随机题池。")); return; }
    const first = sections[0];
    setSections([{ ...first, entries: [...first.entries, { key: globalThis.crypto?.randomUUID?.() ?? `pool-${Date.now()}`, kind: "pool", bank_id: banks[0].id, sample_size: 1, points: "1", shuffle_options: false }] }, ...sections.slice(1)]);
  };

  const publish = async () => {
    if (!draft?.id || publishing || saving) {
      if (draft && !draft.id) setError(text("Save the assessment before publishing.", "发布前请先保存测验。"));
      return;
    }
    setPublishing(true); setError(""); setNotice("");
    try {
      await postJson(endpoint(apiRoot, `assessments/${draft.id}/runs/`), { expected_version: draft.version }, requestKey("publish"));
      setNotice(text("Assessment published. The run uses this saved version.", "测验已发布，运行使用当前保存版本。"));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : text("Publishing failed.", "发布失败。"));
    } finally { setPublishing(false); }
  };

  const addQuestion = async (definitionId: number, revisionId?: number | null, question?: QuestionPickerSelection) => {
    if (!draft || !question) return;
    const item = itemFromQuestion(question, revisionId);
    if (!item) { setError(text("This question has no current revision.", "此题没有当前版本。")); return; }
    if (draft.items.some((existing) => existing.definition_id === definitionId && existing.question_revision_id === item.question_revision_id)) {
      setNotice(text("That pinned revision is already selected.", "此固定版本已经选中。"));
      return;
    }
    setDraft((previous) => previous ? { ...previous, items: normalizeItems([...previous.items, item]), total_points: String(Number(previous.total_points || 0) + Number(item.points || 0)) } : previous);
    setItemsDirty(true); setShowPicker(false); setNotice(text("Question added. Its current revision is pinned when you save.", "题目已添加。保存时会固定当前版本。"));
  };

  const move = (index: number, offset: number) => {
    if (!draft) return;
    const next = index + offset;
    if (next < 0 || next >= draft.items.length) return;
    const items = [...draft.items];
    [items[index], items[next]] = [items[next], items[index]];
    setDraft({ ...draft, items: normalizeItems(items) }); setItemsDirty(true);
  };

  const points = (key: string, value: string) => {
    if (!draft) return;
    setDraft({ ...draft, items: draft.items.map((item) => item.key === key ? { ...item, points: value } : item) }); setItemsDirty(true);
  };

  const remove = (key: string) => {
    if (!draft) return;
    setDraft({ ...draft, items: normalizeItems(draft.items.filter((item) => item.key !== key)) }); setItemsDirty(true);
  };

  const replace = (key: string, question: CurrentQuestion) => {
    if (!draft || !question.current_revision_id) return;
    setDraft({ ...draft, items: draft.items.map((item) => item.key === key ? {
      ...item,
      question_revision_id: question.current_revision_id as number,
      definition_id: question.id,
      type_key: question.type_key,
      definition: question.definition,
      metadata: question.metadata,
      schema_version: item.schema_version,
    } : item) });
    setItemsDirty(true); setNotice(text("The current revision will replace the pinned one after saving.", "保存后将用当前版本替换固定版本。"));
  };

  const save = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!draft || saving) return;
    if (!draft.title.trim()) { setError(text("An assessment title is required.", "请填写测验标题。")); return; }
    if (draft.items.some((item) => !/^\d+(?:\.\d{1,6})?$/.test(item.points.trim()) || Number(item.points) <= 0 || Number(item.points) > 1000)) {
      setError(text("Points must be positive numbers up to 1000 with at most six decimals.", "分值必须是大于零且不超过1000的数字，最多六位小数。")); return;
    }
    setSaving(true); setError(""); setNotice(""); setConflict(false);
    let acknowledgedVersion: number | null = null;
    try {
      const body = {
        title: draft.title.trim(),
        instructions: draft.instructions,
        course_id: draft.course_id,
        settings: draft.settings,
      };
      let saved: Assessment;
      if (!draft.id) {
        saved = await postJson<Assessment>(endpoint(apiRoot, "assessments/"), {
          ...body,
          items: draft.items.map(({ key, question_revision_id, points }) => ({ key, revision_id: question_revision_id, points })),
        }, requestKey("create"));
      } else {
        saved = await patchJson<Assessment>(endpoint(apiRoot, `assessments/${draft.id}/`), { ...body, expected_version: draft.version }, requestKey("update"));
        acknowledgedVersion = saved.version;
        if (itemsDirty) {
          saved = await putJson<Assessment>(endpoint(apiRoot, `assessments/${draft.id}/items/`), {
            expected_version: saved.version,
            items: draft.items.map(({ key, question_revision_id, points }) => ({ key, revision_id: question_revision_id, points })),
          }, requestKey("items"));
        }
      }
      setDraft({ ...saved, items: normalizeItems(saved.items ?? []) }); setSections(saved.sections ?? sections); setItemsDirty(false); setShowPreview(false); setAssessments((previous) => [saved, ...previous.filter((item) => item.id !== saved.id)]); setNotice(text("Assessment saved.", "测验已保存。"));
    } catch (reason) {
      if (acknowledgedVersion !== null) {
        setDraft({ ...draft, version: acknowledgedVersion });
        setItemsDirty(true);
        setError(text("Details saved, but questions are still local. Retry to save them.", "详情已保存，但题目仍在本地。请重试保存。"));
      }
      else
      if (reason instanceof ApiError && reason.status === 409) { setConflict(true); setError(text("This assessment changed elsewhere. Reload it before saving.", "此测验已在其他地方更改。保存前请重新加载。")); }
      else setError(reason instanceof Error ? reason.message : text("Save failed; your draft is still here.", "保存失败；草稿仍然保留。"));
    } finally { setSaving(false); }
  };

  const copy = async () => {
    if (!draft?.id || saving) return;
    setSaving(true); setError("");
    try {
      const copied = await postJson<Assessment>(endpoint(apiRoot, `assessments/${draft.id}/copy/`), { title: `${draft.title} (${text("Copy", "副本")})`, mode: selectedMode }, requestKey("copy"));
      setDraft({ ...copied, items: normalizeItems(copied.items ?? []) }); setItemsDirty(false); await load(); setNotice(text("Assessment copied. The source remains unchanged.", "测验已复制，来源保持不变。"));
    } catch (reason) { setError(reason instanceof Error ? reason.message : text("Copy failed.", "复制失败。")); }
    finally { setSaving(false); }
  };

  const total = useMemo(() => (draft?.items ?? []).reduce((sum, item) => sum + (Number(item.points) || 0), 0), [draft?.items]);

  return (
    <div className="lc-assessment-root">
      <LanguageSwitcher />
      <header className="lc-builder-topbar">
        <div><p className="lc-kicker">{text("Independent assessment", "独立测验")}</p><h1>{text("Assessment builder", "测验编辑器")}</h1><p>{text("Build a reusable quiz, assignment, practice, or timed exam. Keep advanced delivery choices together in Settings.", "创建可复用的测验、作业、练习或限时考试。高级投递选项集中在“设置”中。")}</p></div>
        <button type="button" className="lc-btn lc-btn-primary" onClick={create}>{text("New assessment", "新建测验")}</button>
      </header>
      {error ? <p className="lc-form-error" role="alert">{error} {conflict ? <button type="button" className="lc-btn-sm lc-btn-outline" onClick={() => draft?.id ? void open(draft) : setConflict(false)}>{text("Reload", "重新加载")}</button> : null}</p> : null}
      {notice ? <p className="lc-builder-status lc-builder-status-success" role="status">{notice}</p> : null}
      <div className="lc-assessment-layout">
        <aside className="lc-card lc-assessment-list" aria-label={text("Assessments", "测验列表")}>
          <h2>{text("Your assessments", "我的测验")}</h2>
          {loading ? <p>{text("Loading…", "加载中…")}</p> : assessments.length ? <ul>{assessments.map((assessment) => <li key={assessment.id}><button type="button" className={draft?.id === assessment.id ? "lc-assessment-list-item lc-assessment-selected" : "lc-assessment-list-item"} onClick={() => void open(assessment)}>{assessment.title}<span>{assessment.total_points} {text("points", "分")}</span></button></li>)}</ul> : <p className="lc-empty-notice">{text("No assessments yet. Create one to begin.", "还没有测验。创建一个开始吧。")}</p>}
        </aside>
        <main className="lc-assessment-main">
          {!draft ? <section className="lc-card lc-assessment-empty"><h2>{text("Create a reusable assessment", "创建可复用测验")}</h2><p>{text("Choose New assessment, then add questions from a bank.", "选择“新建测验”，然后从题库添加题目。")}</p></section> : (
            <>
              <form className="lc-card lc-assessment-form" onSubmit={save}>
                <div className="lc-assessment-form-heading"><div><label htmlFor="assessment-title">{text("Title", "标题")}</label><input id="assessment-title" className="lc-input" value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} maxLength={200} required /></div><p className="lc-workspace-meta">{itemsDirty ? text("Unsaved changes", "有未保存的更改") : text("Saved draft", "已保存草稿")} · v{draft.version}</p></div>
                <label htmlFor="assessment-mode">{text("Mode", "模式")}</label>
                <select id="assessment-mode" className="lc-select" value={selectedMode} onChange={(event) => void choosePreset(event.target.value as PresetMode)} disabled={presetSaving}>
                  {PRESET_MODES.map((mode) => <option key={mode} value={mode}>{presetLabel(locale, mode)}</option>)}
                </select>
                <p className="lc-workspace-meta">{selectedMode === "practice" ? text("Unlimited practice keeps answers and completion without presenting missing scores as zero.", "练习不限次数，保留答案和完成状态，不会把缺失分数显示为零。") : selectedMode === "assignment" ? text("Assignments stop accepting answers only at closes at; due date is informational.", "作业仅在停止时间后停止接收答案；截止日期只作提示。") : selectedMode === "exam" ? text("Exam access uses authenticated accounts and needs a duration or explicit open and close times.", "考试需要登录，并需要时长或明确的开始和结束时间。") : text("Quiz settings keep result release manual by default.", "测验默认手动发布结果。")}</p>
                <details className="lc-assessment-settings"><summary>{text("Settings", "设置")}</summary>
                  <label htmlFor="assessment-attempts">{text("Maximum attempts (blank means unlimited)", "最大次数（空白表示不限）")}</label>
                  <input id="assessment-attempts" className="lc-input" type="number" min="1" step="1" value={draft.settings.max_attempts == null ? "" : String(draft.settings.max_attempts)} onChange={(event) => updateSetting("max_attempts", event.target.value ? Number(event.target.value) : null)} />
                  <label htmlFor="assessment-duration">{text("Duration in seconds (optional)", "时长（秒，可选）")}</label>
                  <input id="assessment-duration" className="lc-input" type="number" min="1" step="1" value={draft.settings.duration_seconds == null ? "" : String(draft.settings.duration_seconds)} onChange={(event) => updateSetting("duration_seconds", event.target.value ? Number(event.target.value) : undefined)} />
                  <label htmlFor="assessment-opens">{text("Open at (optional)", "开始时间（可选）")}</label>
                  <input id="assessment-opens" className="lc-input" type="datetime-local" value={dateInputValue(draft.settings.opens_at)} onChange={(event) => updateSetting("opens_at", event.target.value ? new Date(event.target.value).toISOString() : null)} />
                  <label htmlFor="assessment-due">{text("Due date (informational)", "截止日期（仅提示）")}</label>
                  <input id="assessment-due" className="lc-input" type="datetime-local" value={dateInputValue(draft.settings.due_at)} onChange={(event) => updateSetting("due_at", event.target.value ? new Date(event.target.value).toISOString() : null)} />
                  <label htmlFor="assessment-closes">{text("Stop accepting answers at", "停止接收答案时间")}</label>
                  <input id="assessment-closes" className="lc-input" type="datetime-local" value={dateInputValue(draft.settings.closes_at)} onChange={(event) => updateSetting("closes_at", event.target.value ? new Date(event.target.value).toISOString() : null)} />
                  <label htmlFor="assessment-audience">{text("Audience", "访问对象")}</label>
                  <select id="assessment-audience" className="lc-select" value={asText(draft.settings.audience) || "authenticated_link"} onChange={(event) => updateSetting("audience", event.target.value)}>
                    <option value="authenticated_link">{text("Any signed-in learner with the link", "持链接的任意已登录学生")}</option>
                    <option value="class">{text("Students in the selected class", "所选班级的学生")}</option>
                  </select>
                  <label htmlFor="assessment-navigation">{text("Question navigation", "题目导航")}</label>
                  <select id="assessment-navigation" className="lc-select" value={asText(draft.settings.navigation) || "free"} onChange={(event) => updateSetting("navigation", event.target.value)}>
                    <option value="free">{text("Free navigation", "自由导航")}</option>
                    <option value="forward_only">{text("Forward only", "仅可向前")}</option>
                  </select>
                  <label htmlFor="assessment-pass-percent">{text("Pass percent (optional)", "及格百分比（可选）")}</label>
                  <input id="assessment-pass-percent" className="lc-input" type="number" min="0" max="100" step="0.01" value={draft.settings.pass_percent == null ? "" : asText(draft.settings.pass_percent)} onChange={(event) => updateSetting("pass_percent", event.target.value || null)} />
                  <label><input type="checkbox" checked={draft.settings.scoring !== false} onChange={(event) => updateSetting("scoring", event.target.checked)} /> {text("Calculate a score", "计算得分")}</label>
                </details>
                {draft.id ? <details className="lc-assessment-settings"><summary>{text("Question order and random pools", "题目顺序与随机题池")}</summary>
                  <p className="lc-workspace-meta">{text("Fixed questions stay pinned. A pool samples from the selected bank independently for each learner.", "固定题目保持版本固定。题池会为每位学生从选中题库中独立抽题。")}</p>
                  {sections.map((section, sectionIndex) => <section key={section.key} className="lc-card">
                    <label>{text("Section title", "分组标题")}<input className="lc-input" value={section.title} onChange={(event) => setSections(sections.map((row, index) => index === sectionIndex ? { ...row, title: event.target.value } : row))} /></label>
                    <label><input type="checkbox" checked={section.shuffle_questions} onChange={(event) => setSections(sections.map((row, index) => index === sectionIndex ? { ...row, shuffle_questions: event.target.checked } : row))} /> {text("Randomize question order in this section", "随机排列本分组题目")}</label>
                    <ul>{section.entries.map((entry, entryIndex) => <li key={entry.key}>{entry.kind === "fixed" ? <label><input type="checkbox" checked={Boolean(entry.shuffle_options)} onChange={(event) => setSections(sections.map((row, index) => index !== sectionIndex ? row : { ...row, entries: row.entries.map((candidate, candidateIndex) => candidateIndex === entryIndex ? { ...candidate, shuffle_options: event.target.checked } : candidate) }))} /> {text("Shuffle options for fixed question", "随机排列固定题的选项")}</label> : <span>{text("Random pool", "随机题池")}: <select className="lc-select" value={entry.bank_id ?? ""} onChange={(event) => setSections(sections.map((row, index) => index !== sectionIndex ? row : { ...row, entries: row.entries.map((candidate, candidateIndex) => candidateIndex === entryIndex ? { ...candidate, bank_id: Number(event.target.value) } : candidate) }))}>{banks.map((bank) => <option key={bank.id} value={bank.id}>{bank.title}</option>)}</select> <label>{text("Questions", "题数")} <input className="lc-input" type="number" min="1" value={entry.sample_size ?? 1} onChange={(event) => setSections(sections.map((row, index) => index !== sectionIndex ? row : { ...row, entries: row.entries.map((candidate, candidateIndex) => candidateIndex === entryIndex ? { ...candidate, sample_size: Number(event.target.value) } : candidate) }))} /></label> <label>{text("Points each", "每题分值")} <input className="lc-input" inputMode="decimal" value={entry.points ?? ""} onChange={(event) => setSections(sections.map((row, index) => index !== sectionIndex ? row : { ...row, entries: row.entries.map((candidate, candidateIndex) => candidateIndex === entryIndex ? { ...candidate, points: event.target.value } : candidate) }))} /></label> <button type="button" className="lc-btn-sm lc-btn-danger" onClick={() => setSections(sections.map((row, index) => index !== sectionIndex ? row : { ...row, entries: row.entries.filter((_, candidateIndex) => candidateIndex !== entryIndex) }))}>{text("Remove pool", "移除题池")}</button></span>}</li>)}</ul>
                  </section>)}
                  <div className="lc-actions"><button type="button" className="lc-btn lc-btn-outline" onClick={addPool}>{text("Add random pool", "添加随机题池")}</button><button type="button" className="lc-btn lc-btn-primary" onClick={() => void saveSections()} disabled={sectionsSaving || !sections.length}>{sectionsSaving ? text("Saving…", "保存中…") : text("Save question plan", "保存题目计划")}</button></div>
                </details> : null}
                <label htmlFor="assessment-instructions">{text("Instructions", "说明")}</label><textarea id="assessment-instructions" className="lc-textarea" rows={4} maxLength={20000} value={draft.instructions} onChange={(event) => setDraft({ ...draft, instructions: event.target.value })} />
                <label htmlFor="assessment-course">{text("Class (optional)", "班级（可选）")}</label><select id="assessment-course" className="lc-select" value={draft.course_id ?? ""} onChange={(event) => setDraft({ ...draft, course_id: event.target.value ? Number(event.target.value) : null })}><option value="">{text("No class", "无班级")}</option>{courses.map((course) => <option key={course.id} value={String(course.id)}>{course.title}</option>)}</select>
                <div className="lc-actions"><button type="submit" className="lc-btn-primary" disabled={saving || presetSaving}>{saving ? text("Saving…", "保存中…") : text("Save draft", "保存草稿")}</button><button type="button" className="lc-btn-primary" onClick={() => void publish()} disabled={saving || publishing || !draft.items.length}>{publishing ? text("Publishing…", "发布中…") : text("Publish", "发布")}</button><button type="button" className="lc-btn-outline" onClick={() => setShowPicker((value) => !value)} disabled={saving}>{showPicker ? text("Hide question picker", "隐藏题目选择器") : text("Add questions", "添加题目")}</button><button type="button" className="lc-btn-outline" onClick={() => setShowPreview((value) => !value)} disabled={!draft.items.length}>{showPreview ? text("Hide preview", "隐藏预览") : text("Preview", "预览")}</button>{draft.id ? <button type="button" className="lc-btn-outline" onClick={() => void copy()} disabled={saving}>{text("Copy", "复制")}</button> : null}</div>
                <p className="lc-assessment-total" aria-live="polite"><strong>{text("Total", "总分")}:</strong> {Number.isInteger(total) ? total : total.toFixed(6).replace(/0+$/, "").replace(/\.$/, "")} {text("points", "分")}</p>
              </form>
              {showPicker ? <section className="lc-card lc-assessment-picker"><h2>{text("Add from question bank", "从题库添加")}</h2><p>{text("Selecting a question pins its current revision. Later edits will not change this assessment unless you choose Replace with current.", "选择题目时会固定当前版本。以后编辑题目不会改变此测验，除非选择“替换为当前版本”。")}</p><QuestionBankWorkspace apiRoot={apiRoot} picker onPick={addQuestion} pickerLabel={{ en: "Add to assessment", zh: "添加到测验" }} /></section> : null}
              <section className="lc-assessment-items" aria-labelledby="assessment-items-heading"><div className="lc-assessment-section-heading"><h2 id="assessment-items-heading">{text("Questions", "题目")}</h2><span>{draft.items.length}</span></div>{draft.items.length ? <ol>{draft.items.map((item, index) => <AssessmentQuestionRow key={item.key} item={item} index={index} itemCount={draft.items.length} apiRoot={apiRoot} locale={locale} current={currentQuestions[item.definition_id]} onMove={move} onPoints={points} onRemove={remove} onReplace={replace} />)}</ol> : <div className="lc-card lc-empty-notice"><p>{text("No questions selected yet. Open the question picker to add one.", "还没有选择题目。打开题目选择器添加题目。")}</p></div>}</section>
              {showPreview ? <section className="lc-assessment-preview" aria-labelledby="assessment-preview-heading"><h2 id="assessment-preview-heading">{text("Teacher preview", "教师预览")}</h2><p className="lc-guidance-risk">{text("This private preview uses the exact pinned revisions and includes answer keys only for you.", "此私有预览使用固定版本，仅向你显示答案。")}</p>{draft.items.map((item) => <QuestionPinnedPreview key={item.key} item={item} apiRoot={apiRoot} locale={locale} />)}</section> : null}
            </>
          )}
        </main>
      </div>
      <ManualGradingQueue apiRoot={apiRoot} />
      <AssessmentResults apiRoot={apiRoot} assessmentId={draft?.id ?? null} />
      <ContentSharingPanel apiRoot={apiRoot} kind="assessment" objectId={draft?.id ?? null} />
      <MarkdownImportPanel apiRoot={apiRoot} onImported={() => void load()} />
    </div>
  );
}

export function mountAssessmentBuilder(el: HTMLElement): void {
  const rawApiRoot = el.dataset.apiRoot;
  if (!rawApiRoot) return;
  const apiRoot = normalizeApiRoot(rawApiRoot);
  const locale = el.dataset.locale?.startsWith("zh") ? "zh-Hans" : "en";
  const root = createRoot(el);
  root.render(<LocaleProvider initial={locale} root={el}><AssessmentBuilder apiRoot={apiRoot} /></LocaleProvider>);
  el.addEventListener("liveclassroom:unmount", () => root.unmount(), { once: true });
}
