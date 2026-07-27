/** Raycast-style command palette (Ctrl+K): quick actions without the mouse. */
import { useEffect, useMemo, useRef, useState } from "react";
import { Search } from "lucide-react";
import { api } from "../lib/api";
import { useSettings } from "../hooks/useSettings";
import { PageId } from "../App";
import { cn } from "./ui";

interface Action { id: string; label: string; hint?: string; run: () => void }

export default function CommandPalette({ open, onClose, go, notify }: {
  open: boolean; onClose: () => void; go: (p: PageId) => void;
  notify: (msg: string, kind?: string) => void;
}) {
  const { settings, patch } = useSettings();
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const actions = useMemo<Action[]>(() => {
    const nav: Action[] = (
      ["home", "dictation", "vocabulary", "ai", "audio", "hotkeys", "history", "models", "advanced", "about"] as PageId[]
    ).map((p) => ({ id: `go-${p}`, label: `Go to ${p[0].toUpperCase()}${p.slice(1)}`, hint: "Navigate", run: () => go(p) }));
    return [
      { id: "start", label: "Start / Stop Dictation", hint: "Recording", run: () => void api.dictationToggle() },
      {
        id: "toggle-cleanup", label: settings?.ai.enabled ? "Disable AI Cleanup" : "Enable AI Cleanup", hint: "AI",
        run: () => void patch({ ai: { enabled: !settings?.ai.enabled } }).then(() => notify("AI cleanup toggled")),
      },
      {
        id: "toggle-history", label: settings?.history.enabled ? "Disable History" : "Enable History", hint: "Privacy",
        run: () => void patch({ history: { enabled: !settings?.history.enabled } }).then(() => notify("History toggled")),
      },
      ...(["openai", "anthropic", "gemini", "openrouter", "ollama"].map((p) => ({
        id: `provider-${p}`, label: `Switch AI provider to ${p}`, hint: "AI",
        run: () => void patch({ ai: { provider: p } }).then(() => notify(`Provider: ${p}`)),
      }))),
      ...nav,
      { id: "restart", label: "Restart WhisperText", hint: "App", run: () => (window as any).whispertext?.restart() },
    ];
  }, [settings, go, patch, notify]);

  const filtered = useMemo(
    () => actions.filter((a) => a.label.toLowerCase().includes(query.toLowerCase())),
    [actions, query],
  );

  useEffect(() => { if (open) { setQuery(""); setSelected(0); setTimeout(() => inputRef.current?.focus(), 30); } }, [open]);
  useEffect(() => setSelected(0), [query]);

  if (!open) return null;

  const runSelected = () => {
    const a = filtered[selected];
    if (a) { a.run(); onClose(); }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-start justify-center pt-[18vh] animate-fade-in"
         onClick={onClose}>
      <div className="w-[480px] rounded-2xl border border-border bg-surface shadow-2xl animate-scale-in overflow-hidden"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2.5 px-4 border-b border-border">
          <Search size={15} className="text-muted" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") { e.preventDefault(); setSelected((s) => Math.min(s + 1, filtered.length - 1)); }
              if (e.key === "ArrowUp") { e.preventDefault(); setSelected((s) => Math.max(s - 1, 0)); }
              if (e.key === "Enter") runSelected();
              if (e.key === "Escape") onClose();
            }}
            placeholder="Type a command…"
            className="flex-1 h-11 bg-transparent text-sm placeholder:text-muted/60 focus:outline-none"
            aria-label="Command search"
          />
        </div>
        <div className="max-h-[300px] overflow-y-auto py-1.5">
          {filtered.length === 0 && <div className="px-4 py-6 text-center text-sm text-muted">No matching commands</div>}
          {filtered.map((a, i) => (
            <button
              key={a.id}
              onClick={() => { a.run(); onClose(); }}
              onMouseEnter={() => setSelected(i)}
              className={cn("w-full flex items-center justify-between px-4 py-2 text-sm text-left",
                i === selected ? "bg-elevated" : "")}
            >
              <span>{a.label}</span>
              {a.hint && <span className="text-xs text-muted">{a.hint}</span>}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
