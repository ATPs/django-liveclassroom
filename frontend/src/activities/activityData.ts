import { apiEndpoint, type ActivityState, type SessionState } from "../protocol.js";

export type Choice = { id: string; text: string };
export type ActivityContent = Record<string, unknown>;

export function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export function stringValue(value: unknown, fallback = ""): string {
  return typeof value === "string" ? value : fallback;
}

export function numberValue(value: unknown): number | null {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value !== "string" || !value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function escapeHtml(str: string): string {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function activityKind(activity: ActivityState): string {
  const definition = activity.definition;
  const typeKey = stringValue(definition.type_key);
  if (typeKey) return typeKey.split(".").pop() ?? typeKey;
  const question = record(definition.question);
  return stringValue(definition.kind, stringValue(question.type, stringValue(question.question_type)));
}

export function activityContent(activity: ActivityState): ActivityContent {
  const definition = activity.definition;
  const content = record(definition.content);
  const question = record(definition.question);
  if (Object.keys(content).length) return content;
  return question;
}

export function questionPrompt(activity: ActivityState): string {
  const definition = activity.definition;
  const content = activityContent(activity);
  return stringValue(
    content.prompt,
    stringValue(content.stem_markdown, stringValue(definition.prompt, stringValue(definition.stem_markdown))),
  );
}

export function choicesFor(activity: ActivityState): Choice[] {
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

export function answerText(answer: Record<string, unknown>, key: string): string {
  const value = answer[key];
  return typeof value === "string" || typeof value === "number" ? String(value) : "";
}

export function selectedChoices(answer: Record<string, unknown>): string[] {
  const selected = answer.ranking ?? answer.choices ?? answer.choice;
  return Array.isArray(selected) ? selected.map(String) : selected === undefined ? [] : [String(selected)];
}

export function displayAnswer(value: unknown): string {
  if (Array.isArray(value)) return value.map(String).join(", ");
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}

export function answerFor(activity: ActivityState, state: SessionState | undefined): Record<string, unknown> {
  if (state?.current_activity?.id !== activity.id || state?.my_submission?.is_stale) return {};
  return state?.my_submission?.answer ?? {};
}

export function submitUrl(stateUrl: string, activity: ActivityState): string {
  return apiEndpoint(stateUrl, `activities/${activity.id}/submissions`);
}

export function activityTitle(activity: ActivityState, fallback: string): string {
  const definition = activity.definition;
  return stringValue(definition.title, stringValue(definition.kind, fallback));
}
