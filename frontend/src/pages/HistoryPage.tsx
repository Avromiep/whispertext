/** Dictation history: search, favorites, delete, export, privacy mode. */
import { useCallback, useEffect, useState } from "react";
import { Download, Search, Star, Trash2 } from "lucide-react";
import { api, API_BASE, HistoryEntry, bridge } from "../lib/api";
import { useSettings } from "../hooks/useSettings";
import { Button, Card, PageHeader, Toggle, cn } from "../components/ui";

export default function HistoryPage() {
  const { settings, patch } = useSettings();
  const [entries, setEntries] = useState<HistoryEntry[]>([]);
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = useState<number | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);

  const load = useCallback(() => {
    api.history(search).then(setEntries).catch(() => {});
  }, [search]);

  useEffect(() => {
    const t = setTimeout(load, 200); // debounce search
    return () => clearTimeout(t);
  }, [load]);

  if (!settings) return null;

  const clearAll = async () => {
    if (!confirmClear) { setConfirmClear(true); setTimeout(() => setConfirmClear(false), 3000); return; }
    await api.clearHistory();
    setConfirmClear(false);
    load();
  };

  return (
    <div className="animate-fade-in">
      <PageHeader title="History" subtitle="Your past dictations, stored locally in SQLite."
        actions={
          <div className="flex gap-2">
            <Button size="sm" onClick={() => bridge ? bridge.openExternal(`${API_BASE}/history/export`) : window.open(`${API_BASE}/history/export`)}>
              <Download size={13} /> Export CSV
            </Button>
            <Button size="sm" variant="danger" onClick={clearAll}>
              <Trash2 size={13} /> {confirmClear ? "Click again to confirm" : "Clear all"}
            </Button>
          </div>
        } />

      <Card className="mb-4 !p-3">
        <Toggle label="Save dictation history" description="Privacy mode: turn off to never store transcripts"
          checked={settings.history.enabled} onChange={(v) => patch({ history: { enabled: v } })} />
      </Card>

      <div className="relative mb-4">
        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search transcripts…"
          className="w-full h-9 rounded-xl bg-elevated border border-border pl-9 pr-3 text-sm placeholder:text-muted/60 focus:border-accent transition-colors"
        />
      </div>

      {entries.length === 0 ? (
        <Card className="text-center text-sm text-muted py-10">No dictations found.</Card>
      ) : (
        <div className="space-y-2">
          {entries.map((h) => (
            <Card key={h.id} className="!p-4 cursor-pointer" onClick={() => setExpanded(expanded === h.id ? null : h.id)}>
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="text-sm truncate">{h.final_text}</div>
                  <div className="text-[11px] text-muted mt-1 flex gap-3">
                    <span>{new Date(h.ts * 1000).toLocaleString()}</span>
                    {h.app && <span className="truncate max-w-[180px]">{h.app}</span>}
                    <span>{h.duration_s.toFixed(1)}s</span>
                    <span>{h.provider}</span>
                    <span>{h.language}</span>
                  </div>
                </div>
                <div className="flex gap-1 shrink-0">
                  <button
                    aria-label="Favorite"
                    onClick={(e) => { e.stopPropagation(); api.favorite(h.id, !h.favorite).then(load); }}
                    className={cn("p-1.5 rounded-lg hover:bg-elevated", h.favorite ? "text-amber-400" : "text-muted")}>
                    <Star size={14} fill={h.favorite ? "currentColor" : "none"} />
                  </button>
                  <button
                    aria-label="Delete entry"
                    onClick={(e) => { e.stopPropagation(); api.deleteHistory(h.id).then(load); }}
                    className="p-1.5 rounded-lg hover:bg-elevated text-muted hover:text-red-400">
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
              {expanded === h.id && (
                <div className="mt-3 pt-3 border-t border-border/50 animate-fade-in">
                  <div className="text-[11px] text-muted mb-1">Original transcript</div>
                  <div className="text-xs text-muted italic">{h.raw_transcript}</div>
                  <div className="text-[11px] text-muted mb-1 mt-2">Final output</div>
                  <div className="text-xs">{h.final_text}</div>
                </div>
              )}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
