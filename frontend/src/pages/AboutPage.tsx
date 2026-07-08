/** About: versions, hardware, license, update check. */
import { useEffect, useState } from "react";
import { ExternalLink, Mic, RefreshCw } from "lucide-react";
import { api, bridge, SystemInfo } from "../lib/api";
import { Badge, Button, Card, PageHeader } from "../components/ui";

export default function AboutPage() {
  const [info, setInfo] = useState<SystemInfo | null>(null);
  const [update, setUpdate] = useState<{ current: string; latest: string; update_available: boolean; url: string } | null>(null);
  const [checking, setChecking] = useState(false);

  useEffect(() => { api.systemInfo().then(setInfo).catch(() => {}); }, []);

  const check = async () => {
    setChecking(true);
    try { setUpdate(await api.checkUpdates()); } catch { /* offline */ }
    if (bridge) await bridge.checkUpdates().catch(() => {});
    setChecking(false);
  };

  const rows: [string, string][] = info ? [
    ["Application", `WhisperText ${info.version}`],
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
        <div className="mx-auto w-12 h-12 rounded-xl bg-accent flex items-center justify-center shadow-xl shadow-accent/30 mb-3">
          <Mic size={20} className="text-white" />
        </div>
        <div className="font-semibold text-lg">WhisperText</div>
        <div className="text-xs text-muted mt-1">Your AI voice assistant for every application.</div>
        <div className="mt-4 flex items-center justify-center gap-2">
          <Button size="sm" onClick={check} disabled={checking}>
            <RefreshCw size={13} className={checking ? "animate-spin" : ""} /> Check for updates
          </Button>
          <Button size="sm" variant="ghost"
            onClick={() => bridge?.openExternal("https://github.com/Avromiep/whispertext")}>
            <ExternalLink size={13} /> GitHub
          </Button>
        </div>
        {update && (
          <div className="mt-3">
            {update.update_available
              ? <Badge color="blue">Update available: v{update.latest}</Badge>
              : <Badge color="green">You're up to date (v{update.current})</Badge>}
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
