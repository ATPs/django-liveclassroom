import * as React from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
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
  apiRoot?: string;
};

function AiChat({ options, apiRoot }: { options: AiChatOptions; apiRoot: string }) {
  const locale = options.locale;
  const apiUrl = (path: string): string => new URL(path.replace(/^\/+/, ""), new URL(apiRoot, window.location.href)).toString();

  const [models, setModels] = useState<AIModel[]>([]);
  const [threads, setThreads] = useState<AuthoringThread[]>([]);
  const [messages, setMessages] = useState<AuthoringMessage[]>([]);
  const [activeThreadId, setActiveThreadId] = useState<number | null>(null);
  const [generating, setGenerating] = useState(false);
  const [status, setStatus] = useState("");
  const [prompt, setPrompt] = useState("");
  const [attachEnabled, setAttachEnabled] = useState(true);
  const [attachment, setAttachment] = useState<AuthoringAttachment | null>(null);
  const [modelValue, setModelValue] = useState("");

  const mountedRef = useRef(true);
  const pollTimerRef = useRef<number | null>(null);
  const activeJobRef = useRef<number | null>(null);
  const activeThreadRef = useRef<number | null>(null);
  const messagesRef = useRef<HTMLDivElement>(null);

  const loadModels = useCallback(async () => {
    try {
      const data = await getJson<{ models?: AIModel[] }>(apiUrl("authoring/models/"));
      setModels(data.models ?? []);
    } catch {
      setModels([]);
    }
  }, []);

  const selectThread = useCallback(async (threadId: number) => {
    setActiveThreadId(threadId);
    activeThreadRef.current = threadId;
    setStatus(t("loading", locale));
    try {
      const data = await getJson<{ messages: AuthoringMessage[]; jobs: AuthoringJob[] }>(apiUrl(`authoring/threads/${threadId}/`));
      setMessages(data.messages ?? []);
      setStatus("");
      const activeJob = (data.jobs ?? []).find((j) => j.status === "queued" || j.status === "running");
      if (activeJob) {
        pollJob(activeJob.id, threadId);
      }
    } catch (err) {
      setStatus(err instanceof Error ? err.message : t("aiFailedLoadThread", locale));
    }
  }, []);

  const loadThreads = useCallback(async () => {
    try {
      const data = await getJson<{ threads: AuthoringThread[] }>(apiUrl("authoring/threads/"));
      let loaded = data.threads ?? [];
      if (loaded.length === 0) {
        const created = await postJson<AuthoringThread>(apiUrl("authoring/threads/"), { title: t("aiDefaultThread", locale) });
        loaded = [created];
      }
      setThreads(loaded);
      if (!activeThreadId && loaded.length > 0) {
        await selectThread(loaded[0].id);
      }
    } catch (err) {
      setStatus(err instanceof Error ? err.message : t("aiFailedLoadThreads", locale));
    }
  }, [activeThreadId, selectThread]);

  const pollJob = useCallback((jobId: number, threadId: number, attempt = 0) => {
    if (!mountedRef.current || attempt > 60) {
      setGenerating(false);
      setStatus("");
      return;
    }
    setGenerating(true);
    activeJobRef.current = jobId;
    setStatus(t("aiGenerating", locale));
    pollTimerRef.current = window.setTimeout(async () => {
      try {
        const job = await getJson<AuthoringJob>(apiUrl(`authoring/jobs/${jobId}/`));
        if (job.status === "succeeded") {
          setGenerating(false);
          setStatus("");
          activeJobRef.current = null;
          if (activeThreadRef.current === threadId) {
            const thread = await getJson<{ messages: AuthoringMessage[] }>(apiUrl(`authoring/threads/${threadId}/`));
            if (mountedRef.current && activeThreadRef.current === threadId) {
              setMessages(thread.messages ?? []);
            }
          }
        } else if (job.status === "failed") {
          setGenerating(false);
          setStatus(job.error_code ? `AI: ${job.error_code}` : t("aiGenerationFailed", locale));
          activeJobRef.current = null;
        } else {
          pollJob(jobId, threadId, attempt + 1);
        }
      } catch {
        setGenerating(false);
        setStatus(t("aiJobPollingError", locale));
        activeJobRef.current = null;
      }
    }, 1000);
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    void loadModels();
    void loadThreads();
    return () => {
      mountedRef.current = false;
      if (pollTimerRef.current) window.clearTimeout(pollTimerRef.current);
    };
  }, [loadModels, loadThreads]);

  useEffect(() => {
    const update = () => {
      if (!options.getAttachment) return;
      const att = options.getAttachment();
      setAttachment(att);
    };
    update();
    const interval = window.setInterval(update, 2000);
    return () => window.clearInterval(interval);
  }, [options.getAttachment]);

  const send = async () => {
    const text = prompt.trim();
    if (!text || generating || !activeThreadId) return;
    const [backend_key, model_identifier] = modelValue ? modelValue.split(":") : ["", ""];
    if (!backend_key || !model_identifier) {
      setStatus(t("aiSelectModel", locale));
      return;
    }
    const attachments: Array<Record<string, unknown>> = [];
    if (attachEnabled && options.getAttachment) {
      const att = options.getAttachment();
      if (att && att.source_type && att.source_id) {
        attachments.push({ source_type: att.source_type, source_id: att.source_id });
      }
    }
    try {
      setGenerating(true);
      setStatus(t("aiGenerating", locale));
      const res = await postJson<{ message: AuthoringMessage; job: AuthoringJob }>(
        apiUrl(`authoring/threads/${activeThreadId}/messages/`),
        { content: text, backend_key, model_identifier, attachments },
      );
      setPrompt("");
      if (res.message) setMessages((prev) => [...prev, res.message]);
      if (res.job?.id) {
        pollJob(res.job.id, activeThreadId);
      } else {
        setGenerating(false);
        setStatus("");
      }
    } catch (err) {
      setGenerating(false);
      setStatus(err instanceof Error ? err.message : t("aiFailedSend", locale));
    }
  };

  const createThread = async () => {
    const title = window.prompt(t("newFlowPrompt", locale), t("aiDefaultNewThread", locale));
    if (!title || !title.trim()) return;
    try {
      setStatus(t("loading", locale));
      const created = await postJson<AuthoringThread>(apiUrl("authoring/threads/"), { title: title.trim() });
      setThreads((prev) => [created, ...prev]);
      await selectThread(created.id);
      setStatus("");
    } catch (err) {
      setStatus(err instanceof Error ? err.message : t("aiFailedCreateThread", locale));
    }
  };

  return (
    <div className="lc-ai-chat">
      <div className="lc-ai-header">
        <div className="lc-ai-title-row">
          <h3>{t("aiAssistant", locale)}</h3>
          <button type="button" className="lc-btn-sm" onClick={() => void createThread()}>
            + {t("newThread", locale)}
          </button>
        </div>
        <div className="lc-ai-controls">
          <div className="lc-ai-control-group">
            <label>
              {t("aiThread", locale)}:{" "}
              <select
                className="lc-ai-select"
                value={activeThreadId ? String(activeThreadId) : ""}
                onChange={(e) => void selectThread(Number(e.target.value))}
              >
                {threads.map((th) => (
                  <option key={th.id} value={String(th.id)}>
                    {th.title}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <div className="lc-ai-control-group">
            <label>
              {t("aiModel", locale)}:{" "}
              <select className="lc-ai-select" value={modelValue} onChange={(e) => setModelValue(e.target.value)}>
                {models.length === 0 ? (
                  <option value="">{t("aiNoModels", locale)}</option>
                ) : (
                  models.map((m) => (
                    <option key={`${m.backend_key}:${m.identifier}`} value={`${m.backend_key}:${m.identifier}`}>
                      {m.label || `${m.backend_key} (${m.identifier})`}
                    </option>
                  ))
                )}
              </select>
            </label>
          </div>
        </div>
      </div>
      <div className="lc-ai-messages" role="log" aria-live="polite" ref={messagesRef}>
        {messages.length === 0 ? (
          <p className="lc-ai-empty">{t("noMessages", locale)}</p>
        ) : (
          messages.map((msg) => (
            <div key={msg.id} className={`lc-ai-message lc-ai-message-${msg.role}`}>
              <div className="lc-ai-msg-header">
                <strong>{msg.role === "assistant" ? t("aiAssistant", locale) : t("teacher", locale)}</strong>
                {msg.model_identifier ? <small className="lc-ai-msg-model"> ({msg.model_identifier})</small> : null}
              </div>
              <div className="lc-ai-msg-body">{msg.content}</div>
              {msg.role === "assistant" && msg.content.trim() ? (
                <div className="lc-ai-msg-actions">
                  <button
                    type="button"
                    className="lc-btn-sm lc-btn-outline"
                    onClick={() => {
                      if (navigator.clipboard?.writeText) void navigator.clipboard.writeText(msg.content);
                    }}
                  >
                    {t("aiCopy", locale)}
                  </button>
                  {options.onInsertDraft ? (
                    <button type="button" className="lc-btn-sm lc-btn-primary" onClick={() => options.onInsertDraft?.(msg.content)}>
                      {t("aiInsertToBuilder", locale)}
                    </button>
                  ) : null}
                </div>
              ) : null}
            </div>
          ))
        )}
      </div>
      <div className="lc-ai-composer">
        {options.getAttachment ? (
          <div className="lc-ai-attachment-bar">
            <input type="checkbox" checked={attachEnabled} onChange={(e) => setAttachEnabled(e.target.checked)} />
            <label> {t("attachCurrentStep", locale)}</label>
            <span className={attachment ? "lc-ai-attachment-badge lc-ai-attachment-active" : "lc-ai-attachment-badge"}>
              {attachment
                ? attachment.title
                  ? `${attachment.source_type}: ${attachment.title}`
                  : `${attachment.source_type} #${attachment.source_id}`
                : t("noAttachments", locale)}
            </span>
          </div>
        ) : null}
        <textarea
          className="lc-ai-input"
          rows={3}
          placeholder={t("aiPromptPlaceholder", locale)}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
        />
        <div className="lc-ai-footer">
          <small className="lc-ai-note">{t("aiNote", locale)}</small>
          <div className="lc-ai-action-group">
            <span className="lc-ai-status">{status}</span>
            <button type="button" className="lc-ai-send-btn" disabled={generating} onClick={() => void send()}>
              {t("aiSend", locale)}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export function mountAiChat(
  container: HTMLElement,
  options: AiChatOptions = {},
): { unmount: () => void; refreshThreads: () => Promise<void> } {
  const apiRoot = new URL(options.apiRoot ?? "/api/v1/", window.location.href).toString();
  const root = createRoot(container);
  root.render(<AiChat options={options} apiRoot={apiRoot} />);
  return {
    unmount: () => root.unmount(),
    refreshThreads: async () => {
      // Threads refresh automatically within the island; kept for API parity.
    },
  };
}
