import * as React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { readBootstrap, type Bootstrap } from "../../bootstrap.js";
import { LanguageSwitcher, LocaleProvider, useT } from "../../i18n.js";
import { apiEndpoint, getJson, postJson, type ActivityState, type ChatState } from "../../protocol.js";
import { useSessionState } from "../../hooks/useSessionState.js";
import { ActivityView } from "../../activities/ActivityView.js";
import { activityTitle, questionPrompt } from "../../activities/activityData.js";

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

  return (
    <section className="lc-chat" data-liveclassroom-chat aria-labelledby="student-chat-heading">
      <h2 id="student-chat-heading">{t("chat")}</h2>
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
    </section>
  );
}

function History({ stateUrl, stateVersion }: { stateUrl: string; stateVersion: number }) {
  const t = useT();
  const [activities, setActivities] = useState<ActivityState[] | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    getJson<{ activities: ActivityState[] }>(apiEndpoint(stateUrl, "sessions/history"))
      .then((data) => setActivities(data.activities))
      .catch(() => setError(true));
  }, [stateUrl, stateVersion]);

  return (
    <section data-liveclassroom-history aria-live="polite">
      <h2>{t("history")}</h2>
      {error ? (
        <p>{t("historyUnavailable")}</p>
      ) : activities && !activities.length ? (
        <p>{t("noHistory")}</p>
      ) : activities ? (
        <ul>
          {activities.map((activity) => (
            <li key={activity.id}>
              <strong>{activityTitle(activity, t("activity"))}</strong>
              {questionPrompt(activity) ? <span>: {questionPrompt(activity)}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}

function StudentSession({ bootstrap }: { bootstrap: Bootstrap }) {
  const t = useT();
  const stateUrl = bootstrap.stateUrl!;
  const [joined, setJoined] = useState(false);
  const [needName, setNeedName] = useState(false);
  const [signInRequired, setSignInRequired] = useState(false);
  const [joinError, setJoinError] = useState("");
  const joinedRef = useRef(false);

  useEffect(() => {
    let cancelled = false;
    const join = async (): Promise<void> => {
      if (!bootstrap.guestJoinUrl && !bootstrap.accountJoinUrl) {
        // Act-as / inspection surface: no join is needed; fetch state directly.
        if (!cancelled) {
          joinedRef.current = true;
          setJoined(true);
        }
        return;
      }
      if (bootstrap.authenticated && bootstrap.accessMode !== "guest" && bootstrap.accountJoinUrl) {
        try {
          await postJson(bootstrap.accountJoinUrl, {}, `join-account-${bootstrap.sessionId ?? "session"}`);
          if (!cancelled) {
            joinedRef.current = true;
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
            joinedRef.current = true;
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

  const title = state?.current_activity ? activityTitle(state.current_activity, state.session.title) : state?.session.title ?? "…";

  return (
    <>
      <LanguageSwitcher />
      <p className="lc-kicker">{state?.session.title ?? ""}</p>
      <h1 id="student-title">{title}</h1>
      <div id="student-content" data-liveclassroom-content>
        {joined ? (
          state?.participant && state.participant.admission_state !== "admitted" ? (
            <p>{t("waitingAdmission")}</p>
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
        {joinError || sync.error || (state ? state.session.status : "")}
      </p>
      {joined && state?.participant?.admission_state === "admitted" ? (
        <>
          <Chat stateUrl={stateUrl} stateVersion={state?.state_version ?? 0} />
          <History stateUrl={stateUrl} stateVersion={state?.state_version ?? 0} />
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
