import { getJson, postJson, type ActivityState, type Audience, type SessionState } from "./protocol.js";

type Root = HTMLElement & {
  dataset: DOMStringMap & { sessionId?: string; audience?: Audience; stateUrl?: string; startUrl?: string };
};

function text(tag: string, value: unknown): HTMLElement {
  const node = document.createElement(tag);
  node.textContent = String(value ?? "");
  return node;
}

function renderActivity(parent: HTMLElement, activity: ActivityState | null, audience: Audience): void {
  parent.replaceChildren();
  if (!activity) {
    parent.append(text("p", audience === "student" ? "Waiting for the teacher." : "No activity published."));
    return;
  }
  const definition = activity.definition;
  parent.append(text("h2", definition.title ?? definition.kind ?? "Activity"));
  const content = (definition.content ?? {}) as Record<string, unknown>;
  if (typeof content.prompt === "string") parent.append(text("p", content.prompt));
  if (typeof content.markdown === "string") parent.append(text("p", content.markdown));
  const options = content.options;
  if (Array.isArray(options)) {
    const list = document.createElement("ul");
    for (const option of options) {
      if (typeof option === "string") list.append(text("li", option));
      else if (option && typeof option === "object") {
        const row = option as Record<string, unknown>;
        list.append(text("li", `${row.id ?? ""}. ${row.text ?? ""}`));
      }
    }
    parent.append(list);
  }
  if (audience === "teacher") parent.append(text("p", `State: ${activity.state}; revision ${activity.revision}`));
}

async function mount(root: Root): Promise<void> {
  const audience = root.dataset.audience ?? "student";
  const stateUrl = root.dataset.stateUrl;
  if (!stateUrl) return;
  const content = root.querySelector<HTMLElement>("[data-liveclassroom-content]");
  if (!content) return;
  const status = root.querySelector<HTMLElement>("[data-liveclassroom-status]");
  const refresh = async (): Promise<void> => {
    try {
      const state = await getJson<SessionState>(`${stateUrl}${stateUrl.includes("?") ? "&" : "?"}channel=${audience === "display" ? "display" : "participants"}`);
      renderActivity(content, state.current_activity, audience);
      if (status) status.textContent = `${state.session.status} · state ${state.state_version}`;
    } catch (error) {
      if (status) status.textContent = error instanceof Error ? error.message : "Classroom state is unavailable.";
    }
  };
  const websocketUrl = root.dataset.websocketUrl;
  if (websocketUrl) {
    const socket = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}${websocketUrl}`);
    socket.onmessage = () => void refresh();
    socket.onclose = () => { if (status) status.textContent = "Reconnecting…"; };
  }
  await refresh();
  window.setInterval(() => void refresh(), 3000);
}

for (const element of document.querySelectorAll<Root>("[data-liveclassroom-app]")) void mount(element);

export { mount, renderActivity };
