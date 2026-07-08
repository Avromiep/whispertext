/** Auto-reconnecting WebSocket subscription to the backend event bus. */
import { useEffect, useRef } from "react";
import { WS_URL } from "./api";

export interface WTEvent {
  type: "status" | "audio_level" | "error" | "notification" | "settings_changed" | "model_download";
  ts: number;
  state?: string;
  level?: number;
  message?: string;
  kind?: string;
  hands_free?: boolean;
  chars?: number;
  seconds?: number;
  model?: string;
  [key: string]: unknown;
}

export function useBackendEvents(onEvent: (e: WTEvent) => void): void {
  const handler = useRef(onEvent);
  handler.current = onEvent;

  useEffect(() => {
    let ws: WebSocket | null = null;
    let closed = false;
    let retry: ReturnType<typeof setTimeout>;

    const connect = () => {
      if (closed) return;
      ws = new WebSocket(WS_URL);
      ws.onmessage = (m) => {
        try { handler.current(JSON.parse(m.data) as WTEvent); } catch { /* ignore malformed */ }
      };
      ws.onclose = () => { if (!closed) retry = setTimeout(connect, 1500); };
      ws.onerror = () => ws?.close();
    };
    connect();
    return () => { closed = true; clearTimeout(retry); ws?.close(); };
  }, []);
}
