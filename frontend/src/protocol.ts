export type Audience = "teacher" | "display" | "student";

export type SessionState = {
  protocol_version: number;
  session_id: number;
  state_version: number;
  session: {
    id: number;
    title: string;
    status: string;
    version?: number;
    chat_enabled?: boolean;
    access_mode: string;
    admission_mode: string;
  };
  current_activity: ActivityState | null;
  participant: ParticipantState | null;
  my_submission: SubmissionState | null;
  aggregate: AggregateState | null;
  act_as_active?: boolean;
  channel?: string;
  channels?: Record<string, ChannelState>;
};

export type ActivityState = {
  id: number;
  state: string;
  revision: number;
  definition: Record<string, unknown>;
  frontend_manifest?: Record<string, string>;
};

export type SubmissionState = {
  id: number;
  answer: Record<string, unknown>;
  is_stale: boolean;
};

export type AggregateState = {
  submission_count?: number;
  choices?: Record<string, number>;
  values?: unknown[];
  [key: string]: unknown;
};

export type ChatMessage = {
  id: number;
  display_name: string;
  body: string;
  created_at?: string;
};

export type ChatState = {
  enabled: boolean;
  messages: ChatMessage[];
};

export type VisibilityState = {
  show_prompt: boolean;
  show_aggregate: boolean;
  show_answer: boolean;
  show_explanation: boolean;
  show_own_status: boolean;
  allow_review: boolean;
};

export type ChannelState = {
  version: number;
  activity: ActivityState | null;
  visibility: VisibilityState;
  aggregate: AggregateState | null;
  presentation?: PresentationState;
};

export type PresentationNavigationMode = "follow" | "paged" | "scroll";

export type PresentationState = {
  page?: number;
  navigation_mode?: PresentationNavigationMode;
};

export type ParticipantState = {
  id: number;
  display_name: string;
  admission_state: string;
};

export type ApiError = { detail?: string };

export type ApiResponse = Record<string, unknown>;

export function csrfToken(): string {
  const cookie = document.cookie.match(/(?:^|;)\s*csrftoken=([^;]+)/)?.[1];
  if (cookie) {
    try {
      return decodeURIComponent(cookie);
    } catch {
      return cookie;
    }
  }
  return document.querySelector<HTMLInputElement>("input[name=csrfmiddlewaretoken]")?.value ?? "";
}

export async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url, { credentials: "same-origin" });
  const payload = await response.json().catch(() => ({})) as T & ApiError;
  if (!response.ok) throw new Error(payload.detail ?? "Request failed");
  return payload;
}

export async function postJson<T>(
  url: string,
  body: Record<string, unknown> = {},
  idempotencyKey?: string,
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-CSRFToken": csrfToken(),
  };
  if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;
  const response = await fetch(url, {
    method: "POST",
    credentials: "same-origin",
    headers,
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({})) as T & ApiError;
  if (!response.ok) throw new Error(payload.detail ?? "Request failed");
  return payload;
}

export async function putJson<T>(
  url: string,
  body: Record<string, unknown> = {},
  idempotencyKey?: string,
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-CSRFToken": csrfToken(),
  };
  if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;
  const response = await fetch(url, {
    method: "PUT",
    credentials: "same-origin",
    headers,
    body: JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({})) as T & ApiError;
  if (!response.ok) throw new Error(payload.detail ?? "Request failed");
  return payload;
}

export async function deleteJson<T>(
  url: string,
  idempotencyKey?: string,
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-CSRFToken": csrfToken(),
  };
  if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;
  const response = await fetch(url, {
    method: "DELETE",
    credentials: "same-origin",
    headers,
  });
  const payload = await response.json().catch(() => ({})) as T & ApiError;
  if (!response.ok) throw new Error(payload.detail ?? "Request failed");
  return payload;
}


export function apiEndpoint(stateUrl: string, resource: string): string {
  const url = new URL(stateUrl, window.location.href);
  const statePath = /^(.*\/sessions\/)(\d+)\/state\/?$/;
  const match = url.pathname.match(statePath);
  if (!match) throw new Error("Unsupported classroom state URL.");
  const resourcePath = resource.replace(/^\/+/, "").replace(/\/+$/, "");
  if (resourcePath.startsWith("sessions/")) {
    url.pathname = `${match[1]}${match[2]}/${resourcePath.slice("sessions/".length)}/`;
  } else {
    url.pathname = `${match[1].replace(/sessions\/$/, "")}${resourcePath}/`;
  }
  return url.toString();
}

export function websocketUrl(path: string): string {
  if (/^wss?:\/\//i.test(path)) return path;
  return `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}${path}`;
}
