/** Dashboard: live status cards, stats, and recent activity. */
import { useCallback, useEffect, useState } from "react";
import { Cpu, Gauge, Keyboard, Mic, Package, Sparkles, Wifi } from "lucide-react";
import { api, AudioDevice, HistoryEntry, SystemInfo } from "../lib/api";
import { useSettings } from "../hooks/useSettings";
import { Badge, Card, Kbd, PageHeader } from "../components/ui";
import HistoryActions from "../components/HistoryActions";
import { PageId } from "../App";

export default function HomePage({ go }: { go: (p: PageId) => void }) {
  const { settings, backendUp } = useSettings();
  const [stats, setStats] = useState<{ cpu_percent: number; memory_mb: number; history: { total: number; today: number; avg_duration_s: number } } | null>(null);
  const [info, setInfo] = useState<SystemInfo | null>(null);
  const [devices, setDevices] = useState<AudioDevice[]>([]);
  const [recent, setRecent] = useState<HistoryEntry[]>([]);
  const [copiedId, setCopiedId] = useState<number | null>(null);

  const loadRecent = useCallback(() => {
    api.history().then((h) => setRecent(h.slice(0, 5))).catch(() => {});
  }, []);

  const copyEntry = useCallback((h: HistoryEntry) => {
    navigator.clipboard.writeText(h.final_text).then(() => {
      window.getSelection()?.removeAllRanges(); // clear the double-click highlight
      setCopiedId(h.id);
      setTimeout(() => setCopiedId((id) => (id === h.id ? null : id)), 1000);
    }).catch(() => { /* clipboard unavailable — silently ignore */ });
  }, []);

  useEffect(() => {
    if (!backendUp) return;
    api.systemInfo().then(setInfo).catch(() => {});
    api.audioDevices().then(setDevices).catch(() => {});
    loadRecent();
    const t = setInterval(() => api.systemStats().then(setStats).catch(() => {}), 3000);
    return () => clearInterval(t);
  }, [backendUp, loadRecent]);

  const mic = devices.find((d) => d.id === settings?.audio.input_device) ?? devices.find((d) => d.default);

  const cards = [
    { icon: Sparkles, label: "AI Provider", value: settings?.ai.provider ?? "—", page: "ai" as PageId },
    { icon: Package, label: "Speech Model", value: settings?.whisper.model ?? "—", page: "models" as PageId },
    { icon: Mic, label: "Microphone", value: mic?.name?.slice(0, 22) ?? "None detected", page: "audio" as PageId },
    { icon: Keyboard, label: "Shortcut", value: settings?.hotkeys.push_to_talk ?? "—", page: "hotkeys" as PageId },
  ];

  return (
    <div className="animate-fade-in">
      <PageHeader
        title="Home"
        subtitle="Press your shortcut in any app to start dictating."
        actions={<Badge color={backendUp ? "green" : "red"} icon={<Wifi size={11} />}>{backendUp ? "Connected" : "Offline"}</Badge>}
      />

      <div className="grid grid-cols-2 gap-3 mb-6">
        {cards.map(({ icon: Icon, label, value, page }) => (
          <Card key={label} onClick={() => go(page)} className="!p-4">
            <div className="flex items-center gap-2 text-muted text-xs mb-1.5"><Icon size={13} /> {label}</div>
            <div className="text-sm font-medium truncate capitalize">{value}</div>
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-3 gap-3 mb-6">
        <Card className="!p-4">
          <div className="flex items-center gap-2 text-muted text-xs mb-1.5"><Gauge size={13} /> Today</div>
          <div className="text-2xl font-semibold">{stats?.history.today ?? 0}</div>
          <div className="text-xs text-muted">dictations · {stats?.history.total ?? 0} total</div>
        </Card>
        <Card className="!p-4">
          <div className="flex items-center gap-2 text-muted text-xs mb-1.5"><Gauge size={13} /> Avg speed</div>
          <div className="text-2xl font-semibold">{stats?.history.avg_duration_s ?? 0}s</div>
          <div className="text-xs text-muted">per dictation</div>
        </Card>
        <Card className="!p-4">
          <div className="flex items-center gap-2 text-muted text-xs mb-1.5"><Cpu size={13} /> System</div>
          <div className="text-2xl font-semibold">{stats?.cpu_percent ?? 0}%</div>
          <div className="text-xs text-muted">
            CPU · {info?.hardware.cuda ? `GPU: ${info.hardware.gpu}` : "CPU inference"}
          </div>
        </Card>
      </div>

      <Card>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold">Recent activity</h3>
          <button className="text-xs text-accent hover:underline" onClick={() => go("history")}>View all</button>
        </div>
        {recent.length === 0 ? (
          <div className="text-sm text-muted py-6 text-center">
            No dictations yet. Hold <Kbd>{settings?.hotkeys.push_to_talk ?? "Win+Shift"}</Kbd> and speak!
          </div>
        ) : (
          <div className="space-y-1">
            {recent.map((h) => (
              <div key={h.id} className="group flex items-center justify-between gap-3 py-1.5 border-b border-border/50 last:border-0">
                <span
                  className="text-sm truncate flex-1 cursor-pointer select-none"
                  title="Double-click to copy"
                  onDoubleClick={() => copyEntry(h)}>
                  {h.final_text}
                </span>
                {copiedId === h.id ? (
                  <span className="text-xs text-emerald-500 shrink-0 font-medium animate-fade-in">Copied</span>
                ) : (
                  <span className="text-xs text-muted shrink-0 tabular-nums">{new Date(h.ts * 1000).toLocaleTimeString()}</span>
                )}
                <div className="opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
                  <HistoryActions entry={h} onChange={loadRecent} size={13} showCopy={false} />
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
