/** About: versions, hardware, license, and the guided in-app update flow. */
import { ReactNode, useEffect, useState } from "react";
import { ExternalLink, RefreshCw } from "lucide-react";
import { api, bridge, SystemInfo, UpdateState } from "../lib/api";
import { Button, Card, PageHeader } from "../components/ui";

function mb(bytes?: number): string {
  return ((bytes ?? 0) / (1024 * 1024)).toFixed(1);
}

/** Small centered modal, matching the app's confirm dialogs. */
function Dialog({ title, children, actions }: { title: string; children?: ReactNode; actions: ReactNode }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 animate-fade-in"
      role="dialog" aria-modal="true" aria-label={title}>
      <div className="bg-surface border border-border rounded-2xl p-5 max-w-sm mx-4 shadow-xl animate-scale-in">
        <div className="text-sm font-medium mb-1">{title}</div>
        {children && <div className="text-xs text-muted mb-4">{children}</div>}
        <div className="flex justify-end gap-2">{actions}</div>
      </div>
    </div>
  );
}

export default function AboutPage() {
  const [info, setInfo] = useState<SystemInfo | null>(null);
  const [update, setUpdate] = useState<UpdateState | null>(null);
  const [active, setActive] = useState(false);   // user pressed "Update" this visit

  useEffect(() => {
    api.systemInfo().then(setInfo).catch(() => {});
    // A staged download may already be waiting — pick up current state, then
    // follow live progress events.
    bridge?.getUpdateState().then((s) => s && setUpdate(s)).catch(() => {});
    bridge?.onUpdateState(setUpdate);
  }, []);

  // The single "Update" button: check → download → stage install (all driven by
  // events from the main process). Dev/plain-browser has no real updater, so it
  // does a report-only check against the releases feed.
  const startUpdate = async () => {
    setActive(true);
    if (bridge?.startUpdate) {
      const s = await bridge.startUpdate().catch(() => null);
      if (s) setUpdate(s);
      return;
    }
    setUpdate({ state: "checking" });
    try {
      const r = await api.checkUpdates();
      setUpdate(r.update_available ? { state: "dev", version: r.latest } : { state: "up-to-date" });
    } catch {
      setUpdate({ state: "error", message: "Couldn't reach the update server." });
    }
  };

  const st = update?.state;
  const busy = st === "checking" || st === "downloading";
  const pct = Math.max(0, Math.min(100, update?.percent ?? 0));
  const dismiss = () => { setActive(false); setUpdate({ state: "idle" }); };

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
          <Button size="sm" variant="primary" onClick={startUpdate} disabled={busy}>
            <RefreshCw size={13} className={st === "checking" ? "animate-spin" : ""} />
            {st === "checking" ? "Checking…" : st === "downloading" ? "Downloading…" : "Update"}
          </Button>
          <Button size="sm" variant="ghost"
            onClick={() => bridge?.openExternal("https://github.com/Avromiep/whispertext")}>
            <ExternalLink size={13} /> GitHub
          </Button>
        </div>

        {st === "available" && !active && (
          <p className="mt-3 text-xs text-muted">Update v{update?.version} available — click Update to install.</p>
        )}

        {st === "downloading" && (
          <div className="mt-4 flex flex-col items-center gap-2 animate-scale-in">
            <div className="text-xs text-muted">Downloading update{update?.version ? ` v${update.version}` : ""}…</div>
            <div className="w-64 h-1.5 rounded-full bg-border overflow-hidden">
              <div className="h-full bg-accent rounded-full transition-[width] duration-300" style={{ width: `${pct}%` }} />
            </div>
            <div className="text-xs text-muted">
              {update?.total ? `${mb(update.transferred)} / ${mb(update.total)} MB (${Math.round(pct)}%)` : "Starting…"}
            </div>
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

      {/* Already up to date */}
      {active && st === "up-to-date" && (
        <Dialog title="You're up to date"
          actions={<Button size="sm" variant="primary" onClick={dismiss}>OK</Button>}>
          WhisperText{info ? ` v${info.version}` : ""} is the latest version.
        </Dialog>
      )}

      {/* Downloaded → confirm the restart that finishes the install */}
      {st === "ready" && (
        <Dialog title="Update ready"
          actions={<Button size="sm" variant="primary" onClick={() => bridge?.installUpdate()}>OK, restart now</Button>}>
          Update{update?.version ? ` v${update.version}` : ""} downloaded. WhisperText will restart to finish installing.
        </Dialog>
      )}

      {/* Something went wrong */}
      {active && st === "error" && (
        <Dialog title="Update failed"
          actions={<Button size="sm" variant="primary" onClick={dismiss}>OK</Button>}>
          {update?.message || "Something went wrong while updating."}
        </Dialog>
      )}

      {/* Dev build: no real updater */}
      {active && st === "dev" && (
        <Dialog title={update?.version ? "Update available" : "Development build"}
          actions={<Button size="sm" variant="primary" onClick={dismiss}>OK</Button>}>
          {update?.version
            ? `v${update.version} is available. The in-app updater runs in the installed app, not in dev mode.`
            : "Automatic updates are disabled in dev mode."}
        </Dialog>
      )}
    </div>
  );
}
