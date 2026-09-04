import { csrfToken } from "./protocol.js";
import { t, type Locale } from "./locales.js";

type FilePickerOptions = {
  locale: Locale;
  endpoint: string;
  allowServerPath: boolean;
  includeChannels?: boolean;
  onSuccess: () => void;
};

export function mountFilePicker(host: HTMLElement, options: FilePickerOptions): void {
  const form = document.createElement("form");
  form.className = "lc-file-picker";
  const title = document.createElement("input");
  title.type = "text";
  title.placeholder = t("fileTitle", options.locale);
  const caption = document.createElement("input");
  caption.type = "text";
  caption.placeholder = t("captionLabel", options.locale);
  const source = document.createElement("select");
  const uploadOption = new Option(t("fileUpload", options.locale), "upload");
  source.append(uploadOption);
  if (options.allowServerPath) source.append(new Option(t("fileServerPath", options.locale), "server"));
  const upload = document.createElement("input");
  upload.type = "file";
  upload.accept = ".pptx,.pdf,.md,.mp4,.webm";
  const path = document.createElement("input");
  path.type = "text";
  path.placeholder = t("fileServerPath", options.locale);
  path.hidden = true;
  const target = document.createElement("select");
  if (options.includeChannels) {
    target.append(new Option(t("display", options.locale), "display"));
    target.append(new Option(t("participants", options.locale), "participants"));
    target.append(new Option(t("fileBoth", options.locale), "both"));
  }
  const submit = document.createElement("button");
  submit.type = "submit";
  submit.textContent = t("filePresent", options.locale);
  const status = document.createElement("p");
  status.className = "lc-file-status";
  status.setAttribute("aria-live", "polite");
  source.addEventListener("change", () => {
    const server = source.value === "server";
    upload.hidden = server;
    path.hidden = !server;
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const server = source.value === "server";
    if (server ? !path.value.trim() : !upload.files?.[0]) {
      status.textContent = t("validationError", options.locale);
      return;
    }
    submit.disabled = true;
    status.textContent = t("fileLoading", options.locale);
    const request = server
      ? { headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() }, body: JSON.stringify({ server_path: path.value.trim(), title: title.value.trim(), caption: caption.value.trim(), ...(options.includeChannels ? { channels: target.value === "both" ? ["display", "participants"] : [target.value] } : {}) }) }
      : (() => {
          const body = new FormData();
          body.append("file", upload.files![0]);
          if (title.value.trim()) body.append("title", title.value.trim());
          if (caption.value.trim()) body.append("caption", caption.value.trim());
          if (options.includeChannels) body.append("channels", JSON.stringify(target.value === "both" ? ["display", "participants"] : [target.value]));
          return { headers: { "X-CSRFToken": csrfToken() }, body };
        })();
    void fetch(options.endpoint, { method: "POST", credentials: "same-origin", ...request })
      .then(async (response) => {
        const payload = await response.json().catch(() => ({})) as { detail?: string };
        if (!response.ok) throw new Error(payload.detail ?? t("fileUnavailable", options.locale));
        form.reset();
        path.hidden = true;
        status.textContent = t("updated", options.locale);
        options.onSuccess();
      })
      .catch((error: unknown) => { status.textContent = error instanceof Error ? error.message : t("fileUnavailable", options.locale); })
      .finally(() => { submit.disabled = false; });
  });
  form.append(title, caption, source, upload, path);
  if (options.includeChannels) form.append(target);
  form.append(submit, status);
  host.append(form);
}
