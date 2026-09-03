import { getJson, postJson } from "./protocol.js";
import { t, type Locale } from "./locales.js";

export type AIModel = {
  backend_key: string;
  identifier: string;
  label: string;
};

export type AuthoringThread = {
  id: number;
  title: string;
  created_at?: string;
  updated_at?: string;
};

export type AuthoringAttachment = {
  id?: number;
  source_type: string;
  source_id?: number | null;
  provider?: string;
  reference?: Record<string, unknown>;
  title?: string;
};

export type AuthoringMessage = {
  id: number;
  role: "user" | "assistant";
  content: string;
  model_identifier?: string;
  status?: string;
  attachments?: AuthoringAttachment[];
  created_at?: string;
};

export type AuthoringJob = {
  id: number;
  status: "queued" | "running" | "succeeded" | "failed";
  backend_key: string;
  model_identifier: string;
  error_code?: string | null;
  attempt?: number;
  message_id?: number;
  assistant_message_id?: number | null;
};

export type AiChatOptions = {
  onInsertDraft?: (text: string) => void;
  getAttachment?: () => AuthoringAttachment | null;
  locale?: Locale;
};

export function mountAiChat(
  container: HTMLElement,
  options: AiChatOptions = {},
): { unmount: () => void; refreshThreads: () => Promise<void> } {
  let isMounted = true;
  let activeThreadId: number | null = null;
  let activeJobId: number | null = null;
  let pollTimeout: number | null = null;
  let isGenerating = false;

  let models: AIModel[] = [];
  let threads: AuthoringThread[] = [];
  let messages: AuthoringMessage[] = [];

  container.replaceChildren();
  const root = document.createElement("div");
  root.className = "lc-ai-chat";
  container.append(root);

  // Header section
  const header = document.createElement("div");
  header.className = "lc-ai-header";

  const titleRow = document.createElement("div");
  titleRow.className = "lc-ai-title-row";
  const heading = document.createElement("h3");
  heading.textContent = t("aiAssistant", options.locale);
  titleRow.append(heading);

  // New Thread Button
  const newThreadBtn = document.createElement("button");
  newThreadBtn.type = "button";
  newThreadBtn.className = "lc-btn-sm";
  newThreadBtn.textContent = `+ ${t("newThread", options.locale)}`;
  newThreadBtn.addEventListener("click", () => void handleCreateThread());
  titleRow.append(newThreadBtn);
  header.append(titleRow);

  // Controls Row: Model & Thread selectors
  const controlsRow = document.createElement("div");
  controlsRow.className = "lc-ai-controls";

  // Thread selector
  const threadGroup = document.createElement("div");
  threadGroup.className = "lc-ai-control-group";
  const threadLabel = document.createElement("label");
  threadLabel.textContent = `${t("aiThread", options.locale)}: `;
  const threadSelect = document.createElement("select");
  threadSelect.className = "lc-ai-select";
  threadSelect.addEventListener("change", () => {
    const id = parseInt(threadSelect.value, 10);
    if (!Number.isNaN(id) && id !== activeThreadId) {
      void selectThread(id);
    }
  });
  threadLabel.append(threadSelect);
  threadGroup.append(threadLabel);
  controlsRow.append(threadGroup);

  // Model selector
  const modelGroup = document.createElement("div");
  modelGroup.className = "lc-ai-control-group";
  const modelLabel = document.createElement("label");
  modelLabel.textContent = `${t("aiModel", options.locale)}: `;
  const modelSelect = document.createElement("select");
  modelSelect.className = "lc-ai-select";
  modelLabel.append(modelSelect);
  modelGroup.append(modelLabel);
  controlsRow.append(modelGroup);

  header.append(controlsRow);
  root.append(header);

  // Messages log area
  const messagesContainer = document.createElement("div");
  messagesContainer.className = "lc-ai-messages";
  messagesContainer.setAttribute("role", "log");
  messagesContainer.setAttribute("aria-live", "polite");
  root.append(messagesContainer);

  // Input & Composer section
  const composer = document.createElement("div");
  composer.className = "lc-ai-composer";

  // Attachments bar
  const attachmentBar = document.createElement("div");
  attachmentBar.className = "lc-ai-attachment-bar";
  const attachCheckbox = document.createElement("input");
  attachCheckbox.type = "checkbox";
  attachCheckbox.id = `lc-attach-ctx-${Math.random().toString(36).slice(2, 7)}`;
  attachCheckbox.checked = true;

  const attachLabel = document.createElement("label");
  attachLabel.htmlFor = attachCheckbox.id;
  attachLabel.textContent = ` ${t("attachCurrentStep", options.locale)}`;

  const attachBadge = document.createElement("span");
  attachBadge.className = "lc-ai-attachment-badge";
  attachBadge.textContent = t("noAttachments", options.locale);

  attachmentBar.append(attachCheckbox, attachLabel, attachBadge);
  composer.append(attachmentBar);

  // Textarea input
  const promptInput = document.createElement("textarea");
  promptInput.className = "lc-ai-input";
  promptInput.rows = 3;
  promptInput.placeholder = t("aiPromptPlaceholder", options.locale);
  promptInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void handleSendMessage();
    }
  });
  composer.append(promptInput);

  // Action footer
  const footerRow = document.createElement("div");
  footerRow.className = "lc-ai-footer";

  const noteText = document.createElement("small");
  noteText.className = "lc-ai-note";
  noteText.textContent = t("aiNote", options.locale);

  const actionGroup = document.createElement("div");
  actionGroup.className = "lc-ai-action-group";

  const statusText = document.createElement("span");
  statusText.className = "lc-ai-status";

  const sendButton = document.createElement("button");
  sendButton.type = "button";
  sendButton.className = "lc-ai-send-btn";
  sendButton.textContent = t("aiSend", options.locale);
  sendButton.addEventListener("click", () => void handleSendMessage());

  actionGroup.append(statusText, sendButton);
  footerRow.append(noteText, actionGroup);
  composer.append(footerRow);

  root.append(composer);

  // Updates attachment badge when composer is focused or interacted with
  function updateAttachmentInfo(): void {
    if (!options.getAttachment) {
      attachmentBar.style.display = "none";
      return;
    }
    const att = options.getAttachment();
    if (att) {
      attachBadge.textContent = att.title ? `${att.source_type}: ${att.title}` : `${att.source_type} #${att.source_id}`;
      attachBadge.className = "lc-ai-attachment-badge lc-ai-attachment-active";
      attachCheckbox.disabled = false;
    } else {
      attachBadge.textContent = t("noAttachments", options.locale);
      attachBadge.className = "lc-ai-attachment-badge";
      attachCheckbox.disabled = true;
    }
  }

  // Render message list
  function renderMessages(): void {
    messagesContainer.replaceChildren();
    if (messages.length === 0) {
      const emptyNotice = document.createElement("p");
      emptyNotice.className = "lc-ai-empty";
      emptyNotice.textContent = t("noMessages", options.locale);
      messagesContainer.append(emptyNotice);
      return;
    }

    for (const msg of messages) {
      const msgCard = document.createElement("div");
      msgCard.className = `lc-ai-message lc-ai-message-${msg.role}`;

      const msgHeader = document.createElement("div");
      msgHeader.className = "lc-ai-msg-header";
      const authorSpan = document.createElement("strong");
      authorSpan.textContent = msg.role === "assistant" ? "AI Assistant" : "Teacher";
      msgHeader.append(authorSpan);

      if (msg.model_identifier) {
        const modelBadge = document.createElement("small");
        modelBadge.className = "lc-ai-msg-model";
        modelBadge.textContent = ` (${msg.model_identifier})`;
        msgHeader.append(modelBadge);
      }
      msgCard.append(msgHeader);

      const msgContent = document.createElement("div");
      msgContent.className = "lc-ai-msg-body";
      msgContent.textContent = msg.content;
      msgCard.append(msgContent);

      if (msg.role === "assistant" && msg.content.trim()) {
        const actionsRow = document.createElement("div");
        actionsRow.className = "lc-ai-msg-actions";

        // Copy button
        const copyBtn = document.createElement("button");
        copyBtn.type = "button";
        copyBtn.className = "lc-btn-sm lc-btn-outline";
        copyBtn.textContent = t("aiCopy", options.locale);
        copyBtn.addEventListener("click", () => {
          if (navigator.clipboard?.writeText) {
            void navigator.clipboard.writeText(msg.content).then(() => {
              copyBtn.textContent = t("aiCopied", options.locale);
              setTimeout(() => {
                copyBtn.textContent = t("aiCopy", options.locale);
              }, 2000);
            });
          }
        });
        actionsRow.append(copyBtn);

        // Insert into builder callback
        if (options.onInsertDraft) {
          const insertBtn = document.createElement("button");
          insertBtn.type = "button";
          insertBtn.className = "lc-btn-sm lc-btn-primary";
          insertBtn.textContent = t("aiInsertToBuilder", options.locale);
          insertBtn.addEventListener("click", () => {
            options.onInsertDraft?.(msg.content);
          });
          actionsRow.append(insertBtn);
        }

        msgCard.append(actionsRow);
      }

      messagesContainer.append(msgCard);
    }

    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  // Load models from server
  async function loadModels(): Promise<void> {
    try {
      const data = await getJson<{ backends?: string[]; models?: AIModel[] }>("/api/v1/authoring/models/");
      models = data.models ?? [];
      modelSelect.replaceChildren();
      if (models.length === 0) {
        const opt = document.createElement("option");
        opt.value = "";
        opt.textContent = "No models available";
        modelSelect.append(opt);
        modelSelect.disabled = true;
      } else {
        modelSelect.disabled = false;
        for (const m of models) {
          const opt = document.createElement("option");
          opt.value = `${m.backend_key}:${m.identifier}`;
          opt.textContent = m.label || `${m.backend_key} (${m.identifier})`;
          modelSelect.append(opt);
        }
      }
    } catch {
      modelSelect.replaceChildren();
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "Model discovery unavailable";
      modelSelect.append(opt);
      modelSelect.disabled = true;
    }
  }

  // Load threads
  async function loadThreads(): Promise<void> {
    try {
      const data = await getJson<{ threads: AuthoringThread[] }>("/api/v1/authoring/threads/");
      threads = data.threads ?? [];
      threadSelect.replaceChildren();

      if (threads.length === 0) {
        // Auto-create initial thread
        const created = await postJson<AuthoringThread>("/api/v1/authoring/threads/", {
          title: "Authoring Assistant",
        });
        threads = [created];
      }

      for (const th of threads) {
        const opt = document.createElement("option");
        opt.value = String(th.id);
        opt.textContent = th.title;
        threadSelect.append(opt);
      }

      if (!activeThreadId && threads.length > 0) {
        await selectThread(threads[0].id);
      } else if (activeThreadId) {
        threadSelect.value = String(activeThreadId);
      }
    } catch (err) {
      statusText.textContent = err instanceof Error ? err.message : "Failed to load threads";
    }
  }

  // Select and load a thread's messages
  async function selectThread(threadId: number): Promise<void> {
    activeThreadId = threadId;
    threadSelect.value = String(threadId);
    try {
      statusText.textContent = t("loading", options.locale);
      const data = await getJson<{
        id: number;
        title: string;
        messages: AuthoringMessage[];
        jobs: AuthoringJob[];
      }>(`/api/v1/authoring/threads/${threadId}/`);
      messages = data.messages ?? [];
      renderMessages();
      statusText.textContent = "";

      // Check if there is an unfinished job
      const activeJob = (data.jobs ?? []).find(
        (j) => j.status === "queued" || j.status === "running",
      );
      if (activeJob) {
        pollJob(activeJob.id, threadId);
      }
    } catch (err) {
      statusText.textContent = err instanceof Error ? err.message : "Failed to load thread";
    }
  }

  // Create a new thread
  async function handleCreateThread(): Promise<void> {
    const title = window.prompt(t("newFlowPrompt", options.locale), "Lesson helper");
    if (!title || !title.trim()) return;
    try {
      statusText.textContent = t("loading", options.locale);
      const created = await postJson<AuthoringThread>("/api/v1/authoring/threads/", {
        title: title.trim(),
      });
      threads.unshift(created);
      const opt = document.createElement("option");
      opt.value = String(created.id);
      opt.textContent = created.title;
      threadSelect.prepend(opt);
      await selectThread(created.id);
      statusText.textContent = "";
    } catch (err) {
      statusText.textContent = err instanceof Error ? err.message : "Failed to create conversation";
    }
  }

  // Poll job status safely
  function pollJob(jobId: number, threadId: number, attempt = 0): void {
    if (!isMounted || attempt > 60) {
      isGenerating = false;
      sendButton.disabled = false;
      statusText.textContent = "";
      return;
    }

    isGenerating = true;
    activeJobId = jobId;
    sendButton.disabled = true;
    statusText.textContent = t("aiGenerating", options.locale);

    pollTimeout = window.setTimeout(async () => {
      try {
        const job = await getJson<AuthoringJob>(`/api/v1/authoring/jobs/${jobId}/`);
        if (job.status === "succeeded") {
          isGenerating = false;
          sendButton.disabled = false;
          statusText.textContent = "";
          activeJobId = null;
          if (activeThreadId === threadId) {
            await selectThread(threadId);
          }
        } else if (job.status === "failed") {
          isGenerating = false;
          sendButton.disabled = false;
          statusText.textContent = job.error_code ? `AI error: ${job.error_code}` : "Generation failed.";
          activeJobId = null;
        } else {
          pollJob(jobId, threadId, attempt + 1);
        }
      } catch {
        isGenerating = false;
        sendButton.disabled = false;
        statusText.textContent = "AI job polling error";
        activeJobId = null;
      }
    }, 1000);
  }

  // Send message
  async function handleSendMessage(): Promise<void> {
    const text = promptInput.value.trim();
    if (!text || isGenerating || !activeThreadId) return;

    const selectedModelVal = modelSelect.value;
    const [backend_key, model_identifier] = selectedModelVal ? selectedModelVal.split(":") : ["", ""];
    if (!backend_key || !model_identifier) {
      statusText.textContent = "Please select an AI model";
      return;
    }

    const attachments: Array<Record<string, unknown>> = [];
    if (attachCheckbox.checked && options.getAttachment) {
      const att = options.getAttachment();
      if (att && att.source_type && att.source_id) {
        attachments.push({
          source_type: att.source_type,
          source_id: att.source_id,
        });
      }
    }

    try {
      isGenerating = true;
      sendButton.disabled = true;
      statusText.textContent = t("aiGenerating", options.locale);

      const res = await postJson<{
        message: AuthoringMessage;
        job: AuthoringJob;
      }>(`/api/v1/authoring/threads/${activeThreadId}/messages/`, {
        content: text,
        backend_key,
        model_identifier,
        attachments,
      });

      promptInput.value = "";
      // Immediately display the user message
      if (res.message) {
        messages.push(res.message);
        renderMessages();
      }

      if (res.job?.id) {
        pollJob(res.job.id, activeThreadId);
      } else {
        isGenerating = false;
        sendButton.disabled = false;
        statusText.textContent = "";
      }
    } catch (err) {
      isGenerating = false;
      sendButton.disabled = false;
      statusText.textContent = err instanceof Error ? err.message : "Failed to send message";
    }
  }

  // Initialization
  void (async () => {
    await loadModels();
    await loadThreads();
    updateAttachmentInfo();
  })();

  const attachmentInterval = window.setInterval(updateAttachmentInfo, 2000);

  return {
    unmount: () => {
      isMounted = false;
      if (pollTimeout) clearTimeout(pollTimeout);
      clearInterval(attachmentInterval);
    },
    refreshThreads: loadThreads,
  };
}
