/** About: versions, hardware, license, update check. */
import { useEffect, useState } from "react";
import { AlertTriangle, Check, ExternalLink, RefreshCw } from "lucide-react";
import { api, bridge, SystemInfo, UpdateState } from "../lib/api";
import { Badge, Button, Card, PageHeader } from "../components/ui";

function mb(bytes?: number): string {
  return ((bytes ?? 0) / (1024 * 1024)).toFixed(1);
}

function UpdateStatus({ update }: { update: UpdateState }) {
  switch (update.state) {
    case "checking":
      return <Badge color="gray" icon={<RefreshCw size={11} className="animate-spin" />}>Checking for updates…</Badge>;
    case "downloading": {
      const pct = Math.max(0, Math.min(100, update.percent ?? 0));
      return (
        <>
          <Badge color="blue">Downloading{update.version ? ` v${update.version}` : ""}…</Badge>
          <div className="w-64 h-1.5 rounded-full bg-border overflow-hidden">
            <div className="h-full bg-accent rounded-full transition-[width] duration-300"
              style={{ width: `${pct}%` }} />
          </div>
          <div className="text-xs text-muted">
            {update.total
              ? `${mb(update.transferred)} / ${mb(update.total)} MB (${Math.round(pct)}%)`
              : "Starting download…"}
          </div>
        </>
      );
    }
    case "ready":
      return (
        <>
          <Badge color="green" icon={<Check size={11} />}>
            Update downloaded{update.version ? ` — v${update.version}` : ""}
          </Badge>
          <p className="text-xs text-muted max-w-xs">
            WhisperText needs to relaunch to finish installing.
          </p>
          <Button size="sm" variant="primary" onClick={() => bridge?.installUpdate()}>
            <RefreshCw size={13} /> Relaunch &amp; update
          </Button>
        </>
      );
    case "up-to-date":
      return <Badge color="green" icon={<Check size={11} />}>You're up to date</Badge>;
    case "error":
      return (
        <>
          <Badge color="red" icon={<AlertTriangle size={11} />}>Update failed</Badge>
          {update.message && <p className="text-xs text-muted max-w-xs break-words">{update.message}</p>}
        </>
      );
    case "dev":
      return update.version ? (
        <>
          <Badge color="yellow">v{update.version} available</Badge>
          <p className="text-xs text-muted max-w-xs">
            Automatic updates only run in the installed app, not in dev mode.
          </p>
        </>
      ) : (
        <Badge color="gray">Dev build — automatic updates disabled</Badge>
      );
    default:
      return null;
  }
}

export default function AboutPage() {
  const [info, setInfo] = useState<SystemInfo | null>(null);
  const [update, setUpdate] = useState<UpdateState | null>(null);

  useEffect(() => {
    api.systemInfo().then(setInfo).catch(() => {});
    // A check (and download) may already be running in the background —
    // pick up the current state, then follow live progress events.
    bridge?.getUpdateState().then(setUpdate).catch(() => {});
    bridge?.onUpdateState(setUpdate);
  }, []);

  const check = async () => {
    if (bridge) {
      const s = await bridge.checkUpdates().catch(() => null);
      if (s) setUpdate(s);
      if (s && s.state !== "dev") return; // events stream the rest
    }
    // Dev build or plain browser: report-only check against the releases feed.
    setUpdate({ state: "checking" });
    try {
      const r = await api.checkUpdates();
      setUpdate(r.update_available ? { state: "dev", version: r.latest } : { state: "up-to-date" });
    } catch {
      setUpdate({ state: "error", message: "Couldn't reach the update server." });
    }
  };

  const busy = update?.state === "checking" || update?.state === "downloading";

  const rows: [string, string][] = info ? [
    ["Backend", `Python · FastAPI · Faster-Whisper (CTranslate2)`],
    ["Operating system", info.hardware.os],
    ["CPU", `${info.hardware.cpu} (${info.hardware.cpu_cores} cores)`],
    ["Memory", `${info.hardware.ram_gb} GB`],
    ["GPU", info.hardware.gpu ? `${info.hardware.gpu} (${info.hardware.vram_gb} GB${info.hardware.cuda ? ", CUDA" : ", no CUDA"})` : "None"],
    ["License", "MIT"],
  ] : [];

  return (
    <div className="animate-fade-in">
      <PageHeader title="About" />
      <Card className="mb-4 text-center py-8">
        <img src="icon.png" alt="" className="mx-auto w-16 h-16 rounded-2xl shadow-xl shadow-accent/30 mb-3" />
        <div className="font-semibold text-lg">WhisperText</div>
        {info && <div className="text-xs text-muted mt-0.5">Version {info.version}</div>}
        <div className="text-xs text-muted mt-2">Your AI voice assistant for every application.</div>
        <div className="mt-4 flex items-center justify-center gap-2">
          <Button size="sm" onClick={check} disabled={busy}>
            <RefreshCw size={13} className={update?.state === "checking" ? "animate-spin" : ""} /> Check for updates
          </Button>
          <Button size="sm" variant="ghost"
            onClick={() => bridge?.openExternal("https://github.com/Avromiep/whispertext")}>
            <ExternalLink size={13} /> GitHub
          </Button>
        </div>
        {update && update.state !== "idle" && (
          <div className="mt-4 flex flex-col items-center gap-2 animate-scale-in">
            <UpdateStatus update={update} />
          </div>
        )}
      </Card>
      <Card>
        {rows.map(([k, v]) => (
          <div key={k} className="flex justify-between py-2 border-b border-border/50 last:border-0 text-sm">
            <span className="text-muted">{k}</span>
            <span className="text-right max-w-[60%] truncate">{v}</span>
          </div>
        ))}
      </Card>
    </div>
  );
}
