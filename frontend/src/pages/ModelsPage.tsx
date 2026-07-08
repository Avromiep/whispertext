/** Whisper model management: transcription engine choice, local model status, downloads. */
import { useCallback, useEffect, useState } from "react";
import { Check, Cloud, Download, HardDrive, Loader2, Trash2, X, Zap } from "lucide-react";
import { api, SystemInfo, WhisperModelInfo } from "../lib/api";
import { useBackendEvents } from "../lib/ws";
import { useSettings } from "../hooks/useSettings";
import { Badge, Button, Card, PageHeader, SecretInput, Section, cn } from "../components/ui";

interface KeyTestResult { connected: boolean; message: string; latency_ms?: number }

/** One API-key row: secret input, save, test-connection — reused for the
 * primary and backup Groq keys since they behave identically. */
function GroqKeyRow({ label, placeholder, providerId, validate }: {
  label: string; placeholder: string; providerId: string;
  validate: () => Promise<KeyTestResult>;
}) {
  const [key, setKey] = useState("");
  const [configured, setConfigured] = useState(false);
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<KeyTestResult | null>(null);

  useEffect(() => {
    api.hasApiKey(providerId).then((r) => setConfigured(r.configured)).catch(() => {});
  }, [providerId]);

  const save = async () => {
    await api.setApiKey(providerId, key);
    setKey("");
    setConfigured(true);
    setResult(null);
  };

  const test = async () => {
    setTesting(true);
    try { setResult(await validate()); }
    catch (e) { setResult({ connected: false, message: String(e) }); }
    setTesting(false);
  };

  return (
    <div className="space-y-3">
      <SecretInput
        label={configured ? `${label} (saved — enter a new one to replace)` : label}
        value={key} onChange={setKey} placeholder={placeholder} />
      <div className="flex items-center gap-2">
        <Button size="sm" variant="primary" onClick={save} disabled={!key}>Save key</Button>
        <Button size="sm" onClick={test} disabled={testing || !configured}>
          {testing ? <Loader2 size={13} className="animate-spin" /> : null} Test connection
        </Button>
        {result && (result.connected
          ? <span className="text-xs text-emerald-400 flex items-center gap-1"><Check size={13} /> Connected{result.latency_ms ? ` · ${result.latency_ms} ms` : ""}</span>
          : <span className="text-xs text-red-400 flex items-center gap-1"><X size={13} /> {result.message}</span>)}
      </div>
    </div>
  );
}

export default function ModelsPage() {
  const { settings, patch } = useSettings();
  const [models, setModels] = useState<WhisperModelInfo[]>([]);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [info, setInfo] = useState<SystemInfo | null>(null);
  const [showBackup, setShowBackup] = useState(false);

  const load = useCallback(() => { api.models().then(setModels).catch(() => {}); }, []);
  useEffect(() => {
    load();
    api.systemInfo().then(setInfo).catch(() => {});
    api.hasApiKey("groq_backup").then((r) => setShowBackup(r.configured)).catch(() => {});
  }, [load]);

  useBackendEvents((e) => {
    if (e.type === "model_download" && (e.state === "ready" || e.state === "error")) {
      setDownloading(null);
      load();
    }
  });

  if (!settings) return null;
  const engine = settings.whisper.engine;

  const download = async (name: string) => {
    setDownloading(name);
    try { await api.downloadModel(name); } catch { /* error event handles UI */ }
    setDownloading(null);
    load();
  };

  return (
    <div className="animate-fade-in">
      <PageHeader title="Models" subtitle="How your speech becomes text — pick local or cloud transcription."
        actions={
          <Badge color={info?.hardware.cuda ? "green" : "gray"} icon={<Zap size={11} />}>
            {info?.hardware.cuda ? `GPU: ${info.hardware.gpu}` : "CPU inference (int8)"}
          </Badge>
        } />

      <Section title="Transcription engine" description="Local never leaves your machine. Cloud is dramatically faster — Groq runs Whisper on hardware built for speed, benchmarked at 200-300x real-time.">
        <div className="grid grid-cols-2 gap-2 mb-4">
          <button onClick={() => patch({ whisper: { engine: "local" } })}
            className={cn("rounded-xl border p-3 text-left transition-all",
              engine === "local" ? "border-accent bg-accent/10" : "border-border hover:border-accent/40")}>
            <div className="text-sm font-medium flex items-center gap-1.5"><HardDrive size={13} /> Local (Whisper)</div>
            <div className="text-[11px] text-muted mt-0.5">Offline, private, no account needed</div>
          </button>
          <button onClick={() => patch({ whisper: { engine: "groq" } })}
            className={cn("rounded-xl border p-3 text-left transition-all",
              engine === "groq" ? "border-accent bg-accent/10" : "border-border hover:border-accent/40")}>
            <div className="text-sm font-medium flex items-center gap-1.5"><Cloud size={13} /> Groq Cloud</div>
            <div className="text-[11px] text-muted mt-0.5">Free tier: 2,000 requests/day, no card</div>
          </button>
        </div>

        {engine === "groq" && (
          <div className="space-y-4 pt-3 border-t border-border">
            <GroqKeyRow label="Groq API key" placeholder="Get a free key at console.groq.com"
              providerId="groq" validate={api.validateGroq} />

            {!showBackup ? (
              <button className="text-xs text-accent hover:underline" onClick={() => setShowBackup(true)}>
                + Add a backup key
              </button>
            ) : (
              <div className="pt-3 border-t border-border/50">
                <GroqKeyRow label="Backup Groq API key" placeholder="A second account's key, e.g. once the free tier runs out"
                  providerId="groq_backup" validate={api.validateGroqBackup} />
              </div>
            )}

            <p className="text-[11px] text-muted">
              If your primary key is ever unavailable (rate limit, quota exhausted), WhisperText automatically
              tries the backup key, then falls back to local Whisper — you never lose a transcription.
            </p>
          </div>
        )}
      </Section>

      <Section title="Local models" description="Kept installed as your offline fallback, even when using the cloud engine.">
        {info && !info.hardware.cuda && info.hardware.gpu && (
          <div className="mb-3 text-xs text-muted">
            Your {info.hardware.gpu} predates CUDA compute 6.0, so local transcription uses optimized CPU
            inference. Recommended for this machine: <span className="text-fg font-medium">{info.recommendations.whisper_recommendation}</span>.
          </div>
        )}
        <div className="space-y-2">
          {models.map((m) => (
            <Card key={m.name} className="!p-4">
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-4 min-w-0">
                  <HardDrive size={18} className="text-muted shrink-0" />
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium capitalize">{m.name}</span>
                      {m.active && engine === "local" && <Badge color="purple">Active</Badge>}
                      {m.loaded && <Badge color="green">Loaded · {m.device}</Badge>}
                    </div>
                    <div className="text-[11px] text-muted mt-0.5">
                      {"⭐".repeat(m.accuracy)} accuracy · {"⚡".repeat(m.speed)} speed ·
                      ~{m.size_mb >= 1000 ? `${(m.size_mb / 1000).toFixed(1)} GB` : `${m.size_mb} MB`} download · {m.ram_gb} GB RAM
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  {m.installed ? (
                    <>
                      <Badge color="green" icon={<Check size={11} />}>Installed</Badge>
                      {!m.active && (
                        <Button size="sm" onClick={() => patch({ whisper: { model: m.name, engine: "local" } })}>Use</Button>
                      )}
                      {!m.active && (
                        <Button size="sm" variant="danger" aria-label={`Delete ${m.name}`}
                          onClick={() => api.deleteModel(m.name).then(load)}>
                          <Trash2 size={13} />
                        </Button>
                      )}
                    </>
                  ) : (
                    <Button size="sm" onClick={() => download(m.name)} disabled={downloading !== null}>
                      {downloading === m.name
                        ? <><Loader2 size={13} className="animate-spin" /> Downloading…</>
                        : <><Download size={13} /> Download</>}
                    </Button>
                  )}
                </div>
              </div>
            </Card>
          ))}
        </div>
      </Section>
    </div>
  );
}
