import {
  apiEndpoint,
  getJson,
  postJson,
  websocketUrl,
  type ActivityState,
  type AggregateState,
  type Audience,
  type ChannelState,
  type ChatState,
  type SessionState,
  type VisibilityState,
} from "./protocol.js";
import { mountAiChat } from "./ai_chat.js";
import { mountBuilder } from "./builder.js";
import { mountPluginActivity } from "./plugin_runtime.js";
import {
  getLocale,
  mountLanguageSwitcher,
  setStoredLocale,
  t,
  type Locale,
  type TranslationKey,
} from "./locales.js";

type Root = HTMLElement & {
  dataset: DOMStringMap & {
    sessionId?: string;
    audience?: Audience;
    stateUrl?: string;
    websocketUrl?: string;
    pendingName?: string;
    accessMode?: string;
    authenticated?: string;
    guestJoinUrl?: string;
    accountJoinUrl?: string;
    locale?: Locale;
  };
};

type StudentViewRoot = HTMLElement & {
  dataset: DOMStringMap & { participantsUrl?: string; activateUrl?: string; stateUrl?: string };
};

type ActivityContent = Record<string, unknown>;
type Choice = { id: string; text: string };

export function getLabels(locale?: Locale) {
  const loc = locale ?? getLocale();
  return {
    activity: t("activity", loc),
    waiting: t("waiting", loc),
    unavailable: t("unavailable", loc),
    submit: t("submit", loc),
    update: t("update", loc),
    saved: t("saved", loc),
    stale: t("stale", loc),
    noAnswer: t("noAnswer", loc),
    state: t("state", loc),
    revision: t("revision", loc),
    close: t("close", loc),
    reveal: t("reveal", loc),
    start: t("start", loc),
    pause: t("pause", loc),
    end: t("end", loc),
    display: t("display", loc),
    participants: t("participants", loc),
    publish: t("publish", loc),
    showPrompt: t("showPrompt", loc),
    showAggregate: t("showAggregate", loc),
    showAnswer: t("showAnswer", loc),
    showExplanation: t("showExplanation", loc),
    showOwnStatus: t("showOwnStatus", loc),
    allowReview: t("allowReview", loc),
    admit: t("admit", loc),
    pending: t("pending", loc),
    chat: t("chat", loc),
    chatDisabled: t("chatDisabled", loc),
    chatUnavailable: t("chatUnavailable", loc),
    send: t("send", loc),
    enableChat: t("enableChat", loc),
    displayPreview: t("displayPreview", loc),
    participantPreview: t("participantPreview", loc),
    history: t("history", loc),
    timer: t("timer", loc),
    timerRemaining: t("timerRemaining", loc),
    timerFinished: t("timerFinished", loc),
    seconds: t("seconds", loc),
    confirmEnd: t("confirmEnd", loc),
    noActivityPublished: t("noActivityPublished", loc),
    controls: t("controls", loc),
    audienceVisibility: t("audienceVisibility", loc),
    enterDisplayName: t("enterDisplayName", loc),
    joinClassroom: t("joinClassroom", loc),
    displayName: t("displayName", loc),
    signInRequired: t("signInRequired", loc),
    waitingAdmission: t("waitingAdmission", loc),
    notShownYet: t("notShownYet", loc),
    noHistory: t("noHistory", loc),
    historyUnavailable: t("historyUnavailable", loc),
    noMessages: t("noMessages", loc),
    updated: t("updated", loc),
    results: t("results", loc),
    noResponses: t("noResponses", loc),
    publishToReview: t("publishToReview", loc),
    analyticsUnavailable: t("analyticsUnavailable", loc),
    wordCloud: t("wordCloud", loc),
    wordFrequencies: t("wordFrequencies", loc),
    moderation: t("moderation", loc),
    responseRate: t("responseRate", loc),
    admitted: t("admitted", loc),
    connected: t("connected", loc),
    attended: t("attended", loc),
  };
}

export const labels = new Proxy({} as Record<string, string>, {
  get(_target, prop: string) {
    return t(prop as TranslationKey);
  },
});

function text(tag: string, value: unknown): HTMLElement {
  const node = document.createElement(tag);
  node.textContent = String(value ?? "");
  return node;
}

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function stringValue(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

function numberValue(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string" || !value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function escapeHtml(str: string): string {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderMarkdownText(markdown: string): HTMLElement {
  const container = document.createElement("div");
  container.className = "lc-markdown-body";

  const lines = markdown.split("\n");
  let inCodeBlock = false;
  let codeBuffer: string[] = [];
  let currentList: HTMLElement | null = null;
  let inListType: "ul" | "ol" | null = null;
  let currentBlockquote: HTMLElement | null = null;

  const flushList = () => {
    if (currentList) {
      container.append(currentList);
      currentList = null;
      inListType = null;
    }
  };

  const flushBlockquote = () => {
    if (currentBlockquote) {
      container.append(currentBlockquote);
      currentBlockquote = null;
    }
  };

  const formatInline = (escaped: string): string => {
    return escaped
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/__([^_]+)__/g, "<strong>$1</strong>")
      .replace(/\*([^*]+)\*/g, "<em>$1</em>")
      .replace(/_([^_]+)_/g, "<em>$1</em>")
      .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  };

  for (const line of lines) {
    const trimmed = line.trim();

    if (trimmed.startsWith("```")) {
      flushList();
      flushBlockquote();
      if (inCodeBlock) {
        const pre = document.createElement("pre");
        const code = document.createElement("code");
        code.textContent = codeBuffer.join("\n");
        pre.append(code);
        container.append(pre);
        codeBuffer = [];
        inCodeBlock = false;
      } else {
        inCodeBlock = true;
        codeBuffer = [];
      }
      continue;
    }

    if (inCodeBlock) {
      codeBuffer.push(line);
      continue;
    }

    if (!trimmed) {
      flushList();
      flushBlockquote();
      continue;
    }

    const headingMatch = trimmed.match(/^(#{1,6})\s+(.*)$/);
    if (headingMatch) {
      flushList();
      flushBlockquote();
      const level = Math.min(headingMatch[1].length, 6);
      const h = document.createElement(`h${level}`);
      h.innerHTML = formatInline(escapeHtml(headingMatch[2]));
      container.append(h);
      continue;
    }

    if (trimmed.startsWith(">")) {
      flushList();
      const quoteText = trimmed.replace(/^>\s*/, "");
      if (!currentBlockquote) {
        currentBlockquote = document.createElement("blockquote");
      }
      const p = document.createElement("p");
      p.innerHTML = formatInline(escapeHtml(quoteText));
      currentBlockquote.append(p);
      continue;
    } else {
      flushBlockquote();
    }

    const ulMatch = trimmed.match(/^[-*+]\s+(.*)$/);
    if (ulMatch) {
      if (inListType !== "ul") {
        flushList();
        currentList = document.createElement("ul");
        inListType = "ul";
      }
      const li = document.createElement("li");
      li.innerHTML = formatInline(escapeHtml(ulMatch[1]));
      currentList?.append(li);
      continue;
    }

    const olMatch = trimmed.match(/^\d+\.\s+(.*)$/);
    if (olMatch) {
      if (inListType !== "ol") {
        flushList();
        currentList = document.createElement("ol");
        inListType = "ol";
      }
      const li = document.createElement("li");
      li.innerHTML = formatInline(escapeHtml(olMatch[1]));
      currentList?.append(li);
      continue;
    }

    flushList();

    const p = document.createElement("p");
    p.innerHTML = formatInline(escapeHtml(trimmed));
    container.append(p);
  }

  flushList();
  flushBlockquote();
  if (inCodeBlock && codeBuffer.length) {
    const pre = document.createElement("pre");
    const code = document.createElement("code");
    code.textContent = codeBuffer.join("\n");
    pre.append(code);
    container.append(pre);
  }

  return container;
}

function activityKind(activity: ActivityState): string {
  const definition = activity.definition;
  const typeKey = stringValue(definition.type_key);
  if (typeKey) return typeKey.split(".").pop() ?? typeKey;
  const question = record(definition.question);
  return stringValue(definition.kind, stringValue(question.type, stringValue(question.question_type)));
}

function activityContent(activity: ActivityState): ActivityContent {
  const definition = activity.definition;
  const content = record(definition.content);
  const question = record(definition.question);
  if (Object.keys(content).length) return content;
  return question;
}

function questionPrompt(activity: ActivityState): string {
  const definition = activity.definition;
  const content = activityContent(activity);
  return stringValue(
    content.prompt,
    stringValue(content.stem_markdown, stringValue(definition.prompt, stringValue(definition.stem_markdown))),
  );
}

function choicesFor(activity: ActivityState): Choice[] {
  const content = activityContent(activity);
  const data = record(content.data);
  const raw = Array.isArray(content.options)
    ? content.options
    : Array.isArray(content.choices)
      ? content.choices
      : Array.isArray(data.options)
        ? data.options
        : Array.isArray(data.choices)
          ? data.choices
          : [];
  return raw.flatMap((item, index): Choice[] => {
    if (typeof item === "string") return [{ id: String.fromCharCode(65 + index), text: item }];
    const option = record(item);
    const id = stringValue(option.id);
    const optionText = stringValue(option.text, stringValue(option.label));
    return id && optionText ? [{ id, text: optionText }] : [];
  });
}

function answerText(answer: Record<string, unknown>, key: string): string {
  const value = answer[key];
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

function selectedChoices(answer: Record<string, unknown>): string[] {
  const selected = answer.ranking ?? answer.choices ?? answer.choice;
  return Array.isArray(selected) ? selected.map(String) : selected === undefined ? [] : [String(selected)];
}

function submitUrl(stateUrl: string, activity: ActivityState): string {
  return apiEndpoint(stateUrl, `activities/${activity.id}/submissions`);
}

function appendPrompt(parent: HTMLElement, activity: ActivityState): void {
  const prompt = questionPrompt(activity);
  if (prompt) parent.append(text("p", prompt));
  const content = activityContent(activity);
  const markdown = stringValue(content.markdown, stringValue(activity.definition.markdown));
  if (markdown && markdown !== prompt) {
    parent.append(renderMarkdownText(markdown));
  }
}

function displayAnswer(value: unknown): string {
  if (Array.isArray(value)) return value.map(String).join(", ");
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

function appendChoicePresentation(parent: HTMLElement, activity: ActivityState): void {
  const choices = choicesFor(activity);
  if (!choices.length) return;
  const list = document.createElement("ul");
  for (const option of choices) list.append(text("li", `${option.id}. ${option.text}`));
  parent.append(list);
}

function appendRevealedFeedback(parent: HTMLElement, activity: ActivityState, locale: Locale = getLocale()): void {
  const content = activityContent(activity);
  const answer = displayAnswer(content.answer ?? content.correct_answer ?? activity.definition.answer);
  if (answer) {
    const label = locale === "zh-Hans" ? "正确答案" : "Answer";
    parent.append(text("p", `${label}: ${answer}`));
  }
  const explanation = stringValue(content.explanation_markdown, stringValue(content.explanation));
  if (explanation) {
    parent.append(renderMarkdownText(explanation));
  }
}

function answerFor(activity: ActivityState, state: SessionState | undefined): Record<string, unknown> {
  return state?.my_submission?.answer ?? {};
}

function appendAnswerStatus(parent: HTMLElement, state: SessionState | undefined, locale: Locale = getLocale()): void {
  if (!state?.my_submission) return;
  parent.append(text("p", state.my_submission.is_stale ? t("stale", locale) : t("saved", locale)));
}

function createSubmitButton(
  activity: ActivityState,
  state: SessionState | undefined,
  locale: Locale = getLocale(),
): HTMLButtonElement {
  const button = document.createElement("button");
  button.type = "submit";
  button.textContent = state?.my_submission && !state.my_submission.is_stale ? t("update", locale) : t("submit", locale);
  button.disabled = activity.state !== "open";
  return button;
}

function appendChoiceAnswer(
  parent: HTMLElement,
  activity: ActivityState,
  state: SessionState,
  kind: string,
  stateUrl: string,
  locale: Locale = getLocale(),
): void {
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
  const submit = createSubmitButton(activity, state, locale);
  if (activity.state === "open") form.append(submit);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const values = [...new FormData(form).getAll(multiple ? "choices" : "choice")].map(String);
    if (!values.length) return;
    const answerPayload = multiple ? { choices: values } : { choice: values[0] };
    void submitAnswer(form, submitUrl(stateUrl, activity), answerPayload, submit, stateUrl, locale);
  });
  parent.append(form);
}

function appendTextAnswer(
  parent: HTMLElement,
  activity: ActivityState,
  state: SessionState,
  kind: string,
  stateUrl: string,
  locale: Locale = getLocale(),
): void {
  const content = activityContent(activity);
  const form = document.createElement("form");
  const input = document.createElement(
    kind === "short_text" || kind === "word_cloud" ? "textarea" : "input",
  ) as HTMLInputElement | HTMLTextAreaElement;
  const field = kind === "numeric" ? "value" : kind === "rating" ? "rating" : "text";
  input.name = field;
  input.value = answerText(answerFor(activity, state), field);
  if (kind === "word_cloud") {
    input.placeholder = locale === "zh-Hans" ? "输入词语或短语…" : "Enter a word or phrase…";
  }
  if (input instanceof HTMLInputElement) {
    input.type = kind === "numeric" || kind === "rating" ? "number" : "text";
    const minimum = numberValue(content.minimum);
    const maximum = numberValue(content.maximum);
    const step = numberValue(content.step);
    if (minimum !== null) input.min = String(minimum);
    if (maximum !== null) input.max = String(maximum);
    if (step !== null) input.step = String(step);
  }
  input.disabled = activity.state !== "open";
  form.append(input);
  const submit = createSubmitButton(activity, state, locale);
  if (activity.state === "open") form.append(submit);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const raw = input.value.trim();
    if (!raw) return;
    const value = kind === "numeric" || kind === "rating" ? Number(raw) : raw;
    if (typeof value === "number" && !Number.isFinite(value)) return;
    void submitAnswer(form, submitUrl(stateUrl, activity), { [field]: value }, submit, stateUrl, locale);
  });
  parent.append(form);
}

function appendRankingAnswer(
  parent: HTMLElement,
  activity: ActivityState,
  state: SessionState,
  stateUrl: string,
  locale: Locale = getLocale(),
): void {
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
  const submit = createSubmitButton(activity, state, locale);
  if (activity.state === "open") form.append(submit);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const values = [...select.selectedOptions].map((option) => option.value);
    if (!values.length) return;
    void submitAnswer(form, submitUrl(stateUrl, activity), { ranking: values }, submit, stateUrl, locale);
  });
  parent.append(form);
}

async function submitAnswer(
  form: HTMLFormElement,
  url: string,
  answer: Record<string, unknown>,
  button: HTMLButtonElement,
  stateUrl: string,
  locale: Locale = getLocale(),
): Promise<void> {
  button.disabled = true;
  let notice = form.querySelector<HTMLElement>("[data-liveclassroom-form-status]");
  if (!notice) {
    notice = document.createElement("p");
    notice.dataset.liveclassroomFormStatus = "true";
    notice.setAttribute("aria-live", "polite");
    form.append(notice);
  }
  try {
    await postJson(url, { answer });
    notice.textContent = t("saved", locale);
    window.setTimeout(() => void refreshMountedState(form.closest<Root>("[data-liveclassroom-app]"), stateUrl), 0);
  } catch (error) {
    notice.textContent = error instanceof Error ? error.message : t("unavailable", locale);
    button.disabled = false;
  }
}

// Media renderer
function renderMedia(parent: HTMLElement, activity: ActivityState): void {
  const content = activityContent(activity);
  const mediaDisabled = content.media_disabled === true || activity.definition.media_disabled === true;
  if (mediaDisabled) {
    parent.append(text("p", "This media is unavailable."));
    return;
  }
  const url = stringValue(content.url, stringValue(activity.definition.url));
  if (!url) return;
  const rawMediaType = stringValue(content.media_type, stringValue(activity.definition.media_type)).toLowerCase();
  const caption = stringValue(content.caption, stringValue(activity.definition.caption));

  let mediaType = rawMediaType;
  const cleanUrl = url.split("?")[0].toLowerCase();
  if (!mediaType) {
    if (cleanUrl.match(/\.(png|jpe?g|svg|webp|gif)$/i)) {
      mediaType = "image";
    } else if (cleanUrl.match(/\.(mp4|webm)$/i)) {
      mediaType = "video";
    } else if (cleanUrl.match(/\.(mp3|ogg|wav)$/i)) {
      mediaType = "audio";
    } else {
      mediaType = "iframe";
    }
  }

  const container = document.createElement("div");
  container.className = "lc-media-container";

  if (mediaType === "image" || cleanUrl.match(/\.(png|jpe?g|svg|webp|gif)$/i)) {
    const img = document.createElement("img");
    img.src = url;
    img.alt = caption || "Media image";
    img.style.maxWidth = "100%";
    img.style.borderRadius = "8px";
    container.append(img);
  } else if (mediaType === "video" || cleanUrl.match(/\.(mp4|webm)$/i)) {
    const video = document.createElement("video");
    video.controls = true;
    video.src = url;
    video.style.maxWidth = "100%";
    container.append(video);
  } else if (mediaType === "audio" || cleanUrl.match(/\.(mp3|ogg|wav)$/i)) {
    const audio = document.createElement("audio");
    audio.controls = true;
    audio.src = url;
    container.append(audio);
  } else {
    const iframe = document.createElement("iframe");
    const provider = stringValue(content.provider, stringValue(activity.definition.provider)).toLowerCase();
    iframe.src = url;
    iframe.sandbox.value = provider === "vaultpub" ? "allow-scripts allow-same-origin" : "allow-scripts";
    iframe.referrerPolicy = provider === "vaultpub" ? "same-origin" : "no-referrer";
    iframe.allow = "";
    iframe.loading = "lazy";
    iframe.title = caption || (provider === "vaultpub" ? "VaultPub presentation" : "Embedded content");
    iframe.style.width = "100%";
    iframe.style.minHeight = "400px";
    iframe.style.border = "none";
    iframe.style.borderRadius = "8px";
    container.append(iframe);
  }

  if (caption) {
    const figcaption = document.createElement("p");
    figcaption.className = "lc-media-caption";
    figcaption.textContent = caption;
    container.append(figcaption);
  }

  parent.append(container);
}

// Timer renderer
const activeTimerStartTimes = new Map<string, number>();

function renderTimer(parent: HTMLElement, activity: ActivityState, audience: Audience, locale: Locale): void {
  const content = activityContent(activity);
  const duration = numberValue(content.duration_seconds) ?? numberValue(activity.definition.duration_seconds) ?? 60;
  const label = stringValue(content.label, stringValue(activity.definition.label, t("timer", locale)));

  const container = document.createElement("div");
  container.className = "lc-timer-display";

  if (label) {
    const labelEl = document.createElement("div");
    labelEl.className = "lc-timer-label";
    labelEl.textContent = label;
    container.append(labelEl);
  }

  const countdownEl = document.createElement("div");
  countdownEl.className = "lc-timer-countdown";

  const totalDurationEl = document.createElement("div");
  totalDurationEl.className = "lc-timer-subtext";
  totalDurationEl.textContent = `${t("timerRemaining", locale)} (${duration}${t("seconds", locale)})`;

  container.append(countdownEl, totalDurationEl);
  parent.append(container);

  const timerKey = `timer_${activity.id}_${activity.revision}`;
  let startTime = activeTimerStartTimes.get(timerKey);
  if (!startTime) {
    startTime = Date.now();
    activeTimerStartTimes.set(timerKey, startTime);
  }

  const updateDisplay = (): boolean => {
    if (!countdownEl.isConnected) return false;
    let remaining = 0;
    if (activity.state === "open") {
      const elapsed = Math.floor((Date.now() - startTime!) / 1000);
      remaining = Math.max(0, duration - elapsed);
    } else if (activity.state === "closed") {
      remaining = 0;
    } else {
      remaining = duration;
    }

    const mm = String(Math.floor(remaining / 60)).padStart(2, "0");
    const ss = String(remaining % 60).padStart(2, "0");

    if (remaining <= 0) {
      countdownEl.textContent = "00:00";
      countdownEl.classList.add("lc-timer-ended");
      totalDurationEl.textContent = t("timerFinished", locale);
      totalDurationEl.classList.add("lc-timer-ended-text");
      return false;
    } else {
      countdownEl.textContent = `${mm}:${ss}`;
      return true;
    }
  };

  const initialRun = updateDisplay();
  if (activity.state === "open" && initialRun) {
    const interval = window.setInterval(() => {
      const keepTicking = updateDisplay();
      if (!keepTicking) {
        window.clearInterval(interval);
      }
    }, 1000);
  }
}

// Word cloud renderer
function renderWordCloud(parent: HTMLElement, aggregate: AggregateState | null, locale: Locale, isTeacher = false): void {
  const container = document.createElement("div");
  container.className = "lc-word-cloud";

  const wordMap = ((aggregate?.word_frequencies ?? aggregate?.words) ?? {}) as Record<string, number>;
  const entries = Object.entries(wordMap);
  if (!entries.length) {
    container.append(text("p", t("noResponses", locale)));
    parent.append(container);
    return;
  }

  let minCount = Infinity;
  let maxCount = -Infinity;
  for (const [, count] of entries) {
    const num = Number(count) || 1;
    if (num < minCount) minCount = num;
    if (num > maxCount) maxCount = num;
  }
  if (!Number.isFinite(minCount)) minCount = 1;
  if (!Number.isFinite(maxCount)) maxCount = 1;

  const tagsContainer = document.createElement("div");
  tagsContainer.className = "lc-word-cloud-tags";

  const sorted = [...entries].sort((a, b) => (Number(b[1]) || 0) - (Number(a[1]) || 0) || a[0].localeCompare(b[0]));
  for (const [word, countVal] of sorted) {
    const count = Number(countVal) || 1;
    const tag = document.createElement("span");
    tag.className = "lc-word-tag";
    const fontSize = maxCount === minCount
      ? 18
      : Math.round(14 + ((count - minCount) / (maxCount - minCount)) * (36 - 14));
    tag.style.fontSize = `${fontSize}px`;
    tag.textContent = `${word} (${count})`;
    tag.title = `${word}: ${count}`;
    tagsContainer.append(tag);
  }
  container.append(tagsContainer);

  if (isTeacher) {
    const rawAnswers = (aggregate?.raw_answers ?? aggregate?.values ?? []) as Array<unknown>;
    if (rawAnswers.length > 0) {
      const moderationSection = document.createElement("div");
      moderationSection.className = "lc-word-cloud-moderation";
      const modHeading = document.createElement("h4");
      modHeading.textContent = `${t("moderation", locale)} (${rawAnswers.length})`;
      moderationSection.append(modHeading);
      const list = document.createElement("ul");
      list.className = "lc-moderation-list";
      for (const item of rawAnswers) {
        list.append(text("li", displayAnswer(item)));
      }
      moderationSection.append(list);
      container.append(moderationSection);
    }
  }

  parent.append(container);
}

function renderAggregate(parent: HTMLElement, aggregate: AggregateState | null, locale: Locale = getLocale()): void {
  if (!aggregate) return;
  const count = aggregate.submission_count;
  const summary = typeof count === "number"
    ? `${count} ${locale === "zh-Hans" ? "人作答" : (count === 1 ? "response" : "responses")}`
    : t("results", locale);
  parent.append(text("p", summary));

  if (aggregate.choices) {
    const entries = Object.entries(aggregate.choices);
    let totalVotes = 0;
    for (const [, v] of entries) totalVotes += Number(v) || 0;

    const barsContainer = document.createElement("div");
    barsContainer.className = "lc-choice-bars";

    for (const [choice, value] of entries) {
      const voteCount = Number(value) || 0;
      const pct = totalVotes > 0 ? Math.round((voteCount / totalVotes) * 100) : 0;

      const row = document.createElement("div");
      row.className = "lc-choice-bar-row";

      const header = document.createElement("div");
      header.className = "lc-choice-bar-header";
      header.append(
        text("strong", choice),
        text("span", `${pct}% (${voteCount} ${voteCount === 1 ? t("vote", locale) : t("votes", locale)})`),
      );

      const barContainer = document.createElement("div");
      barContainer.className = "lc-bar-container";

      const bar = document.createElement("div");
      bar.className = "lc-bar";
      bar.style.width = `${pct}%`;

      const barText = document.createElement("span");
      barText.className = "lc-bar-text";
      barText.textContent = `${pct}% (${voteCount} ${locale === "zh-Hans" ? "票" : "votes"})`;

      barContainer.append(bar, barText);
      row.append(header, barContainer);
      barsContainer.append(row);
    }
    parent.append(barsContainer);
  }

  if (aggregate.words || aggregate.word_frequencies) {
    renderWordCloud(parent, aggregate, locale, false);
  }

  if (aggregate.values?.length && !aggregate.words && !aggregate.word_frequencies) {
    const values = document.createElement("ul");
    for (const value of aggregate.values) values.append(text("li", displayAnswer(value)));
    parent.append(values);
  }
}

function renderBuiltinActivity(
  parent: HTMLElement,
  activity: ActivityState | null,
  audience: Audience,
  state?: SessionState,
  stateUrl?: string,
  aggregate?: AggregateState | null,
  rootLocale?: Locale,
): void {
  const locale = rootLocale ?? getLocale(parent.closest<HTMLElement>("[data-liveclassroom-app]"));
  parent.replaceChildren();
  if (!activity) {
    parent.append(text("p", audience === "student" ? t("waiting", locale) : t("noActivityPublished", locale)));
    return;
  }
  const definition = activity.definition;
  parent.append(text("h2", stringValue(definition.title, stringValue(definition.kind, t("activity", locale)))));

  const kind = activityKind(activity);

  if (kind === "timer") {
    renderTimer(parent, activity, audience, locale);
    if (audience === "teacher") {
      parent.append(text("p", `${t("state", locale)}: ${activity.state}; ${t("revision", locale)} ${activity.revision}`));
    }
    return;
  }

  if (kind === "media") {
    appendPrompt(parent, activity);
    renderMedia(parent, activity);
    if (audience === "teacher") {
      parent.append(text("p", `${t("state", locale)}: ${activity.state}; ${t("revision", locale)} ${activity.revision}`));
    }
    return;
  }

  if (kind === "markdown") {
    const content = activityContent(activity);
    const md = stringValue(content.markdown, stringValue(activity.definition.markdown, questionPrompt(activity)));
    if (md) {
      parent.append(renderMarkdownText(md));
    } else {
      appendPrompt(parent, activity);
    }
    if (audience === "teacher") {
      parent.append(text("p", `${t("state", locale)}: ${activity.state}; ${t("revision", locale)} ${activity.revision}`));
    }
    return;
  }

  appendPrompt(parent, activity);
  const responseKinds = [
    "single_choice",
    "multiple_choice",
    "true_false",
    "poll",
    "short_text",
    "word_cloud",
    "numeric",
    "rating",
    "ranking",
  ];
  if (
    audience === "student"
    && state
    && stateUrl
    && state.act_as_active !== false
    && state.participant?.admission_state === "admitted"
  ) {
    const content = activityContent(activity);
    const hasVisibleContent = questionPrompt(activity) !== ""
      || choicesFor(activity).length > 0
      || stringValue(content.markdown, stringValue(activity.definition.markdown)) !== "";
    if (responseKinds.includes(kind) && !hasVisibleContent) {
      parent.append(text("p", t("notShownYet", locale)));
    } else if (["single_choice", "multiple_choice", "true_false", "poll"].includes(kind)) {
      appendChoiceAnswer(parent, activity, state, kind, stateUrl, locale);
    } else if (["short_text", "word_cloud", "numeric", "rating"].includes(kind)) {
      appendTextAnswer(parent, activity, state, kind, stateUrl, locale);
    } else if (kind === "ranking") {
      appendRankingAnswer(parent, activity, state, stateUrl, locale);
    } else {
      parent.append(text("p", t("noAnswer", locale)));
    }
    appendAnswerStatus(parent, state, locale);
  }
  if (audience !== "student") {
    if (kind === "word_cloud") {
      renderWordCloud(parent, aggregate ?? state?.aggregate ?? null, locale, audience === "teacher");
    } else {
      appendChoicePresentation(parent, activity);
    }
  }
  if (audience !== "student" || state?.participant?.admission_state === "admitted") {
    appendRevealedFeedback(parent, activity, locale);
  }
  if ((audience === "display" || audience === "teacher") && kind !== "word_cloud") {
    renderAggregate(parent, aggregate ?? state?.aggregate ?? null, locale);
  }
  if (audience === "teacher") {
    parent.append(text("p", `${t("state", locale)}: ${activity.state}; ${t("revision", locale)} ${activity.revision}`));
  }
}

const activityUnmounts = new WeakMap<HTMLElement, () => void>();

function renderActivity(
  parent: HTMLElement,
  activity: ActivityState | null,
  audience: Audience,
  state?: SessionState,
  stateUrl?: string,
  aggregate?: AggregateState | null,
  rootLocale?: Locale,
): void {
  activityUnmounts.get(parent)?.();
  const locale = rootLocale ?? getLocale(parent.closest<HTMLElement>("[data-liveclassroom-app]"));
  const unmount = mountPluginActivity({
    parent,
    activity,
    audience,
    state,
    stateUrl,
    aggregate,
    locale,
    manifest: activity?.frontend_manifest,
    fallback: (container) => {
      renderBuiltinActivity(container, activity, audience, state, stateUrl, aggregate, locale);
    },
  });
  activityUnmounts.set(parent, unmount);
}

function setStatus(root: Root, message: string): void {
  const status = root.querySelector<HTMLElement>("[data-liveclassroom-status]");
  if (status) status.textContent = message;
}

function channelState(state: SessionState, channel: string): ChannelState | null {
  return state.channels?.[channel] ?? null;
}

function button(label: string, disabled = false): HTMLButtonElement {
  const control = document.createElement("button");
  control.type = "button";
  control.textContent = label;
  control.disabled = disabled;
  return control;
}

function bindCommand(
  control: HTMLButtonElement | null,
  command: () => void,
): void {
  if (!control || control.dataset.liveclassroomCommandBound === "true") return;
  control.dataset.liveclassroomCommandBound = "true";
  control.addEventListener("click", command);
}

function actionUrl(stateUrl: string, suffix: string): string {
  return apiEndpoint(stateUrl, suffix);
}

async function ensureStudentJoin(root: Root): Promise<boolean> {
  const locale = getLocale(root);
  if (root.dataset.audience !== "student") return true;
  if (root.dataset.joined === "true") return true;
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
    await postJson(
      guestJoinUrl,
      { display_name: pendingName },
      `join-guest-${root.dataset.sessionId ?? "session"}`,
    );
    root.dataset.joined = "true";
    return true;
  }
  if (!authenticated && accessMode === "authenticated") return false;
  if (guestJoinUrl && accessMode !== "authenticated") {
    let prompt = root.querySelector<HTMLElement>("[data-liveclassroom-join-prompt]");
    if (!prompt) {
      prompt = document.createElement("form");
      prompt.dataset.liveclassroomJoinPrompt = "true";
      const label = document.createElement("label");
      label.textContent = `${t("displayName", locale)} `;
      const input = document.createElement("input");
      input.name = "display_name";
      input.required = true;
      input.maxLength = 100;
      const submit = button(t("joinClassroom", locale));
      submit.type = "submit";
      label.append(input);
      prompt.append(label, submit);
      prompt.addEventListener("submit", (event) => {
        event.preventDefault();
        const name = input.value.trim();
        if (!name) return;
        root.dataset.pendingName = name;
        prompt?.remove();
        void refreshMountedState(root, root.dataset.stateUrl);
      });
      (root.querySelector<HTMLElement>("[data-liveclassroom-content]") ?? root).prepend(prompt);
    }
  }
  return false;
}

async function execute(root: Root, url: string, body: Record<string, unknown> = {}): Promise<void> {
  const locale = getLocale(root);
  const key = `${root.dataset.sessionId ?? "session"}-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  try {
    await postJson(url, body, key);
    setStatus(root, t("updated", locale));
    await refreshMountedState(root, root.dataset.stateUrl);
  } catch (error) {
    setStatus(root, error instanceof Error ? error.message : t("unavailable", locale));
  }
}

function addCell(row: HTMLTableRowElement, value: unknown): void {
  const cell = document.createElement("td");
  cell.textContent = String(value ?? "");
  row.append(cell);
}

function emptyRow(message: string, columns: number): HTMLTableRowElement {
  const row = document.createElement("tr");
  const cell = document.createElement("td");
  cell.colSpan = columns;
  cell.textContent = message;
  row.append(cell);
  return row;
}

function renderTeacherAnalytics(root: Root, data: Record<string, unknown>, currentActivityId: number | null): void {
  const locale = getLocale(root);
  const attendance = record(data.attendance);
  const summary = root.querySelector<HTMLElement>("#analytics-summary");
  if (summary) {
    summary.textContent = `${attendance.admitted ?? 0} ${t("admitted", locale)} · ${attendance.currently_connected ?? 0} ${t("connected", locale)} · ${attendance.ever_connected ?? 0} ${t("attended", locale)} · ${attendance.pending ?? 0} ${t("pending", locale)}`;
  }
  const activities = Array.isArray(data.activities) ? data.activities.map(record) : [];
  const activityBody = root.querySelector<HTMLTableSectionElement>("#analytics-activities");
  if (activityBody) {
    activityBody.replaceChildren();
    if (!activities.length) activityBody.append(emptyRow(locale === "zh-Hans" ? "暂无活动。" : "No activities yet.", 6));
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
  const participantBody = root.querySelector<HTMLTableSectionElement>("#analytics-participants");
  const participants = Array.isArray(data.participants) ? data.participants.map(record) : [];
  if (participantBody) {
    participantBody.replaceChildren();
    if (!participants.length) participantBody.append(emptyRow(locale === "zh-Hans" ? "暂无学生。" : "No participants yet.", 5));
    for (const participant of participants) {
      const row = document.createElement("tr");
      addCell(row, participant.display_name);
      addCell(row, participant.admission_state);
      addCell(row, participant.current_response_count ?? 0);
      addCell(row, participant.stale_response_count ?? 0);
      const connStatus = participant.connected_at
        ? (participant.disconnected_at ? t("offline", locale) : t("connected", locale))
        : t("notConnected", locale);
      addCell(row, connStatus);
      participantBody.append(row);
    }
  }
  const current = activities.find((activity) => activity.id === currentActivityId);
  const caption = root.querySelector<HTMLElement>("#analytics-responses-caption");
  if (caption) {
    caption.textContent = current
      ? `${locale === "zh-Hans" ? "作答详情：" : "Responses for "}${current.title || current.kind}`
      : (locale === "zh-Hans" ? "当前活动作答详情" : "Responses for the current activity");
  }
  const responseBody = root.querySelector<HTMLTableSectionElement>("#analytics-responses");
  if (responseBody) {
    responseBody.replaceChildren();
    const responses = current && Array.isArray(current.responses) ? current.responses.map(record) : [];
    if (!current || !responses.length) {
      responseBody.append(emptyRow(current ? (locale === "zh-Hans" ? "暂无作答。" : "No responses yet.") : (locale === "zh-Hans" ? "发布活动后可在此查看学生作答。" : "Publish an activity to review responses."), 4));
    }
    for (const response of responses) {
      const row = document.createElement("tr");
      addCell(row, response.display_name);
      addCell(row, JSON.stringify(response.answer ?? {}));
      addCell(row, response.revision ?? "-");
      addCell(row, response.is_stale ? (locale === "zh-Hans" ? "已过期" : "Stale") : (locale === "zh-Hans" ? "最新" : "Current"));
      responseBody.append(row);
    }
  }
  const resultSummary = root.querySelector<HTMLElement>("#result-summary");
  if (resultSummary) {
    resultSummary.replaceChildren();
    if (!current) {
      resultSummary.append(text("p", t("noActivityPublished", locale)));
    } else {
      const rateBadge = document.createElement("div");
      rateBadge.className = "lc-rate-badge";
      rateBadge.textContent = `${t("responseRate", locale)}: ${current.response_rate ?? 0}% (${current.submitted_count ?? 0}/${current.eligible_participant_count ?? 0})`;
      resultSummary.append(rateBadge);

      const aggregate = record(current.aggregate);
      const choices = record(aggregate.choices);
      const choiceEntries = Object.entries(choices);

      if (choiceEntries.length > 0) {
        let totalVotes = 0;
        for (const [, count] of choiceEntries) totalVotes += Number(count) || 0;

        const barsContainer = document.createElement("div");
        barsContainer.className = "lc-choice-bars";

        for (const [choice, countVal] of choiceEntries) {
          const voteCount = Number(countVal) || 0;
          const pct = totalVotes > 0 ? Math.round((voteCount / totalVotes) * 100) : 0;

          const row = document.createElement("div");
          row.className = "lc-choice-bar-row";

          const header = document.createElement("div");
          header.className = "lc-choice-bar-header";
          header.append(
            text("strong", choice),
            text("span", `${pct}% (${voteCount} ${voteCount === 1 ? t("vote", locale) : t("votes", locale)})`),
          );

          const barContainer = document.createElement("div");
          barContainer.className = "lc-bar-container";

          const bar = document.createElement("div");
          bar.className = "lc-bar";
          bar.style.width = `${pct}%`;

          const barText = document.createElement("span");
          barText.className = "lc-bar-text";
          barText.textContent = `${pct}% (${voteCount} ${locale === "zh-Hans" ? "票" : "votes"})`;

          barContainer.append(bar, barText);
          row.append(header, barContainer);
          barsContainer.append(row);
        }
        resultSummary.append(barsContainer);
      } else if (aggregate.words || aggregate.word_frequencies) {
        renderWordCloud(resultSummary, aggregate as AggregateState, locale, true);
      } else {
        resultSummary.append(text("p", `${current.submitted_count ?? 0} ${locale === "zh-Hans" ? "人已提交" : "submitted"}`));
      }
    }
  }
}

function renderChat(root: Root, state: ChatState, stateUrl: string): void {
  const locale = getLocale(root);
  const audience = root.dataset.audience ?? "student";
  const host = root.querySelector<HTMLElement>("[data-liveclassroom-chat]");
  if (!host) return;
  const status = host.querySelector<HTMLElement>("[data-liveclassroom-chat-status]");
  const messages = host.querySelector<HTMLElement>("[data-liveclassroom-chat-messages]");
  const form = host.querySelector<HTMLFormElement>("[data-liveclassroom-chat-form]");
  const input = form?.querySelector<HTMLTextAreaElement>("textarea[name=body]");
  const send = form?.querySelector<HTMLButtonElement>("button[type=submit]");
  const settings = host.querySelector<HTMLElement>("[data-liveclassroom-chat-settings]");
  const chatHeading = host.querySelector<HTMLElement>("#chat-heading, h2");
  if (chatHeading) chatHeading.textContent = t("chat", locale);
  if (status) status.textContent = state.enabled ? "" : t("chatDisabled", locale);
  if (messages) {
    messages.replaceChildren();
    if (!state.messages.length) messages.append(text("li", state.enabled ? t("noMessages", locale) : t("chatDisabled", locale)));
    for (const message of state.messages) {
      const item = document.createElement("li");
      item.append(text("strong", `${stringValue(message.display_name)}: `), text("span", message.body));
      messages.append(item);
    }
  }
  if (form && input && send) {
    send.textContent = t("send", locale);
    form.hidden = audience === "student" ? !state.enabled : false;
    input.disabled = !state.enabled;
    send.disabled = !state.enabled;
    if (form.dataset.liveclassroomChatBound !== "true") {
      form.dataset.liveclassroomChatBound = "true";
      form.addEventListener("submit", (event) => {
        event.preventDefault();
        const body = input.value.trim();
        if (!body) return;
        send.disabled = true;
        void postJson(actionUrl(stateUrl, "sessions/chat/send"), { body }, `chat-${Date.now()}-${Math.random().toString(36).slice(2)}`)
          .then(() => {
            input.value = "";
            return refreshMountedState(root, stateUrl);
          })
          .catch((error: unknown) => {
            if (status) status.textContent = error instanceof Error ? error.message : t("chatUnavailable", locale);
            send.disabled = false;
          });
      });
    }
  }
  if (audience !== "teacher" || !settings) return;
  let toggle = settings.querySelector<HTMLInputElement>("input[type=checkbox]");
  let toggleLabel = settings.querySelector<HTMLLabelElement>("label");
  if (!toggle) {
    toggleLabel = document.createElement("label");
    toggle = document.createElement("input");
    toggle.type = "checkbox";
    toggleLabel.append(toggle, document.createTextNode(` ${t("enableChat", locale)}`));
    settings.append(toggleLabel);
    toggle.addEventListener("change", () => void execute(
      root,
      actionUrl(stateUrl, "sessions/chat/settings"),
      { enabled: toggle?.checked ?? false },
    ));
  } else if (toggleLabel) {
    toggleLabel.lastChild?.remove();
    toggleLabel.append(document.createTextNode(` ${t("enableChat", locale)}`));
  }
  toggle.checked = state.enabled;
}

async function refreshChat(root: Root, stateUrl: string): Promise<void> {
  const locale = getLocale(root);
  try {
    const chat = await getJson<ChatState>(actionUrl(stateUrl, "sessions/chat"));
    renderChat(root, chat, stateUrl);
  } catch {
    const status = root.querySelector<HTMLElement>("[data-liveclassroom-chat-status]");
    if (status) status.textContent = t("chatUnavailable", locale);
  }
}

function renderStudentHistory(root: Root, stateUrl: string): void {
  const locale = getLocale(root);
  const host = root.querySelector<HTMLElement>("[data-liveclassroom-history]");
  if (!host || host.dataset.liveclassroomHistoryLoaded === "true") return;
  host.dataset.liveclassroomHistoryLoaded = "true";
  void getJson<{ activities: ActivityState[] }>(actionUrl(stateUrl, "sessions/history"))
    .then((data) => {
      host.replaceChildren(text("h2", t("history", locale)));
      if (!data.activities.length) {
        host.append(text("p", t("noHistory", locale)));
        return;
      }
      const list = document.createElement("ul");
      for (const activity of data.activities) {
        const item = document.createElement("li");
        item.append(text("strong", stringValue(activity.definition.title, t("activity", locale))));
        const prompt = questionPrompt(activity);
        if (prompt) item.append(text("span", `: ${prompt}`));
        list.append(item);
      }
      host.append(list);
    })
    .catch(() => {
      host.replaceChildren(text("p", t("historyUnavailable", locale)));
    });
}

async function refreshTeacherAnalytics(root: Root, state: SessionState, stateUrl: string): Promise<void> {
  const locale = getLocale(root);
  try {
    const data = await getJson<Record<string, unknown>>(actionUrl(stateUrl, "sessions/analytics"));
    renderTeacherAnalytics(root, data, state.current_activity?.id ?? null);
  } catch {
    const summary = root.querySelector<HTMLElement>("#analytics-summary");
    if (summary) summary.textContent = t("analyticsUnavailable", locale);
  }
}

function renderTeacherControls(root: Root, state: SessionState, stateUrl: string): void {
  const locale = getLocale(root);
  const actionHost = root.querySelector<HTMLElement>("[data-liveclassroom-teacher-controls]") ?? (() => {
    const host = document.createElement("section");
    host.dataset.liveclassroomTeacherControls = "true";
    host.setAttribute("aria-label", t("controls", locale));
    root.prepend(host);
    return host;
  })();
  actionHost.replaceChildren();
  const lifecycle = document.createElement("div");
  lifecycle.className = "lc-actions";
  const status = state.session.status;
  const activity = state.current_activity;
  const activityStatus = root.querySelector<HTMLElement>("#activity-status");
  if (activityStatus) {
    activityStatus.textContent = activity
      ? `${stringValue(activity.definition.title, stringValue(activity.definition.kind, t("activity", locale)))} (${activity.state})`
      : t("noActivityPublished", locale);
  }
  const existingStart = root.querySelector<HTMLButtonElement>("#start-session");
  const existingPause = root.querySelector<HTMLButtonElement>("#pause-session");
  const existingEnd = root.querySelector<HTMLButtonElement>("#end-session");
  if (existingStart) existingStart.textContent = t("start", locale);
  if (existingPause) existingPause.textContent = t("pause", locale);
  if (existingEnd) existingEnd.textContent = t("end", locale);

  if (!existingStart && !existingPause && !existingEnd) {
    const startControl = button(t("start", locale), ["live", "ended"].includes(status));
    const pauseControl = button(t("pause", locale), status !== "live");
    const endControl = button(t("end", locale), status === "ended");
    lifecycle.append(startControl, pauseControl, endControl);
    startControl.addEventListener("click", () => void execute(root, actionUrl(stateUrl, "sessions/start")));
    pauseControl.addEventListener("click", () => void execute(root, actionUrl(stateUrl, "sessions/pause")));
    endControl.addEventListener("click", () => {
      if (window.confirm(t("confirmEnd", locale))) {
        void execute(root, actionUrl(stateUrl, "sessions/end"));
      }
    });
    actionHost.append(lifecycle);
  } else {
    if (existingStart) existingStart.disabled = ["live", "ended"].includes(status);
    if (existingPause) existingPause.disabled = status !== "live";
    if (existingEnd) existingEnd.disabled = status === "ended";
    bindCommand(existingStart, () => void execute(root, actionUrl(stateUrl, "sessions/start")));
    bindCommand(existingPause, () => void execute(root, actionUrl(stateUrl, "sessions/pause")));
    bindCommand(existingEnd, () => {
      if (window.confirm(t("confirmEnd", locale))) {
        void execute(root, actionUrl(stateUrl, "sessions/end"));
      }
    });
  }
  for (const item of root.querySelectorAll<HTMLButtonElement>(".lc-item[data-step-id]")) {
    if (item.dataset.liveclassroomBound === "true") continue;
    item.dataset.liveclassroomBound = "true";
    item.addEventListener("click", () => {
      const stepId = numberValue(item.dataset.stepId);
      if (stepId !== null) void execute(root, actionUrl(stateUrl, "sessions/activities"), { flow_step_id: stepId });
    });
  }
  if (!activity) return;
  const activityActions = document.createElement("div");
  activityActions.className = "lc-actions";
  const existingClose = root.querySelector<HTMLButtonElement>("#close-activity");
  const existingReveal = root.querySelector<HTMLButtonElement>("#reveal-activity");
  if (existingClose) existingClose.textContent = t("close", locale);
  if (existingReveal) existingReveal.textContent = t("reveal", locale);

  if (!existingClose && !existingReveal) {
    const closeControl = button(t("close", locale), activity.state !== "open");
    const revealControl = button(t("reveal", locale), activity.state !== "closed");
    activityActions.append(closeControl, revealControl);
    closeControl.addEventListener("click", () => void execute(root, actionUrl(stateUrl, `activities/${activity.id}/close`)));
    revealControl.addEventListener("click", () => void execute(root, actionUrl(stateUrl, `activities/${activity.id}/reveal`)));
    actionHost.append(activityActions);
  } else {
    if (existingClose) existingClose.disabled = activity.state !== "open";
    if (existingReveal) existingReveal.disabled = activity.state !== "closed";
    bindCommand(existingClose, () => void execute(root, actionUrl(stateUrl, `activities/${activity.id}/close`)));
    bindCommand(existingReveal, () => void execute(root, actionUrl(stateUrl, `activities/${activity.id}/reveal`)));
  }
  const channels = document.createElement("div");
  channels.className = "lc-actions";
  for (const channel of ["display", "participants"]) {
    const publish = button(`${t("publish", locale)} · ${channel === "display" ? t("display", locale) : t("participants", locale)}`);
    publish.addEventListener("click", () => void execute(root, actionUrl(stateUrl, "sessions/channels/publish"), {
      channel,
      activity_id: activity.id,
    }));
    channels.append(publish);
  }
  actionHost.append(channels);
  const visibility = document.createElement("fieldset");
  visibility.append(text("legend", t("audienceVisibility", locale)));
  const participantChannel = channelState(state, "participants");
  const currentVisibility: VisibilityState = participantChannel?.visibility ?? {
    show_prompt: true,
    show_aggregate: false,
    show_answer: false,
    show_explanation: false,
    show_own_status: true,
    allow_review: false,
  };
  const visibilityFields: Array<[keyof VisibilityState, string]> = [
    ["show_prompt", t("showPrompt", locale)],
    ["show_aggregate", t("showAggregate", locale)],
    ["show_answer", t("showAnswer", locale)],
    ["show_explanation", t("showExplanation", locale)],
    ["show_own_status", t("showOwnStatus", locale)],
    ["allow_review", t("allowReview", locale)],
  ];
  for (const [field, label] of visibilityFields) {
    const wrapper = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = currentVisibility[field];
    checkbox.addEventListener("change", () => void execute(root, actionUrl(stateUrl, "sessions/channels/settings"), {
      channel: "participants",
      [field]: checkbox.checked,
    }));
    wrapper.append(checkbox, document.createTextNode(` ${label}`));
    visibility.append(wrapper, document.createElement("br"));
  }
  actionHost.append(visibility);
}

function renderAdmission(root: Root, participants: Array<Record<string, unknown>>, stateUrl: string): void {
  const locale = getLocale(root);
  const pending = participants.filter((participant) => participant.admission_state === "pending");
  const existing = root.querySelector<HTMLElement>("[data-liveclassroom-admission]") ?? (() => {
    const host = document.createElement("section");
    host.dataset.liveclassroomAdmission = "true";
    root.append(host);
    return host;
  })();
  existing.replaceChildren();
  if (!pending.length) return;
  existing.append(text("h2", `${t("participants", locale)} (${pending.length} ${t("pending", locale)})`));
  for (const participant of pending) {
    const participantId = numberValue(participant.id);
    if (participantId === null) continue;
    const admit = button(`${t("admit", locale)} ${stringValue(participant.display_name)}`);
    admit.addEventListener("click", () => void execute(
      root,
      actionUrl(stateUrl, `sessions/participants/${participantId}/admission`),
      { admitted: true },
    ));
    existing.append(admit);
  }
}

async function refreshTeacher(root: Root, state: SessionState, stateUrl: string): Promise<void> {
  const locale = getLocale(root);
  const content = root.querySelector<HTMLElement>("[data-liveclassroom-content]");
  if (content) {
    renderActivity(content, state.current_activity, "teacher", state, stateUrl, null, locale);
  }
  const participantPreview = root.querySelector<HTMLElement>("[data-liveclassroom-participant-preview]");
  const participantState = channelState(state, "participants");
  if (participantPreview) {
    renderActivity(
      participantPreview,
      participantState?.activity ?? null,
      "student",
      state,
      stateUrl,
      participantState?.aggregate,
      locale,
    );
  }
  renderTeacherControls(root, state, stateUrl);
  try {
    const participants = await getJson<{ participants: Array<Record<string, unknown>> }>(actionUrl(stateUrl, "sessions/participants"));
    renderAdmission(root, participants.participants, stateUrl);
  } catch {
    renderAdmission(root, [], stateUrl);
  }
}

async function refreshMountedState(root: Root | null, explicitStateUrl?: string): Promise<void> {
  if (!root) return;
  const locale = getLocale(root);
  mountLanguageSwitcher(root, () => {
    void refreshMountedState(root, explicitStateUrl ?? root.dataset.stateUrl);
  });

  const audience = root.dataset.audience ?? "student";
  const stateUrl = explicitStateUrl ?? root.dataset.stateUrl;
  if (!stateUrl) return;
  try {
    if (!(await ensureStudentJoin(root))) {
      if (audience === "student") {
        setStatus(
          root,
          root.dataset.accessMode === "authenticated" && root.dataset.authenticated !== "true"
            ? t("signInRequired", locale)
            : t("enterDisplayName", locale),
        );
      }
      return;
    }
    const channel = audience === "display" ? "display" : audience === "teacher" ? "display" : "participants";
    const state = await getJson<SessionState>(`${stateUrl}${stateUrl.includes("?") ? "&" : "?"}channel=${channel}`);
    const content = root.querySelector<HTMLElement>("[data-liveclassroom-content]");
    if (content && audience !== "teacher") {
      if (audience === "student" && state.participant && state.participant.admission_state !== "admitted") {
        content.replaceChildren(text("p", t("waitingAdmission", locale)));
      } else {
        renderActivity(content, state.current_activity, audience, state, stateUrl, null, locale);
      }
      const heading = root.querySelector<HTMLElement>(audience === "display" ? "#display-title" : "#student-title");
      if (heading) {
        heading.textContent = state.current_activity
          ? stringValue(state.current_activity.definition.title, state.session.title)
          : state.session.title;
      }
    } else if (audience === "teacher") {
      await refreshTeacher(root, state, stateUrl);
      const sessionStatus = root.querySelector<HTMLElement>("#session-status");
      if (sessionStatus) sessionStatus.textContent = state.session.status;
      await refreshTeacherAnalytics(root, state, stateUrl);
    }
    if (audience === "teacher" || (audience === "student" && state.participant?.admission_state === "admitted")) {
      await refreshChat(root, stateUrl);
    }
    if (audience === "student" && state.participant?.admission_state === "admitted") {
      renderStudentHistory(root, stateUrl);
    }
    setStatus(root, `${state.session.status} · ${t("state", locale)} ${state.state_version}`);
    root.dataset.stateVersion = String(state.state_version);
  } catch (error) {
    setStatus(root, error instanceof Error ? error.message : t("unavailable", locale));
  }
}

function connect(root: Root, refresh: () => Promise<void>): () => void {
  const path = root.dataset.websocketUrl;
  if (!path) return () => undefined;
  let retry = 1000;
  let retryTimer: number | undefined;
  let socket: WebSocket | undefined;
  let stopped = false;
  let lastVersion = numberValue(root.dataset.stateVersion) ?? -1;
  const open = (): void => {
    if (stopped) return;
    const connectedSocket = new WebSocket(websocketUrl(path));
    socket = connectedSocket;
    connectedSocket.onopen = () => { retry = 1000; };
    connectedSocket.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data) as { version?: unknown };
        const version = numberValue(message.version);
        if (version !== null) {
          lastVersion = Math.max(lastVersion, numberValue(root.dataset.stateVersion) ?? -1);
          if (version <= lastVersion) return;
          lastVersion = version;
        }
      } catch {
        // A malformed notification cannot change authoritative state.
      }
      void refresh();
    };
    connectedSocket.onerror = () => connectedSocket.close();
    connectedSocket.onclose = () => {
      if (stopped) return;
      const locale = getLocale(root);
      setStatus(root, locale === "zh-Hans" ? "正在重新连接…" : "Reconnecting…");
      retryTimer = window.setTimeout(open, retry);
      retry = Math.min(retry * 2, 30000);
    };
  };
  open();
  return () => {
    stopped = true;
    if (retryTimer !== undefined) window.clearTimeout(retryTimer);
    socket?.close();
  };
}

async function mount(root: Root): Promise<() => void> {
  const stateUrl = root.dataset.stateUrl;
  if (!stateUrl) return () => undefined;
  mountLanguageSwitcher(root, () => {
    void refreshMountedState(root, stateUrl);
  });
  let refreshing = false;
  const refresh = async (): Promise<void> => {
    if (refreshing) return;
    refreshing = true;
    try {
      await refreshMountedState(root, stateUrl);
    } finally {
      refreshing = false;
    }
  };
  const disconnect = connect(root, refresh);
  await refresh();
  const pollTimer = window.setInterval(() => void refresh(), 3000);
  const unmount = (): void => {
    disconnect();
    window.clearInterval(pollTimer);
  };
  root.addEventListener("liveclassroom:unmount", unmount, { once: true });
  return unmount;
}

async function mountStudentView(root: StudentViewRoot): Promise<void> {
  const app = document.querySelector<Root>("[data-liveclassroom-app][data-audience='student']");
  const select = root.querySelector<HTMLSelectElement>("[data-student-view-participant]");
  const inspect = root.querySelector<HTMLButtonElement>("[data-student-view-inspect]");
  const activate = root.querySelector<HTMLButtonElement>("[data-student-view-activate]");
  const status = root.querySelector<HTMLElement>("[data-student-view-status]");
  if (!app || !select || !inspect || !activate || !root.dataset.participantsUrl || !root.dataset.activateUrl || !root.dataset.stateUrl) return;
  const show = (message: string) => { if (status) status.textContent = message; };
  try {
    const payload = await getJson<{ participants: Array<{ id: number; display_name: string; admission_state: string; inspection_token: string }> }>(root.dataset.participantsUrl);
    for (const participant of payload.participants) {
      const option = document.createElement("option");
      option.value = String(participant.id);
      option.dataset.token = participant.inspection_token;
      option.textContent = `${participant.display_name} (${participant.admission_state})`;
      select.append(option);
    }
    const inspectSelection = async (token: string, active = false) => {
      app.dispatchEvent(new Event("liveclassroom:unmount"));
      app.dataset.stateUrl = `${root.dataset.stateUrl}?act_as_token=${encodeURIComponent(token)}`;
      await mount(app);
      show(active ? "Acting as selected participant." : "Inspecting selected participant.");
    };
    inspect.addEventListener("click", () => {
      const token = select.selectedOptions[0]?.dataset.token;
      if (token) void inspectSelection(token);
    });
    activate.addEventListener("click", () => {
      const participantId = Number(select.value);
      if (!Number.isInteger(participantId)) return;
      void postJson<{ act_as_token: string }>(root.dataset.activateUrl!, { participant_id: participantId, confirm: true })
        .then(({ act_as_token }) => inspectSelection(act_as_token, true))
        .catch((error: unknown) => show(error instanceof Error ? error.message : "Unable to activate act-as."));
    });
  } catch (error) {
    show(error instanceof Error ? error.message : "Unable to load participants.");
  }
}

if (typeof document !== "undefined") {
  for (const element of document.querySelectorAll<Root>("[data-liveclassroom-app]")) void mount(element);
  for (const element of document.querySelectorAll<HTMLElement>("[data-liveclassroom-builder]")) void mountBuilder(element);
  for (const element of document.querySelectorAll<HTMLElement>("[data-liveclassroom-ai-chat]")) void mountAiChat(element);
  for (const element of document.querySelectorAll<StudentViewRoot>("[data-student-view]")) void mountStudentView(element);
}

export {
  mount,
  refreshMountedState,
  renderActivity,
  mountBuilder,
  mountAiChat,
  mountLanguageSwitcher,
};
