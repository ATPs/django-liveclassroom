import { SessionPlanPanel } from "./SessionPlanPanel.js";
import * as React from "react";
import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { createPortal } from "react-dom";
import { readBootstrap, type Bootstrap } from "../../bootstrap.js";
import { LocaleProvider, useLocale, useT } from "../../i18n.js";
import {
  apiEndpoint,
  getJson,
  idempotencyKey,
  postJson,
  type ActivityState,
  type SessionState,
  type VisibilityState,
} from "../../protocol.js";
import { useSessionState } from "../../hooks/useSessionState.js";
import { AggregateView, MediaView, TimerDisplay, WordCloud, ChoiceBars } from "../../activities/renderers.js";
import { isBuiltinActivity, PluginActivityView, Prompt, RevealedFeedback } from "../../activities/ActivityView.js";
import { FileActivity } from "../../activities/FileActivity.js";
import { NativeDeckView } from "../../activities/NativeDeckView.js";
import { activityContent, activityKind, activityTitle, choicesFor, presentationTitle, selectedChoices, stringValue } from "../../activities/activityData.js";
import { FilePicker } from "../FilePicker.js";
import { PresentationSourcePicker } from "./PresentationSourcePicker.js";
import { Icon } from "../navigation/AppShell.js";
import { getSessionActionSlot, subscribeSessionActionSlot } from "../navigation/sessionActionSlot.js";
import { useQuerySelection } from "../../navigation.js";

type TeacherBootstrap = Bootstrap & {
  capabilities: string[];
  workspaceUrl: string;
  sessionTitle: string;
  flowTitle: string;
  joinCode: string;
  joinUrl: string;
  displayUrl: string;
  qrUrl: string;
  exportUrl: string;
  builderUrl: string;
  studentViewUrl: string;
  decksUrl: string;
  isSuperuser: boolean;
  flowSteps: Array<{ id: number; position: number; title: string }>;
};

type ConsolePanel = "responses" | "results" | "lesson" | "more" | "students" | "decks" | "content";

const CONSOLE_PANELS: readonly ConsolePanel[] = ["responses", "results", "lesson", "more", "students", "decks", "content"];

function isConsolePanel(value: string): value is ConsolePanel {
  return CONSOLE_PANELS.includes(value as ConsolePanel);
}

function activityIdFromQuery(value: string): number | null {
  if (!/^\d+$/.test(value)) return null;
  const id = Number(value);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
}

function readTeacherBootstrap(root: HTMLElement): TeacherBootstrap {
  const base = readBootstrap(root);
  const d = root.dataset;
  let flowSteps: TeacherBootstrap["flowSteps"] = [];
  try {
    flowSteps = JSON.parse(d.flowSteps ?? "[]") as TeacherBootstrap["flowSteps"];
  } catch {
    flowSteps = [];
  }
  let capabilities: string[] = [];
  try {
    capabilities = JSON.parse(d.capabilities ?? "[]") as string[];
  } catch {
    capabilities = [];
  }
  return {
    ...base,
    capabilities,
    workspaceUrl: d.workspaceUrl ?? "",
    sessionTitle: d.sessionTitle ?? "",
    flowTitle: d.flowTitle ?? "",
    joinCode: d.joinCode ?? "",
    joinUrl: d.joinUrl ?? "",
    displayUrl: d.displayUrl ?? "",
    qrUrl: d.qrUrl ?? "",
    exportUrl: d.exportUrl ?? "",
    builderUrl: d.builderUrl ?? "",
    studentViewUrl: d.studentViewUrl ?? "",
    decksUrl: d.decksUrl ?? "",
    isSuperuser: d.isSuperuser === "true",
    flowSteps,
  };
}

function useCommand(stateUrl: string, refresh: () => void) {
  const t = useT();
  const [status, setStatus] = useState("");
  const [pendingCount, setPendingCount] = useState(0);
  const pendingRef = useRef(0);
  const run = async (suffix: string, body: Record<string, unknown> = {}): Promise<boolean> => {
    pendingRef.current += 1;
    setPendingCount(pendingRef.current);
    try {
      await postJson(apiEndpoint(stateUrl, suffix), body, `cmd-${Date.now()}-${Math.random().toString(36).slice(2)}`);
      setStatus("");
      await refresh();
      return true;
    } catch (error) {
      setStatus(error instanceof Error ? error.message : t("unavailable"));
      return false;
    } finally {
      pendingRef.current -= 1;
      setPendingCount(pendingRef.current);
    }
  };
  return { run, status, setStatus, pending: pendingCount > 0 };
}

function LifecycleControls({ state, run, startingStepId, pending, onStarted }: { state: SessionState | null; run: (s: string, body?: Record<string, unknown>) => Promise<boolean>; startingStepId: number | null; pending: boolean; onStarted: () => void }) {
  const t = useT();
  const status = state?.session.status ?? "draft";
  if (status === "ended") return <div className="lc-lifecycle-bar"><p role="status" className="lc-ended-notice">{t("teachingEnded")}</p></div>;
  if (status === "paused") {
    return (
      <div className="lc-lifecycle-bar">
        <button id="start-session" className="lc-btn lc-btn-primary" disabled={pending} onClick={() => void run("sessions/start").then((ok) => { if (ok) onStarted(); })}>
          <span aria-hidden="true">▶ </span>{t("resumeClass")}
        </button>
      </div>
    );
  }
  if (status === "live") {
    return (
      <div className="lc-lifecycle-bar">
        <div className="lc-lifecycle-group">
          <button id="pause-session" className="lc-btn lc-btn-outline" disabled={pending} onClick={() => void run("sessions/pause")}>
            <span aria-hidden="true">❚❚ </span>{t("pause")}
          </button>
          <button id="end-session" className="lc-btn lc-btn-outline lc-btn-end" disabled={pending} onClick={() => { if (window.confirm(t("confirmEnd"))) void run("sessions/end"); }}>
            <span aria-hidden="true">■ </span>{t("endClass")}
          </button>
        </div>
      </div>
    );
  }
  return (
    <div className="lc-lifecycle-bar" aria-label={t("controls")}>
      <button id="start-session" className="lc-btn lc-btn-primary" disabled={pending} onClick={() => void run("sessions/start", startingStepId ? { plan_step_id: startingStepId } : {}).then((ok) => { if (ok) onStarted(); })}>
        <span aria-hidden="true">▶ </span>{t("startClass")}
      </button>
    </div>
  );
}

function InviteControls({ bootstrap }: { bootstrap: TeacherBootstrap }) {
  const t = useT();
  const locale = useLocale();
  const [notice, setNotice] = useState("");
  const [copyFallback, setCopyFallback] = useState("");
  const [open, setOpen] = useState(false);
  const popup = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const text = (en: string, zh: string) => locale.startsWith("zh") ? zh : en;
  const close = (restoreFocus = false) => {
    setOpen(false);
    if (restoreFocus) window.requestAnimationFrame(() => trigger.current?.focus());
  };
  useEffect(() => {
    if (!open) return;
    const dismiss = (event: MouseEvent) => { if (popup.current && !popup.current.contains(event.target as Node)) close(); };
    const escape = (event: KeyboardEvent) => { if (event.key === "Escape") { event.preventDefault(); close(true); } };
    document.addEventListener("mousedown", dismiss);
    window.addEventListener("keydown", escape);
    return () => { document.removeEventListener("mousedown", dismiss); window.removeEventListener("keydown", escape); };
  }, [open]);
  const copy = async (value: string) => {
    setCopyFallback("");
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(value);
      setNotice(t("copied"));
      setTimeout(() => setNotice(""), 2000);
    } catch {
      setCopyFallback(value);
      setNotice(text("Clipboard access is unavailable. Select and copy the text below.", "剪贴板不可用。请选中下方文字后复制。"));
    }
  };
  return (
    <div ref={popup} className="lc-invite-controls">
      <button ref={trigger} type="button" className="lc-btn lc-btn-outline lc-invite-trigger" aria-expanded={open} aria-haspopup="dialog" onClick={() => setOpen((current) => !current)}>{t("inviteStudents")}</button>
      {open ? <div className="lc-invite-dropdown" role="dialog" aria-label={t("inviteStudents")}>
        <figure className="lc-join-qr">
          <img src={bootstrap.qrUrl} alt={`${t("joinCode")}: ${bootstrap.sessionTitle}`} />
          <figcaption>{t("studentJoinCode")}: <strong>{bootstrap.joinCode}</strong></figcaption>
        </figure>
        <div className="lc-actions">
          <button type="button" className="lc-btn lc-btn-sm" onClick={() => void copy(new URL(bootstrap.joinUrl, window.location.href).toString())}>{t("copyJoinLink")}</button>
          <button type="button" className="lc-btn lc-btn-sm" onClick={() => void copy(bootstrap.joinCode)}>{t("copyJoinCode")}</button>
          <a href={bootstrap.joinUrl} className="lc-btn lc-btn-sm lc-btn-outline" target="_blank" rel="noopener noreferrer">{t("studentJoinPage")}</a>
          {bootstrap.capabilities.includes("view_display") ? <a href={bootstrap.displayUrl} className="lc-btn lc-btn-sm lc-btn-outline" target="_blank" rel="noopener noreferrer">{t("openDisplay")}</a> : null}
        </div>
        {notice ? <p className="lc-invite-notice" aria-live="polite">{notice}</p> : null}
        {copyFallback ? <label className="lc-invite-copy-fallback">{text("Copy manually", "手动复制")}<input readOnly value={copyFallback} onFocus={(event) => event.currentTarget.select()} /></label> : null}
      </div> : null}
    </div>
  );
}

function FlowSteps({
  steps,
  builderUrl,
  run,
}: {
  steps: TeacherBootstrap["flowSteps"];
  builderUrl: string;
  run: (s: string, b: Record<string, unknown>) => Promise<boolean>;
}) {
  const t = useT();
  return (
    <section>
      <h2>{t("flow")}</h2>
      {steps.length ? (
        steps.map((step) => (
          <button
            key={step.id}
            className="lc-item"
            data-step-id={String(step.id)}
            onClick={() => void run("sessions/activities", { flow_step_id: step.id })}
          >
            {t("push")} {step.position}. {step.title}
          </button>
        ))
      ) : (
        <p>
          {t("noActivityPublished")} —{" "}
          <a href={builderUrl}>{t("builderTitle")}</a>
        </p>
      )}
    </section>
  );
}

const DEFAULT_PARTICIPANT_VISIBILITY: VisibilityState = {
  show_prompt: true,
  show_aggregate: false,
  show_answer: false,
  show_explanation: false,
  show_own_status: true,
  allow_review: false,
};

function ChannelControls({state,run}: {state:SessionState|null;run:(suffix:string,body?:Record<string,unknown>)=>Promise<boolean>}) {
  const t=useT();
  const selected=state?.current_activity;
  const fields: Array<[keyof VisibilityState,string]> = [["show_prompt",t("showPrompt")],["show_aggregate",t("showAggregate")],["show_explanation",t("showExplanation")],["show_own_status",t("showOwnStatus")],["allow_review",t("allowReview")]];
  return <section className="lc-channel-controls" aria-label={t("controls")}>{(["display","participants"] as const).map(channel=>{
    const current=state?.channels?.[channel];
    const visibility=current?.visibility??DEFAULT_PARTICIPANT_VISIBILITY;
    return <fieldset key={channel}><legend>{channel==="display"?t("display"):t("participants")}</legend>
      <p>{current?.activity?activityTitle(current.activity,t("activity")):t("noActivityPublished")}</p>
      <button type="button" className="lc-btn lc-btn-sm lc-btn-outline" disabled={!selected||state?.session.status!=="live"} onClick={()=>selected&&void run("sessions/channels/publish",{channel,activity_id:selected.id})}>{t("publish")}</button>
      <div className="lc-checkbox-list">{fields.map(([field,label])=><label key={field}><input type="checkbox" checked={visibility[field]} disabled={!current?.activity||state?.session.status==="ended"} onChange={e=>void run("sessions/channels/settings",{channel,[field]:e.target.checked})}/>{label}</label>)}</div>
    </fieldset>;
  })}</section>;
}

function AudienceControls({
  state, steps, holdStudents, setHoldStudents, run,
}: {
  state: SessionState | null;
  steps: PresenterStep[];
  holdStudents: boolean;
  setHoldStudents: (held: boolean) => void;
  run: (suffix: string, body?: Record<string, unknown>) => Promise<boolean>;
}) {
  const t = useT();
  const [restoring, setRestoring] = useState(false);
  const currentId = state?.channels?.display?.activity?.id ?? state?.current_activity?.id ?? null;
  const studentActivity = state?.channels?.participants?.activity ?? null;
  const currentStep = steps.find((step) => step.activity_id === currentId);
  const held = holdStudents || (studentActivity?.id !== currentId && Boolean(studentActivity));
  const bringStudents = () => {
    if (!currentStep || restoring || state?.session.status !== "live") return;
    setRestoring(true);
    void run(`sessions/plan/${currentStep.id}/launch`, { channel: "both" })
      .then((ok) => { if (ok) setHoldStudents(false); })
      .finally(() => setRestoring(false));
  };
  return <>
    {held && studentActivity ? <div className="lc-audience-held" role="status">
      <span>{t("studentsHeld")} <strong>{activityTitle(studentActivity, t("activity"))}</strong></span>
      <button type="button" className="lc-btn lc-btn-sm lc-btn-outline" disabled={!currentStep || state?.session.status !== "live" || restoring} onClick={bringStudents}>{t("bringStudents")}</button>
    </div> : null}
    <section className="lc-audience-panel">
      <h3>{t("audience")}</h3>
      <p>{held ? t("studentsHeld") : t("studentsFollow")}</p>
      <label><input type="checkbox" checked={held} disabled={state?.session.status !== "live" || restoring} onChange={(event) => event.target.checked ? setHoldStudents(true) : bringStudents()} /> {t("keepStudents")}</label>
    </section>
  </>;
}

function ParticipantPreview({ state, stateUrl }: { state: SessionState | null; stateUrl: string }) {
  const t = useT();
  const channel = state?.channels?.participants;
  const activity = channel?.activity ?? null;
  if (!activity) {
    return (
      <section data-liveclassroom-participant-preview>
        <h2>{t("participantPreview")}</h2>
        <p>{t("noActivityPublished")}</p>
      </section>
    );
  }
  const fallback = (
    <>
      <Prompt activity={activity} />
      <AggregateView aggregate={channel?.aggregate ?? null} activity={activity} />
    </>
  );
  return (
    <section data-liveclassroom-participant-preview>
      <h2>{t("participantPreview")}</h2>
      <h3>{activityTitle(activity, t("activity"))}</h3>
      {activityKind(activity) === "file" ? (
        <FileActivity activity={activity} audience="student" state={state} stateUrl={stateUrl} />
      ) : !isBuiltinActivity(activity) ? (
        <PluginActivityView activity={activity} state={state} stateUrl={stateUrl} audience="student" fallback={fallback} />
      ) : (
        fallback
      )}
    </section>
  );
}

function TeacherActivityView({
  activity,
  aggregate,
  state,
  stateUrl,
  onRefresh,
  onError,
}: {
  activity: ActivityState | null;
  aggregate: unknown;
  state: SessionState | null;
  stateUrl: string;
  onRefresh: () => Promise<void>;
  onError: (message: string) => void;
}) {
  const t = useT();
  if (!activity) return <p>{t("noActivityPublished")}</p>;
  if (!isBuiltinActivity(activity)) {
    return (
      <PluginActivityView
        activity={activity}
        state={state}
        stateUrl={stateUrl}
        audience="teacher"
        fallback={<BuiltinTeacherActivityView activity={activity} aggregate={aggregate} state={state} stateUrl={stateUrl} onRefresh={onRefresh} onError={onError} />}
      />
    );
  }
  return <BuiltinTeacherActivityView activity={activity} aggregate={aggregate} state={state} stateUrl={stateUrl} onRefresh={onRefresh} onError={onError} />;
}

function TimerControls({ activity, state, stateUrl, onRefresh, onError }: { activity: ActivityState; state: SessionState | null; stateUrl: string; onRefresh: () => Promise<void>; onError: (message: string) => void }) {
  const t = useT();
  const runtime = activity.runtime;
  const [pending, setPending] = useState(false);
  const send = async (action: "start" | "pause" | "resume" | "reset") => {
    if (pending || state?.session.status !== "live") return;
    setPending(true);
    try {
      await postJson(apiEndpoint(stateUrl, `activities/${activity.id}/timer`), { action }, idempotencyKey(`timer-${activity.id}-${action}`));
      await onRefresh();
    } catch (error) {
      onError(error instanceof Error ? error.message : "Unable to update timer.");
    } finally {
      setPending(false);
    }
  };
  const disabled = pending || state?.session.status !== "live";
  return <div className="lc-actions" aria-label={t("timer")}>
    {runtime?.status === "running" ? <button type="button" className="lc-btn lc-btn-sm lc-btn-outline" disabled={disabled} onClick={() => void send("pause")}>{t("pauseTimer")}</button> : null}
    {runtime?.status === "paused" ? <button type="button" className="lc-btn lc-btn-sm lc-btn-outline" disabled={disabled} onClick={() => void send("resume")}>{t("resumeTimer")}</button> : null}
    {runtime?.status === "idle" ? <button type="button" className="lc-btn lc-btn-sm lc-btn-outline" disabled={disabled} onClick={() => void send("start")}>{t("startTimer")}</button> : null}
    <button type="button" className="lc-btn lc-btn-sm lc-btn-outline" disabled={disabled} onClick={() => void send("reset")}>{t("resetTimer")}</button>
  </div>;
}

function BuiltinTeacherActivityView({
  activity,
  aggregate,
  state,
  stateUrl,
  onRefresh,
  onError,
}: {
  activity: ActivityState;
  aggregate: unknown;
  state: SessionState | null;
  stateUrl: string;
  onRefresh: () => Promise<void>;
  onError: (message: string) => void;
}) {
  const t = useT();
  const kind = activityKind(activity);
  const heading = <h2>{activityTitle(activity, t("activity"))}</h2>;
  if (kind === "media") {
    return <>{heading}<Prompt activity={activity} /><MediaView activity={activity} state={state} stateUrl={stateUrl} audience="teacher" /></>;
  }
  if (kind === "timer") {
    return (
      <>
        {heading}
        <Prompt activity={activity} />
        <TimerDisplay activity={activity} state={state} />
        <TimerControls activity={activity} state={state} stateUrl={stateUrl} onRefresh={onRefresh} onError={onError} />
      </>
    );
  }
  if (kind === "markdown") return <>{heading}<Prompt activity={activity} /></>;
  if (kind === "file") {
    return (
      <>
        {heading}
        <FileActivity activity={activity} audience="teacher" state={state} stateUrl={stateUrl} />
      </>
    );
  }
  return (
    <>
      {heading}
      {kind === "essay" ? <p className="lc-manual-grading-notice" role="status">{t("manualGradingRequired")}</p> : null}
      <Prompt activity={activity} />
      {kind === "word_cloud" ? <WordCloud aggregate={aggregate as never} isTeacher /> : null}
      <RevealedFeedback activity={activity} />
      {kind !== "word_cloud" ? <AggregateView aggregate={aggregate as never} activity={activity} /> : null}
      <p>{activity.state === "open" ? t("studentsFollow") : t("results")}</p>
    </>
  );
}

type PresenterStep = { id: number; key?: string; position: number; title: string; activity_id: number | null; snapshot?: Record<string, unknown> };

function PresenterStage({
  state, steps, stateUrl, onRefresh, canManage, onError, onPreviewChange, deliveryChannel,
}: { state: SessionState | null; steps: PresenterStep[]; stateUrl: string; onRefresh: () => Promise<void>; canManage: boolean; onError: (message: string) => void; onPreviewChange: (step: PresenterStep | null) => void; deliveryChannel: "both" | "display" }) {
  const t = useT();
  const locale = useLocale();
  const tr = (en: string, zh: string) => locale.startsWith("zh") ? zh : en;
  const currentId = state?.channels?.display?.activity?.id ?? state?.current_activity?.id ?? null;
  const currentIndex = steps.findIndex((step) => step.activity_id === currentId);
  const next = steps[currentIndex >= 0 ? currentIndex + 1 : 0] ?? null;
  const previous = currentIndex > 0 ? steps[currentIndex - 1] : null;
  const [preview, setPreview] = useState<PresenterStep | null>(null);
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState<{ step: PresenterStep; channel: "both" | "display" } | null>(null);
  const [outlineOpen, setOutlineOpen] = useState(true);
  const [nextOpen, setNextOpen] = useState(true);
  const intentKeys = useRef(new Map<string, string>());
  const stepButtons = useRef(new Map<number, HTMLButtonElement>());
  const choosePreview = (step: PresenterStep | null) => {
    setPreview(step);
    onPreviewChange(step);
  };
  useEffect(() => {
    const media = window.matchMedia("(max-width: 767px)");
    const collapseOnNarrowViewport = () => {
      if (media.matches) setOutlineOpen(false);
    };
    collapseOnNarrowViewport();
    media.addEventListener("change", collapseOnNarrowViewport);
    return () => media.removeEventListener("change", collapseOnNarrowViewport);
  }, []);
  useEffect(() => {
    const current = steps.find((step) => step.activity_id === currentId);
    if (current) stepButtons.current.get(current.id)?.scrollIntoView({ block: "nearest" });
  }, [currentId, steps]);
  useEffect(() => {
    if (preview && preview.activity_id === currentId) {
      setPreview(null);
      onPreviewChange(null);
    }
  }, [currentId, onPreviewChange, preview]);
  const present = async (step: PresenterStep, channel: "both" | "display"): Promise<boolean> => {
    if (pending || state?.session.status !== "live" || step.activity_id === currentId) return false;
    const intent = `${channel}:${step.id}`;
    const key = intentKeys.current.get(intent) ?? idempotencyKey(`present-${channel}-${step.id}`);
    intentKeys.current.set(intent, key);
    setPending(true);
    setFailed(null);
    try {
      await postJson(apiEndpoint(stateUrl, `sessions/plan/${step.id}/launch`), { channel }, key);
      await onRefresh();
      intentKeys.current.delete(intent);
      return true;
    } catch (error) {
      const message = error instanceof Error ? error.message : t("unavailable");
      setFailed({ step, channel });
      onError(message);
    } finally {
      setPending(false);
    }
    return false;
  };
  const draftPreview = state?.session.status === "draft" ? (preview ?? steps[0] ?? null) : null;
  const renderedPreview = draftPreview ?? preview;
  const previewActivity = renderedPreview ? {
    id: -renderedPreview.id,
    state: "open",
    revision: 1,
    revision_id: 0,
    definition: renderedPreview.snapshot ?? { title: renderedPreview.title, type_key: "liveclassroom.markdown", content: {} },
  } : null;
  return (
    <section className={`lc-presenter${outlineOpen ? "" : " lc-outline-collapsed"}${nextOpen ? "" : " lc-next-collapsed"}`} aria-label={tr("Presenter workspace", "演示者工作区")}>
      {outlineOpen && (
        <aside className="lc-presenter-drawer" aria-label={tr("Lesson outline", "教案目录")}>
          <div className="lc-drawer-header">
            <span className="lc-drawer-icon" aria-hidden="true">☰</span>
            <span className="lc-drawer-title">{tr("Lesson items", "教案目录")}</span>
            <span className="lc-drawer-badge">{steps.length}</span>
            <button
              type="button"
              className="lc-drawer-collapse-btn"
              title={tr("Hide outline", "折叠目录")}
              aria-label={tr("Hide outline", "折叠目录")}
              onClick={() => setOutlineOpen(false)}
            >
              ✕
            </button>
          </div>
          <nav className="lc-presenter-strip" aria-label={tr("Lesson outline", "教案目录")}>
            {steps.map((step) => (
              <button
                type="button"
                ref={(element) => { if (element) stepButtons.current.set(step.id, element); else stepButtons.current.delete(step.id); }}
                key={step.id}
                aria-current={step.activity_id === currentId ? "step" : undefined}
                disabled={!canManage || pending || state?.session.status === "ended" || step.activity_id === currentId}
                onClick={() => state?.session.status === "live" ? void present(step, deliveryChannel) : choosePreview(step)}
                className={step.activity_id === currentId ? "lc-presenter-step lc-presenter-step-current" : "lc-presenter-step"}
              >
                {step.position}. {presentationTitle(step.title)}
              </button>
            ))}
          </nav>
        </aside>
      )}
      <div className="lc-presenter-current">
        <div className="lc-presenter-current-header">
          <div className="lc-presenter-header-left">
            <button
              type="button"
              className={`lc-btn lc-btn-outline lc-outline-toggle-btn ${outlineOpen ? "active" : ""}`}
              onClick={() => setOutlineOpen((open) => !open)}
              title={outlineOpen ? tr("Hide lesson outline", "折叠教案目录") : tr("Show lesson outline", "展开教案目录")}
            >
              <span aria-hidden="true">{outlineOpen ? "◧ " : "☰ "}</span>
              {outlineOpen ? tr("Hide outline", "折叠目录") : tr("Outline", "教案目录")}
            </button>
            <p className="lc-presenter-label">{draftPreview ? tr("Private preview", "私有预览") : tr("Now showing", "当前展示")}</p>
          </div>
          <div className="lc-presenter-navigation" aria-label={tr("Lesson navigation", "教案导航")}>
            {!nextOpen ? <button
              type="button"
              className="lc-presenter-next-toggle"
              aria-controls="lc-presenter-next"
              aria-expanded="false"
              onClick={() => setNextOpen(true)}
              title={tr("Show next item", "显示下一项")}
              aria-label={tr("Show next item", "显示下一项")}
            >
              <Icon name="overview" size={16} />
            </button> : null}
            <button
              type="button"
              className="lc-btn lc-btn-nav lc-btn-prev lc-btn-outline"
              disabled={!canManage || pending || !previous || state?.session.status !== "live"}
              onClick={() => previous && void present(previous, deliveryChannel)}
              title={previous ? `${tr("Previous", "上一项")}: ${previous.position}. ${presentationTitle(previous.title)}` : tr("No previous item", "已是第一项")}
            >
              <span aria-hidden="true">◀ </span>{tr("Previous", "上一项")}
            </button>
            <span className="lc-presenter-step-count" title={tr("Current step / Total steps", "当前进度 / 总数")}>
              {currentIndex >= 0 ? `${currentIndex + 1} / ${steps.length}` : `0 / ${steps.length}`}
            </span>
            <button
              type="button"
              className="lc-btn lc-btn-nav lc-btn-next lc-btn-primary"
              disabled={!canManage || pending || !next || state?.session.status !== "live"}
              onClick={() => next && void present(next, deliveryChannel)}
              title={next ? `${tr("Next", "下一项")}: ${next.position}. ${presentationTitle(next.title)}` : tr("No next item", "已是最后一项")}
            >
              {tr("Next", "下一项")}<span aria-hidden="true"> ▶</span>
            </button>
          </div>
        </div>
        {draftPreview ? (
          <>
            <p>{tr("Students cannot see this item. Start class to publish it.", "学生看不到此项目。开始课堂后才会发布。")}</p>
            <TeacherActivityView activity={previewActivity} aggregate={null} state={state} stateUrl={stateUrl} onRefresh={onRefresh} onError={onError} />
          </>
        ) : state?.current_deck && !state.current_activity ? (
          <NativeDeckView deck={state.current_deck} state={state} audience="teacher" stateUrl={stateUrl} />
        ) : (
          <TeacherActivityView activity={state?.current_activity ?? null} aggregate={state?.aggregate ?? null} state={state} stateUrl={stateUrl} onRefresh={onRefresh} onError={onError} />
        )}
      </div>
      {nextOpen ? <aside id="lc-presenter-next" className="lc-presenter-next">
        <div className="lc-presenter-next-heading">
          <p className="lc-presenter-label">{tr("Up next", "下一项")}</p>
          <button
            type="button"
            className="lc-presenter-next-toggle"
            aria-controls="lc-presenter-next"
            aria-expanded="true"
            onClick={() => setNextOpen(false)}
            title={tr("Hide next item", "隐藏下一项")}
            aria-label={tr("Hide next item", "隐藏下一项")}
          >
            <Icon name="close" size={16} />
          </button>
        </div>
        {draftPreview ? (
          <p>{tr("Choose any lesson item to preview it before starting.", "开始前可选择任意教案项目进行预览。")}</p>
        ) : preview ? (
          <>
            <h2>{preview.position}. {presentationTitle(preview.title)}</h2>
            <p>{tr("Private preview — students cannot see this item.", "私有预览——学生不会看到此项目。")}</p>
            <TeacherActivityView activity={previewActivity} aggregate={null} state={state} stateUrl={stateUrl} onRefresh={onRefresh} onError={onError} />
            <button className="lc-btn lc-btn-primary" disabled={!canManage || pending || state?.session.status !== "live"} onClick={() => { void present(preview, deliveryChannel).then((published) => { if (published) choosePreview(null); }); }}>{tr("Show this item", "展示此项目")}</button>
            <button className="lc-btn lc-btn-outline" onClick={() => choosePreview(null)}>{tr("Return", "返回")}</button>
          </>
        ) : next ? (
          <>
            <h2>{next.position}. {presentationTitle(next.title)}</h2>
            <p>{tr("Students follow by default.", "学生默认跟随演示。")}</p>
            <button className="lc-btn lc-btn-outline" disabled={!canManage} onClick={() => choosePreview(next)}>{tr("Preview", "预览")}</button>
          </>
        ) : (
          <p>{tr("Last item.", "最后一项。")}</p>
        )}
        <p className="lc-presenter-status">{tr("Student channel", "学生端")}: {state?.channels?.participants?.activity?.id === currentId ? tr("following", "跟随") : state?.channels?.participants?.activity ? `${tr("held on", "停留在")} “${activityTitle(state.channels.participants.activity, t("activity"))}”` : tr("waiting", "等待中")}</p>
      </aside> : null}
      {failed ? (
        <p className="lc-builder-status-error" role="status">{tr("Could not publish this item.", "无法发布此项目。")} <button type="button" className="lc-btn lc-btn-sm lc-btn-outline" onClick={() => void present(failed.step, failed.channel)}>{tr("Retry", "重试")}</button></p>
      ) : null}
    </section>
  );
}

type DeckSummary = { id: number; title: string; version: number };
type DeckSnapshotSummary = { id: number; source_version: number; title: string; slides?: unknown[] };

function NativeDeckPresenter({
  bootstrap, state, stateUrl, onRefresh, planSteps,
}: {
  bootstrap: TeacherBootstrap;
  state: SessionState | null;
  stateUrl: string;
  onRefresh: () => Promise<void>;
  planSteps: Array<{ key?: string; id: number; position: number; title: string }>;
}) {
  const locale = useLocale();
  const tr = (en: string, zh: string) => locale.startsWith("zh") ? zh : en;
  const [decks, setDecks] = useState<DeckSummary[]>([]);
  const [snapshots, setSnapshots] = useState<DeckSnapshotSummary[]>([]);
  const [deckId, setDeckId] = useState<number | null>(null);
  const [status, setStatus] = useState("");
  const [pending, setPending] = useState(false);
  const selectedDeck = decks.find((deck) => deck.id === deckId) ?? null;

  useEffect(() => {
    if (!bootstrap.decksUrl) return;
    void getJson<{ decks: DeckSummary[] }>(bootstrap.decksUrl)
      .then((data) => setDecks(data.decks ?? []))
      .catch(() => setStatus(tr("Decks are unavailable.", "无法加载幻灯片。")));
  }, [bootstrap.decksUrl]);

  useEffect(() => {
    if (!selectedDeck) {
      setSnapshots([]);
      return;
    }
    const url = new URL(bootstrap.decksUrl, window.location.href);
    url.pathname = `${url.pathname.replace(/\/$/, "")}/${selectedDeck.id}/snapshots/`;
    void getJson<{ snapshots: DeckSnapshotSummary[] }>(url.toString())
      .then((data) => setSnapshots(data.snapshots ?? []))
      .catch(() => setStatus(tr("Snapshots are unavailable.", "无法加载快照。")));
  }, [bootstrap.decksUrl, selectedDeck?.id]);

  const present = async (snapshot: DeckSnapshotSummary) => {
    if (pending || state?.session.status !== "live") return;
    setPending(true);
    setStatus("");
    try {
      await postJson(apiEndpoint(stateUrl, "sessions/presentation"), {
        snapshot_id: snapshot.id,
        channels: ["display"],
      }, idempotencyKey(`deck-present-${snapshot.id}`));
      await onRefresh();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : tr("Unable to present deck.", "无法展示幻灯片。"));
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="lc-native-deck-presenter">
      <div className="lc-form-row">
        <label>{tr("Deck", "幻灯片")}{" "}
          <select value={deckId ?? ""} onChange={(event) => setDeckId(event.target.value ? Number(event.target.value) : null)}>
            <option value="">{tr("Choose a deck", "选择幻灯片")}</option>
            {decks.map((deck) => <option value={deck.id} key={deck.id}>{deck.title}</option>)}
          </select>
        </label>
      </div>
      {selectedDeck ? <div className="lc-actions" style={{ marginTop: "0.5rem" }}>
        {snapshots.map((snapshot) => <button type="button" key={snapshot.id} className="lc-btn lc-btn-primary" disabled={pending || state?.session.status !== "live"} onClick={() => void present(snapshot)}>{tr("Present", "展示")} {snapshot.title} ({snapshot.slides?.length ?? "?"})</button>)}
        {!snapshots.length ? <p>{tr("Create a snapshot from the deck editor first.", "请先在幻灯片编辑器中创建快照。")} </p> : null}
      </div> : null}
      {status ? <p role="status" className="lc-builder-status-error">{status}</p> : null}
      <div style={{ marginTop: "1rem" }}>
        <PresentationSourcePicker stateUrl={stateUrl} snapshots={snapshots} steps={planSteps} onRefresh={onRefresh} />
      </div>
    </div>
  );
}

function LiveResults({
  state,
  analytics,
  run,
  pending,
  canManage,
}: {
  state: SessionState | null;
  analytics: Record<string, unknown> | null;
  run: (s: string, body?: Record<string, unknown>) => Promise<boolean>;
  pending: boolean;
  canManage: boolean;
}) {
  const t = useT();
  const activity = state?.current_activity ?? null;
  const hasAnswer = Boolean(activity?.has_answer);
  const hasExplanation = Boolean(activity?.has_explanation);
  const live = state?.session.status === "live";
  const visibility = state?.channels?.display?.visibility;
  const setVisibility = async (field: "show_aggregate" | "show_explanation", value: boolean) => {
    await run("sessions/channels/settings", { channel: "both", [field]: value });
  };
  const current = activity
    ? (Array.isArray(analytics?.activities) ? (analytics!.activities as Array<Record<string, unknown>>).find((a) => a.id === activity.id) : undefined)
    : undefined;
  return (
    <section id="results" className="lc-live-responses">
      <p id="activity-status">{activity ? t("responsesForCurrentActivity") : t("noActivityPublished")}</p>
      {activity ? <h4 className="lc-live-response-activity">{activityTitle(activity, t("activity"))}</h4> : null}
      {activity && activityKind(activity) === "essay" ? <p className="lc-manual-grading-notice" role="status">{t("manualGradingRequired")}</p> : null}
      <div id="result-summary">
        {current ? (
          <>
            <div className="lc-rate-badge">
              {t("responseRate")}: {String(current.response_rate ?? 0)}% ({String(current.submitted_count ?? 0)}/
              {String(current.eligible_participant_count ?? 0)})
            </div>
            {current.aggregate && (current.aggregate as Record<string, unknown>).choices ? (
              <ChoiceBars choices={(current.aggregate as { choices: Record<string, number> }).choices} activity={activity ?? undefined} />
            ) : current.aggregate && ((current.aggregate as Record<string, unknown>).words || (current.aggregate as Record<string, unknown>).word_frequencies) ? (
              <WordCloud aggregate={current.aggregate as never} isTeacher />
            ) : (
              <p>
                {String(current.submitted_count ?? 0)} {t("submitted")}
              </p>
            )}
          </>
        ) : (
          <p>{activity ? t("noResponses") : t("noActivityPublished")}</p>
        )}
      </div>
      {canManage ? <div className="lc-actions lc-response-actions">
        <button id="close-activity" disabled={pending || !live || !activity || activity.state !== "open"} onClick={() => activity && void run(`activities/${activity.id}/close`)}>{t("close")}</button>
        <button type="button" disabled={pending || !live || !activity} onClick={() => void setVisibility("show_aggregate", !visibility?.show_aggregate)}>{visibility?.show_aggregate ? t("hideResults") : t("showResults")}</button>
        {hasAnswer ? <button id="reveal-activity" disabled={pending || !live || !activity || activity.state === "revealed"} onClick={() => activity && void run(`activities/${activity.id}/close-and-show-answer`)}>{t("showAnswer")}</button> : null}
        {hasExplanation ? <button type="button" disabled={pending || !live || !activity} onClick={() => void setVisibility("show_explanation", !visibility?.show_explanation)}>{visibility?.show_explanation ? t("hideExplanation") : t("showExplanation")}</button> : null}
      </div> : null}
    </section>
  );
}

function readableResponse(answer: unknown, activity: ActivityState | null, completedLabel: string): string {
  if (!answer || typeof answer !== "object" || Array.isArray(answer)) return "—";
  const value = answer as Record<string, unknown>;
  const selected = selectedChoices(value);
  if (selected.length) {
    const labels = new Map((activity ? choicesFor(activity) : []).map((choice) => [choice.id, choice.text]));
    const separator = activity && activityKind(activity) === "ranking" ? " → " : ", ";
    return selected.map((choice) => labels.get(choice) ?? choice).join(separator);
  }
  for (const key of ["text", "value", "rating"]) {
    if (typeof value[key] === "string" || typeof value[key] === "number") return String(value[key]);
  }
  if (value.completed === true) return completedLabel;
  return "—";
}

function AnalyticsPanel({ analytics, activity }: { analytics: Record<string, unknown> | null; activity: ActivityState | null }) {
  const t = useT();
  const locale = useLocale();
  const tr = (en: string, zh: string) => locale.startsWith("zh") ? zh : en;
  const attendance = (analytics?.attendance ?? {}) as Record<string, unknown>;
  const activities = (Array.isArray(analytics?.activities) ? analytics!.activities : []) as Array<Record<string, unknown>>;
  const participants = (Array.isArray(analytics?.participants) ? analytics!.participants : []) as Array<Record<string, unknown>>;
  const current = activities.find((a) => a.id === activity?.id);
  const responses = (current && Array.isArray(current.responses) ? current.responses : []) as Array<Record<string, unknown>>;
  const activityState = (state: unknown) => ({
    open: tr("Accepting responses", "正在收集答案"),
    closed: tr("Responses closed", "已停止收集答案"),
    revealed: tr("Answer shown", "已展示答案"),
  }[String(state)] ?? tr("Not started", "尚未开始"));
  const admissionState = (state: unknown) => ({
    admitted: t("admitted"),
    pending: t("pending"),
    denied: tr("not admitted", "未获准加入"),
  }[String(state)] ?? "—");

  return (
    <section className="lc-analytics" aria-labelledby="analytics-heading">
      <div className="lc-analytics-header">
        <div>
          <h2 id="analytics-heading">{t("analyticsSummary")}</h2>
          <p id="analytics-summary" aria-live="polite">
            {String(attendance.admitted ?? 0)} {t("admitted")} · {String(attendance.currently_connected ?? 0)} {t("connected")} ·{" "}
            {String(attendance.ever_connected ?? 0)} {t("attended")} · {String(attendance.pending ?? 0)} {t("pending")}
          </p>
        </div>
      </div>
      <div className="lc-table-wrap">
        <table className="lc-table">
          <caption>{t("responseRateByActivity")}</caption>
          <thead>
            <tr>
              <th scope="col">#</th>
              <th scope="col">{t("activityColumn")}</th>
              <th scope="col">{t("responsesColumn")}</th>
              <th scope="col">{t("rate")}</th>
              <th scope="col">{t("staleColumn")}</th>
              <th scope="col">{t("stateColumn")}</th>
            </tr>
          </thead>
          <tbody id="analytics-activities">
            {!activities.length ? (
              <tr>
                <td colSpan={6}>{t("noActivitiesYet")}</td>
              </tr>
            ) : (
              activities.map((activity) => (
                <tr key={String(activity.id)}>
                  <td>{String(activity.sequence ?? "")}</td>
                  <td>{String(activity.title || activity.kind)}</td>
                  <td>
                    {String(activity.submitted_count ?? 0)}/{String(activity.eligible_participant_count ?? 0)}
                  </td>
                  <td>{String(activity.response_rate ?? 0)}%</td>
                  <td>{String(activity.stale_submission_count ?? 0)}</td>
                  <td>{activityState(activity.state)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <div className="lc-table-wrap">
        <table className="lc-table">
          <caption>{t("participantAttendance")}</caption>
          <thead>
            <tr>
              <th scope="col">{t("participantColumn")}</th>
              <th scope="col">{t("admission")}</th>
              <th scope="col">{t("current")}</th>
              <th scope="col">{t("staleColumn")}</th>
              <th scope="col">{t("connection")}</th>
            </tr>
          </thead>
          <tbody id="analytics-participants">
            {!participants.length ? (
              <tr>
                <td colSpan={5}>{t("noParticipantsYet")}</td>
              </tr>
            ) : (
              participants.map((participant) => (
                <tr key={String(participant.id)}>
                  <td>{String(participant.display_name)}</td>
                  <td>{admissionState(participant.admission_state)}</td>
                  <td>{String(participant.current_response_count ?? 0)}</td>
                  <td>{String(participant.stale_response_count ?? 0)}</td>
                  <td>{participant.connected_at ? (participant.disconnected_at ? t("offline") : t("connected")) : t("notConnected")}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <div className="lc-table-wrap">
        <table className="lc-table">
          <caption id="analytics-responses-caption">
            {current ? `${t("responses")}: ${String(current.title || current.kind)}` : t("responsesForCurrentActivity")}
          </caption>
          <thead>
            <tr>
              <th scope="col">{t("participantColumn")}</th>
              <th scope="col">{t("answerColumn")}</th>
              <th scope="col">{t("statusColumn")}</th>
            </tr>
          </thead>
          <tbody id="analytics-responses">
            {!current || !responses.length ? (
              <tr>
                <td colSpan={3}>{current ? t("noResponses") : t("publishToReview")}</td>
              </tr>
            ) : (
              responses.map((response, index) => (
                <tr key={index}>
                  <td>{String(response.display_name)}</td>
                  <td className={activity && activityKind(activity) === "essay" ? "lc-essay-response" : undefined}>{readableResponse(response.answer, activity, tr("Completed", "已完成"))}</td>
                  <td>{response.is_stale ? t("staleColumn") : t("current")}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function TeacherConsole({ bootstrap }: { bootstrap: TeacherBootstrap }) {
  const t = useT();
  const stateUrl = bootstrap.stateUrl!;
  const canManage = bootstrap.capabilities.includes("manage_session");
  const canAdmit = bootstrap.capabilities.includes("manage_admission");
  const locale = useLocale();
  const tr = (en:string,zh:string) => locale.startsWith("zh") ? zh : en;
  const sync = useSessionState({ stateUrl, websocketPath: bootstrap.websocketUrl, channel: canManage ? "display" : "participants", enabled: true });
  const state = sync.state;
  const { run, status, setStatus, pending: commandPending } = useCommand(stateUrl, sync.refresh);
  const serverCurrentActivityId = state?.current_activity?.id ?? null;
  const [activitySelection, selectActivity] = useQuerySelection(
    "activity",
    serverCurrentActivityId === null ? "" : String(serverCurrentActivityId),
  );
  const [panelSelection, selectPanel] = useQuerySelection("panel", "responses");
  const [analytics, setAnalytics] = useState<Record<string, unknown> | null>(null);
  const [participants, setParticipants] = useState<Array<Record<string, unknown>>>([]);
  const [chat, setChat] = useState<{ enabled: boolean; messages: Array<{ id: number; display_name: string; body: string }> } | null>(null);
  const [history,setHistory] = useState<Array<ActivityState & {reviewable:boolean;review_visibility:Record<string,boolean>}>>([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [planSteps, setPlanSteps] = useState<PresenterStep[]>([]);
  const [previewStep, setPreviewStep] = useState<PresenterStep | null>(null);
  const [holdStudents, setHoldStudents] = useState(false);
  const [chatBody, setChatBody] = useState("");
  const [supportingError, setSupportingError] = useState("");
  const [supportRefresh, setSupportRefresh] = useState(0);
  const supportGeneration = useRef(0);

  const stateVersion = state?.state_version ?? 0;

  useEffect(() => {
    if (!state) return;
    const generation = ++supportGeneration.current;
    setHistoryLoaded(false);
    const failed = (err?: unknown) => {
      if (err) console.warn("Failed to load classroom details:", err);
    };
    void getJson<{activities:typeof history}>(apiEndpoint(stateUrl,"sessions/history")).then(d=>{ if (supportGeneration.current === generation) { setHistory(d.activities); setHistoryLoaded(true); } }).catch(failed);
    void getJson<{steps: PresenterStep[]}>(apiEndpoint(stateUrl, "sessions/plan")).then(d => { if (supportGeneration.current === generation) setPlanSteps(d.steps ?? []); }).catch((err) => console.warn("Could not load plan steps:", err));
    void getJson<Record<string, unknown>>(apiEndpoint(stateUrl, "sessions/analytics"))
      .then((data) => { if (supportGeneration.current === generation) setAnalytics(data); })
      .catch((err) => console.warn("Could not load analytics:", err));
    void getJson<{ participants: Array<Record<string, unknown>> }>(apiEndpoint(stateUrl, "sessions/participants"))
      .then((d) => { if (supportGeneration.current === generation) setParticipants(d.participants); })
      .catch((err) => console.warn("Could not load participants:", err));
    void getJson<{ enabled: boolean; messages: Array<{ id: number; display_name: string; body: string }> }>(apiEndpoint(stateUrl, "sessions/chat"))
      .then((data) => { if (supportGeneration.current === generation) setChat(data); })
      .catch((err) => console.warn("Could not load chat:", err));
  }, [stateUrl, stateVersion, supportRefresh]);

  useEffect(() => {
    if (!state || !historyLoaded) return;
    const selectedId = activityIdFromQuery(activitySelection);
    const available = selectedId !== null && (
      selectedId === serverCurrentActivityId
      || history.some((activity) => activity.id === selectedId)
    );
    if (available) return;
    if (serverCurrentActivityId === null) {
      if (activitySelection) selectActivity("", { replace: true });
    } else if (activitySelection !== String(serverCurrentActivityId)) {
      selectActivity(String(serverCurrentActivityId), { replace: true });
    }
  }, [activitySelection, history, historyLoaded, selectActivity, serverCurrentActivityId, state]);

  useEffect(() => {
    if (panelSelection === "current") {
      selectPanel("responses", { replace: true });
      return;
    }
    const available = new Set<ConsolePanel>(["responses", "results", "lesson", "students"]);
    if (canManage) {
      available.add("decks");
      available.add("more");
      if (state?.session.status === "live") available.add("content");
    }
    if (isConsolePanel(panelSelection) && available.has(panelSelection)) return;
    selectPanel("responses", { replace: true });
  }, [canManage, panelSelection, selectPanel, state?.session.status]);

  const selectedId = activityIdFromQuery(activitySelection);
  const focused = history.find((activity) => activity.id === (selectedId ?? serverCurrentActivityId))
    ?? (selectedId === serverCurrentActivityId ? state?.current_activity : null)
    ?? state?.current_activity
    ?? null;
  const pending = participants.filter((p) => p.admission_state === "pending");
  const studentsHeld = holdStudents || Boolean(
    state?.channels?.participants?.activity
    && state.channels.participants.activity.id !== state.channels.display?.activity?.id
  );

  useEffect(() => {
    if (state?.session.status) {
      window.dispatchEvent(new CustomEvent("liveclassroom:session-state", {
        detail: {
          status: state.session.status,
          joinCode: bootstrap.joinCode,
          title: bootstrap.sessionTitle,
        }
      }));
    }
  }, [state?.session.status, bootstrap.joinCode, bootstrap.sessionTitle]);

  const [codeCopied, setCodeCopied] = useState(false);
  const copyJoinCode = async () => {
    if (bootstrap.joinCode && navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(bootstrap.joinCode);
        setCodeCopied(true);
        setTimeout(() => setCodeCopied(false), 2000);
      } catch {
        // clipboard unavailable
      }
    }
  };
  const sessionActions = <div className="lc-session-header-actions">
    <span id="session-status" className={`lc-status-pill lc-status-${state?.session.status ?? "draft"}`} role="status">
      {state?.session.status === "live" ? <><span className="lc-live-dot" aria-hidden="true" />{t("liveClass")}</> : state?.session.status === "paused" ? <><span aria-hidden="true">❚❚ </span>{t("classPaused")}</> : state?.session.status === "ended" ? <>{t("teachingEnded")}</> : <>{t("startClass")}</>}
    </span>
    {canManage && <LifecycleControls state={state} run={run} startingStepId={previewStep?.id ?? planSteps[0]?.id ?? null} pending={commandPending} onStarted={() => setPreviewStep(null)} />}
    <InviteControls bootstrap={bootstrap} />
    {canManage ? <a href={bootstrap.studentViewUrl} className="lc-btn lc-btn-outline lc-student-view-btn" target="_blank" rel="noopener noreferrer">{t("studentView")}</a> : null}
  </div>;
  const sessionActionSlot = React.useSyncExternalStore(
    subscribeSessionActionSlot,
    getSessionActionSlot,
    () => null,
  );
  const [sessionSlotResolved, setSessionSlotResolved] = useState(false);
  useEffect(() => {
    setSessionSlotResolved(true);
  }, []);
  const navigateConsoleTabs = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    const tabs = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('[role="tab"]'));
    const current = tabs.indexOf(event.target as HTMLButtonElement);
    if (current < 0 || !tabs.length) return;
    event.preventDefault();
    const index = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (current + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
    const tab = tabs[index];
    tab.focus();
    const panel = tab.id.replace("tab-btn-", "");
    if (isConsolePanel(panel)) selectPanel(panel);
  };

  return (
    <>
      {sessionActionSlot ? createPortal(sessionActions, sessionActionSlot) : null}
      <header className="lc-session-command-bar">
        <div className="lc-session-header-primary">
          <div className="lc-session-title-group">
            <h1 className="lc-session-title">{bootstrap.sessionTitle || bootstrap.flowTitle || t("instantSession")}</h1>
            {bootstrap.flowTitle && bootstrap.flowTitle !== bootstrap.sessionTitle ? (
              <span className="lc-session-flow-tag">{bootstrap.flowTitle}</span>
            ) : null}
          </div>
        </div>
        {sessionSlotResolved && !sessionActionSlot ? sessionActions : null}
      </header>
      <PresenterStage state={state} steps={planSteps} stateUrl={stateUrl} onRefresh={sync.refresh} canManage={canManage} onError={setStatus} onPreviewChange={setPreviewStep} deliveryChannel={studentsHeld ? "display" : "both"} />
      {studentsHeld && state?.channels?.participants?.activity ? <div className="lc-audience-held" role="status">
        <span>{t("studentsHeld")} <strong>{activityTitle(state.channels.participants.activity, t("activity"))}</strong></span>
        <button type="button" className="lc-btn lc-btn-sm lc-btn-outline" disabled={commandPending || state.session.status !== "live"} onClick={() => {
          const displayId = state.channels?.display?.activity?.id;
          const step = planSteps.find((item) => item.activity_id === displayId);
          if (step) void run(`sessions/plan/${step.id}/launch`, { channel: "both" }).then((ok) => { if (ok) setHoldStudents(false); });
        }}>{t("bringStudents")}</button>
      </div> : null}
      {status ? <p className="lc-builder-status-error" role="status">{status} <button type="button" className="lc-dismiss-btn" onClick={() => setStatus("")}>✕</button></p> : null}
      {sync.error ? <p className="lc-builder-status-error" role="status">{sync.error} <button type="button" className="lc-btn lc-btn-sm lc-btn-outline" onClick={() => void sync.refresh()}>{tr("Retry", "重试")}</button></p> : sync.reconnecting ? <p role="status">{t("reconnecting")}</p> : null}
      {state?.session.status === "ended" ? <div className="lc-actions"><a className="lc-btn lc-btn-outline" href="#results">{t("viewResults")}</a><button type="button" className="lc-btn lc-btn-outline" onClick={() => { const endpoint = new URL(stateUrl, window.location.href); endpoint.pathname = endpoint.pathname.replace(/sessions\/\d+\/state\/?$/, "sessions/"); void postJson<{ console_url: string }>(endpoint.toString(), { title: `${bootstrap.sessionTitle} — ${t("teachAgain")}`, source_session_id: state.session.id }, idempotencyKey("teach-again")).then(({ console_url }) => window.location.assign(console_url)).catch((error) => setStatus(error instanceof Error ? error.message : t("unavailable"))); }}>{t("teachAgain")}</button></div> : null}

      <div className="lc-console-tabs-section">
        <div className="lc-console-tabs-bar" role="tablist" aria-label={tr("Classroom management tabs", "课堂管理功能区")} onKeyDown={navigateConsoleTabs}>
          <button type="button" role="tab" id="tab-btn-responses" aria-controls="console-panel-responses" aria-selected={panelSelection === "responses"} className={`lc-console-tab-btn ${panelSelection === "responses" ? "active" : ""}`} onClick={() => selectPanel("responses")}>
            <Icon name="results" size={16} />{tr("Responses", "答题情况")}
          </button>
          {canManage && (
            <button
              type="button"
              role="tab"
              id="tab-btn-decks"
              aria-controls="console-panel-decks"
              aria-selected={panelSelection === "decks"}
              className={`lc-console-tab-btn ${panelSelection === "decks" ? "active" : ""}`}
              onClick={() => selectPanel("decks")}
            >
              <Icon name="deck" size={16} />{tr("Slide decks", "原生幻灯片")}
            </button>
          )}
          {canManage && state?.session.status === "live" && (
            <button
              type="button"
              role="tab"
              id="tab-btn-content"
              aria-controls="console-panel-content"
              aria-selected={panelSelection === "content"}
              className={`lc-console-tab-btn ${panelSelection === "content" ? "active" : ""}`}
              onClick={() => selectPanel("content")}
            >
              <Icon name="join" size={16} />{tr("Add content", "添加内容")}
            </button>
          )}
          <button
            type="button"
            role="tab"
            id="tab-btn-results"
            aria-controls="console-panel-results"
            aria-selected={panelSelection === "results"}
            className={`lc-console-tab-btn ${panelSelection === "results" ? "active" : ""}`}
            onClick={() => selectPanel("results")}
          >
            <Icon name="results" size={16} />{tr("Results", "结果")}
          </button>
          <button
            type="button"
            role="tab"
            id="tab-btn-lesson"
            aria-controls="console-panel-lesson"
            aria-selected={panelSelection === "lesson"}
            className={`lc-console-tab-btn ${panelSelection === "lesson" ? "active" : ""}`}
            onClick={() => selectPanel("lesson")}
          >
            <Icon name="lesson" size={16} />{tr("Edit lesson", "编辑教案")}
          </button>
          <button
            type="button"
            role="tab"
            id="tab-btn-students"
            aria-controls="console-panel-students"
            aria-selected={panelSelection === "students"}
            className={`lc-console-tab-btn ${panelSelection === "students" ? "active" : ""}`}
            onClick={() => selectPanel("students")}
          >
            <Icon name="students" size={16} />{tr("Students", "学生")}
            {pending.length > 0 ? <span className="lc-tab-badge">({pending.length})</span> : null}
          </button>
          {canManage && (
            <button
              type="button"
              role="tab"
              id="tab-btn-more"
              aria-controls="console-panel-more"
              aria-selected={panelSelection === "more"}
              className={`lc-console-tab-btn ${panelSelection === "more" ? "active" : ""}`}
              onClick={() => selectPanel("more")}
            >
              <Icon name="settings" size={16} />{tr("Settings", "设置")}
            </button>
          )}
        </div>

        {panelSelection && (
          <div id={`console-panel-${panelSelection}`} className="lc-console-tab-pane" role="tabpanel" aria-labelledby={`tab-btn-${panelSelection}`}>
            <div className="lc-console-tab-pane-header">
              <h3 className="lc-console-tab-pane-title">
                {panelSelection === "responses" && <>{tr("Responses", "答题情况")}</>}
                {panelSelection === "decks" && <><Icon name="deck" size={16} />{tr("Slide decks", "原生幻灯片")}</>}
                {panelSelection === "content" && <><Icon name="join" size={16} />{tr("Add content", "添加内容")}</>}
                {panelSelection === "results" && <><Icon name="results" size={16} />{tr("Results", "结果")}</>}
                {panelSelection === "lesson" && <><Icon name="lesson" size={16} />{tr("Edit lesson", "编辑教案")}</>}
                {panelSelection === "students" && <><Icon name="students" size={16} />{tr("Students", "学生")}{pending.length ? ` (${pending.length})` : ""}</>}
                {panelSelection === "more" && <><Icon name="settings" size={16} />{tr("Session settings", "课堂设置")}</>}
              </h3>
            </div>
            <div className="lc-console-tab-pane-content">
              {panelSelection === "responses" && <LiveResults state={state} analytics={analytics} run={run} pending={commandPending} canManage={canManage} />}
              {panelSelection === "decks" && canManage && (
                <NativeDeckPresenter bootstrap={bootstrap} state={state} stateUrl={stateUrl} onRefresh={sync.refresh} planSteps={planSteps} />
              )}
              {panelSelection === "content" && canManage && state?.session.status === "live" && (
                <FilePicker
                  endpoint={apiEndpoint(stateUrl, "sessions/files")}
                  isSuperuser={bootstrap.isSuperuser}
                  includeChannels
                  onSuccess={() => void sync.refresh()}
                />
              )}
              {panelSelection === "results" && (
                <>
                  <label className="lc-field lc-results-activity-field">{tr("Activity to inspect", "选择查看的活动")}<select value={activitySelection || (serverCurrentActivityId === null ? "" : String(serverCurrentActivityId))} onChange={(event) => selectActivity(event.target.value)}>{serverCurrentActivityId !== null && state?.current_activity ? <option value={String(serverCurrentActivityId)}>{activityTitle(state.current_activity, t("activity"))}</option> : <option value="" disabled>{tr("No current display activity", "当前没有投屏活动")}</option>}{history.filter((activity) => activity.id !== serverCurrentActivityId).map((activity) => <option key={activity.id} value={activity.id}>{activityTitle(activity,t("activity"))}</option>)}</select></label>
                  <div className="lc-actions lc-export-actions">{canAdmit && <>{["summary","responses","participants","chat"].map(dataset=><a className="lc-btn lc-btn-outline lc-btn-sm" key={dataset} href={`${bootstrap.exportUrl}?format=csv&dataset=${dataset}`}><Icon name="download" size={14} />{({summary:tr("Summary","汇总"),responses:tr("Responses","答案"),participants:tr("Attendance","出席"),chat:tr("Chat","聊天")} as Record<string,string>)[dataset]} CSV</a>)}<a className="lc-btn lc-btn-outline lc-btn-sm" href={bootstrap.exportUrl}><Icon name="download" size={14} />JSON</a></>}</div>
                  <AnalyticsPanel analytics={analytics} activity={focused} />
                </>
              )}
              {panelSelection === "lesson" && (
                <SessionPlanPanel stateUrl={stateUrl} state={state} onRefresh={sync.refresh}/>
              )}
              {panelSelection === "students" && (
                <div id="students-panel">
                  <ParticipantPreview state={state} stateUrl={stateUrl} />
                  {canAdmit && pending.length ? (
                    <section data-liveclassroom-admission>
                      <h2>
                        {t("participants")} ({pending.length} {t("pending")})
                      </h2>
                      {pending.map((participant) => (
                        <button
                          key={String(participant.id)}
                          onClick={() => void run(`sessions/participants/${participant.id}/admission`, { admitted: true })}
                        >
                          {t("admit")} {stringValue(participant.display_name)}
                        </button>
                      ))}
                    </section>
                  ) : null}
                  <section className="lc-chat" data-liveclassroom-chat aria-labelledby="chat-heading">
                    <h2 id="chat-heading">{t("chat")}</h2>
                    <p data-liveclassroom-chat-status aria-live="polite">{chat ? (chat.enabled ? "" : t("chatDisabled")) : ""}</p>
                    <ul data-liveclassroom-chat-messages aria-live="polite">
                      {chat && chat.messages.length
                        ? chat.messages.map((m) => (
                            <li key={m.id}>
                              <strong>{m.display_name}: </strong>
                              {m.body}
                            </li>
                          ))
                        : <li>{chat?.enabled ? t("noMessages") : t("chatDisabled")}</li>}
                    </ul>
                    {canAdmit && <div data-liveclassroom-chat-settings>
                      <label>
                        <input
                          type="checkbox"
                          checked={chat?.enabled ?? false}
                          disabled={state?.session.status === "ended"}
                          onChange={(e) => void run("sessions/chat/settings", { enabled: e.target.checked })}
                        />{" "}
                        {t("enableChat")}
                      </label>
                    </div>}
                    <form
                      hidden={!canAdmit || state?.session.status!=="live"}
                      data-liveclassroom-chat-form
                      onSubmit={(e) => {
                        e.preventDefault();
                        const body = chatBody.trim();
                        if (!body) return;
                        void run("sessions/chat/send", { body }).then(() => setChatBody(""));
                      }}
                    >
                      <label className="lc-field">
                        <span>{t("message")}</span><textarea name="body" rows={2} maxLength={4000} value={chatBody} onChange={(e) => setChatBody(e.target.value)} />
                      </label>
                      <div className="lc-actions"><button type="submit" className="lc-btn lc-btn-primary">{t("send")}</button></div>
                    </form>
                  </section>
                </div>
              )}
              {panelSelection === "more" && canManage && (
                <div className="lc-console-panel-content">
                  <AudienceControls state={state} steps={planSteps} holdStudents={holdStudents} setHoldStudents={setHoldStudents} run={run} />
                  <ChannelControls state={state} run={run} />{focused && <fieldset className="lc-review-access"><legend>{tr("Student review access","学生复习权限")}</legend>
                  <p className="lc-workspace-meta">{tr("Applies to", "应用于")}: <strong>{activityTitle(focused, t("activity"))}</strong></p>
                  <label><input type="checkbox" checked={Boolean((focused as typeof history[number]).reviewable)} onChange={e=>void run(`activities/${focused.id}/review`,{reviewable:e.target.checked})}/>{tr("Allow review","允许复习")}</label>
                  {(["show_answer","show_explanation"] as const).map(field=><label key={field}><input type="checkbox" checked={Boolean((focused as typeof history[number]).review_visibility?.[field])} onChange={e=>void run(`activities/${focused.id}/review`,{[field]:e.target.checked})}/>{field==="show_answer"?t("showAnswer"):t("showExplanation")}</label>)}
                  </fieldset>}
                  {["draft", "ended"].includes(state?.session.status ?? "") && <section className="lc-delete-classroom"><p>{tr("Deleting removes this classroom and its records. The reusable lesson remains.", "删除会移除此课堂及其记录；可复用教案会保留。")}</p><button className="lc-btn lc-btn-outline lc-btn-end" onClick={()=>{if(window.confirm(tr("Delete this classroom permanently? Its classroom records will be removed; its reusable lesson remains.","永久删除本次课堂吗？课堂记录将被移除，教案会保留。"))) void postJson(apiEndpoint(stateUrl,"sessions/delete"),{confirm:true},idempotencyKey("delete-classroom")).then(()=>window.location.assign(bootstrap.workspaceUrl)).catch(error=>window.alert(error instanceof Error?error.message:tr("Delete failed","删除失败")));}}>{tr("Delete classroom","删除课堂")}</button></section>}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </>
  );
}

export function mountTeacherConsole(el: HTMLElement): void {
  const bootstrap = readTeacherBootstrap(el);
  if (!bootstrap.stateUrl) return;
  const root = createRoot(el);
  root.render(
    <LocaleProvider initial={bootstrap.locale} root={el}>
      <TeacherConsole bootstrap={bootstrap} />
    </LocaleProvider>,
  );
  el.addEventListener("liveclassroom:unmount", () => root.unmount(), { once: true });
}
