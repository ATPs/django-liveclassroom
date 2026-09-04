import { useCallback, useEffect, useRef, useState } from "react";
import { getJson, websocketUrl, type SessionState } from "../protocol.js";

type Options = {
  stateUrl: string | null;
  websocketPath: string | null;
  channel: "participants" | "display";
  enabled: boolean;
};

export type SessionSync = {
  state: SessionState | null;
  error: string;
  reconnecting: boolean;
  refresh: () => Promise<void>;
};

/**
 * Poll + WebSocket sync for one audience channel. The WebSocket only carries
 * version-gated notifications; authoritative state always comes from HTTP.
 */
export function useSessionState({ stateUrl, websocketPath, channel, enabled }: Options): SessionSync {
  const [state, setState] = useState<SessionState | null>(null);
  const [error, setError] = useState("");
  const [reconnecting, setReconnecting] = useState(false);
  const versionRef = useRef(-1);

  const refresh = useCallback(async () => {
    if (!stateUrl) return;
    try {
      const sep = stateUrl.includes("?") ? "&" : "?";
      const next = await getJson<SessionState>(`${stateUrl}${sep}channel=${channel}`);
      if ((next.state_version ?? -1) < versionRef.current) return;
      setState(next);
      versionRef.current = Math.max(versionRef.current, next.state_version ?? -1);
      setError("");
      setReconnecting(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "unavailable");
    }
  }, [stateUrl, channel]);

  useEffect(() => {
    if (!enabled || !stateUrl) return;
    let stopped = false;
    let retry = 1000;
    let retryTimer: number | undefined;
    let socket: WebSocket | undefined;
    const open = (): void => {
      if (stopped || !websocketPath) return;
      const connected = new WebSocket(websocketUrl(websocketPath));
      socket = connected;
      connected.onopen = () => {
        retry = 1000;
        setReconnecting(false);
      };
      connected.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data) as { version?: unknown };
          const version = typeof message.version === "number" ? message.version : null;
          if (version !== null) {
            if (version <= versionRef.current) return;
          }
        } catch {
          // A malformed notification cannot change authoritative state.
        }
        void refresh();
      };
      connected.onerror = () => connected.close();
      connected.onclose = () => {
        if (stopped) return;
        setReconnecting(true);
        retryTimer = window.setTimeout(open, retry);
        retry = Math.min(retry * 2, 30000);
      };
    };

    open();
    void refresh();
    const pollTimer = window.setInterval(() => void refresh(), 3000);
    return () => {
      stopped = true;
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
      socket?.close();
      window.clearInterval(pollTimer);
    };
  }, [enabled, stateUrl, websocketPath, refresh]);

  return { state, error, reconnecting, refresh };
}
