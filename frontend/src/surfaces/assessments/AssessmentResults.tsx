import * as React from "react";
import { useEffect, useState } from "react";

import { ApiError, getJson, postJson } from "../../protocol.js";
import { useLocale } from "../../i18n.js";

type Run = { public_id: string; title: string; created_at?: string };
type Progress = {
  run: { course_id?: number | null };
  counts: Record<string, number | null>;
  students: Array<{ student_id: number; student_username: string; status: string; latest_attempt?: { id: string; grade?: { awarded_points?: string; possible_points?: string } | null } | null }>;
};
type Analytics = { questions?: Array<{ identity: string; type_key?: string; completion?: { submitted?: number }; distribution?: Array<{ label?: string; count?: number }> }> };
type StudentOverview = { student: { username: string }; summary: Record<string, number>; attempts: Array<{ id: string; status: string; progress_status: string; grade?: { awarded_points?: string; possible_points?: string } | null }> };

function endpoint(apiRoot: string, path: string): string {
  const base = new URL(apiRoot, window.location.href);
  base.pathname = base.pathname.replace(/workspace\/?$/, "");
  if (!base.pathname.endsWith("/")) base.pathname += "/";
  return new URL(path, base).toString();
}
function text(locale: string, en: string, zh: string): string { return locale.startsWith("zh") ? zh : en; }

export function AssessmentResults({ apiRoot, assessmentId }: { apiRoot: string; assessmentId: number | null }) {
  const locale = useLocale();
  const [runs, setRuns] = useState<Run[]>([]);
  const [run, setRun] = useState<Run | null>(null);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [reason, setReason] = useState("");
  const [ruleVersion, setRuleVersion] = useState("activity-registry-v2");
  const [ruleConfig, setRuleConfig] = useState('{"answer": 11}');
  const [preview, setPreview] = useState<{ preview_fingerprint: string; counts?: Record<string, number>; items?: Array<{ old?: Record<string, string>; new?: Record<string, string> }> } | null>(null);
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [student, setStudent] = useState<StudentOverview | null>(null);
  const loadRuns = async () => {
    if (!assessmentId) { setRuns([]); setRun(null); return; }
    setLoading(true); setError("");
    try {
      const result = await getJson<{ runs: Run[] }>(endpoint(apiRoot, `assessments/${assessmentId}/runs/`));
      setRuns(result.runs); setRun((current) => result.runs.find((item) => item.public_id === current?.public_id) ?? result.runs[0] ?? null);
    } catch (cause) { setError(cause instanceof ApiError ? cause.message : text(locale, "Unable to load published runs.", "无法加载已发布运行。")); }
    finally { setLoading(false); }
  };
  useEffect(() => { void loadRuns(); }, [assessmentId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!run) { setProgress(null); return; }
    void getJson<Progress>(endpoint(apiRoot, `assessment-runs/${run.public_id}/progress/`)).then(setProgress).catch((cause) => setError(cause instanceof ApiError ? cause.message : text(locale, "Unable to load results.", "无法加载结果。")));
  }, [run]); // eslint-disable-line react-hooks/exhaustive-deps
  const release = async (dimension: string) => {
    if (!run) return;
    try {
      await postJson(endpoint(apiRoot, `assessment-runs/${run.public_id}/release/`), { dimension });
      setError("");
    } catch (cause) { setError(cause instanceof ApiError ? cause.message : text(locale, "Unable to release this result.", "无法发布此结果。")); }
  };
  const previewRegrade = async () => {
    if (!run || !reason.trim()) { setError(text(locale, "A correction reason is required.", "请填写更正理由。")); return; }
    try {
      const config = JSON.parse(ruleConfig) as Record<string, unknown>;
      const result = await postJson<typeof preview>(endpoint(apiRoot, `assessment-runs/${run.public_id}/regrade/preview/`), { rule_version: ruleVersion, rule_config: config, reason });
      setPreview(result); setError("");
    } catch (cause) { setError(cause instanceof SyntaxError ? text(locale, "Rule configuration must be JSON.", "规则配置必须是 JSON。") : cause instanceof ApiError ? cause.message : text(locale, "Unable to preview this correction.", "无法预览此更正。")); }
  };
  const applyRegrade = async () => {
    if (!run || !preview) return;
    try {
      const config = JSON.parse(ruleConfig) as Record<string, unknown>;
      await postJson(endpoint(apiRoot, `assessment-runs/${run.public_id}/regrade/apply/`), { rule_version: ruleVersion, rule_config: config, reason, preview_fingerprint: preview.preview_fingerprint, idempotency_key: crypto.randomUUID() });
      setPreview(null);
      const result = await getJson<Progress>(endpoint(apiRoot, `assessment-runs/${run.public_id}/progress/`));
      setProgress(result);
    } catch (cause) { setError(cause instanceof ApiError ? cause.message : text(locale, "Unable to apply this correction.", "无法应用此更正。")); }
  };
  const loadAnalytics = async () => {
    if (!run) return;
    try { setAnalytics(await getJson<Analytics>(endpoint(apiRoot, `assessment-runs/${run.public_id}/question-analytics/`))); setError(""); }
    catch (cause) { setError(cause instanceof ApiError ? cause.message : text(locale, "Unable to load question analytics.", "无法加载题目分析。")); }
  };
  const loadStudent = async (studentId: number) => {
    try { setStudent(await getJson<StudentOverview>(endpoint(apiRoot, `students/${studentId}/overview/`))); setError(""); }
    catch (cause) { setError(cause instanceof ApiError ? cause.message : text(locale, "Unable to load learner overview.", "无法加载学生概览。")); }
  };
  const courseId = progress?.run.course_id;
  return <section className="lc-card lc-assessment-results" aria-labelledby="assessment-results-heading">
    <h2 id="assessment-results-heading">{text(locale, "Published results", "已发布结果")}</h2>
    {!assessmentId ? <p>{text(locale, "Save an assessment to view its published runs.", "保存测验后可查看其已发布运行。")}</p> : null}
    {assessmentId ? <label>{text(locale, "Published run", "已发布运行")}<select className="lc-select" value={run?.public_id ?? ""} onChange={(event) => setRun(runs.find((item) => item.public_id === event.target.value) ?? null)}><option value="">{text(locale, "Choose a run", "选择运行")}</option>{runs.map((item) => <option key={item.public_id} value={item.public_id}>{item.title}</option>)}</select></label> : null}
    <button type="button" className="lc-btn lc-btn-outline" onClick={() => void loadRuns()} disabled={loading || !assessmentId}>{text(locale, "Refresh runs", "刷新运行")}</button>
    {progress ? <><p>{text(locale, "Not started", "未开始")}: {progress.counts.not_started ?? 0}; {text(locale, "In progress", "进行中")}: {progress.counts.in_progress ?? 0}; {text(locale, "Submitted", "已提交")}: {progress.counts.submitted ?? 0}; {text(locale, "Graded", "已评分")}: {progress.counts.graded ?? 0}</p><ul>{progress.students.map((student) => <li key={student.student_id}><button type="button" className="lc-btn-sm lc-btn-outline" onClick={() => void loadStudent(student.student_id)}>{student.student_username}</button>: {student.status}{student.latest_attempt?.grade ? ` (${student.latest_attempt.grade.awarded_points ?? "—"}/${student.latest_attempt.grade.possible_points ?? "—"})` : ""}</li>)}</ul><div className="lc-actions">{["scores", "answers", "explanations", "comments"].map((dimension) => <button type="button" className="lc-btn lc-btn-outline" key={dimension} onClick={() => void release(dimension)}>{text(locale, `Release ${dimension}`, `发布${dimension}`)}</button>)}{run ? <><a className="lc-btn lc-btn-outline" href={endpoint(apiRoot, `assessment-runs/${run.public_id}/results/export/?format=csv`)}>{text(locale, "Download CSV", "下载 CSV")}</a><a className="lc-btn lc-btn-outline" href={endpoint(apiRoot, `assessment-runs/${run.public_id}/results/export/?format=json`)}>{text(locale, "Download JSON", "下载 JSON")}</a><button type="button" className="lc-btn lc-btn-outline" onClick={() => void loadAnalytics()}>{text(locale, "Question analytics", "题目分析")}</button></> : null}{courseId ? <a className="lc-btn lc-btn-outline" href={endpoint(apiRoot, `classes/${courseId}/results/export/?format=csv`)}>{text(locale, "Download class CSV", "下载班级 CSV")}</a> : null}</div></> : null}
    {student ? <section className="lc-card lc-student-overview" aria-label={text(locale, "Learner overview", "学生概览")}><h3>{student.student.username}</h3><p>{text(locale, "Attempts", "作答次数")}: {student.summary.attempt_count ?? 0}; {text(locale, "Graded", "已评分")}: {student.summary.graded ?? 0}</p><ul>{student.attempts.map((attempt) => <li key={attempt.id}>{attempt.progress_status}{attempt.grade ? ` (${attempt.grade.awarded_points ?? "—"}/${attempt.grade.possible_points ?? "—"})` : ""}</li>)}</ul></section> : null}
    {analytics ? <section className="lc-card lc-question-analytics" aria-label={text(locale, "Question analytics", "题目分析")}><h3>{text(locale, "Question analytics", "题目分析")}</h3>{analytics.questions?.length ? <ul>{analytics.questions.map((question) => <li key={question.identity}>{question.type_key ?? text(locale, "Question", "题目")}: {question.completion?.submitted ?? 0} {text(locale, "responses", "份作答")}{question.distribution?.length ? ` · ${question.distribution.map((row) => `${row.label ?? "—"}: ${row.count ?? 0}`).join(", ")}` : ""}</li>)}</ul> : <p>{text(locale, "No submitted answers yet.", "尚无已提交答案。")}</p>}</section> : null}
    {run ? <section className="lc-assessment-regrade" aria-label={text(locale, "Regrade correction", "重新评分更正")}>
      <h3>{text(locale, "Correct objective grading", "更正客观题评分")}</h3>
      <label>{text(locale, "Rule version", "规则版本")}<input className="lc-input" value={ruleVersion} onChange={(event) => { setRuleVersion(event.target.value); setPreview(null); }} /></label>
      <label>{text(locale, "Grading rule JSON", "评分规则 JSON")}<textarea className="lc-textarea" rows={3} value={ruleConfig} onChange={(event) => { setRuleConfig(event.target.value); setPreview(null); }} /></label>
      <label>{text(locale, "Correction reason", "更正理由")}<input className="lc-input" value={reason} onChange={(event) => { setReason(event.target.value); setPreview(null); }} required /></label>
      <div className="lc-actions"><button type="button" className="lc-btn lc-btn-outline" onClick={() => void previewRegrade()}>{text(locale, "Preview correction", "预览更正")}</button>{preview ? <button type="button" className="lc-btn lc-btn-primary" onClick={() => void applyRegrade()}>{text(locale, "Apply correction", "应用更正")}</button> : null}</div>
      {preview ? <section role="status"><p>{text(locale, "Review the affected items, then apply the correction.", "检查受影响题目后再应用更正。")} {preview.items?.length ?? 0}</p><ul>{preview.items?.map((item, index) => <li key={index}>{text(locale, "Item", "题目")} {index + 1}: {item.old?.awarded_points ?? "—"} → {item.new?.awarded_points ?? "—"}</li>)}</ul></section> : null}
    </section> : null}
    {error ? <p className="lc-form-error" role="alert">{error}</p> : null}
  </section>;
}
