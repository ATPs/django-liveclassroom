import { SessionPlanPanel } from "./SessionPlanPanel.js";
import * as React from "react";
import { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { readBootstrap, type Bootstrap } from "../../bootstrap.js";
import { LanguageSwitcher, LocaleProvider, useLocale, useT } from "../../i18n.js";
import {
  apiEndpoint,
  getJson,
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

function readTeacherBootstrap(root: HTMLElement): TeacherBootstrap {
  const base = readBootstrap(root);
  const d = root.dataset;
  let flowSteps: TeacherBootstrap["flowSteps"] = [];
  try {
    flowSteps = JSON.parse(d.flowSteps ?? "[]") as TeacherBootstrap["flowSteps"];
  } catch {
    flowSteps = [];
  }
  return {
    ...base,
    capabilities: JSON.parse(d.capabilities ?? "[]") as string[],
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
  if (status === "ended") return <p role="status">{t("teachingEnded")}</p>;
  if (status === "paused") return <button id="start-session" className="lc-btn-primary" disabled={pending} onClick={() => void run("sessions/start").then((ok) => { if (ok) onStarted(); })}>{t("resumeClass")}</button>;
  if (status === "live") return <div className="lc-actions"><span className="lc-live-status" role="status">{t("liveClass")}</span><details className="lc-class-menu"><summary>{t("classMenu")}</summary><div className="lc-actions"><button id="pause-session" disabled={pending} onClick={() => void run("sessions/pause")}>{t("pause")}</button><button id="end-session" className="lc-btn-danger" disabled={pending} onClick={() => { if (window.confirm(t("confirmEnd"))) void run("sessions/end"); }}>{t("endClass")}</button></div></details></div>;
  return (
    <div className="lc-actions" aria-label={t("controls")}>
      <button id="start-session" className="lc-btn-primary" disabled={pending} onClick={() => void run("sessions/start", startingStepId ? { plan_step_id: startingStepId } : {}).then((ok) => { if (ok) onStarted(); })}>{t("startClass")}</button>
    </div>
  );
}

function InviteControls({ bootstrap }: { bootstrap: TeacherBootstrap }) {
  const t = useT();
  const [notice, setNotice] = useState("");
  const copy = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setNotice(t("copied"));
    } catch {
      setNotice(t("unavailable"));
    }
  };
  return <details className="lc-invite-controls"><summary>{t("inviteStudents")}</summary>
    <figure className="lc-join-qr">
      <img src={bootstrap.qrUrl} alt={`${t("joinCode")}: ${bootstrap.sessionTitle}`} />
      <figcaption>{t("studentJoinCode")}: {bootstrap.joinCode}</figcaption>
    </figure>
    <div className="lc-actions"><button type="button" onClick={() => void copy(new URL(bootstrap.joinUrl, window.location.href).toString())}>{t("copyJoinLink")}</button><button type="button" onClick={() => void copy(bootstrap.joinCode)}>{t("copyJoinCode")}</button><a href={bootstrap.joinUrl}>{t("studentJoinPage")}</a>{bootstrap.capabilities.includes("view_display") ? <a href={bootstrap.displayUrl}>{t("openDisplay")}</a> : null}</div><p aria-live="polite">{notice}</p>
  </details>;
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
  return <section className="lc-grid">{(["display","participants"] as const).map(channel=>{
    const current=state?.channels?.[channel];
    const visibility=current?.visibility??DEFAULT_PARTICIPANT_VISIBILITY;
    return <fieldset key={channel}><legend>{channel==="display"?t("display"):t("participants")}</legend>
      <p>{current?.activity?activityTitle(current.activity,t("activity")):t("noActivityPublished")}</p>
      <button disabled={!selected||state?.session.status!=="live"} onClick={()=>selected&&void run("sessions/channels/publish",{channel,activity_id:selected.id})}>{t("publish")}</button>
      {fields.map(([field,label])=><label key={field} style={{display:"block"}}><input type="checkbox" checked={visibility[field]} disabled={!current?.activity||state?.session.status==="ended"} onChange={e=>void run("sessions/channels/settings",{channel,[field]:e.target.checked})}/>{label}</label>)}
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
      <button type="button" disabled={!currentStep || state?.session.status !== "live" || restoring} onClick={bringStudents}>{t("bringStudents")}</button>
    </div> : null}
    <details className="lc-audience-panel"><summary>{t("audience")}</summary>
      <p>{held ? t("studentsHeld") : t("studentsFollow")}</p>
      <label><input type="checkbox" checked={held} disabled={state?.session.status !== "live" || restoring} onChange={(event) => event.target.checked ? setHoldStudents(true) : bringStudents()} /> {t("keepStudents")}</label>
    </details>
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
      await postJson(apiEndpoint(stateUrl, `activities/${activity.id}/timer`), { action }, `timer-${activity.id}-${action}-${crypto.randomUUID()}`);
      await onRefresh();
    } catch (error) {
      onError(error instanceof Error ? error.message : "Unable to update timer.");
    } finally {
      setPending(false);
    }
  };
  const disabled = pending || state?.session.status !== "live";
  return <div className="lc-actions" aria-label={t("timer")}>
    {runtime?.status === "running" ? <button type="button" disabled={disabled} onClick={() => void send("pause")}>{t("pauseTimer")}</button> : null}
    {runtime?.status === "paused" ? <button type="button" disabled={disabled} onClick={() => void send("resume")}>{t("resumeTimer")}</button> : null}
    {runtime?.status === "idle" ? <button type="button" disabled={disabled} onClick={() => void send("start")}>{t("startTimer")}</button> : null}
    <button type="button" disabled={disabled} onClick={() => void send("reset")}>{t("resetTimer")}</button>
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

type PresenterStep = { id: number; position: number; title: string; activity_id: number | null; snapshot?: Record<string, unknown> };

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
  const intentKeys = useRef(new Map<string, string>());
  const stepButtons = useRef(new Map<number, HTMLButtonElement>());
  const choosePreview = (step: PresenterStep | null) => {
    setPreview(step);
    onPreviewChange(step);
  };
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
    const key = intentKeys.current.get(intent) ?? `present-${channel}-${step.id}-${crypto.randomUUID()}`;
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
  return <section className="lc-presenter" aria-label={tr("Presenter workspace", "演示者工作区")}>
    <div className="lc-presenter-current">
      <p className="lc-presenter-label">{draftPreview ? tr("Private preview", "私有预览") : tr("Now showing", "当前展示")}</p>
      {draftPreview ? <>
        <p>{tr("Students cannot see this item. Start class to publish it.", "学生看不到此项目。开始课堂后才会发布。")}</p>
        <TeacherActivityView activity={previewActivity} aggregate={null} state={state} stateUrl={stateUrl} onRefresh={onRefresh} onError={onError} />
      </> : state?.current_deck && !state.current_activity ? <NativeDeckView deck={state.current_deck} state={state} audience="teacher" stateUrl={stateUrl} /> : <TeacherActivityView activity={state?.current_activity ?? null} aggregate={state?.aggregate ?? null} state={state} stateUrl={stateUrl} onRefresh={onRefresh} onError={onError} />}
    </div>
    <aside className="lc-presenter-next">
      <p className="lc-presenter-label">{tr("Up next", "下一项")}</p>
      {draftPreview ? <p>{tr("Choose any lesson item to preview it before starting.", "开始前可选择任意教案项目进行预览。")}</p> : preview ? <><h2>{preview.position}. {presentationTitle(preview.title)}</h2><p>{tr("Private preview — students cannot see this item.", "私有预览——学生不会看到此项目。")}</p>
        <TeacherActivityView activity={previewActivity} aggregate={null} state={state} stateUrl={stateUrl} onRefresh={onRefresh} onError={onError} />
        <button className="lc-btn-primary" disabled={!canManage || pending || state?.session.status !== "live"} onClick={() => { void present(preview, deliveryChannel).then((published) => { if (published) choosePreview(null); }); }}>{tr("Show this item", "展示此项目")}</button>
        <button onClick={() => choosePreview(null)}>{tr("Return", "返回")}</button></> : next ? <><h2>{next.position}. {presentationTitle(next.title)}</h2><p>{tr("Students follow by default.", "学生默认跟随演示。")}</p>
        <button disabled={!canManage} onClick={() => choosePreview(next)}>{tr("Preview", "预览")}</button></> : <p>{tr("Last item.", "最后一项。")}</p>}
      <p className="lc-presenter-status">{tr("Student channel", "学生端")}: {state?.channels?.participants?.activity?.id === currentId ? tr("following", "跟随") : state?.channels?.participants?.activity ? `${tr("held on", "停留在")} “${activityTitle(state.channels.participants.activity, t("activity"))}”` : tr("waiting", "等待中")}</p>
    </aside>
    <details className="lc-presenter-drawer">
      <summary>{tr("Lesson items", "教案项目")}</summary>
      <nav className="lc-presenter-strip" aria-label={tr("Lesson outline", "教案目录")}>
      {steps.map((step) => <button type="button" ref={(element) => { if (element) stepButtons.current.set(step.id, element); else stepButtons.current.delete(step.id); }} key={step.id} aria-current={step.activity_id === currentId ? "step" : undefined} disabled={!canManage || pending || state?.session.status === "ended" || step.activity_id === currentId} onClick={() => state?.session.status === "live" ? void present(step, deliveryChannel) : choosePreview(step)} className={step.activity_id === currentId ? "lc-presenter-step lc-presenter-step-current" : "lc-presenter-step"}>{step.position}. {presentationTitle(step.title)}</button>)}
      </nav>
    </details>
    <div className="lc-presenter-navigation">
      <button type="button" disabled={!canManage || pending || !previous || state?.session.status !== "live"} onClick={() => previous && void present(previous, deliveryChannel)}>{tr("Previous", "上一项")}</button>
      <span>{currentIndex >= 0 ? `${currentIndex + 1} / ${steps.length}` : `0 / ${steps.length}`}</span>
      <button type="button" disabled={!canManage || pending || !next || state?.session.status !== "live"} onClick={() => next && void present(next, deliveryChannel)}>{tr("Next", "下一项")}</button>
    </div>
    {failed ? <p className="lc-builder-status-error" role="status">{tr("Could not publish this item.", "无法发布此项目。")} <button type="button" onClick={() => void present(failed.step, failed.channel)}>{tr("Retry", "重试")}</button></p> : null}
  </section>;
}

type DeckSummary = { id: number; title: string; version: number };
type DeckSnapshotSummary = { id: number; source_version: number; title: string; slides?: unknown[] };

function NativeDeckPresenter({
  bootstrap, state, stateUrl, onRefresh,
}: {
  bootstrap: TeacherBootstrap;
  state: SessionState | null;
  stateUrl: string;
  onRefresh: () => Promise<void>;
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
      }, `deck-present-${snapshot.id}-${crypto.randomUUID()}`);
      await onRefresh();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : tr("Unable to present deck.", "无法展示幻灯片。"));
    } finally {
      setPending(false);
    }
  };

  return <details className="lc-console-panel" data-native-deck-presenter>
    <summary>{tr("Native decks", "原生幻灯片")}</summary>
    <label>{tr("Deck", "幻灯片")}{" "}
      <select value={deckId ?? ""} onChange={(event) => setDeckId(event.target.value ? Number(event.target.value) : null)}>
        <option value="">{tr("Choose a deck", "选择幻灯片")}</option>
        {decks.map((deck) => <option value={deck.id} key={deck.id}>{deck.title}</option>)}
      </select>
    </label>
    {selectedDeck ? <div className="lc-actions">
      {snapshots.map((snapshot) => <button type="button" key={snapshot.id} disabled={pending || state?.session.status !== "live"} onClick={() => void present(snapshot)}>{tr("Present", "展示")} {snapshot.title} ({snapshot.slides?.length ?? "?"})</button>)}
      {!snapshots.length ? <p>{tr("Create a snapshot from the deck editor first.", "请先在幻灯片编辑器中创建快照。")} </p> : null}
    </div> : null}
    {status ? <p role="status" className="lc-builder-status-error">{status}</p> : null}
  </details>;
}

function LiveResults({
  state,
  analytics,
  run,
  pending,
}: {
  state: SessionState | null;
  analytics: Record<string, unknown> | null;
  run: (s: string, body?: Record<string, unknown>) => Promise<boolean>;
  pending: boolean;
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
    <section id="results">
      <h2>{t("results")}</h2>
      <p id="activity-status">{activity ? t("responsesForCurrentActivity") : t("noActivityPublished")}</p>
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
          <p>{t("noActivityPublished")}</p>
        )}
      </div>
      <button id="close-activity" disabled={pending || !live || !activity || activity.state !== "open"} onClick={() => activity && void run(`activities/${activity.id}/close`)}>
        {t("close")}
      </button>
      <button type="button" disabled={pending || !live || !activity} onClick={() => void setVisibility("show_aggregate", !visibility?.show_aggregate)}>{visibility?.show_aggregate ? t("hideResults") : t("showResults")}</button>
      {hasAnswer ? <button id="reveal-activity" disabled={pending || !live || !activity || activity.state === "revealed"} onClick={() => activity && void run(`activities/${activity.id}/close-and-show-answer`)}>{t("showAnswer")}</button> : null}
      {hasExplanation ? <button type="button" disabled={pending || !live || !activity} onClick={() => void setVisibility("show_explanation", !visibility?.show_explanation)}>{visibility?.show_explanation ? t("hideExplanation") : t("showExplanation")}</button> : null}
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

function AnalyticsPanel({ stateUrl, analytics, activity }: { stateUrl: string; analytics: Record<string, unknown> | null; activity: ActivityState | null }) {
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
        <a href={`${stateUrl.replace(/state\/?$/, "export/")}?format=csv&dataset=summary`}>{t("save")} CSV</a>
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
  const [analytics, setAnalytics] = useState<Record<string, unknown> | null>(null);
  const [participants, setParticipants] = useState<Array<Record<string, unknown>>>([]);
  const [chat, setChat] = useState<{ enabled: boolean; messages: Array<{ id: number; display_name: string; body: string }> } | null>(null);
  const [selectedId,setSelectedId] = useState<number|null>(null);
  const [history,setHistory] = useState<Array<ActivityState & {reviewable:boolean;review_visibility:Record<string,boolean>}>>([]);
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
    setSupportingError("");
    const failed = () => {
      if (supportGeneration.current === generation) setSupportingError(tr("Some classroom details could not be refreshed.", "部分课堂信息无法刷新。"));
    };
    void getJson<{activities:typeof history}>(apiEndpoint(stateUrl,"sessions/history")).then(d=>{ if (supportGeneration.current === generation) setHistory(d.activities); }).catch(failed);
    void getJson<{steps: PresenterStep[]}>(apiEndpoint(stateUrl, "sessions/plan")).then(d => { if (supportGeneration.current === generation) setPlanSteps(d.steps ?? []); }).catch(failed);
    void getJson<Record<string, unknown>>(apiEndpoint(stateUrl, "sessions/analytics"))
      .then((data) => { if (supportGeneration.current === generation) setAnalytics(data); })
      .catch(failed);
    void getJson<{ participants: Array<Record<string, unknown>> }>(apiEndpoint(stateUrl, "sessions/participants"))
      .then((d) => { if (supportGeneration.current === generation) setParticipants(d.participants); })
      .catch(failed);
    void getJson<{ enabled: boolean; messages: Array<{ id: number; display_name: string; body: string }> }>(apiEndpoint(stateUrl, "sessions/chat"))
      .then((data) => { if (supportGeneration.current === generation) setChat(data); })
      .catch(failed);
  }, [stateUrl, stateVersion, supportRefresh]);

  const focused = history.find(a=>a.id===(selectedId ?? state?.current_activity?.id)) ?? state?.current_activity ?? null;
  const pending = participants.filter((p) => p.admission_state === "pending");
  const studentsHeld = holdStudents || Boolean(
    state?.channels?.participants?.activity
    && state.channels.participants.activity.id !== state.channels.display?.activity?.id
  );

  return (
    <>
      <LanguageSwitcher />
      <a href={bootstrap.workspaceUrl}>{tr("Teacher home","教师首页")}</a>
      <p className="lc-kicker">{t("teacher")} · {bootstrap.sessionTitle}</p>
      <h1>{bootstrap.flowTitle || t("instantSession")}</h1>
      <div className="lc-actions"><InviteControls bootstrap={bootstrap} />{canManage ? <a href={bootstrap.studentViewUrl}>{t("studentView")}</a> : null}</div>
      <p id="session-status" className="lc-kicker">{state?.session.status === "live" ? t("liveClass") : state?.session.status === "paused" ? t("classPaused") : state?.session.status === "ended" ? t("teachingEnded") : t("startClass")}</p>
      {state?.session.status === "draft" ? <p>{t("startClassHint")}</p> : null}
      {canManage && <LifecycleControls state={state} run={run} startingStepId={previewStep?.id ?? planSteps[0]?.id ?? null} pending={commandPending} onStarted={() => setPreviewStep(null)} />}
      {state?.session.status === "paused" ? <p role="status">{t("classPaused")}</p> : null}
      <PresenterStage state={state} steps={planSteps} stateUrl={stateUrl} onRefresh={sync.refresh} canManage={canManage} onError={setStatus} onPreviewChange={setPreviewStep} deliveryChannel={studentsHeld ? "display" : "both"} />
      {canManage ? <NativeDeckPresenter bootstrap={bootstrap} state={state} stateUrl={stateUrl} onRefresh={sync.refresh} /> : null}
      {studentsHeld && state?.channels?.participants?.activity ? <div className="lc-audience-held" role="status">
        <span>{t("studentsHeld")} <strong>{activityTitle(state.channels.participants.activity, t("activity"))}</strong></span>
        <button type="button" disabled={commandPending || state.session.status !== "live"} onClick={() => {
          const displayId = state.channels?.display?.activity?.id;
          const step = planSteps.find((item) => item.activity_id === displayId);
          if (step) void run(`sessions/plan/${step.id}/launch`, { channel: "both" }).then((ok) => { if (ok) setHoldStudents(false); });
        }}>{t("bringStudents")}</button>
      </div> : null}
      {canManage && state?.session.status==="live" && <FilePicker
        endpoint={apiEndpoint(stateUrl, "sessions/files")}
        isSuperuser={bootstrap.isSuperuser}
        includeChannels
        onSuccess={() => void sync.refresh()}
      />}
      {status ? <p className="lc-builder-status-error">{status}</p> : null}
      {sync.reconnecting && !sync.error ? <p role="status">{t("reconnecting")}</p> : null}
      {supportingError ? <p className="lc-builder-status-error" role="status">{supportingError} <button type="button" onClick={() => setSupportRefresh((value) => value + 1)}>{tr("Retry", "重试")}</button></p> : null}
      {canManage && <LiveResults state={state} analytics={analytics} run={run} pending={commandPending} />}
      {state?.session.status === "ended" ? <div className="lc-actions"><a href="#results">{t("viewResults")}</a><button type="button" onClick={() => { const endpoint = new URL(stateUrl, window.location.href); endpoint.pathname = endpoint.pathname.replace(/sessions\/\d+\/state\/?$/, "sessions/"); void postJson<{ console_url: string }>(endpoint.toString(), { title: `${bootstrap.sessionTitle} — ${t("teachAgain")}`, source_session_id: state.session.id }, crypto.randomUUID()).then(({ console_url }) => window.location.assign(console_url)).catch((error) => setStatus(error instanceof Error ? error.message : t("unavailable"))); }}>{t("teachAgain")}</button></div> : null}
      {canAdmit && pending.length ? <button type="button" className="lc-pending-notice" onClick={() => {
        const panel = document.getElementById("students-panel") as HTMLDetailsElement | null;
        if (panel) { panel.open = true; panel.scrollIntoView({ block: "nearest" }); }
      }}>{pending.length} {t("pending")}</button> : null}
      <details className="lc-console-panel"><summary>{tr("Results", "结果")}</summary>
        <label>{tr("Activity to inspect", "选择查看的活动")}<select value={selectedId??""} onChange={e=>setSelectedId(e.target.value?Number(e.target.value):null)}><option value="">{tr("Current display activity","当前投屏活动")}</option>{history.map(a=><option key={a.id} value={a.id}>{activityTitle(a,t("activity"))}</option>)}</select></label>
        <div className="lc-actions">{canAdmit && <>{["summary","responses","participants","chat"].map(dataset=><a key={dataset} href={`${bootstrap.exportUrl}?format=csv&dataset=${dataset}`}>{({summary:tr("Summary","汇总"),responses:tr("Responses","答案"),participants:tr("Attendance","出席"),chat:tr("Chat","聊天")} as Record<string,string>)[dataset]} CSV</a>)}<a href={bootstrap.exportUrl}>JSON</a></>}</div>
        <AnalyticsPanel stateUrl={stateUrl} analytics={analytics} activity={focused} />
      </details>
      <details className="lc-console-panel"><summary>{tr("Edit lesson", "编辑教案")}</summary><SessionPlanPanel stateUrl={stateUrl} state={state} onRefresh={sync.refresh}/></details>
      {canManage && <details className="lc-console-panel"><summary>{tr("More", "更多")}</summary>
        <AudienceControls state={state} steps={planSteps} holdStudents={holdStudents} setHoldStudents={setHoldStudents} run={run} />
        <h2>{tr("Advanced audience and review", "高级受众与复习设置")}</h2>
        <ChannelControls state={state} run={run} />{focused && <fieldset><legend>{tr("Student review access","学生复习权限")}</legend>
        <label><input type="checkbox" checked={Boolean((focused as typeof history[number]).reviewable)} onChange={e=>void run(`activities/${focused.id}/review`,{reviewable:e.target.checked})}/>{tr("Allow review","允许复习")}</label>
        {(["show_answer","show_explanation"] as const).map(field=><label key={field}><input type="checkbox" checked={Boolean((focused as typeof history[number]).review_visibility?.[field])} onChange={e=>void run(`activities/${focused.id}/review`,{[field]:e.target.checked})}/>{field==="show_answer"?t("showAnswer"):t("showExplanation")}</label>)}
        </fieldset>}
        {["draft", "ended"].includes(state?.session.status ?? "") && <button className="lc-btn-danger" onClick={()=>{if(window.confirm(tr("Delete this classroom permanently? Its classroom records will be removed; its reusable lesson remains.","永久删除本次课堂吗？课堂记录将被移除，教案会保留。"))) void postJson(apiEndpoint(stateUrl,"sessions/delete"),{confirm:true},crypto.randomUUID()).then(()=>window.location.assign(bootstrap.workspaceUrl)).catch(error=>window.alert(error instanceof Error?error.message:tr("Delete failed","删除失败")));}}>{tr("Delete classroom","删除课堂")}</button>}
      </details>}
      <details id="students-panel" className="lc-console-panel"><summary>{tr("Students", "学生")}{pending.length ? ` (${pending.length})` : ""}</summary>
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
          <label>
            {t("message")} <textarea name="body" rows={2} maxLength={4000} value={chatBody} onChange={(e) => setChatBody(e.target.value)} />
          </label>
          <button type="submit">{t("send")}</button>
        </form>
      </section>
      </details>
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
