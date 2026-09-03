// src/protocol.ts
function csrfToken() {
  const cookie = document.cookie.match(/(?:^|;)\s*csrftoken=([^;]+)/)?.[1];
  if (cookie) {
    try {
      return decodeURIComponent(cookie);
    } catch {
      return cookie;
    }
  }
  return document.querySelector("input[name=csrfmiddlewaretoken]")?.value ?? "";
}
async function getJson(url) {
  const response = await fetch(url, { credentials: "same-origin" });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok)
    throw new Error(payload.detail ?? "Request failed");
  return payload;
}
async function postJson(url, body = {}, idempotencyKey) {
  const headers = {
    "Content-Type": "application/json",
    "X-CSRFToken": csrfToken()
  };
  if (idempotencyKey)
    headers["Idempotency-Key"] = idempotencyKey;
  const response = await fetch(url, {
    method: "POST",
    credentials: "same-origin",
    headers,
    body: JSON.stringify(body)
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok)
    throw new Error(payload.detail ?? "Request failed");
  return payload;
}
function apiEndpoint(stateUrl, resource) {
  const url = new URL(stateUrl, window.location.href);
  const statePath = /^(.*\/sessions\/)(\d+)\/state\/?$/;
  const match = url.pathname.match(statePath);
  if (!match)
    throw new Error("Unsupported classroom state URL.");
  const resourcePath = resource.replace(/^\/+/, "").replace(/\/+$/, "");
  if (resourcePath.startsWith("sessions/")) {
    url.pathname = `${match[1]}${match[2]}/${resourcePath.slice("sessions/".length)}/`;
  } else {
    url.pathname = `${match[1].replace(/sessions\/$/, "")}${resourcePath}/`;
  }
  url.search = "";
  return url.toString();
}
function websocketUrl(path) {
  if (/^wss?:\/\//i.test(path))
    return path;
  return `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}${path}`;
}

// src/app.ts
var labels = {
  activity: "Activity",
  waiting: "Waiting for the teacher.",
  unavailable: "Classroom state is unavailable.",
  submit: "Submit answer",
  update: "Update answer",
  saved: "Answer saved.",
  stale: "This activity changed. Review and submit again.",
  noAnswer: "This item does not require a response.",
  state: "State",
  revision: "revision",
  close: "Close answers",
  reveal: "Reveal answer",
  start: "Start classroom",
  pause: "Pause",
  end: "End classroom",
  display: "Display",
  participants: "Participants",
  publish: "Publish",
  showPrompt: "Show prompt",
  showAggregate: "Show aggregate",
  showAnswer: "Show answer",
  showExplanation: "Show explanation",
  showOwnStatus: "Show response status",
  allowReview: "Allow review",
  admit: "Admit",
  pending: "pending",
  chat: "Class chat",
  chatDisabled: "Chat is disabled.",
  chatUnavailable: "Chat is unavailable.",
  send: "Send",
  enableChat: "Enable chat",
  displayPreview: "Display preview",
  participantPreview: "Student preview",
  history: "Previous activities"
};
function text(tag, value) {
  const node = document.createElement(tag);
  node.textContent = String(value ?? "");
  return node;
}
function record(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? value : {};
}
function stringValue(value, fallback = "") {
  return typeof value === "string" ? value : fallback;
}
function numberValue(value) {
  if (typeof value === "number")
    return Number.isFinite(value) ? value : null;
  if (typeof value !== "string" || !value.trim())
    return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}
function activityKind(activity) {
  const definition = activity.definition;
  const typeKey = stringValue(definition.type_key);
  if (typeKey)
    return typeKey.split(".").pop() ?? typeKey;
  const question = record(definition.question);
  return stringValue(definition.kind, stringValue(question.type, stringValue(question.question_type)));
}
function activityContent(activity) {
  const definition = activity.definition;
  const content = record(definition.content);
  const question = record(definition.question);
  if (Object.keys(content).length)
    return content;
  return question;
}
function questionPrompt(activity) {
  const definition = activity.definition;
  const content = activityContent(activity);
  return stringValue(content.prompt, stringValue(content.stem_markdown, stringValue(definition.prompt, stringValue(definition.stem_markdown))));
}
function choicesFor(activity) {
  const content = activityContent(activity);
  const data = record(content.data);
  const raw = Array.isArray(content.options) ? content.options : Array.isArray(content.choices) ? content.choices : Array.isArray(data.options) ? data.options : Array.isArray(data.choices) ? data.choices : [];
  return raw.flatMap((item, index) => {
    if (typeof item === "string")
      return [{ id: String.fromCharCode(65 + index), text: item }];
    const option = record(item);
    const id = stringValue(option.id);
    const optionText = stringValue(option.text, stringValue(option.label));
    return id && optionText ? [{ id, text: optionText }] : [];
  });
}
function answerText(answer, key) {
  const value = answer[key];
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}
function selectedChoices(answer) {
  const selected = answer.ranking ?? answer.choices ?? answer.choice;
  return Array.isArray(selected) ? selected.map(String) : selected === undefined ? [] : [String(selected)];
}
function submitUrl(stateUrl, activity) {
  return apiEndpoint(stateUrl, `activities/${activity.id}/submissions`);
}
function appendPrompt(parent, activity) {
  const prompt = questionPrompt(activity);
  if (prompt)
    parent.append(text("p", prompt));
  const content = activityContent(activity);
  const markdown = stringValue(content.markdown, stringValue(activity.definition.markdown));
  if (markdown && markdown !== prompt)
    parent.append(text("p", markdown));
}
function displayAnswer(value) {
  if (Array.isArray(value))
    return value.map(String).join(", ");
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean")
    return String(value);
  return "";
}
function appendChoicePresentation(parent, activity) {
  const choices = choicesFor(activity);
  if (!choices.length)
    return;
  const list = document.createElement("ul");
  for (const option of choices)
    list.append(text("li", `${option.id}. ${option.text}`));
  parent.append(list);
}
function appendRevealedFeedback(parent, activity) {
  const content = activityContent(activity);
  const answer = displayAnswer(content.answer ?? content.correct_answer ?? activity.definition.answer);
  if (answer)
    parent.append(text("p", `Answer: ${answer}`));
  const explanation = stringValue(content.explanation_markdown, stringValue(content.explanation));
  if (explanation)
    parent.append(text("p", explanation));
}
function answerFor(activity, state) {
  return state?.my_submission?.answer ?? {};
}
function appendAnswerStatus(parent, state) {
  if (!state?.my_submission)
    return;
  parent.append(text("p", state.my_submission.is_stale ? labels.stale : labels.saved));
}
function createSubmitButton(activity, state) {
  const button = document.createElement("button");
  button.type = "submit";
  button.textContent = state?.my_submission && !state.my_submission.is_stale ? labels.update : labels.submit;
  button.disabled = activity.state !== "open";
  return button;
}
function appendChoiceAnswer(parent, activity, state, kind, stateUrl) {
  const form = document.createElement("form");
  const answer = answerFor(activity, state);
  const selected = selectedChoices(answer);
  const multiple = kind === "multiple_choice";
  for (const option of choicesFor(activity)) {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = multiple ? "checkbox" : "radio";
    input.name = multiple ? "choices" : "choice";
    input.value = option.id;
    input.checked = selected.includes(option.id);
    input.disabled = activity.state !== "open";
    label.append(input, document.createTextNode(` ${option.text}`));
    form.append(label, document.createElement("br"));
  }
  const submit = createSubmitButton(activity, state);
  if (activity.state === "open")
    form.append(submit);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const values = [...new FormData(form).getAll(multiple ? "choices" : "choice")].map(String);
    if (!values.length)
      return;
    const answerPayload = multiple ? { choices: values } : { choice: values[0] };
    submitAnswer(form, submitUrl(stateUrl, activity), answerPayload, submit, stateUrl);
  });
  parent.append(form);
}
function appendTextAnswer(parent, activity, state, kind, stateUrl) {
  const content = activityContent(activity);
  const form = document.createElement("form");
  const input = document.createElement(kind === "short_text" || kind === "word_cloud" ? "textarea" : "input");
  const field = kind === "numeric" ? "value" : kind === "rating" ? "rating" : "text";
  input.name = field;
  input.value = answerText(answerFor(activity, state), field);
  if (input instanceof HTMLInputElement) {
    input.type = kind === "numeric" || kind === "rating" ? "number" : "text";
    const minimum = numberValue(content.minimum);
    const maximum = numberValue(content.maximum);
    const step = numberValue(content.step);
    if (minimum !== null)
      input.min = String(minimum);
    if (maximum !== null)
      input.max = String(maximum);
    if (step !== null)
      input.step = String(step);
  }
  input.disabled = activity.state !== "open";
  form.append(input);
  const submit = createSubmitButton(activity, state);
  if (activity.state === "open")
    form.append(submit);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const raw = input.value.trim();
    if (!raw)
      return;
    const value = kind === "numeric" || kind === "rating" ? Number(raw) : raw;
    if (typeof value === "number" && !Number.isFinite(value))
      return;
    submitAnswer(form, submitUrl(stateUrl, activity), { [field]: value }, submit, stateUrl);
  });
  parent.append(form);
}
function appendRankingAnswer(parent, activity, state, stateUrl) {
  const form = document.createElement("form");
  const select = document.createElement("select");
  select.multiple = true;
  select.name = "ranking";
  const selected = selectedChoices(answerFor(activity, state));
  for (const option of choicesFor(activity)) {
    const element = document.createElement("option");
    element.value = option.id;
    element.textContent = option.text;
    element.selected = selected.includes(option.id);
    select.append(element);
  }
  select.disabled = activity.state !== "open";
  form.append(select);
  const submit = createSubmitButton(activity, state);
  if (activity.state === "open")
    form.append(submit);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const values = [...select.selectedOptions].map((option) => option.value);
    if (!values.length)
      return;
    submitAnswer(form, submitUrl(stateUrl, activity), { ranking: values }, submit, stateUrl);
  });
  parent.append(form);
}
async function submitAnswer(form, url, answer, button, stateUrl) {
  button.disabled = true;
  let notice = form.querySelector("[data-liveclassroom-form-status]");
  if (!notice) {
    notice = document.createElement("p");
    notice.dataset.liveclassroomFormStatus = "true";
    notice.setAttribute("aria-live", "polite");
    form.append(notice);
  }
  try {
    await postJson(url, { answer });
    notice.textContent = labels.saved;
    window.setTimeout(() => void refreshMountedState(form.closest("[data-liveclassroom-app]"), stateUrl), 0);
  } catch (error) {
    notice.textContent = error instanceof Error ? error.message : labels.unavailable;
    button.disabled = false;
  }
}
function renderAggregate(parent, aggregate) {
  if (!aggregate)
    return;
  const count = aggregate.submission_count;
  const summary = typeof count === "number" ? `${count} response${count === 1 ? "" : "s"}` : "Results";
  parent.append(text("p", summary));
  if (aggregate.choices) {
    const list = document.createElement("ul");
    for (const [choice, value] of Object.entries(aggregate.choices))
      list.append(text("li", `${choice}: ${value}`));
    parent.append(list);
  }
  if (aggregate.values?.length) {
    const values = document.createElement("ul");
    for (const value of aggregate.values)
      values.append(text("li", displayAnswer(value)));
    parent.append(values);
  }
}
function renderActivity(parent, activity, audience, state, stateUrl, aggregate) {
  parent.replaceChildren();
  if (!activity) {
    parent.append(text("p", audience === "student" ? labels.waiting : "No activity published."));
    return;
  }
  const definition = activity.definition;
  parent.append(text("h2", stringValue(definition.title, stringValue(definition.kind, labels.activity))));
  appendPrompt(parent, activity);
  const kind = activityKind(activity);
  const responseKinds = [
    "single_choice",
    "multiple_choice",
    "true_false",
    "poll",
    "short_text",
    "word_cloud",
    "numeric",
    "rating",
    "ranking"
  ];
  if (audience === "student" && state && stateUrl && state.participant?.admission_state === "admitted") {
    const content = activityContent(activity);
    const hasVisibleContent = questionPrompt(activity) !== "" || choicesFor(activity).length > 0 || stringValue(content.markdown, stringValue(activity.definition.markdown)) !== "";
    if (responseKinds.includes(kind) && !hasVisibleContent) {
      parent.append(text("p", "The teacher has not shown this activity yet."));
    } else if (["single_choice", "multiple_choice", "true_false", "poll"].includes(kind)) {
      appendChoiceAnswer(parent, activity, state, kind, stateUrl);
    } else if (["short_text", "word_cloud", "numeric", "rating"].includes(kind)) {
      appendTextAnswer(parent, activity, state, kind, stateUrl);
    } else if (kind === "ranking") {
      appendRankingAnswer(parent, activity, state, stateUrl);
    } else {
      parent.append(text("p", labels.noAnswer));
    }
    appendAnswerStatus(parent, state);
  }
  if (audience !== "student")
    appendChoicePresentation(parent, activity);
  if (audience !== "student" || state?.participant?.admission_state === "admitted") {
    appendRevealedFeedback(parent, activity);
  }
  if (audience === "display" || audience === "teacher")
    renderAggregate(parent, aggregate ?? state?.aggregate ?? null);
  if (audience === "teacher")
    parent.append(text("p", `${labels.state}: ${activity.state}; ${labels.revision} ${activity.revision}`));
}
function setStatus(root, message) {
  const status = root.querySelector("[data-liveclassroom-status]");
  if (status)
    status.textContent = message;
}
function channelState(state, channel) {
  return state.channels?.[channel] ?? null;
}
function button(label, disabled = false) {
  const control = document.createElement("button");
  control.type = "button";
  control.textContent = label;
  control.disabled = disabled;
  return control;
}
function bindCommand(control, command) {
  if (!control || control.dataset.liveclassroomCommandBound === "true")
    return;
  control.dataset.liveclassroomCommandBound = "true";
  control.addEventListener("click", command);
}
function actionUrl(stateUrl, suffix) {
  return apiEndpoint(stateUrl, suffix);
}
async function ensureStudentJoin(root) {
  if (root.dataset.audience !== "student")
    return true;
  if (root.dataset.joined === "true")
    return true;
  const pendingName = root.dataset.pendingName?.trim() ?? "";
  const authenticated = root.dataset.authenticated === "true";
  const accessMode = root.dataset.accessMode ?? "guest";
  const guestJoinUrl = root.dataset.guestJoinUrl;
  const accountJoinUrl = root.dataset.accountJoinUrl;
  if (authenticated && accessMode !== "guest" && accountJoinUrl) {
    await postJson(accountJoinUrl, {}, `join-account-${root.dataset.sessionId ?? "session"}`);
    root.dataset.joined = "true";
    return true;
  }
  if (pendingName && accessMode !== "authenticated" && guestJoinUrl) {
    await postJson(guestJoinUrl, { display_name: pendingName }, `join-guest-${root.dataset.sessionId ?? "session"}`);
    root.dataset.joined = "true";
    return true;
  }
  if (!authenticated && accessMode === "authenticated")
    return false;
  if (guestJoinUrl && accessMode !== "authenticated") {
    let prompt = root.querySelector("[data-liveclassroom-join-prompt]");
    if (!prompt) {
      prompt = document.createElement("form");
      prompt.dataset.liveclassroomJoinPrompt = "true";
      const label = document.createElement("label");
      label.textContent = "Display name";
      const input = document.createElement("input");
      input.name = "display_name";
      input.required = true;
      input.maxLength = 100;
      const submit = button("Join classroom");
      label.append(input);
      prompt.append(label, submit);
      prompt.addEventListener("submit", (event) => {
        event.preventDefault();
        const name = input.value.trim();
        if (!name)
          return;
        root.dataset.pendingName = name;
        prompt?.remove();
        refreshMountedState(root, root.dataset.stateUrl);
      });
      (root.querySelector("[data-liveclassroom-content]") ?? root).prepend(prompt);
    }
  }
  return false;
}
async function execute(root, url, body = {}) {
  const key = `${root.dataset.sessionId ?? "session"}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  try {
    await postJson(url, body, key);
    setStatus(root, "Updated");
    await refreshMountedState(root, root.dataset.stateUrl);
  } catch (error) {
    setStatus(root, error instanceof Error ? error.message : labels.unavailable);
  }
}
function addCell(row, value) {
  const cell = document.createElement("td");
  cell.textContent = String(value ?? "");
  row.append(cell);
}
function emptyRow(message, columns) {
  const row = document.createElement("tr");
  const cell = document.createElement("td");
  cell.colSpan = columns;
  cell.textContent = message;
  row.append(cell);
  return row;
}
function renderTeacherAnalytics(root, data, currentActivityId) {
  const attendance = record(data.attendance);
  const summary = root.querySelector("#analytics-summary");
  if (summary) {
    summary.textContent = `${attendance.admitted ?? 0} admitted · ${attendance.currently_connected ?? 0} connected · ${attendance.ever_connected ?? 0} attended · ${attendance.pending ?? 0} pending`;
  }
  const activities = Array.isArray(data.activities) ? data.activities.map(record) : [];
  const activityBody = root.querySelector("#analytics-activities");
  if (activityBody) {
    activityBody.replaceChildren();
    if (!activities.length)
      activityBody.append(emptyRow("No activities yet.", 6));
    for (const activity of activities) {
      const row = document.createElement("tr");
      addCell(row, activity.sequence);
      addCell(row, activity.title || activity.kind);
      addCell(row, `${activity.submitted_count ?? 0}/${activity.eligible_participant_count ?? 0}`);
      addCell(row, `${activity.response_rate ?? 0}%`);
      addCell(row, activity.stale_submission_count ?? 0);
      addCell(row, activity.state);
      activityBody.append(row);
    }
  }
  const participantBody = root.querySelector("#analytics-participants");
  const participants = Array.isArray(data.participants) ? data.participants.map(record) : [];
  if (participantBody) {
    participantBody.replaceChildren();
    if (!participants.length)
      participantBody.append(emptyRow("No participants yet.", 5));
    for (const participant of participants) {
      const row = document.createElement("tr");
      addCell(row, participant.display_name);
      addCell(row, participant.admission_state);
      addCell(row, participant.current_response_count ?? 0);
      addCell(row, participant.stale_response_count ?? 0);
      addCell(row, participant.connected_at ? participant.disconnected_at ? "Offline" : "Connected" : "Not connected");
      participantBody.append(row);
    }
  }
  const current = activities.find((activity) => activity.id === currentActivityId);
  const caption = root.querySelector("#analytics-responses-caption");
  if (caption)
    caption.textContent = current ? `Responses for ${current.title || current.kind}` : "Responses for the current activity";
  const responseBody = root.querySelector("#analytics-responses");
  if (responseBody) {
    responseBody.replaceChildren();
    const responses = current && Array.isArray(current.responses) ? current.responses.map(record) : [];
    if (!current || !responses.length)
      responseBody.append(emptyRow(current ? "No responses yet." : "Publish an activity to review responses.", 4));
    for (const response of responses) {
      const row = document.createElement("tr");
      addCell(row, response.display_name);
      addCell(row, JSON.stringify(response.answer ?? {}));
      addCell(row, response.revision ?? "-");
      addCell(row, response.is_stale ? "Stale" : "Current");
      responseBody.append(row);
    }
  }
  const resultSummary = root.querySelector("#result-summary");
  if (resultSummary) {
    const aggregate = current ? record(current.aggregate) : {};
    const choices = record(aggregate.choices);
    const choiceSummary = Object.entries(choices).map(([choice, count]) => `${choice}: ${count}`).join(" · ");
    resultSummary.textContent = current ? `${current.submitted_count ?? 0} submitted · ${choiceSummary || "No answers yet"}` : "No activity published.";
  }
}
function renderChat(root, state, stateUrl) {
  const audience = root.dataset.audience ?? "student";
  const host = root.querySelector("[data-liveclassroom-chat]");
  if (!host)
    return;
  const status = host.querySelector("[data-liveclassroom-chat-status]");
  const messages = host.querySelector("[data-liveclassroom-chat-messages]");
  const form = host.querySelector("[data-liveclassroom-chat-form]");
  const input = form?.querySelector("textarea[name=body]");
  const send = form?.querySelector("button[type=submit]");
  const settings = host.querySelector("[data-liveclassroom-chat-settings]");
  if (status)
    status.textContent = state.enabled ? "" : labels.chatDisabled;
  if (messages) {
    messages.replaceChildren();
    if (!state.messages.length)
      messages.append(text("li", state.enabled ? "No messages yet." : labels.chatDisabled));
    for (const message of state.messages) {
      const item = document.createElement("li");
      item.append(text("strong", `${stringValue(message.display_name)}: `), text("span", message.body));
      messages.append(item);
    }
  }
  if (form && input && send) {
    form.hidden = audience === "student" ? !state.enabled : false;
    input.disabled = !state.enabled;
    send.disabled = !state.enabled;
    if (form.dataset.liveclassroomChatBound !== "true") {
      form.dataset.liveclassroomChatBound = "true";
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        const body = input.value.trim();
        if (!body)
          return;
        send.disabled = true;
        postJson(actionUrl(stateUrl, "sessions/chat/send"), { body }, `chat-${Date.now()}-${Math.random().toString(36).slice(2)}`).then(() => {
          input.value = "";
          return refreshMountedState(root, stateUrl);
        }).catch((error) => {
          if (status)
            status.textContent = error instanceof Error ? error.message : labels.chatUnavailable;
          send.disabled = false;
        });
      });
    }
  }
  if (audience !== "teacher" || !settings)
    return;
  let toggle = settings.querySelector("input[type=checkbox]");
  if (!toggle) {
    const label = document.createElement("label");
    toggle = document.createElement("input");
    toggle.type = "checkbox";
    label.append(toggle, document.createTextNode(` ${labels.enableChat}`));
    settings.append(label);
    toggle.addEventListener("change", () => void execute(root, actionUrl(stateUrl, "sessions/chat/settings"), { enabled: toggle?.checked ?? false }));
  }
  toggle.checked = state.enabled;
}
async function refreshChat(root, stateUrl) {
  try {
    const chat = await getJson(actionUrl(stateUrl, "sessions/chat"));
    renderChat(root, chat, stateUrl);
  } catch {
    const status = root.querySelector("[data-liveclassroom-chat-status]");
    if (status)
      status.textContent = labels.chatUnavailable;
  }
}
function renderStudentHistory(root, stateUrl) {
  const host = root.querySelector("[data-liveclassroom-history]");
  if (!host || host.dataset.liveclassroomHistoryLoaded === "true")
    return;
  host.dataset.liveclassroomHistoryLoaded = "true";
  getJson(actionUrl(stateUrl, "sessions/history")).then((data) => {
    host.replaceChildren(text("h2", labels.history));
    if (!data.activities.length) {
      host.append(text("p", "No previous activities are available."));
      return;
    }
    const list = document.createElement("ul");
    for (const activity of data.activities) {
      const item = document.createElement("li");
      item.append(text("strong", stringValue(activity.definition.title, labels.activity)));
      const prompt = questionPrompt(activity);
      if (prompt)
        item.append(text("span", `: ${prompt}`));
      list.append(item);
    }
    host.append(list);
  }).catch(() => {
    host.replaceChildren(text("p", "Activity history is unavailable."));
  });
}
async function refreshTeacherAnalytics(root, state, stateUrl) {
  try {
    const data = await getJson(actionUrl(stateUrl, "sessions/analytics"));
    renderTeacherAnalytics(root, data, state.current_activity?.id ?? null);
  } catch {
    const summary = root.querySelector("#analytics-summary");
    if (summary)
      summary.textContent = "Analytics are unavailable.";
  }
}
function renderTeacherControls(root, state, stateUrl) {
  const actionHost = root.querySelector("[data-liveclassroom-teacher-controls]") ?? (() => {
    const host = document.createElement("section");
    host.dataset.liveclassroomTeacherControls = "true";
    host.setAttribute("aria-label", "Classroom controls");
    root.prepend(host);
    return host;
  })();
  actionHost.replaceChildren();
  const lifecycle = document.createElement("div");
  lifecycle.className = "lc-actions";
  const status = state.session.status;
  const activity = state.current_activity;
  const activityStatus = root.querySelector("#activity-status");
  if (activityStatus) {
    activityStatus.textContent = activity ? `${stringValue(activity.definition.title, stringValue(activity.definition.kind, labels.activity))} (${activity.state})` : "No activity published.";
  }
  const existingStart = root.querySelector("#start-session");
  const existingPause = root.querySelector("#pause-session");
  const existingEnd = root.querySelector("#end-session");
  if (!existingStart && !existingPause && !existingEnd) {
    const startControl = button(labels.start, ["live", "ended"].includes(status));
    const pauseControl = button(labels.pause, status !== "live");
    const endControl = button(labels.end, status === "ended");
    lifecycle.append(startControl, pauseControl, endControl);
    startControl.addEventListener("click", () => void execute(root, actionUrl(stateUrl, "sessions/start")));
    pauseControl.addEventListener("click", () => void execute(root, actionUrl(stateUrl, "sessions/pause")));
    endControl.addEventListener("click", () => {
      if (window.confirm("End this classroom? Students will no longer be able to join.")) {
        execute(root, actionUrl(stateUrl, "sessions/end"));
      }
    });
    actionHost.append(lifecycle);
  } else {
    if (existingStart)
      existingStart.disabled = ["live", "ended"].includes(status);
    if (existingPause)
      existingPause.disabled = status !== "live";
    if (existingEnd)
      existingEnd.disabled = status === "ended";
    bindCommand(existingStart, () => void execute(root, actionUrl(stateUrl, "sessions/start")));
    bindCommand(existingPause, () => void execute(root, actionUrl(stateUrl, "sessions/pause")));
    bindCommand(existingEnd, () => {
      if (window.confirm("End this classroom? Students will no longer be able to join.")) {
        execute(root, actionUrl(stateUrl, "sessions/end"));
      }
    });
  }
  for (const item of root.querySelectorAll(".lc-item[data-item-id]")) {
    if (item.dataset.liveclassroomBound === "true")
      continue;
    item.dataset.liveclassroomBound = "true";
    item.addEventListener("click", () => {
      const itemId = numberValue(item.dataset.itemId);
      if (itemId !== null)
        execute(root, actionUrl(stateUrl, "sessions/activities"), { flow_item_id: itemId });
    });
  }
  if (!activity)
    return;
  const activityActions = document.createElement("div");
  activityActions.className = "lc-actions";
  const existingClose = root.querySelector("#close-activity");
  const existingReveal = root.querySelector("#reveal-activity");
  if (!existingClose && !existingReveal) {
    const closeControl = button(labels.close, activity.state !== "open");
    const revealControl = button(labels.reveal, activity.state !== "closed");
    activityActions.append(closeControl, revealControl);
    closeControl.addEventListener("click", () => void execute(root, actionUrl(stateUrl, `activities/${activity.id}/close`)));
    revealControl.addEventListener("click", () => void execute(root, actionUrl(stateUrl, `activities/${activity.id}/reveal`)));
    actionHost.append(activityActions);
  } else {
    if (existingClose)
      existingClose.disabled = activity.state !== "open";
    if (existingReveal)
      existingReveal.disabled = activity.state !== "closed";
    bindCommand(existingClose, () => void execute(root, actionUrl(stateUrl, `activities/${activity.id}/close`)));
    bindCommand(existingReveal, () => void execute(root, actionUrl(stateUrl, `activities/${activity.id}/reveal`)));
  }
  const channels = document.createElement("div");
  channels.className = "lc-actions";
  for (const channel of ["display", "participants"]) {
    const publish = button(`${labels.publish} · ${channel === "display" ? labels.display : labels.participants}`);
    publish.addEventListener("click", () => void execute(root, actionUrl(stateUrl, "sessions/channels/publish"), {
      channel,
      activity_id: activity.id
    }));
    channels.append(publish);
  }
  actionHost.append(channels);
  const visibility = document.createElement("fieldset");
  visibility.append(text("legend", "Audience visibility"));
  const participantChannel = channelState(state, "participants");
  const currentVisibility = participantChannel?.visibility ?? {
    show_prompt: true,
    show_aggregate: false,
    show_answer: false,
    show_explanation: false,
    show_own_status: true,
    allow_review: false
  };
  const visibilityFields = [
    ["show_prompt", labels.showPrompt],
    ["show_aggregate", labels.showAggregate],
    ["show_answer", labels.showAnswer],
    ["show_explanation", labels.showExplanation],
    ["show_own_status", labels.showOwnStatus],
    ["allow_review", labels.allowReview]
  ];
  for (const [field, label] of visibilityFields) {
    const wrapper = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = currentVisibility[field];
    checkbox.addEventListener("change", () => void execute(root, actionUrl(stateUrl, "sessions/channels/settings"), {
      channel: "participants",
      [field]: checkbox.checked
    }));
    wrapper.append(checkbox, document.createTextNode(` ${label}`));
    visibility.append(wrapper, document.createElement("br"));
  }
  actionHost.append(visibility);
}
function renderAdmission(root, participants, stateUrl) {
  const pending = participants.filter((participant) => participant.admission_state === "pending");
  const existing = root.querySelector("[data-liveclassroom-admission]") ?? (() => {
    const host = document.createElement("section");
    host.dataset.liveclassroomAdmission = "true";
    root.append(host);
    return host;
  })();
  existing.replaceChildren();
  if (!pending.length)
    return;
  existing.append(text("h2", `Participants (${pending.length} ${labels.pending})`));
  for (const participant of pending) {
    const participantId = numberValue(participant.id);
    if (participantId === null)
      continue;
    const admit = button(`${labels.admit} ${stringValue(participant.display_name)}`);
    admit.addEventListener("click", () => void execute(root, actionUrl(stateUrl, `sessions/participants/${participantId}/admission`), { admitted: true }));
    existing.append(admit);
  }
}
async function refreshTeacher(root, state, stateUrl) {
  const content = root.querySelector("[data-liveclassroom-content]");
  if (content) {
    renderActivity(content, state.current_activity, "teacher", state, stateUrl);
  }
  const participantPreview = root.querySelector("[data-liveclassroom-participant-preview]");
  const participantState = channelState(state, "participants");
  if (participantPreview) {
    renderActivity(participantPreview, participantState?.activity ?? null, "student", state, stateUrl, participantState?.aggregate);
  }
  renderTeacherControls(root, state, stateUrl);
  try {
    const participants = await getJson(actionUrl(stateUrl, "sessions/participants"));
    renderAdmission(root, participants.participants, stateUrl);
  } catch {
    renderAdmission(root, [], stateUrl);
  }
}
async function refreshMountedState(root, explicitStateUrl) {
  if (!root)
    return;
  const audience = root.dataset.audience ?? "student";
  const stateUrl = explicitStateUrl ?? root.dataset.stateUrl;
  if (!stateUrl)
    return;
  try {
    if (!await ensureStudentJoin(root)) {
      if (audience === "student") {
        setStatus(root, root.dataset.accessMode === "authenticated" && root.dataset.authenticated !== "true" ? "Sign in to join this classroom." : "Enter a display name to join this classroom.");
      }
      return;
    }
    const channel = audience === "display" ? "display" : audience === "teacher" ? "display" : "participants";
    const state = await getJson(`${stateUrl}${stateUrl.includes("?") ? "&" : "?"}channel=${channel}`);
    const content = root.querySelector("[data-liveclassroom-content]");
    if (content && audience !== "teacher") {
      if (audience === "student" && state.participant && state.participant.admission_state !== "admitted") {
        content.replaceChildren(text("p", "Waiting for teacher admission."));
      } else {
        renderActivity(content, state.current_activity, audience, state, stateUrl);
      }
      const heading = root.querySelector(audience === "display" ? "#display-title" : "#student-title");
      if (heading && state.current_activity) {
        heading.textContent = stringValue(state.current_activity.definition.title, state.session.title);
      }
    } else if (audience === "teacher") {
      await refreshTeacher(root, state, stateUrl);
      const sessionStatus = root.querySelector("#session-status");
      if (sessionStatus)
        sessionStatus.textContent = state.session.status;
      await refreshTeacherAnalytics(root, state, stateUrl);
    }
    if (audience === "teacher" || audience === "student" && state.participant?.admission_state === "admitted") {
      await refreshChat(root, stateUrl);
    }
    if (audience === "student" && state.participant?.admission_state === "admitted") {
      renderStudentHistory(root, stateUrl);
    }
    setStatus(root, `${state.session.status} · state ${state.state_version}`);
  } catch (error) {
    setStatus(root, error instanceof Error ? error.message : labels.unavailable);
  }
}
function connect(root, refresh) {
  const path = root.dataset.websocketUrl;
  if (!path)
    return;
  let retry = 1000;
  const open = () => {
    const socket = new WebSocket(websocketUrl(path));
    socket.onopen = () => {
      retry = 1000;
    };
    socket.onmessage = () => void refresh();
    socket.onerror = () => socket.close();
    socket.onclose = () => {
      setStatus(root, "Reconnecting…");
      window.setTimeout(open, retry);
      retry = Math.min(retry * 2, 30000);
    };
  };
  open();
}
async function mount(root) {
  const stateUrl = root.dataset.stateUrl;
  if (!stateUrl)
    return;
  let refreshing = false;
  const refresh = async () => {
    if (refreshing)
      return;
    refreshing = true;
    try {
      await refreshMountedState(root, stateUrl);
    } finally {
      refreshing = false;
    }
  };
  connect(root, refresh);
  await refresh();
  window.setInterval(() => void refresh(), 3000);
}
if (typeof document !== "undefined") {
  for (const element of document.querySelectorAll("[data-liveclassroom-app]"))
    mount(element);
}
export {
  renderActivity,
  refreshMountedState,
  mount
};
