/** About: versions, hardware, license, update check. */
import { useEffect, useState } from "react";
import { Check, Download, ExternalLink, RefreshCw } from "lucide-react";
import { api, bridge, SystemInfo } from "../lib/api";
import { Badge, Button, Card, PageHeader } from "../components/ui";

export default function AboutPage() {
  const [info, setInfo] = useState<SystemInfo | null>(null);
  const [update, setUpdate] = useState<{ current: string; latest: string; update_available: boolean; url: string } | null>(null);
  const [checking, setChecking] = useState(false);
  const [updateReady, setUpdateReady] = useState(false);

  useEffect(() => {
    api.systemInfo().then(setInfo).catch(() => {});
    // The background download may have finished before this page was opened,
    // so ask for the current state as well as subscribing to the event.
    bridge?.isUpdateReady?.().then((r) => r && setUpdateReady(true)).catch(() => {});
    bridge?.onUpdateReady(() => setUpdateReady(true));
  }, []);

  const check = async () => {
    setChecking(true);
    try { setUpdate(await api.checkUpdates()); } catch { /* offline */ }
    if (bridge) await bridge.checkUpdates().catch(() => {});
    setChecking(false);
  };

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
          <Button size="sm" onClick={check} disabled={checking}>
            <RefreshCw size={13} className={checking ? "animate-spin" : ""} /> Check for updates
          </Button>
          <Button size="sm" variant="ghost"
            onClick={() => bridge?.openExternal("https://github.com/Avromiep/whispertext")}>
            <ExternalLink size={13} /> GitHub
          </Button>
        </div>
        {(update || updateReady) && (
          <div className="mt-4 flex flex-col items-center gap-2 animate-scale-in">
            {updateReady ? (
              <>
                <Badge color="green" icon={<Check size={11} />}>Update downloaded</Badge>
                <Button size="sm" variant="primary" onClick={() => bridge?.installUpdate()}>
                  <RefreshCw size={13} /> Restart & install{update?.latest ? ` v${update.latest}` : ""}
                </Button>
              </>
            ) : update?.update_available ? (
              <>
                <Badge color="blue">New version available: v{update.latest}</Badge>
                <p className="text-xs text-muted max-w-xs">
                  Downloading in the background — a "Restart &amp; install" button appears here when it's ready.
                </p>
                {update.url && (
                  <Button size="sm" variant="ghost" onClick={() => bridge?.openExternal(update.url)}>
                    <Download size={13} /> Download manually instead
                  </Button>
                )}
              </>
            ) : (
              <Badge color="green" icon={<Check size={11} />}>You're up to date</Badge>
            )}
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
