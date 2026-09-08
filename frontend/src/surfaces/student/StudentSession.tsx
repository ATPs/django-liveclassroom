import * as React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { readBootstrap, type Bootstrap } from "../../bootstrap.js";
import { LanguageSwitcher, LocaleProvider, useT } from "../../i18n.js";
import {
  ApiError,
  apiEndpoint,
  getJson,
  postJson,
  type ActivityState,
  type ChatState,
  type SessionState,
} from "../../protocol.js";
import { useSessionState } from "../../hooks/useSessionState.js";
import { ActivityView } from "../../activities/ActivityView.js";
import { activityKind, answerText, choicesFor, selectedChoices } from "../../activities/activityData.js";

function JoinPrompt({ onJoined }: { onJoined: (name: string) => Promise<void> }) {
  const t = useT();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  return (
    <form
      data-liveclassroom-join-prompt
      onSubmit={(event) => {
        event.preventDefault();
        const value = name.trim();
        if (!value || busy) return;
        setBusy(true);
        setError("");
        void onJoined(value)
          .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : t("unavailable")))
          .finally(() => setBusy(false));
      }}
    >
      <label>
        {t("displayName")}{" "}
        <input name="display_name" required maxLength={100} value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <button type="submit" disabled={busy}>
        {t("joinClassroom")}
      </button>
      {error ? <p aria-live="polite">{error}</p> : null}
    </form>
  );
}

function Chat({ stateUrl, stateVersion }: { stateUrl: string; stateVersion: number }) {
  const t = useT();
  const [chat, setChat] = useState<ChatState | null>(null);
  const [status, setStatus] = useState("");
  const [body, setBody] = useState("");
  const [sending, setSending] = useState(false);

  const load = useCallback(() => {
    getJson<ChatState>(apiEndpoint(stateUrl, "sessions/chat"))
      .then(setChat)
      .catch(() => setStatus(t("chatUnavailable")));
  }, [stateUrl, t]);

  useEffect(() => {
    load();
  }, [load, stateVersion]);

  const send = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const text = body.trim();
    if (!text || sending) return;
    setSending(true);
    void postJson(apiEndpoint(stateUrl, "sessions/chat/send"), { body: text }, `chat-${Date.now()}-${Math.random().toString(36).slice(2)}`)
      .then(() => {
        setBody("");
        return getJson<ChatState>(apiEndpoint(stateUrl, "sessions/chat"));
      })
      .then(setChat)
      .catch((error: unknown) => {
        setStatus(error instanceof Error ? error.message : t("chatUnavailable"));
      })
      .finally(() => setSending(false));
  };

  if (chat && !chat.enabled && !chat.messages.length && !status) return null;
  return (
    <details className="lc-chat" data-liveclassroom-chat>
      <summary id="student-chat-heading">{t("chat")}</summary>
      <p data-liveclassroom-chat-status aria-live="polite">
        {chat ? (chat.enabled ? "" : t("chatDisabled")) : status}
      </p>
      <ul data-liveclassroom-chat-messages aria-live="polite">
        {chat && chat.messages.length
          ? chat.messages.map((message) => (
              <li key={message.id}>
                <strong>{message.display_name}: </strong>
                {message.body}
              </li>
            ))
          : <li>{chat?.enabled ? t("noMessages") : t("chatDisabled")}</li>}
      </ul>
      {chat ? (
        <form data-liveclassroom-chat-form onSubmit={send} hidden={!chat.enabled}>
          <label>
            {t("message")}{" "}
            <textarea
              name="body"
              rows={2}
              maxLength={4000}
              value={body}
              onChange={(e) => setBody(e.target.value)}
              disabled={!chat.enabled || sending}
            />
          </label>
          <button type="submit" disabled={!chat.enabled || sending}>
            {t("send")}
          </button>
        </form>
      ) : null}
    </details>
  );
}

type OwnSubmission = { answer: Record<string, unknown>; is_stale: boolean };
type ReviewActivity = ActivityState & {
  own_submission?: OwnSubmission | null;
  reviewable?: boolean;
  review_visibility?: Record<string, boolean>;
};

function OwnAnswer({ activity, submission }: { activity: ActivityState; submission: OwnSubmission }) {
  const t = useT();
  const kind = activityKind(activity);
  const answer = submission.answer;
  const labels = new Map(choicesFor(activity).map((choice) => [choice.id, choice.text]));
  const selected = selectedChoices(answer);
  const selectedLabels = selected.map((choice) => labels.get(choice) ?? choice);
  const directAnswer = kind === "numeric"
    ? answerText(answer, "value")
    : kind === "rating"
      ? answerText(answer, "rating")
      : answerText(answer, "text") || answerText(answer, "value");
  const transcript = Array.isArray(answer.transcript)
    ? answer.transcript.filter((entry): entry is Record<string, unknown> => Boolean(entry) && typeof entry === "object")
    : [];
  const finalDirectory = transcript.length ? answerText(transcript[transcript.length - 1], "cwd") : "";
  return (
    <div data-liveclassroom-own-answer>
      <h3>{t("answer")}</h3>
      {answer.completed === true && transcript.length ? (
        <>
          <p>{t("saved")}{finalDirectory ? ` · ${finalDirectory}` : ""}</p>
          <pre>{transcript.map((entry) => `$ ${answerText(entry, "command")}\n${answerText(entry, "output")}`).join("\n")}</pre>
        </>
      ) : kind === "ranking" && selectedLabels.length ? (
        <ol>
          {selectedLabels.map((label, index) => <li key={`${index}-${label}`}>{label}</li>)}
        </ol>
      ) : selectedLabels.length ? (
        <p>{selectedLabels.join(", ")}</p>
      ) : directAnswer ? (
        <p>{directAnswer}</p>
      ) : <p>{t("noAnswer")}</p>}
      {submission.is_stale ? <p>{t("stale")}</p> : null}
    </div>
  );
}

function History({
  stateUrl,
  stateVersion,
  state,
}: {
  stateUrl: string;
  stateVersion: number;
  state: SessionState | null;
}) {
  const t = useT();
  const [activities, setActivities] = useState<ReviewActivity[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    setError(false);
    getJson<{ activities: ReviewActivity[] }>(apiEndpoint(stateUrl, "sessions/history"))
      .then((data) => setActivities(data.activities))
      .catch(() => setError(true));
  }, [stateUrl, stateVersion]);

  if (activities && !activities.length && !error) return null;
  return (
    <details data-liveclassroom-history>
      <summary>{t("history")}</summary>
      <div aria-live="polite">
      {error ? (
        <p>{t("historyUnavailable")}</p>
      ) : activities ? (
        <ul>
          {activities.map((activity) => {
            const readOnlyState = state
              ? {
                  ...state,
                  current_activity: activity,
                  my_submission: null,
                  act_as_active: false,
                }
              : null;
            return (
              <li key={`${activity.id}:${activity.revision_id}`}>
                <ActivityView
                  activity={activity}
                  state={readOnlyState}
                  stateUrl={stateUrl}
                  refresh={() => undefined}
                />
                {activity.own_submission ? <OwnAnswer activity={activity} submission={activity.own_submission} /> : null}
              </li>
            );
          })}
        </ul>
      ) : null}
      </div>
    </details>
  );
}

function StudentSession({ bootstrap }: { bootstrap: Bootstrap }) {
  const t = useT();
  const [stateUrl, setStateUrl] = useState(bootstrap.stateUrl!);
  const [joined, setJoined] = useState(false);
  const [needName, setNeedName] = useState(false);
  const [signInRequired, setSignInRequired] = useState(false);
  const [joinError, setJoinError] = useState("");
  const joinedRef = useRef(false);

  useEffect(() => {
    const updateStateUrl = (event: Event) => {
      const next = (event as CustomEvent<{ stateUrl?: string }>).detail?.stateUrl;
      if (next) setStateUrl(next);
    };
    window.addEventListener("liveclassroom:update-state-url", updateStateUrl);
    return () => window.removeEventListener("liveclassroom:update-state-url", updateStateUrl);
  }, []);

  useEffect(() => {
    let cancelled = false;
    const join = async (): Promise<void> => {
      if (joinedRef.current) return;
      joinedRef.current = true;
      if (bootstrap.preview || (!bootstrap.guestJoinUrl && !bootstrap.accountJoinUrl)) {
        // Act-as / inspection surface: no join is needed; fetch state directly.
        if (!cancelled) {
          setJoined(true);
        }
        return;
      }

      let participantState: SessionState | null = null;
      try {
        const url = new URL(stateUrl, window.location.href);
        url.searchParams.set("channel", "participants");
        participantState = await getJson<SessionState>(url.toString());
      } catch (error) {
        if (!(error instanceof ApiError) || error.status !== 403) {
          if (!cancelled) setJoinError(error instanceof Error ? error.message : t("unavailable"));
          return;
        }
      }
      if (participantState?.participant) {
        if (!cancelled) setJoined(true);
        return;
      }

      if (bootstrap.authenticated && bootstrap.accessMode !== "guest" && bootstrap.accountJoinUrl) {
        try {
          await postJson(bootstrap.accountJoinUrl, {}, `join-account-${bootstrap.sessionId ?? "session"}`);
          if (!cancelled) {
            setJoined(true);
          }
        } catch (error) {
          if (!cancelled) setJoinError(error instanceof Error ? error.message : t("unavailable"));
        }
        return;
      }
      const pendingName = bootstrap.pendingName?.trim() ?? "";
      if (pendingName && bootstrap.accessMode !== "authenticated" && bootstrap.guestJoinUrl) {
        try {
          await postJson(bootstrap.guestJoinUrl, { display_name: pendingName }, `join-guest-${bootstrap.sessionId ?? "session"}`);
          if (!cancelled) {
            setJoined(true);
          }
        } catch (error) {
          if (!cancelled) setJoinError(error instanceof Error ? error.message : t("unavailable"));
        }
        return;
      }
      if (!bootstrap.authenticated && bootstrap.accessMode === "authenticated") {
        if (!cancelled) setSignInRequired(true);
        return;
      }
      if (bootstrap.guestJoinUrl && bootstrap.accessMode !== "authenticated") {
        if (!cancelled) setNeedName(true);
      }
    };
    void join();
    return () => {
      cancelled = true;
    };
  }, [bootstrap, t]);

  const joinByName = useCallback(
    async (name: string) => {
      if (!bootstrap.guestJoinUrl) return;
      await postJson(bootstrap.guestJoinUrl, { display_name: name }, `join-guest-${bootstrap.sessionId ?? "session"}`);
      joinedRef.current = true;
      setJoinError("");
      setJoined(true);
      setNeedName(false);
    },
    [bootstrap],
  );

  const sync = useSessionState({
    stateUrl,
    websocketPath: bootstrap.websocketUrl,
    channel: "participants",
    enabled: joined,
  });
  const state = sync.state;

  const title = state?.session.title ?? "…";
  const stateMessage = state?.session.status === "paused"
    ? t("studentClassPaused")
    : state?.session.status === "ended"
      ? t("classEnded")
      : "";

  return (
    <>
      <LanguageSwitcher />
      <h1 id="student-title">{title}</h1>
      <div id="student-content" data-liveclassroom-content>
        {joined ? (
          state?.participant && state.participant.admission_state !== "admitted" ? (
            <p>{t("waitingAdmission")}</p>
          ) : state?.session.status === "ended" ? (
            <p role="status">{t("classEnded")}</p>
          ) : state?.session.status === "paused" ? (
            <>
              <p role="status">{t("studentClassPaused")}</p>
              <ActivityView activity={state?.current_activity ?? null} state={state} stateUrl={stateUrl} refresh={sync.refresh} />
            </>
          ) : bootstrap.preview ? (
            <>
              <p role="status">{t("participantPreview")}: {t("responsesDisabled")}</p>
              <ActivityView activity={state?.current_activity ?? null} state={state ? { ...state, act_as_active: false } : null} stateUrl={stateUrl} refresh={sync.refresh} />
            </>
          ) : (
            <ActivityView activity={state?.current_activity ?? null} state={state} stateUrl={stateUrl} refresh={sync.refresh} />
          )
        ) : needName ? (
          <JoinPrompt onJoined={joinByName} />
        ) : signInRequired ? (
          <p>{t("signInRequired")}</p>
        ) : null}
      </div>
      <p data-liveclassroom-status aria-live="polite">
        {joinError || sync.error || (sync.reconnecting ? t("reconnecting") : "") || stateMessage}
      </p>
      {joined && state?.participant?.admission_state === "admitted" ? (
        <>
          <Chat stateUrl={stateUrl} stateVersion={state?.state_version ?? 0} />
          <History stateUrl={stateUrl} stateVersion={state?.state_version ?? 0} state={state} />
        </>
      ) : null}
    </>
  );
}

export function mountStudentSession(el: HTMLElement): void {
  const bootstrap = readBootstrap(el);
  if (!bootstrap.stateUrl) return;
  const root = createRoot(el);
  root.render(
    <LocaleProvider initial={bootstrap.locale} root={el}>
      <StudentSession bootstrap={bootstrap} />
    </LocaleProvider>,
  );
  el.addEventListener(
    "liveclassroom:unmount",
    () => root.unmount(),
    { once: true },
  );
}
