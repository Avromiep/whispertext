/** Auto-reconnecting WebSocket subscription to the backend event bus. */
import { useEffect, useRef } from "react";
import { WS_URL } from "./api";

export interface WTEvent {
  type: "status" | "audio_level" | "error" | "notification" | "settings_changed" | "model_download" | "test_result" | "heartbeat";
  ts: number;
  state?: string;
  level?: number;
  message?: string;
  kind?: string;
  hands_free?: boolean;
  chars?: number;
  seconds?: number;
  model?: string;
  text?: string;
  language?: string;
  [key: string]: unknown;
}

/** The backend sends a heartbeat every 5s; miss three and the socket is dead. */
const STALE_MS = 16_000;
const RETRY_MS = 500;

export function useBackendEvents(onEvent: (e: WTEvent) => void): void {
  const handler = useRef(onEvent);
  handler.current = onEvent;

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let retry: ReturnType<typeof setTimeout>;
    let watchdog: ReturnType<typeof setInterval>;
    let lastSeen = Date.now();

    const connect = () => {
      if (closed) return;
      lastSeen = Date.now();
      ws = new WebSocket(WS_URL);
      ws.onopen = () => { lastSeen = Date.now(); };
      ws.onmessage = (m) => {
        lastSeen = Date.now();
        try { handler.current(JSON.parse(m.data) as WTEvent); } catch { /* ignore malformed */ }
      };
      ws.onclose = () => { if (!closed) retry = setTimeout(connect, RETRY_MS); };
      ws.onerror = () => ws?.close();
    };

    // Sleep/resume can leave the socket readyState OPEN but permanently silent,
    // with no onclose to trigger a reconnect — the overlay would then stop
    // reacting to the hotkey entirely. Tear it down once the heartbeat stops.
    const check = () => {
      if (closed || Date.now() - lastSeen < STALE_MS) return;
      lastSeen = Date.now();
      if (ws && ws.readyState === WebSocket.OPEN) ws.close(); // onclose reconnects
      else if (!ws || ws.readyState === WebSocket.CLOSED) connect();
    };

    connect();
    watchdog = setInterval(check, 4000);
    window.addEventListener("online", check);

    return () => {
      closed = true;
      clearTimeout(retry);
      clearInterval(watchdog);
      window.removeEventListener("online", check);
      ws?.close();
    };
  }, []);
}
