/** Whisper model management: transcription engine choice, local model status, downloads. */
import { useCallback, useEffect, useState } from "react";
import { Check, Cloud, Download, ExternalLink, HardDrive, Loader2, Radio, RefreshCw, Trash2, X, Zap } from "lucide-react";
import { api, bridge, SystemInfo, WhisperModelInfo } from "../lib/api";
import { useBackendEvents } from "../lib/ws";
import { useSettings } from "../hooks/useSettings";
import { Badge, Button, Card, PageHeader, SecretInput, Section, cn } from "../components/ui";

interface KeyTestResult { connected: boolean; message: string; latency_ms?: number }

/** One API-key row: secret input, save, test-connection — reused for the
 * primary and backup Groq keys since they behave identically. */
function GroqKeyRow({ label, placeholder, providerId, validate, onConfiguredChange }: {
  label: string; placeholder: string; providerId: string;
  validate: () => Promise<KeyTestResult>;
  onConfiguredChange?: (configured: boolean) => void;
}) {
  const [key, setKey] = useState("");
  const [configured, setConfigured] = useState(false);
  const [testing, setTesting] = useState(false);
  const [result, setResult] = useState<KeyTestResult | null>(null);

  useEffect(() => {
    api.hasApiKey(providerId).then((r) => { setConfigured(r.configured); onConfiguredChange?.(r.configured); }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [providerId]);

  const save = async () => {
    await api.setApiKey(providerId, key);
    setKey("");
    setConfigured(true);
    onConfiguredChange?.(true);
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

/** "Get an API key" helper: a button that opens the provider's console in the
 * default browser, plus numbered steps for setting the key up. */
function KeySetupHelp({ url, buttonLabel, steps }: { url: string; buttonLabel: string; steps: string[] }) {
  const open = () => { if (bridge) bridge.openExternal(url); else window.open(url, "_blank"); };
  return (
    <div className="rounded-xl border border-border bg-black/5 p-3 space-y-2">
      <button onClick={open}
        className="text-xs text-accent hover:underline inline-flex items-center gap-1 font-medium">
        <ExternalLink size={12} /> {buttonLabel}
      </button>
      <ol className="text-[11px] text-muted list-decimal ml-4 space-y-0.5">
        {steps.map((s, i) => <li key={i}>{s}</li>)}
      </ol>
    </div>
  );
}

interface BalanceResult { ok: boolean; amount?: number; units?: string; message?: string; needs_admin?: boolean }

/** Remaining Deepgram credit. Reading the balance needs an Admin-scoped key;
 * a Member key (fine for transcription) gets a clear note instead of a number. */
function DeepgramBalance() {
  const [loading, setLoading] = useState(true);
  const [bal, setBal] = useState<BalanceResult | null>(null);

  const refresh = useCallback(() => {
    setLoading(true);
    api.deepgramBalance()
      .then(setBal)
      .catch((e) => setBal({ ok: false, message: String(e) }))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  return (
    <div className="rounded-xl border border-border bg-black/5 p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs text-muted">Credit remaining</div>
          {loading ? (
            <div className="text-sm font-medium flex items-center gap-1.5 mt-0.5">
              <Loader2 size={14} className="animate-spin" /> Checking…
            </div>
          ) : bal?.ok ? (
            <div className="text-lg font-semibold mt-0.5">
              ${bal.amount?.toFixed(2)}
              <span className="text-xs text-muted font-normal ml-1 uppercase">{bal.units}</span>
            </div>
          ) : (
            <div className="text-xs text-amber-500 mt-0.5">{bal?.message || "Unavailable"}</div>
          )}
        </div>
        <Button size="sm" onClick={refresh} disabled={loading}>
          {loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />} Refresh
        </Button>
      </div>
    </div>
  );
}

/** Estimated Grok spend this month. xAI's exact bill lives in its console and
 * needs a separate management key; this is a no-extra-key estimate from how much
 * audio you've transcribed via Grok times the streaming rate. */
function GrokUsage() {
  const [loading, setLoading] = useState(true);
  const [u, setU] = useState<{ minutes: number; rate_per_hour: number; estimated_usd: number } | null>(null);

  const refresh = useCallback(() => {
    setLoading(true);
    api.grokUsage().then(setU).catch(() => setU(null)).finally(() => setLoading(false));
  }, []);
  useEffect(() => { refresh(); }, [refresh]);

  return (
    <div className="rounded-xl border border-border bg-black/5 p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-xs text-muted">Estimated spend this month</div>
          {loading ? (
            <div className="text-sm font-medium flex items-center gap-1.5 mt-0.5">
              <Loader2 size={14} className="animate-spin" /> Checking…
            </div>
          ) : u ? (
            <>
              <div className="text-lg font-semibold mt-0.5">~${u.estimated_usd.toFixed(2)}</div>
              <div className="text-[11px] text-muted mt-0.5">
                {u.minutes.toFixed(1)} min of audio · ${u.rate_per_hour.toFixed(2)}/hr · estimate, see console.x.ai for the exact bill
              </div>
            </>
          ) : (
            <div className="text-xs text-amber-500 mt-0.5">Usage unavailable</div>
          )}
        </div>
        <Button size="sm" onClick={refresh} disabled={loading}>
          {loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />} Refresh
        </Button>
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
  const [groqConfigured, setGroqConfigured] = useState(false);
  const [deepgramConfigured, setDeepgramConfigured] = useState(false);
  const [grokConfigured, setGrokConfigured] = useState(false);

  const load = useCallback(() => { api.models().then(setModels).catch(() => {}); }, []);
  useEffect(() => {
    load();
    api.systemInfo().then(setInfo).catch(() => {});
    api.hasApiKey("groq_backup").then((r) => setShowBackup(r.configured)).catch(() => {});
    api.hasApiKey("groq").then((r) => setGroqConfigured(r.configured)).catch(() => {});
    api.hasApiKey("deepgram").then((r) => setDeepgramConfigured(r.configured)).catch(() => {});
    api.hasApiKey("grok").then((r) => setGrokConfigured(r.configured)).catch(() => {});
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

      <Section title="Transcription engine" description="Local never leaves your machine. Groq is a fast batch cloud engine. Deepgram and Grok (xAI) both stream live — they transcribe while you talk, so there's no wait after you release the hotkey.">
        <div className="grid grid-cols-2 gap-2 mb-4">
          <button onClick={() => patch({ whisper: { engine: "local" } })}
            className={cn("rounded-xl border p-3 text-left transition-all",
              engine === "local" ? "border-accent bg-accent/10" : "border-border hover:border-accent/40")}>
            <div className="text-sm font-medium flex items-center gap-1.5"><HardDrive size={13} /> Local</div>
            <div className="text-[11px] text-muted mt-0.5">Offline, private, no account</div>
          </button>
          <button onClick={() => patch({ whisper: { engine: "groq" } })}
            className={cn("rounded-xl border p-3 text-left transition-all",
              engine === "groq" ? "border-accent bg-accent/10" : "border-border hover:border-accent/40")}>
            <div className="text-sm font-medium flex items-center gap-1.5"><Cloud size={13} /> Groq · Whisper</div>
            <div className="text-[11px] text-muted mt-0.5">{groqConfigured ? "Key configured ✓" : "Fast batch · needs key"}</div>
          </button>
          <button onClick={() => patch({ whisper: { engine: "deepgram" } })}
            className={cn("rounded-xl border p-3 text-left transition-all",
              engine === "deepgram" ? "border-accent bg-accent/10" : "border-border hover:border-accent/40")}>
            <div className="text-sm font-medium flex items-center gap-1.5"><Radio size={13} /> Deepgram</div>
            <div className="text-[11px] text-muted mt-0.5">{deepgramConfigured ? "Key configured ✓" : "Live · feels instant"}</div>
          </button>
          <button onClick={() => patch({ whisper: { engine: "grok" } })}
            className={cn("rounded-xl border p-3 text-left transition-all",
              engine === "grok" ? "border-accent bg-accent/10" : "border-border hover:border-accent/40")}>
            <div className="text-sm font-medium flex items-center gap-1.5"><Zap size={13} /> Grok · xAI</div>
            <div className="text-[11px] text-muted mt-0.5">{grokConfigured ? "Key configured ✓" : "Live · cheaper stream"}</div>
          </button>
        </div>

        {engine === "deepgram" && (
          <div className="space-y-4 pt-3 border-t border-border">
            <KeySetupHelp url="https://console.deepgram.com/signup"
              buttonLabel="Get a Deepgram API key → console.deepgram.com"
              steps={[
                "Sign up — it's free and includes $200 of credit (no card required).",
                "In the console, open API Keys and click Create a New API Key.",
                "Copy the key, paste it below, and click Save key.",
                "For the credit meter to show, create the key with Owner or Admin permission.",
              ]} />
            <GroqKeyRow label="Deepgram API key" placeholder="Paste your Deepgram API key"
              providerId="deepgram" validate={api.validateDeepgram} onConfiguredChange={setDeepgramConfigured} />
            {deepgramConfigured && <DeepgramBalance />}
            <p className="text-[11px] text-muted">
              Deepgram transcribes as you speak, so releasing the hotkey feels instant. If it's ever
              unavailable, WhisperText falls back to Groq (if configured), then local Whisper — you never
              lose a transcription. Groq's key is kept and used whenever you switch back.
            </p>
          </div>
        )}

        {engine === "grok" && (
          <div className="space-y-4 pt-3 border-t border-border">
            <KeySetupHelp url="https://console.x.ai/"
              buttonLabel="Get an xAI API key → console.x.ai"
              steps={[
                "Sign in to the xAI developer console (this is separate from a SuperGrok/X subscription).",
                "Open Billing and add a payment method or prepaid credits — API usage is billed separately.",
                "Open API Keys and click Create API Key.",
                "Copy the key, paste it below, and click Save key.",
              ]} />
            <GroqKeyRow label="xAI API key" placeholder="Paste your xAI API key"
              providerId="grok" validate={api.validateGrok} onConfiguredChange={setGrokConfigured} />
            {grokConfigured && <GrokUsage />}
            <p className="text-[11px] text-muted">
              Grok Voice Transcribe (xAI) streams live like Deepgram, at a lower price ($0.20/hr). It needs an
              xAI <b>API</b> key from console.x.ai with its own billing — a SuperGrok/X subscription does not
              include API access. If it's ever unavailable, WhisperText falls back to Groq (if configured),
              then local Whisper. Not to be confused with the “Groq · Whisper” engine above.
            </p>
          </div>
        )}

        {engine === "groq" && (
          <div className="space-y-4 pt-3 border-t border-border">
            <KeySetupHelp url="https://console.groq.com/keys"
              buttonLabel="Get a Groq API key → console.groq.com"
              steps={[
                "Sign up at console.groq.com — the free tier is enough for dictation.",
                "On the API Keys page, click Create API Key.",
                "Copy the key, paste it below, and click Save key.",
              ]} />
            <GroqKeyRow label="Groq API key" placeholder="Paste your Groq API key"
              providerId="groq" validate={api.validateGroq} onConfiguredChange={setGroqConfigured} />

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
