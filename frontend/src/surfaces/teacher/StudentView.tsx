import * as React from "react";
import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { getJson, postJson } from "../../protocol.js";
import { getLocale } from "../../locales.js";
import { LocaleProvider, useT } from "../../i18n.js";
import { mountStudentSession } from "../student/StudentSession.js";

type Participant = { id: number; display_name: string; admission_state: string; inspection_token: string };

function StudentViewControls({
  participantsUrl,
  activateUrl,
  stateUrl,
}: {
  participantsUrl: string;
  activateUrl: string;
  stateUrl: string;
}) {
  const t = useT();
  const [participants, setParticipants] = useState<Participant[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    getJson<{ participants: Participant[] }>(participantsUrl)
      .then((data) => {
        setParticipants(data.participants);
        if (data.participants.length) setSelectedId(String(data.participants[0].id));
      })
      .catch((error: unknown) => setStatus(error instanceof Error ? error.message : t("unableToLoadParticipants")));
  }, [participantsUrl]);

  const inspectSelection = (token: string, active = false) => {
    const app = document.querySelector<HTMLElement>("[data-liveclassroom-app][data-audience='student']");
    if (!app) return;
    app.dispatchEvent(new Event("liveclassroom:unmount"));
    app.dataset.stateUrl = `${stateUrl}?act_as_token=${encodeURIComponent(token)}`;
    mountStudentSession(app);
    setStatus(active ? t("actingAsParticipant") : t("inspectingParticipant"));
  };

  const selected = participants.find((p) => String(p.id) === selectedId);

  return (
    <>
      <label>
        {t("participants")} {" "}
        <select value={selectedId} onChange={(e) => setSelectedId(e.target.value)}>
          {participants.map((participant) => (
            <option key={participant.id} value={String(participant.id)}>
              {participant.display_name} ({participant.admission_state})
            </option>
          ))}
        </select>
      </label>
      <button type="button" onClick={() => selected && inspectSelection(selected.inspection_token)}>
        {t("inspect")}
      </button>
      <button
        type="button"
        onClick={() => {
          const participantId = Number(selectedId);
          if (!Number.isInteger(participantId)) return;
          void postJson<{ act_as_token: string }>(activateUrl, { participant_id: participantId, confirm: true })
            .then(({ act_as_token }) => inspectSelection(act_as_token, true))
            .catch((error: unknown) => setStatus(error instanceof Error ? error.message : t("unableToActivateActAs")));
        }}
      >
        {t("actAsParticipant")}
      </button>
      <p aria-live="polite">{status}</p>
    </>
  );
}

export function mountStudentView(el: HTMLElement): void {
  const d = el.dataset;
  if (!d.participantsUrl || !d.activateUrl || !d.stateUrl) return;
  const root = createRoot(el);
  root.render(
    <LocaleProvider initial={getLocale()} root={el}>
      <StudentViewControls participantsUrl={d.participantsUrl} activateUrl={d.activateUrl} stateUrl={d.stateUrl} />
    </LocaleProvider>,
  );
}
