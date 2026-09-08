import { SessionPlanPanel } from "./SessionPlanPanel.js";
import * as React from "react";
import { useEffect, useState } from "react";
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
import { AggregateView, MediaView, WordCloud, ChoiceBars } from "../../activities/renderers.js";
import { isBuiltinActivity, PluginActivityView, Prompt, RevealedFeedback } from "../../activities/ActivityView.js";
import { FileActivity } from "../../activities/FileActivity.js";
import { activityKind, activityTitle, stringValue } from "../../activities/activityData.js";
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
    isSuperuser: d.isSuperuser === "true",
    flowSteps,
  };
}

function useCommand(stateUrl: string, refresh: () => void) {
  const t = useT();
  const [status, setStatus] = useState("");
  const run = async (suffix: string, body: Record<string, unknown> = {}): Promise<void> => {
    try {
      await postJson(apiEndpoint(stateUrl, suffix), body, `cmd-${Date.now()}-${Math.random().toString(36).slice(2)}`);
      setStatus("");
      await refresh();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : t("unavailable"));
    }
  };
  return { run, status, setStatus };
}

function LifecycleControls({ state, run }: { state: SessionState | null; run: (s: string) => Promise<void> }) {
  const t = useT();
  const status = state?.session.status ?? "draft";
  return (
    <div className="lc-actions" aria-label={t("controls")}>
      <button id="start-session" disabled={["live", "ended"].includes(status)} onClick={() => void run("sessions/start")}>
        {t("start")}
      </button>
      <button id="pause-session" disabled={status !== "live"} onClick={() => void run("sessions/pause")}>
        {t("pause")}
      </button>
      <button
        id="end-session"
        disabled={status === "ended"}
        onClick={() => {
          if (window.confirm(t("confirmEnd"))) void run("sessions/end");
        }}
      >
        {t("end")}
      </button>
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
  run: (s: string, b: Record<string, unknown>) => Promise<void>;
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

function ChannelControls({state,run}: {state:SessionState|null;run:(suffix:string,body?:Record<string,unknown>)=>Promise<void>}) {
  const t=useT();
  const selected=state?.current_activity;
  const fields: Array<[keyof VisibilityState,string]> = [["show_prompt",t("showPrompt")],["show_aggregate",t("showAggregate")],["show_answer",t("showAnswer")],["show_explanation",t("showExplanation")],["show_own_status",t("showOwnStatus")],["allow_review",t("allowReview")]];
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
      <AggregateView aggregate={channel?.aggregate ?? null} />
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
}: {
  activity: ActivityState | null;
  aggregate: unknown;
  state: SessionState | null;
  stateUrl: string;
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
        fallback={<BuiltinTeacherActivityView activity={activity} aggregate={aggregate} state={state} stateUrl={stateUrl} />}
      />
    );
  }
  return <BuiltinTeacherActivityView activity={activity} aggregate={aggregate} state={state} stateUrl={stateUrl} />;
}

function BuiltinTeacherActivityView({
  activity,
  aggregate,
  state,
  stateUrl,
}: {
  activity: ActivityState;
  aggregate: unknown;
  state: SessionState | null;
  stateUrl: string;
}) {
  const t = useT();
  const kind = activityKind(activity);
  const heading = <h2>{activityTitle(activity, t("activity"))}</h2>;
  if (kind === "media") {
    return <>{heading}<Prompt activity={activity} /><MediaView activity={activity} state={state} stateUrl={stateUrl} audience="teacher" /></>;
  }
  if (kind === "timer" || kind === "markdown") {
    return (
      <>
        {heading}
        <Prompt activity={activity} />
        <p>
          {t("state")}: {activity.state}; {t("revision")} {activity.revision}
        </p>
      </>
    );
  }
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
      <Prompt activity={activity} />
      {kind === "word_cloud" ? <WordCloud aggregate={aggregate as never} isTeacher /> : null}
      <RevealedFeedback activity={activity} />
      {kind !== "word_cloud" ? <AggregateView aggregate={aggregate as never} /> : null}
      <p>
        {t("state")}: {activity.state}; {t("revision")} {activity.revision}
      </p>
    </>
  );
}

type PresenterStep = { id: number; position: number; title: string; activity_id: number | null };

function PresenterStage({
  state, steps, stateUrl, onRefresh, canManage,
}: { state: SessionState | null; steps: PresenterStep[]; stateUrl: string; onRefresh: () => Promise<void>; canManage: boolean }) {
  const t = useT();
  const locale = useLocale();
  const tr = (en: string, zh: string) => locale.startsWith("zh") ? zh : en;
  const currentId = state?.channels?.display?.activity?.id ?? state?.current_activity?.id ?? null;
  const currentIndex = steps.findIndex((step) => step.activity_id === currentId);
  const next = steps[currentIndex >= 0 ? currentIndex + 1 : 0] ?? null;
  const showNext = async (channel: "both" | "display") => {
    if (!next || state?.session.status !== "live") return;
    await postJson(apiEndpoint(stateUrl, `sessions/plan/${next.id}/launch`), { channel }, `present-${channel}-${next.id}-${Date.now()}`);
    await onRefresh();
  };
  return <section className="lc-presenter" aria-label={tr("Presenter workspace", "演示者工作区")}>
    <div className="lc-presenter-current">
      <p className="lc-presenter-label">{tr("Now showing", "当前展示")}</p>
      <TeacherActivityView activity={state?.current_activity ?? null} aggregate={state?.aggregate ?? null} state={state} stateUrl={stateUrl} />
    </div>
    <aside className="lc-presenter-next">
      <p className="lc-presenter-label">{tr("Up next", "下一项")}</p>
      {next ? <><h2>{next.position}. {next.title}</h2><p>{tr("Students follow by default.", "学生默认跟随演示。")}</p>
        <button className="lc-btn-primary" disabled={!canManage || state?.session.status !== "live"} onClick={() => void showNext("both").catch(() => undefined)}>{tr("Show to everyone", "展示给所有人")}</button>
        <button disabled={!canManage || state?.session.status !== "live"} onClick={() => void showNext("display").catch(() => undefined)}>{tr("Continue display only", "仅继续投屏")}</button></> : <p>{tr("End of this lesson.", "已到教案末尾。")}</p>}
      <p className="lc-presenter-status">{tr("Student channel", "学生端")}: {state?.channels?.participants?.activity?.id === currentId ? tr("following", "跟随") : tr("held on another item", "停留在其他内容")}</p>
    </aside>
    <nav className="lc-presenter-strip" aria-label={tr("Lesson outline", "教案目录")}>
      {steps.map((step) => <span key={step.id} className={step.activity_id === currentId ? "lc-presenter-step lc-presenter-step-current" : "lc-presenter-step"}>{step.position}. {step.title}</span>)}
    </nav>
  </section>;
}

function LiveResults({
  state,
  analytics,
  run,
}: {
  state: SessionState | null;
  analytics: Record<string, unknown> | null;
  run: (s: string) => Promise<void>;
}) {
  const t = useT();
  const activity = state?.current_activity ?? null;
  const current = activity
    ? (Array.isArray(analytics?.activities) ? (analytics!.activities as Array<Record<string, unknown>>).find((a) => a.id === activity.id) : undefined)
    : undefined;
  return (
    <section>
      <h2>{t("results")}</h2>
      <p id="activity-status">
        {activity
          ? `${activityTitle(activity, t("activity"))} (${activity.state})`
          : t("noActivityPublished")}
      </p>
      <div id="result-summary">
        {current ? (
          <>
            <div className="lc-rate-badge">
              {t("responseRate")}: {String(current.response_rate ?? 0)}% ({String(current.submitted_count ?? 0)}/
              {String(current.eligible_participant_count ?? 0)})
            </div>
            {current.aggregate && (current.aggregate as Record<string, unknown>).choices ? (
              <ChoiceBars choices={(current.aggregate as { choices: Record<string, number> }).choices} />
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
      <button id="close-activity" disabled={!activity || activity.state !== "open"} onClick={() => activity && void run(`activities/${activity.id}/close`)}>
        {t("close")}
      </button>
      <button id="reveal-activity" disabled={!activity || activity.state !== "closed"} onClick={() => activity && void run(`activities/${activity.id}/reveal`)}>
        {t("reveal")}
      </button>
    </section>
  );
}

function AnalyticsPanel({ stateUrl, analytics, activityId }: { stateUrl: string; analytics: Record<string, unknown> | null; activityId: number | null }) {
  const t = useT();
  const attendance = (analytics?.attendance ?? {}) as Record<string, unknown>;
  const activities = (Array.isArray(analytics?.activities) ? analytics!.activities : []) as Array<Record<string, unknown>>;
  const participants = (Array.isArray(analytics?.participants) ? analytics!.participants : []) as Array<Record<string, unknown>>;
  const current = activities.find((a) => a.id === activityId);
  const responses = (current && Array.isArray(current.responses) ? current.responses : []) as Array<Record<string, unknown>>;

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
                  <td>{String(activity.state)}</td>
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
                  <td>{String(participant.admission_state)}</td>
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
              <th scope="col">{t("revision")}</th>
              <th scope="col">{t("statusColumn")}</th>
            </tr>
          </thead>
          <tbody id="analytics-responses">
            {!current || !responses.length ? (
              <tr>
                <td colSpan={4}>{current ? t("noResponses") : t("publishToReview")}</td>
              </tr>
            ) : (
              responses.map((response, index) => (
                <tr key={index}>
                  <td>{String(response.display_name)}</td>
                  <td>{JSON.stringify(response.answer ?? {})}</td>
                  <td>{String(response.revision ?? "-")}</td>
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
  const { run, status } = useCommand(stateUrl, sync.refresh);
  const [analytics, setAnalytics] = useState<Record<string, unknown> | null>(null);
  const [participants, setParticipants] = useState<Array<Record<string, unknown>>>([]);
  const [chat, setChat] = useState<{ enabled: boolean; messages: Array<{ id: number; display_name: string; body: string }> } | null>(null);
  const [selectedId,setSelectedId] = useState<number|null>(null);
  const [history,setHistory] = useState<Array<ActivityState & {reviewable:boolean;review_visibility:Record<string,boolean>}>>([]);
  const [planSteps, setPlanSteps] = useState<PresenterStep[]>([]);
  const [chatBody, setChatBody] = useState("");

  const stateVersion = state?.state_version ?? 0;

  useEffect(() => {
    if (!state) return;
    void getJson<{activities:typeof history}>(apiEndpoint(stateUrl,"sessions/history")).then(d=>setHistory(d.activities)).catch(()=>undefined);
    void getJson<{steps: PresenterStep[]}>(apiEndpoint(stateUrl, "sessions/plan")).then(d => setPlanSteps(d.steps ?? [])).catch(() => undefined);
    void getJson<Record<string, unknown>>(apiEndpoint(stateUrl, "sessions/analytics"))
      .then(setAnalytics)
      .catch(() => undefined);
    void getJson<{ participants: Array<Record<string, unknown>> }>(apiEndpoint(stateUrl, "sessions/participants"))
      .then((d) => setParticipants(d.participants))
      .catch(() => undefined);
    void getJson<{ enabled: boolean; messages: Array<{ id: number; display_name: string; body: string }> }>(apiEndpoint(stateUrl, "sessions/chat"))
      .then(setChat)
      .catch(() => undefined);
  }, [stateUrl, stateVersion]);

  const focused = history.find(a=>a.id===(selectedId ?? state?.current_activity?.id)) ?? state?.current_activity ?? null;
  const focusedState = state ? {...state,current_activity:focused} : null;
  const pending = participants.filter((p) => p.admission_state === "pending");

  return (
    <>
      <LanguageSwitcher />
      <a href={bootstrap.workspaceUrl}>{tr("Teacher home","教师首页")}</a>
      <p className="lc-kicker">{t("teacher")} · {bootstrap.sessionTitle}</p>
      <h1>{bootstrap.flowTitle || t("instantSession")}</h1>
      <p>
        {t("joinCode")}: <strong className="lc-code">{bootstrap.joinCode}</strong> · <a href={bootstrap.joinUrl}>{t("studentJoinPage")}</a> ·{" "}
        {bootstrap.capabilities.includes("view_display") && <a href={bootstrap.displayUrl}>{t("openDisplay")}</a>} {canManage && <a href={bootstrap.studentViewUrl}>{t("studentView")}</a>}
      </p>
      {canManage && <figure className="lc-join-qr">
        <img src={bootstrap.qrUrl} alt={`${t("joinCode")}: ${bootstrap.sessionTitle}`} />
        <figcaption>{t("studentJoinCode")}: {bootstrap.joinCode}</figcaption>
      </figure>}
      <p>
        {t("statusColumn")}: <strong id="session-status">{state?.session.status ?? ""}</strong>
      </p>
      {canManage && <LifecycleControls state={state} run={run} />}
      <PresenterStage state={state} steps={planSteps} stateUrl={stateUrl} onRefresh={sync.refresh} canManage={canManage} />
      {canManage && state?.session.status==="live" && <FilePicker
        endpoint={apiEndpoint(stateUrl, "sessions/files")}
        isSuperuser={bootstrap.isSuperuser}
        includeChannels
        onSuccess={() => void sync.refresh()}
      />}
      {status ? <p className="lc-builder-status-error">{status}</p> : null}
      {canManage && <LiveResults state={focusedState} analytics={analytics} run={run} />}
      <details className="lc-console-panel"><summary>{tr("Lesson and classroom editing", "教案与课堂编辑")}</summary><SessionPlanPanel stateUrl={stateUrl} state={state} onRefresh={sync.refresh}/></details>
      <label>{tr("Activity to inspect or control", "选择查看或控制的活动")}<select value={selectedId??""} onChange={e=>setSelectedId(e.target.value?Number(e.target.value):null)}><option value="">{tr("Current display activity","当前投屏活动")}</option>{history.map(a=><option key={a.id} value={a.id}>{activityTitle(a,t("activity"))}</option>)}</select></label>
      {canManage && <ChannelControls state={focusedState} run={run} />}
      {canManage && focused && <fieldset><legend>{tr("Student review access","学生复习权限")}</legend>
        <label><input type="checkbox" checked={Boolean((focused as typeof history[number]).reviewable)} onChange={e=>void run(`activities/${focused.id}/review`,{reviewable:e.target.checked})}/>{tr("Allow review","允许复习")}</label>
        {(["show_answer","show_explanation"] as const).map(field=><label key={field}><input type="checkbox" checked={Boolean((focused as typeof history[number]).review_visibility?.[field])} onChange={e=>void run(`activities/${focused.id}/review`,{[field]:e.target.checked})}/>{field==="show_answer"?t("showAnswer"):t("showExplanation")}</label>)}
      </fieldset>}
      <div className="lc-actions">{canAdmit && <>{["summary","responses","participants","chat"].map(dataset=><a key={dataset} href={`${bootstrap.exportUrl}?format=csv&dataset=${dataset}`}>{({summary:tr("Summary","汇总"),responses:tr("Responses","答案"),participants:tr("Attendance","出席"),chat:tr("Chat","聊天")} as Record<string,string>)[dataset]} CSV</a>)}<a href={bootstrap.exportUrl}>JSON</a></>}
      {canManage && ["draft", "ended"].includes(state?.session.status ?? "") && <button className="lc-btn-danger" onClick={()=>{if(window.confirm(tr("Delete this classroom permanently? Its classroom records will be removed; its reusable lesson remains.","永久删除本次课堂吗？课堂记录将被移除，教案会保留。"))) void postJson(apiEndpoint(stateUrl,"sessions/delete"),{confirm:true},crypto.randomUUID()).then(()=>window.location.assign(bootstrap.workspaceUrl)).catch(error=>window.alert(error instanceof Error?error.message:tr("Delete failed","删除失败")));}}>{tr("Delete classroom","删除课堂")}</button>}
      </div>
      <ParticipantPreview state={state} stateUrl={stateUrl} />
      <AnalyticsPanel stateUrl={stateUrl} analytics={analytics} activityId={focused?.id ?? null} />
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
