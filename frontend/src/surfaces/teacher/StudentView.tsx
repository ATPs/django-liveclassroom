import * as React from "react";
import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { getJson, postJson } from "../../protocol.js";
import type { SessionState } from "../../protocol.js";
import { getLocale } from "../../locales.js";
import { LocaleProvider, useT } from "../../i18n.js";
import { mountStudentSession } from "../student/StudentSession.js";

type Participant = { id: number; display_name: string; admission_state: string; inspection_token: string };

function StudentViewControls({
  participantsUrl,
  activateUrl,
  testStudentUrl,
  renewTestStudentUrl,
  teacherUrl,
  stateUrl,
}: {
  participantsUrl: string;
  activateUrl: string;
  testStudentUrl: string;
  renewTestStudentUrl: string;
  teacherUrl: string;
  stateUrl: string;
}) {
  const t = useT();
  const [participants, setParticipants] = useState<Participant[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [status, setStatus] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [testStudentActive, setTestStudentActive] = useState(false);
  const [testToken, setTestToken] = useState("");
  const [testSaved, setTestSaved] = useState(false);

  useEffect(() => {
    getJson<{ participants: Participant[] }>(participantsUrl)
      .then((data) => {
        setParticipants(data.participants);
        setLoaded(true);
      })
      .catch((error: unknown) => setStatus(error instanceof Error ? error.message : t("unableToLoadParticipants")));
  }, [participantsUrl]);

  const inspectSelection = (token: string, active = false) => {
    const app = document.querySelector<HTMLElement>("[data-liveclassroom-app][data-audience='student']");
    if (!app) return;
    app.dispatchEvent(new Event("liveclassroom:unmount"));
    app.dataset.preview = "false";
    app.dataset.stateUrl = `${stateUrl}?act_as_token=${encodeURIComponent(token)}`;
    mountStudentSession(app);
    setStatus(active ? t("actingAsParticipant") : t("inspectingParticipant"));
  };

  const updateActiveToken = (token: string) => {
    const nextStateUrl = `${stateUrl}?act_as_token=${encodeURIComponent(token)}`;
    const app = document.querySelector<HTMLElement>("[data-liveclassroom-app][data-audience='student']");
    if (app) app.dataset.stateUrl = nextStateUrl;
    window.dispatchEvent(new CustomEvent("liveclassroom:update-state-url", { detail: { stateUrl: nextStateUrl } }));
  };

  const selected = participants.find((p) => String(p.id) === selectedId);

  const activateTestStudent = () => {
    return postJson<{ act_as_token: string }>(testStudentUrl, {}, crypto.randomUUID())
      .then(({ act_as_token }) => {
        inspectSelection(act_as_token, true);
        setTestStudentActive(true);
        setTestToken(act_as_token);
        setStatus(t("testStudentNotice"));
      })
      .catch((error: unknown) => setStatus(error instanceof Error ? error.message : t("unableToActivateActAs")));
  };

  useEffect(() => {
    if (!testStudentActive) return undefined;
    // Test tokens last 15 minutes; renew before that limit while this panel
    // remains open so a teaching demo does not silently become read-only.
    const renew = window.setInterval(() => {
      void postJson<{ act_as_token: string }>(renewTestStudentUrl, {}, crypto.randomUUID())
        .then(({ act_as_token }) => {
          setTestToken(act_as_token);
          updateActiveToken(act_as_token);
          setStatus(t("testStudentNotice"));
        })
        .catch((error: unknown) => setStatus(error instanceof Error ? error.message : t("unavailable")));
    }, 10 * 60 * 1000);
    return () => window.clearInterval(renew);
  }, [renewTestStudentUrl, testStudentActive]);

  useEffect(() => {
    if (!testStudentActive || !testToken) return undefined;
    let active = true;
    const refresh = () => {
      void getJson<SessionState>(`${stateUrl}?act_as_token=${encodeURIComponent(testToken)}`)
        .then((next) => { if (active) setTestSaved(Boolean(next.my_submission && !next.my_submission.is_stale)); })
        .catch(() => undefined);
    };
    refresh();
    const interval = window.setInterval(refresh, 3000);
    return () => { active = false; window.clearInterval(interval); };
  }, [stateUrl, testStudentActive, testToken]);

  return (
    <>
      <p>{t("testStudentNotice")}</p>
      <button
        type="button"
        className="lc-btn-primary"
        onClick={() => {
          void activateTestStudent();
        }}
      >
        {t("tryTestStudent")}
      </button>
      {testStudentActive ? <button type="button" onClick={() => {
        const app = document.querySelector<HTMLElement>("[data-liveclassroom-app][data-audience='student']");
        if (!app) return;
        app.dispatchEvent(new Event("liveclassroom:unmount"));
        app.dataset.preview = "true";
        app.dataset.stateUrl = `${stateUrl}?preview=1&channel=participants`;
        mountStudentSession(app);
        setTestStudentActive(false);
        setTestToken("");
        setTestSaved(false);
        setStatus(t("participantPreview"));
      }}>{t("backToPreview")}</button> : null}
      {testStudentActive ? <section data-liveclassroom-test-results><h2>{t("testStudentResults")}</h2><p>{testSaved ? t("saved") : t("testStudentNoAnswer")}</p></section> : null}
      {!loaded ? <p aria-live="polite">{t("loading")}</p> : null}
      {loaded ? <details className="lc-console-panel">
        <summary>{t("participants")}</summary>
        {!participants.length ? <p aria-live="polite">{t("noParticipantsYet")}</p> : <>
          <label>
            {t("participants")} {" "}
            <select value={selectedId} onChange={(e) => setSelectedId(e.target.value)}>
              <option value="">—</option>
              {participants.map((participant) => (
                <option key={participant.id} value={String(participant.id)}>
                  {participant.display_name} ({participant.admission_state})
                </option>
              ))}
            </select>
          </label>
          <button type="button" disabled={!selected} onClick={() => selected && inspectSelection(selected.inspection_token)}>
            {t("inspect")}
          </button>
          <button
            type="button"
            disabled={!selected}
            onClick={() => {
              const participantId = Number(selectedId);
              if (!Number.isInteger(participantId)) return;
              if (!window.confirm(t("confirmAnswerOnBehalf"))) return;
              void postJson<{ act_as_token: string }>(activateUrl, { participant_id: participantId, confirm: true })
                .then(({ act_as_token }) => { setTestToken(act_as_token); inspectSelection(act_as_token, true); })
                .catch((error: unknown) => setStatus(error instanceof Error ? error.message : t("unableToActivateActAs")));
            }}
          >
            {t("answerOnBehalf")}
          </button>
        </>}
      </details> : null}
      <button type="button" onClick={() => window.location.assign(teacherUrl)}>{t("backToTeaching")}</button>
      <p aria-live="polite">{status}</p>
    </>
  );
}

export function mountStudentView(el: HTMLElement): void {
  const d = el.dataset;
  if (!d.participantsUrl || !d.activateUrl || !d.testStudentUrl || !d.renewTestStudentUrl || !d.teacherUrl || !d.stateUrl) return;
  const root = createRoot(el);
  root.render(
    <LocaleProvider initial={getLocale()} root={el}>
      <StudentViewControls participantsUrl={d.participantsUrl} activateUrl={d.activateUrl} testStudentUrl={d.testStudentUrl} renewTestStudentUrl={d.renewTestStudentUrl} teacherUrl={d.teacherUrl} stateUrl={d.stateUrl} />
    </LocaleProvider>,
  );
}
