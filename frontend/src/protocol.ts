export type Audience = "teacher" | "display" | "student";

export type SessionState = {
  protocol_version: number;
  session_id: number;
  state_version: number;
  session: {
    id: number;
    title: string;
    status: string;
    access_mode: string;
    admission_mode: string;
  };
  current_activity: ActivityState | null;
  participant: ParticipantState | null;
  my_submission: Record<string, unknown> | null;
  aggregate: Record<string, unknown> | null;
};

export type ActivityState = {
  id: number;
  state: string;
  revision: number;
  definition: Record<string, unknown>;
};

export type ParticipantState = {
  id: number;
  display_name: string;
  admission_state: string;
};

export type ApiError = { detail?: string };

export function csrfToken(): string {
  return document.cookie.match(/(?:^|;)\s*csrftoken=([^;]+)/)?.[1] ?? "";
}

export async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { credentials: "same-origin" });
  const payload = (await response.json()) as T & ApiError;
  if (!response.ok) throw new Error(payload.detail ?? "Request failed");
  return payload;
}

export async function postJson<T>(url: string, body: Record<string, unknown> = {}): Promise<T> {
  const response = await fetch(url, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
    body: JSON.stringify(body),
  });
  const payload = (await response.json()) as T & ApiError;
  if (!response.ok) throw new Error(payload.detail ?? "Request failed");
  return payload;
}
