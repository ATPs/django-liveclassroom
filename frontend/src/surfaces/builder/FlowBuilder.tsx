import { ActivityEditor } from "../../activities/ActivityEditor.js";
import * as React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { deleteJson, getJson, postJson, putJson } from "../../protocol.js";
import { getLocale, type Locale, type TranslationKey } from "../../locales.js";
import { LanguageSwitcher, LocaleProvider, useLocale, useT } from "../../i18n.js";
import { mountAiChat } from "../../ai_chat.js";
import { FilePicker } from "../FilePicker.js";
import { QuestionBankWorkspace } from "../questions/QuestionBankWorkspace.js";

export type FlowSummary = {
  id: number;
  title: string;
  slug?: string;
  description?: string;
  course_id?: number | null;
  steps_count?: number;
  created_at?: string;
  updated_at?: string;
};

export type FlowStep = {
  id: number;
  position: number;
  kind: string;
  title: string;
  content?: Record<string, unknown> | null;
  activity_definition_id?: number | null;
  activity_definition?: {
    id: number;
    title: string;
    type_key: string;
    schema_version?: number;
    status?: string;
    definition: Record<string, unknown>;
  } | null;
  created_at?: string;
  updated_at?: string;
};

export type FlowDetail = FlowSummary & {
  token: string;
  demo?: boolean;
  can_edit?: boolean;
  steps: FlowStep[];
};

export type ActivityTypeInfo = {
  type_key: string;
  labelKey:
    | "singleChoice"
    | "multipleChoice"
    | "trueFalse"
    | "poll"
    | "shortText"
    | "essay"
    | "numeric"
    | "rating"
    | "ranking"
    | "wordCloud"
    | "bashSimulator"
    | "timer"
    | "markdownContent"
    | "mediaContent";
};

const ACTIVITY_TYPES: ActivityTypeInfo[] = [
  { type_key: "liveclassroom.single_choice", labelKey: "singleChoice" },
  { type_key: "liveclassroom.multiple_choice", labelKey: "multipleChoice" },
  { type_key: "liveclassroom.true_false", labelKey: "trueFalse" },
  { type_key: "liveclassroom.poll", labelKey: "poll" },
  { type_key: "liveclassroom.short_text", labelKey: "shortText" },
  { type_key: "liveclassroom.essay", labelKey: "essay" },
  { type_key: "liveclassroom.numeric", labelKey: "numeric" },
  { type_key: "liveclassroom.rating", labelKey: "rating" },
  { type_key: "liveclassroom.ranking", labelKey: "ranking" },
  { type_key: "liveclassroom.word_cloud", labelKey: "wordCloud" },
  { type_key: "liveclassroom.bash_simulator", labelKey: "bashSimulator" },
  { type_key: "liveclassroom.timer", labelKey: "timer" },
  { type_key: "liveclassroom.markdown", labelKey: "markdownContent" },
  { type_key: "liveclassroom.media", labelKey: "mediaContent" },
];

function typeName(typeKey: string, kind: string): TranslationKey | null {
  const info = ACTIVITY_TYPES.find((at) => at.type_key === typeKey);
  if (info) return info.labelKey;
  return kind === "markdown" ? "markdownContent" : null;
}

function StepPreview({ step }: { step: FlowStep }) {
  const t = useT();
  const definition: Record<string, unknown> =
    step.activity_definition?.definition ?? (step.content as Record<string, unknown> | undefined) ?? {};
  const promptText = (definition.prompt as string) || step.title || "";
  const typeKey = step.activity_definition?.type_key || step.kind;

  const choiceKinds = ["liveclassroom.single_choice", "liveclassroom.multiple_choice", "liveclassroom.poll", "liveclassroom.ranking"];
  const options = Array.isArray(definition.options) ? (definition.options as Array<Record<string, string>>) : [];
  const isMultiple = typeKey === "liveclassroom.multiple_choice";
  const isRanking = typeKey === "liveclassroom.ranking";
  const answerText = Array.isArray(definition.answer) ? (definition.answer as string[]).join(", ") : String(definition.answer ?? "");

  return (
    <div className="lc-builder-step-preview">
      <div className="lc-preview-header">
        <small>👁 {t("previewHeading")}</small>
      </div>
      {promptText ? <h4 className="lc-preview-prompt">{promptText}</h4> : null}
      {choiceKinds.includes(typeKey) ? (
        <>
          <div className="lc-preview-options-list">
            {options.map((opt, idx) => (
              <div key={idx} className="lc-preview-option-item">
                {isRanking ? (
                  `${idx + 1}. ${opt.text || opt.id}`
                ) : (
                  <>
                    <input type={isMultiple ? "checkbox" : "radio"} name={`preview-opt-${step.id}`} disabled />
                    <span>
                      {" "}
                      {opt.id ? `${opt.id}. ` : ""}
                      {opt.text || ""}
                    </span>
                  </>
                )}
              </div>
            ))}
          </div>
          {answerText ? <p className="lc-preview-answer">{t("correctAnswer")}: {answerText}</p> : null}
          {definition.explanation_markdown || definition.explanation ? (
            <p className="lc-preview-explanation">{t("explanation")}: {String(definition.explanation_markdown || definition.explanation)}</p>
          ) : null}
        </>
      ) : typeKey === "liveclassroom.true_false" ? (
        <>
          <div className="lc-preview-tf-row">
            <button type="button" disabled>{t("trueValue")}</button>
            <button type="button" disabled>{t("falseValue")}</button>
          </div>
          {answerText ? <p className="lc-preview-answer">{t("correctAnswer")}: {answerText}</p> : null}
        </>
      ) : typeKey === "liveclassroom.essay" ? (
        <textarea className="lc-preview-input lc-essay-preview" rows={4} placeholder={t("essayResponse")} disabled />
      ) : typeKey === "liveclassroom.short_text" || typeKey === "liveclassroom.word_cloud" ? (
        <input type="text" className="lc-preview-input" placeholder={typeKey === "liveclassroom.word_cloud" ? t("previewEnterWord") : t("previewEnterAnswer")} disabled />
      ) : typeKey === "liveclassroom.numeric" ? (
        <input
          type="number"
          className="lc-preview-input"
          disabled
          min={definition.minimum !== undefined ? String(definition.minimum) : undefined}
          max={definition.maximum !== undefined ? String(definition.maximum) : undefined}
          step={definition.step !== undefined ? String(definition.step) : undefined}
        />
      ) : typeKey === "liveclassroom.rating" ? (
        <div className="lc-preview-rating-row">
          {Array.from({ length: typeof definition.maximum === "number" ? definition.maximum : 5 }, (_, i) => (
            <button key={i} type="button" className="lc-rating-btn" disabled>
              {String(i + 1)}
            </button>
          ))}
        </div>
      ) : typeKey === "liveclassroom.bash_simulator" ? (
        <div className="lc-preview-bash-simulator">
          <code>pwd · ls · cd · cat · echo · help · clear · reset</code>
        </div>
      ) : typeKey === "liveclassroom.timer" ? (
        <div className="lc-preview-timer-box">
          ⏱ {(definition.label as string) || t("timer")}: {String(definition.duration_seconds ?? 60)}
          {t("seconds")}
        </div>
      ) : typeKey === "liveclassroom.markdown" || step.kind === "markdown" ? (
        <div className="lc-preview-markdown">{(definition.markdown as string) || ""}</div>
      ) : typeKey === "liveclassroom.media" ? (
        <div className="lc-preview-media">
          {(definition.media_type as string) === "image" ? (
            <img src={(definition.url as string) || ""} alt={(definition.caption as string) || "Preview image"} style={{ maxWidth: "100%", maxHeight: "16rem" }} />
          ) : (
            <a href={(definition.url as string) || ""} target="_blank" rel="noreferrer">
              🔗 Open {(definition.media_type as string) || "image"}: {String(definition.url || "")}
            </a>
          )}
          {definition.caption ? <p className="lc-preview-caption">{String(definition.caption)}</p> : null}
        </div>
      ) : null}
    </div>
  );
}

function StepCard({
  step,
  index,
  total,
  previewOpen,
  sessionId,
  editable,
  onMove,
  onTogglePreview,
  onDelete,
  onLaunch,
  onEdit,
}: {
  step: FlowStep;
  index: number;
  total: number;
  previewOpen: boolean;
  sessionId: number | null;
  editable: boolean;
  onMove: (index: number, direction: -1 | 1) => void;
  onTogglePreview: (id: number) => void;
  onDelete: (step: FlowStep) => void;
  onLaunch: (step: FlowStep) => void;
  onEdit: (step: FlowStep) => void;
}) {
  const t = useT();
  const typeKey = step.activity_definition?.type_key || step.kind;
  const labelKey = typeName(typeKey, step.kind);
  const name = labelKey ? t(labelKey) : typeKey;

  return (
    <div className="lc-builder-step-card" id={`step-card-${step.id}`}>
      <div className="lc-builder-step-header">
        <div className="lc-builder-step-title-area">
          <span className="lc-step-pos">#{step.position || index + 1}</span>
          <span className="lc-step-type-badge">{name}</span>
          <strong className="lc-step-name">{step.title || step.activity_definition?.title || name}</strong>
        </div>
        <div className="lc-builder-step-actions">
          {editable ? <>
            <button type="button" onClick={() => onEdit(step)}>{t("edit")}</button>
            <button type="button" className="lc-btn-icon" title={t("moveUp")} disabled={index === 0} onClick={() => onMove(index, -1)}>
              ↑
            </button>
            <button type="button" className="lc-btn-icon" title={t("moveDown")} disabled={index === total - 1} onClick={() => onMove(index, 1)}>
              ↓
            </button>
          </> : null}
          <button type="button" className={`lc-btn-sm ${previewOpen ? "lc-btn-primary" : "lc-btn-outline"}`} onClick={() => onTogglePreview(step.id)}>
            {previewOpen ? t("hidePreview") : t("showPreview")}
          </button>
          {sessionId && editable ? (
            <button type="button" className="lc-btn-sm lc-btn-secondary" onClick={() => onLaunch(step)}>
              🚀 {t("launchToClassroom")}
            </button>
          ) : null}
          {editable ? <button type="button" className="lc-btn-sm lc-btn-danger" onClick={() => onDelete(step)}>
            {t("removeStep")}
          </button> : null}
        </div>
      </div>
      {previewOpen ? <StepPreview step={step} /> : null}
    </div>
  );
}

function AddStepForm({
  flowId,
  apiUrl,
  initialDraft,
  onSaved,
  onCancel,
}: {
  flowId: number;
  apiUrl: (path: string) => string;
  initialDraft: string;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const t = useT();
  const [type, setType] = useState(ACTIVITY_TYPES[0].type_key);
  const [fields, setFields] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  const set = (key: string, value: string) => setFields((prev) => ({ ...prev, [key]: value }));
  const choiceIds = (fields.options ?? "").split("\n").map((line, index) =>
    line.trim() ? String.fromCharCode(65 + index) : ""
  ).filter(Boolean);
  const selectedAnswers = (fields.answer ?? "").split(/[, ]+/).filter(Boolean);
  const toggleAnswer = (id: string, checked: boolean) => {
    const next = checked
      ? [...selectedAnswers, id].filter((value, index, values) => values.indexOf(value) === index)
      : selectedAnswers.filter(value => value !== id);
    set("answer", next.join(", "));
  };

  useEffect(() => {
    if (initialDraft) {
      setFields((prev) => ({ ...prev, prompt: initialDraft, markdown: initialDraft }));
    }
  }, [initialDraft]);

  const submit = async () => {
    setError("");
    const title = (fields.title ?? "").trim();
    const prompt = (fields.prompt ?? "").trim();
    const isChoice = ["liveclassroom.single_choice", "liveclassroom.multiple_choice", "liveclassroom.poll", "liveclassroom.ranking"].includes(type);
    const isText = ["liveclassroom.short_text", "liveclassroom.word_cloud"].includes(type);
    const isEssay = type === "liveclassroom.essay";
    const isNum = type === "liveclassroom.numeric" || type === "liveclassroom.rating";
    const isBashSimulator = type === "liveclassroom.bash_simulator";

    if ((isChoice || isText || isEssay || isNum || isBashSimulator || type === "liveclassroom.true_false") && !prompt && !title) {
      setError(t("validationError"));
      return;
    }

    let payload: Record<string, unknown>;
    if (isChoice) {
      const lines = (fields.options ?? "").split("\n").map((l) => l.trim()).filter(Boolean);
      if (lines.length < 2) {
        setError(t("atLeastTwoOptions"));
        return;
      }
      const options = lines.map((text, idx) => {
        const id = String.fromCharCode(65 + idx);
        const cleaned = text.replace(/^[A-Z][.:]\s*/, "");
        return { id, text: cleaned || text };
      });
      const definition: Record<string, unknown> = { prompt: prompt || title, options };
      if ((fields.answer ?? "").trim()) {
        const rawAns = fields.answer.split(/[, ]+/).map((s) => s.trim().toUpperCase()).filter(Boolean);
        // Keep the single-choice shape identical to ActivityEditor and the
        // registry's canonical form. Multiple choice remains an ordered list.
        definition.answer = type === "liveclassroom.single_choice" ? rawAns[0] : rawAns;
      }
      if (type === "liveclassroom.multiple_choice") definition.partial_credit = fields.partialCredit === "true";
      if ((fields.explanation ?? "").trim()) definition.explanation_markdown = fields.explanation.trim();
      payload = { kind: "activity", title: title || prompt, activity_definition: { title: title || prompt, type_key: type, definition } };
    } else if (type === "liveclassroom.true_false") {
      payload = {
        kind: "activity",
        title: title || prompt,
        activity_definition: {
          title: title || prompt,
          type_key: type,
          definition: {
            prompt: prompt || title,
            options: [{ id: "true", text: t("trueValue") }, { id: "false", text: t("falseValue") }],
            ...((fields.answer ?? "").trim() ? { answer: fields.answer } : {}),
          },
        },
      };
    } else if (isEssay) {
      const maxLength = Number(fields.maxLength || "10000");
      if (!Number.isInteger(maxLength) || maxLength < 1 || maxLength > 50000) {
        setError(t("essayLengthInvalid"));
        return;
      }
      const definition: Record<string, unknown> = { prompt: prompt || title, max_length: maxLength };
      payload = { kind: "activity", title: title || prompt, activity_definition: { title: title || prompt, type_key: type, definition } };
    } else if (isText) {
      const definition: Record<string, unknown> = { prompt: prompt || title };
      if (type === "liveclassroom.short_text" && (fields.answer ?? "").trim()) {
        definition.answer = [...new Set(fields.answer.split("\n").map((value) => value.trim()).filter(Boolean))];
        definition.case_sensitive = fields.caseSensitive === "true";
      }
      if (type === "liveclassroom.word_cloud" && (fields.stopwords ?? "").trim()) {
        definition.stop_words = fields.stopwords.split(/[, ]+/).map((s) => s.trim()).filter(Boolean);
      }
      payload = { kind: "activity", title: title || prompt, activity_definition: { title: title || prompt, type_key: type, definition } };
    } else if (isNum) {
      const definition: Record<string, unknown> = { prompt: prompt || title };
      if (fields.min) definition.minimum = parseFloat(fields.min);
      if (fields.max) definition.maximum = parseFloat(fields.max);
      if (type === "liveclassroom.numeric" && (fields.answer ?? "").trim()) {
        definition.answer = fields.answer.trim();
        if ((fields.tolerance ?? "").trim()) definition.tolerance = fields.tolerance.trim();
      }
      payload = { kind: "activity", title: title || prompt, activity_definition: { title: title || prompt, type_key: type, definition } };
    } else if (isBashSimulator) {
      let filesystem: unknown;
      let completion: unknown;
      try {
        filesystem = JSON.parse(fields.filesystem || "{}");
        completion = JSON.parse(fields.completion || "{}");
      } catch {
        setError(t("bashSimulatorJsonError"));
        return;
      }
      if (!filesystem || typeof filesystem !== "object" || Array.isArray(filesystem) || !completion || typeof completion !== "object" || Array.isArray(completion)) {
        setError(t("bashSimulatorJsonError"));
        return;
      }
      const definition = {
        prompt: prompt || title,
        filesystem,
        initial_directory: (fields.initialDirectory ?? "").trim() || "/",
        completion,
      };
      payload = { kind: "activity", title: title || prompt, activity_definition: { title: title || prompt, type_key: type, definition } };
    } else if (type === "liveclassroom.timer") {
      const dur = parseFloat(fields.duration || "0");
      if (!dur || dur <= 0) {
        setError(t("durationPositive"));
        return;
      }
      payload = {
        kind: "activity",
        title: title || `${t("timer")} ${dur}${t("seconds")}`,
        activity_definition: { title: title || `${t("timer")} ${dur}${t("seconds")}`, type_key: type, definition: { duration_seconds: dur, label: title || t("timer") } },
      };
    } else if (type === "liveclassroom.markdown") {
      const md = (fields.markdown ?? "").trim();
      if (!md) {
        setError(t("markdownRequired"));
        return;
      }
      payload = { kind: "markdown", title: title || t("defaultLectureNote"), content: { markdown: md } };
    } else {
      const url = (fields.url ?? "").trim();
      if (!url) {
        setError(t("mediaUrlRequired"));
        return;
      }
      payload = {
        kind: "activity",
        title: title || t("defaultMediaPresentation"),
        activity_definition: {
          title: title || t("defaultMediaPresentation"),
          type_key: type,
          definition: { url, media_type: fields.mediaType || "image", caption: (fields.caption ?? "").trim() },
        },
      };
    }

    setSaving(true);
    try {
      await postJson(apiUrl(`flows/${flowId}/steps/`), payload);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("failedAddStep"));
      setSaving(false);
    }
  };

  const input = (key: string, extra: Record<string, unknown> = {}) => (
    <input className="lc-input" value={fields[key] ?? ""} onChange={(e) => set(key, e.target.value)} {...extra} />
  );
  const area = (key: string, rows: number, placeholder?: string) => (
    <textarea className="lc-textarea" rows={rows} placeholder={placeholder} value={fields[key] ?? ""} onChange={(e) => set(key, e.target.value)} />
  );

  return (
    <div className="lc-builder-step-form">
      <h4>{t("addStep")}</h4>
      {error ? <div className="lc-form-error">{error}</div> : null}
      <div className="lc-form-group">
        <label>{t("flowTitle")}: </label>
        {input("title", { placeholder: "e.g. Mendel's First Experiment" })}
      </div>
      <div className="lc-form-group">
        <label>{t("stepType")}: </label>
        <select className="lc-select" value={type} onChange={(e) => setType(e.target.value)}>
          {ACTIVITY_TYPES.map((at) => (
            <option key={at.type_key} value={at.type_key}>
              {t(at.labelKey)}
            </option>
          ))}
        </select>
      </div>
      <div className="lc-dynamic-fields">
        {(["liveclassroom.single_choice", "liveclassroom.multiple_choice", "liveclassroom.poll", "liveclassroom.ranking"].includes(type)) ? (
          <>
            <div className="lc-form-group">
              <label>{t("promptLabel")}: </label>
              {area("prompt", 2)}
            </div>
            <div className="lc-form-group">
              <label>{t("optionsLabel")}: </label>
              {area("options", 4, "Choice 1\nChoice 2\nChoice 3\nChoice 4")}
            </div>
            {type === "liveclassroom.single_choice" ? (
              <div className="lc-form-group">
                <label>{t("correctAnswer")}: </label>
                <select className="lc-select" value={fields.answer ?? ""} onChange={(e) => set("answer", e.target.value)}>
                  <option value="">{t("notGraded")}</option>
                  {choiceIds.map((id) => <option key={id} value={id}>{id}</option>)}
                </select>
              </div>
            ) : null}
            {type === "liveclassroom.multiple_choice" ? (
              <fieldset><legend>{t("correctAnswer")}</legend>
                {choiceIds.map((id) => <label key={id}><input type="checkbox" checked={selectedAnswers.includes(id)} onChange={(e) => toggleAnswer(id, e.target.checked)} /> {id}</label>)}
                <label><input type="checkbox" checked={fields.partialCredit === "true"} onChange={(e) => set("partialCredit", String(e.target.checked))} /> {t("partialCredit")}</label>
              </fieldset>
            ) : null}
            <div className="lc-form-group">
              <label>{t("explanation")}: </label>
              {area("explanation", 2)}
            </div>
          </>
        ) : type === "liveclassroom.true_false" ? (
          <>
            <div className="lc-form-group">
              <label>{t("promptLabel")}: </label>
              {area("prompt", 2)}
            </div>
            <div className="lc-form-group">
              <label>{t("correctAnswer")}: </label>
              <select className="lc-select" value={fields.answer ?? ""} onChange={(e) => set("answer", e.target.value)}>
                <option value="">{t("notGraded")}</option>
                <option value="true">{t("trueValue")}</option>
                <option value="false">{t("falseValue")}</option>
              </select>
            </div>
          </>
        ) : type === "liveclassroom.essay" ? (
          <>
            <div className="lc-form-group">
              <label>{t("promptLabel")}: </label>
              {area("prompt", 4)}
            </div>
            <div className="lc-form-group">
              <label>{t("maxLengthLabel")}: </label>
              {input("maxLength", { type: "number", min: 1, max: 50000, step: 1, value: fields.maxLength ?? "10000" })}
              <small>{t("manualGradingRequired")}</small>
            </div>
          </>
        ) : type === "liveclassroom.short_text" || type === "liveclassroom.word_cloud" ? (
          <>
            <div className="lc-form-group">
              <label>{t("promptLabel")}: </label>
              {area("prompt", 2)}
            </div>
            {type === "liveclassroom.word_cloud" ? (
              <div className="lc-form-group">
                <label>{t("stopWordsLabel")}: </label>
                {input("stopwords", { placeholder: "e.g. the, a, is" })}
              </div>
            ) : <>
              <div className="lc-form-group">
                <label>{t("acceptedAnswers")}: </label>
                {area("answer", 4)}
              </div>
              <label><input type="checkbox" checked={fields.caseSensitive === "true"} onChange={(e) => set("caseSensitive", String(e.target.checked))} disabled={!(fields.answer ?? "").trim()} /> {t("caseSensitive")}</label>
            </>}
          </>
        ) : type === "liveclassroom.numeric" || type === "liveclassroom.rating" ? (
          <>
            <div className="lc-form-group">
              <label>{t("promptLabel")}: </label>
              {area("prompt", 2)}
            </div>
            <div className="lc-form-row">
              <div className="lc-form-group">
                <label>{t("numericMinLabel")}: </label>
                <input type="number" className="lc-input" value={fields.min ?? (type === "liveclassroom.rating" ? "1" : "")} onChange={(e) => set("min", e.target.value)} />
              </div>
              <div className="lc-form-group">
                <label>{t("numericMaxLabel")}: </label>
                <input type="number" className="lc-input" value={fields.max ?? (type === "liveclassroom.rating" ? "5" : "")} onChange={(e) => set("max", e.target.value)} />
              </div>
            </div>
            {type === "liveclassroom.numeric" ? <div className="lc-form-row">
              <div className="lc-form-group"><label>{t("correctNumber")}: </label>{input("answer", { inputMode: "decimal" })}</div>
              <div className="lc-form-group"><label>{t("numericTolerance")}: </label>{input("tolerance", { type: "number", min: 0, step: "any", disabled: !(fields.answer ?? "").trim() })}</div>
            </div> : null}
          </>
        ) : type === "liveclassroom.bash_simulator" ? (
          <>
            <div className="lc-form-group">
              <label>{t("promptLabel")}: </label>
              {area("prompt", 2, "Guide the learner through the virtual shell")}
            </div>
            <div className="lc-form-group">
              <label>{t("bashSimulatorFilesystemLabel")}: </label>
              {area("filesystem", 8, '{"/README.txt":"Read this file"}')}
            </div>
            <div className="lc-form-group">
              <label>{t("bashSimulatorInitialDirectoryLabel")}: </label>
              {input("initialDirectory", { placeholder: "/" })}
            </div>
            <div className="lc-form-group">
              <label>{t("bashSimulatorCompletionLabel")}: </label>
              {area("completion", 4, '{"required_commands":["pwd"]}')}
            </div>
          </>
        ) : type === "liveclassroom.timer" ? (
          <div className="lc-form-group">
            <label>{t("durationSecondsLabel")}: </label>
            <input type="number" className="lc-input" value={fields.duration ?? "60"} onChange={(e) => set("duration", e.target.value)} />
          </div>
        ) : type === "liveclassroom.markdown" ? (
          <div className="lc-form-group">
            <label>{t("markdownContentLabel")}: </label>
            {area("markdown", 6)}
          </div>
        ) : (
          <>
            <div className="lc-form-group">
              <label>{t("mediaUrlLabel")}: </label>
              {input("url", { type: "url" })}
            </div>
            <div className="lc-form-group">
              <label>{t("mediaTypeLabel")}: </label>
              <select className="lc-select" value={fields.mediaType ?? "image"} onChange={(e) => set("mediaType", e.target.value)}>
                <option value="image">{t("imageType")}</option>
                <option value="video">{t("videoType")}</option>
                <option value="audio">{t("audioType")}</option>
              </select>
            </div>
            <div className="lc-form-group">
              <label>{t("captionLabel")}: </label>
              {input("caption")}
            </div>
          </>
        )}
      </div>
      <div className="lc-form-btn-row">
        <button type="button" className="lc-btn-sm lc-btn-primary" disabled={saving} onClick={() => void submit()}>
          {t("saveStep")}
        </button>
        <button type="button" className="lc-btn-sm lc-btn-outline" onClick={onCancel}>
          {t("cancelStep")}
        </button>
      </div>
    </div>
  );
}

function ImportModal({ apiUrl, onImported, onClose }: { apiUrl: (p: string) => string; onImported: () => void; onClose: () => void }) {
  const t = useT();
  const [format, setFormat] = useState("");
  const [source, setSource] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const doImport = async () => {
    const text = source.trim();
    if (!text) {
      setError(t("pasteContent"));
      return;
    }
    setBusy(true);
    try {
      const body: Record<string, unknown> = { source: text };
      if (format) body.format = format;
      await postJson(apiUrl("flows/import/"), body);
      onImported();
    } catch (err) {
      setBusy(false);
      setError(`${t("importError")} ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  return (
    <div className="lc-modal-overlay" id="lc-import-modal" onClick={onClose}>
      <div className="lc-modal" onClick={(e) => e.stopPropagation()}>
        <h3>{t("importContent")}</h3>
        {error ? <div className="lc-form-error">{error}</div> : null}
        <div className="lc-form-group">
          <label>{t("formatLabel")}: </label>
          <select className="lc-select" value={format} onChange={(e) => setFormat(e.target.value)}>
            <option value="">{t("autoDetect")}</option>
            <option value="json">JSON</option>
            <option value="markdown">Markdown / YAML</option>
          </select>
        </div>
        <div className="lc-form-group">
          <textarea className="lc-textarea" rows={8} placeholder={t("importPlaceholder")} value={source} onChange={(e) => setSource(e.target.value)} />
        </div>
        <div className="lc-modal-actions">
          <button type="button" className="lc-btn-sm lc-btn-primary" disabled={busy} onClick={() => void doImport()}>
            {t("importButton")}
          </button>
          <button type="button" className="lc-btn-sm lc-btn-outline" onClick={onClose}>
            {t("cancel")}
          </button>
        </div>
      </div>
    </div>
  );
}

function FlowBuilder({
  flowsUrl,
  sessionId,
  initialFlowId,
  isSuperuser,
}: {
  flowsUrl: string;
  sessionId: number | null;
  initialFlowId: number | null;
  isSuperuser: boolean;
}) {
  const t = useT();
  const locale = useLocale();
  const apiRoot = new URL("../", new URL(flowsUrl, window.location.href)).toString();
  const apiUrl = useCallback((path: string) => new URL(path.replace(/^\/+/, ""), new URL(apiRoot, window.location.href)).toString(), [apiRoot]);

  const [flows, setFlows] = useState<FlowSummary[]>([]);
  const [currentFlow, setCurrentFlow] = useState<FlowDetail | null>(null);
  const [previewOpen, setPreviewOpen] = useState<Set<number>>(new Set());
  const [editingStep, setEditingStep] = useState<FlowStep | null>(null);
  const [addStepOpen, setAddStepOpen] = useState(false);
  const [aiSidebarOpen, setAiSidebarOpen] = useState(true);
  const [status, setStatus] = useState<{ msg: string; error: boolean } | null>(null);
  const [importOpen, setImportOpen] = useState(false);
  const [draftPrompt, setDraftPrompt] = useState("");
  const [questionPickerOpen, setQuestionPickerOpen] = useState(false);

  const currentFlowRef = useRef<FlowDetail | null>(null);
  currentFlowRef.current = currentFlow;
  const sidebarRef = useRef<HTMLDivElement>(null);
  const flowSelectRef = useRef<HTMLSelectElement>(null);

  const showStatus = useCallback((msg: string, error = false) => {
    setStatus({ msg, error });
    window.setTimeout(() => setStatus((s) => (s && s.msg === msg ? null : s)), 4000);
  }, []);

  const loadFlow = useCallback(async (flowId: number) => {
    try {
      const data = await getJson<FlowDetail>(apiUrl(`flows/${flowId}/`));
      setCurrentFlow(data);
    } catch (err) {
      showStatus(err instanceof Error ? err.message : t("failedLoadFlowDetails"), true);
    }
  }, [apiUrl, showStatus]);

  const loadFlows = useCallback(async () => {
    try {
      const data = await getJson<{ flows: FlowSummary[] }>(apiUrl("flows/"));
      const list = data.flows ?? [];
      setFlows(list);
      if (list.length > 0) {
        await loadFlow(list[0].id);
      } else {
        setCurrentFlow(null);
      }
    } catch (err) {
      showStatus(err instanceof Error ? err.message : t("failedLoadFlows"), true);
    }
  }, [apiUrl, loadFlow, showStatus]);

  useEffect(() => {
    if (initialFlowId) void loadFlow(initialFlowId);
    else void loadFlows();
  }, [initialFlowId, loadFlow, loadFlows]);

  useEffect(() => {
    if (!sidebarRef.current) return;
    const widget = mountAiChat(sidebarRef.current, {
      locale,
      apiRoot,
      getAttachment: () => {
        const f = currentFlowRef.current;
        return f ? { source_type: "flow", source_id: f.id, title: f.title } : null;
      },
      onInsertDraft: (draftText) => {
        setDraftPrompt(draftText);
        setAddStepOpen(true);
      },
    });
    return () => widget.unmount();
  }, [locale, apiRoot]);

  const createFlow = async () => {
    const title = window.prompt(t("newFlowPrompt"), t("defaultLessonFlow"));
    if (!title || !title.trim()) return;
    try {
      const created = await postJson<FlowSummary>(apiUrl("flows/"), { title: title.trim() });
      showStatus(t("flowUpdated"));
      await loadFlows();
      await loadFlow(created.id);
    } catch (err) {
      showStatus(err instanceof Error ? err.message : t("failedCreateFlow"), true);
    }
  };

  const duplicateFlow = async () => {
    if (!currentFlow) return;
    const title = window.prompt(t("duplicateFlowPrompt"), `${t("copiedFlowPrefix")} ${currentFlow.title}`);
    if (title === null) return;
    try {
      const payload: Record<string, unknown> = {};
      if (title.trim()) payload.title = title.trim();
      const duplicated = await postJson<FlowDetail>(apiUrl(`flows/${currentFlow.id}/duplicate/`), payload);
      showStatus(t("flowUpdated"));
      await loadFlows();
      await loadFlow(duplicated.id);
    } catch (err) {
      showStatus(err instanceof Error ? err.message : t("failedDuplicateFlow"), true);
    }
  };

  const saveSessionAsFlow = async () => {
    if (!sessionId) return;
    const title = window.prompt(t("saveAsFlowPrompt"), t("defaultClassroomFlow"));
    if (!title || !title.trim()) return;
    try {
      const flow = await postJson<FlowDetail>(apiUrl(`sessions/${sessionId}/save-flow/`), { title: title.trim() });
      showStatus(t("flowUpdated"));
      await loadFlows();
      await loadFlow(flow.id);
    } catch (err) {
      showStatus(err instanceof Error ? err.message : t("failedSaveSessionFlow"), true);
    }
  };

  const addQuestionFromBank = async (definitionId: number) => {
    if (!currentFlow) return;
    try {
      await postJson(apiUrl(`flows/${currentFlow.id}/steps/`), { activity_definition_id: definitionId }, globalThis.crypto?.randomUUID?.());
      setQuestionPickerOpen(false);
      showStatus(locale.startsWith("zh") ? "题目已加入教案。" : "Question added to lesson.");
      await loadFlow(currentFlow.id);
    } catch (err) {
      showStatus(err instanceof Error ? err.message : (locale.startsWith("zh") ? "无法加入题目。" : "Unable to add question."), true);
    }
  };

  const moveStep = async (index: number, direction: -1 | 1) => {
    if (!currentFlow) return;
    const targetIndex = index + direction;
    if (targetIndex < 0 || targetIndex >= currentFlow.steps.length) return;
    const newSteps = [...currentFlow.steps];
    const [moved] = newSteps.splice(index, 1);
    newSteps.splice(targetIndex, 0, moved);
    try {
      const res = await putJson<{ steps: FlowStep[] }>(apiUrl(`flows/${currentFlow.id}/steps/reorder/`), { step_ids: newSteps.map((s) => s.id) });
      setCurrentFlow({ ...currentFlow, steps: res.steps });
      showStatus(t("stepsReordered"));
    } catch (err) {
      showStatus(err instanceof Error ? err.message : t("failedReorderSteps"), true);
    }
  };

  const deleteStep = async (step: FlowStep) => {
    if (!currentFlow) return;
    if (!window.confirm(t("confirmDeleteStep"))) return;
    try {
      await deleteJson<{ deleted: boolean }>(apiUrl(`flows/${currentFlow.id}/steps/${step.id}/`));
      setCurrentFlow({ ...currentFlow, steps: currentFlow.steps.filter((s) => s.id !== step.id) });
      setPreviewOpen((prev) => {
        const next = new Set(prev);
        next.delete(step.id);
        return next;
      });
      showStatus(t("stepDeleted"));
    } catch (err) {
      showStatus(err instanceof Error ? err.message : t("failedDeleteStep"), true);
    }
  };

  const launchStep = async (step: FlowStep) => {
    if (!sessionId) return;
    try {
      await postJson(apiUrl(`sessions/${sessionId}/activities/`), { flow_step_id: step.id });
      showStatus(t("launchedSuccess"));
    } catch (err) {
      showStatus(err instanceof Error ? err.message : t("failedLaunchActivity"), true);
    }
  };

  const togglePreview = (id: number) => {
    setPreviewOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const activeFlowId = currentFlow?.id ?? initialFlowId;
  const editable = currentFlow?.can_edit !== false;

  return (
    <>
      <LanguageSwitcher />
      <div className="lc-builder-root">
        <div className="lc-builder-layout">
          <div className="lc-builder-main">
            <div className="lc-builder-topbar">
              <div className="lc-builder-title-group">
                <h2>{t("builderTitle")}</h2>
                <label className="lc-builder-flow-select-label">
                  {t("flows")}:{" "}
                  <select
                    className="lc-builder-flow-select"
                    ref={flowSelectRef}
                    value={activeFlowId ? String(activeFlowId) : ""}
                    onChange={(e) => void loadFlow(Number(e.target.value))}
                  >
                    {flows.length === 0 ? (
                      <option value="">{t("noStepsYet")}</option>
                    ) : (
                      flows.map((f) => (
                        <option key={f.id} value={String(f.id)}>
                          {f.title} ({f.steps_count ?? 0} {t("steps").toLowerCase()})
                        </option>
                      ))
                    )}
                  </select>
                </label>
              </div>
              <div className="lc-builder-actions">
                <button type="button" className="lc-btn-sm" onClick={() => void createFlow()}>+ {t("createFlow")}</button>
                <button type="button" className="lc-btn-sm lc-btn-outline" onClick={() => void duplicateFlow()}>{t("duplicateFlow")}</button>
                {editable ? <button type="button" className="lc-btn-sm lc-btn-outline" onClick={() => setImportOpen(true)}>{t("importContent")}</button> : null}
                {sessionId ? (
                  <button type="button" className="lc-btn-sm lc-btn-outline" onClick={() => void saveSessionAsFlow()}>{t("saveSessionAsFlow")}</button>
                ) : null}
                <button type="button" className="lc-btn-sm lc-btn-subtle" onClick={() => setAiSidebarOpen((v) => !v)}>
                  🤖 {t("aiAssistant")}
                </button>
              </div>
            </div>
            {status ? <div className={`lc-builder-status ${status.error ? "lc-builder-status-error" : "lc-builder-status-success"}`}>{status.msg}</div> : null}
            <section className="lc-builder-flow-detail">
              {currentFlow ? (
                <div className="lc-builder-flow-info">
                  <h1>{currentFlow.title}</h1>
                  {currentFlow.description ? <p className="lc-builder-flow-desc">{currentFlow.description}</p> : null}
                  <div className="lc-builder-flow-meta">
                    <span className="lc-badge">{currentFlow.steps.length} {t("steps")}</span>
                  </div>
                  {!editable ? <p className="lc-guidance-risk">{locale.startsWith("zh") ? "这是只读公共示例。请在教师工作区选择“使用此示例”，创建自己的可编辑课堂。" : "This is a read-only public demo. Use “Use this demo” in the teacher workspace to create your own editable classroom."}</p> : null}
                </div>
              ) : (
                <p className="lc-empty-notice">{t("selectFlow")}</p>
              )}
            </section>
            <section className="lc-builder-steps-section">
              <div className="lc-builder-steps-header">
                <h3>{t("steps")}</h3>
                {editable ? <button type="button" className="lc-btn-sm lc-btn-primary" onClick={() => setAddStepOpen((v) => !v)}>+ {t("addStep")}</button> : null}
                {editable ? <button type="button" className="lc-btn-sm lc-btn-outline" onClick={() => setQuestionPickerOpen((v) => !v)}>{locale.startsWith("zh") ? "从题库加入" : "Add from question bank"}</button> : null}
              </div>
              {editable && addStepOpen && currentFlow ? (
                <AddStepForm
                  flowId={currentFlow.id}
                  apiUrl={apiUrl}
                  initialDraft={draftPrompt}
                  onSaved={() => {
                    setAddStepOpen(false);
                    setDraftPrompt("");
                    showStatus(t("stepAdded"));
                    void loadFlow(currentFlow.id);
                  }}
                  onCancel={() => setAddStepOpen(false)}
                />
              ) : null}
              {editable && currentFlow && questionPickerOpen ? (
                <div className="lc-card lc-question-picker">
                  <QuestionBankWorkspace apiRoot={apiRoot} picker onPick={addQuestionFromBank} />
                </div>
              ) : null}
              {editable && currentFlow ? (
                <FilePicker
                  endpoint={apiUrl(`flows/${currentFlow.id}/files/`)}
                  isSuperuser={isSuperuser}
                  includeChannels={false}
                  onSuccess={() => void loadFlow(currentFlow.id)}
                />
              ) : null}
              {editable && editingStep?.activity_definition && currentFlow && <ActivityEditor key={editingStep.id}
                initial={{title:editingStep.activity_definition.title,type_key:editingStep.activity_definition.type_key,content:editingStep.activity_definition.definition}}
                onCancel={()=>setEditingStep(null)} onSave={async(snapshot)=>{
                  const updated=await postJson<FlowDetail>(apiUrl(`flows/${currentFlow.id}/steps/${editingStep.id}/edit/`),{token:currentFlow.token,snapshot},crypto.randomUUID());
                  setCurrentFlow(updated);setEditingStep(null);
                }}/>}
              <div className="lc-builder-step-list">
                {currentFlow && currentFlow.steps.length === 0 ? (
                  <p className="lc-empty-notice">{t("noStepsYet")}</p>
                ) : (
                  currentFlow?.steps.map((step, index) => (
                    <StepCard
                      key={step.id}
                      step={step}
                      index={index}
                      total={currentFlow.steps.length}
                      previewOpen={previewOpen.has(step.id)}
                      sessionId={sessionId}
                      editable={editable}
                      onMove={(i, d) => void moveStep(i, d)}
                      onTogglePreview={togglePreview}
                      onDelete={(s) => void deleteStep(s)}
                      onLaunch={(s) => void launchStep(s)}
                      onEdit={setEditingStep}
                    />
                  ))
                )}
              </div>
            </section>
          </div>
          <div className="lc-builder-sidebar" style={{ display: aiSidebarOpen ? "block" : "none" }}>
            <div ref={sidebarRef} />
          </div>
        </div>
      </div>
      {importOpen ? <ImportModal apiUrl={apiUrl} onImported={() => { setImportOpen(false); showStatus(t("importSuccess")); void loadFlows(); }} onClose={() => setImportOpen(false)} /> : null}
    </>
  );
}

export function mountBuilder(container: HTMLElement): void {
  const locale: Locale = getLocale(container);
  const dataset = container.dataset;
  const flowsUrl = dataset.apiV1Url ?? "/api/v1/flows/";

  let sessionId: number | null = dataset.sessionId ? parseInt(dataset.sessionId, 10) || null : null;
  if (!sessionId && typeof window !== "undefined") {
    const param = new URLSearchParams(window.location.search).get("session_id");
    if (param) sessionId = parseInt(param, 10) || null;
  }
  let flowId: number | null = dataset.flowId ? parseInt(dataset.flowId, 10) || null : null;
  if (!flowId && typeof window !== "undefined") {
    const param = new URLSearchParams(window.location.search).get("flow_id");
    if (param) flowId = parseInt(param, 10) || null;
  }
  const isSuperuser = dataset.isSuperuser === "true";

  const root = createRoot(container);
  root.render(
    <LocaleProvider initial={locale} root={container}>
      <FlowBuilder
        flowsUrl={flowsUrl}
        sessionId={sessionId}
        initialFlowId={flowId}
        isSuperuser={isSuperuser}
      />
    </LocaleProvider>,
  );
}
