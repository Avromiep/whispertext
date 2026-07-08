/** AI providers: selection, keys, model discovery, presets, hybrid/cost modes. */
import { useCallback, useEffect, useState } from "react";
import { Check, Loader2, RefreshCw, X } from "lucide-react";
import { api, PresetInfo, ProviderInfo, SystemInfo } from "../lib/api";
import { useSettings } from "../hooks/useSettings";
import {
  Badge, Button, Card, Input, PageHeader, SecretInput, Section, Select, Slider, Toggle, cn,
} from "../components/ui";

export default function AIPage() {
  const { settings, patch } = useSettings();
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [presets, setPresets] = useState<Record<string, PresetInfo>>({});
  const [models, setModels] = useState<string[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsError, setModelsError] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [testResult, setTestResult] = useState<{ connected: boolean; message: string; latency_ms: number } | null>(null);
  const [testing, setTesting] = useState(false);
  const [recs, setRecs] = useState<SystemInfo["recommendations"] | null>(null);

  const active = settings?.ai.provider ?? "openai";
  const activeInfo = providers.find((p) => p.id === active);
  const cfg = settings?.ai.providers[active];

  const refreshProviders = useCallback(() => {
    api.providers().then(setProviders).catch(() => {});
  }, []);

  const refreshModels = useCallback(() => {
    setModelsLoading(true);
    setModelsError("");
    api.providerModels(active)
      .then((r) => setModels(r.models))
      .catch((e) => { setModels([]); setModelsError(String(e.message ?? e)); })
      .finally(() => setModelsLoading(false));
  }, [active]);

  useEffect(() => { refreshProviders(); api.presets().then(setPresets).catch(() => {}); }, [refreshProviders]);
  useEffect(() => {
    setTestResult(null); setApiKey(""); setModels([]);
    api.systemInfo().then((i) => setRecs(i.recommendations)).catch(() => {});
    if (activeInfo?.configured) refreshModels();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, activeInfo?.configured]);

  if (!settings || !cfg) return null;

  const saveKey = async () => {
    await api.setApiKey(active, apiKey);
    setApiKey("");
    refreshProviders();
    refreshModels();
  };

  const testConnection = async () => {
    setTesting(true);
    try {
      const r = await api.validateProvider(active);
      setTestResult(r);
      if (r.connected && r.models.length) setModels(r.models);
    } catch (e) {
      setTestResult({ connected: false, message: String(e), latency_ms: 0 });
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="animate-fade-in">
      <PageHeader title="AI" subtitle="Cleans your transcription: grammar, punctuation, filler words — never meaning."
        actions={
          <Toggle label="" checked={settings.ai.enabled} onChange={(v) => patch({ ai: { enabled: v } })} />
        } />

      <Section title="Provider" description="Cloud for maximum quality, local for maximum privacy.">
        <div className="grid grid-cols-2 gap-2 mb-4">
          {providers.map((p) => (
            <button key={p.id}
              onClick={() => patch({ ai: { provider: p.id } })}
              className={cn("flex items-center justify-between rounded-xl border p-3 text-left transition-all",
                active === p.id ? "border-accent bg-accent/10" : "border-border hover:border-accent/40")}>
              <div>
                <div className="text-sm font-medium">{p.name}</div>
                <div className="text-[11px] text-muted">{p.local ? "Local · offline · free" : "Cloud API"}</div>
              </div>
              {p.configured
                ? <Badge color="green">Ready</Badge>
                : <Badge color="yellow">Needs key</Badge>}
            </button>
          ))}
        </div>

        {activeInfo?.needs_api_key && (
          <div className="space-y-3 pt-3 border-t border-border">
            <SecretInput
              label={activeInfo.configured ? "API key (saved — enter a new one to replace)" : "API key"}
              value={apiKey} onChange={setApiKey} placeholder="Paste your key…" />
            <div className="flex items-center gap-2">
              <Button size="sm" variant="primary" onClick={saveKey} disabled={!apiKey}>Save key</Button>
              <Button size="sm" onClick={testConnection} disabled={testing || !activeInfo.configured}>
                {testing ? <Loader2 size={13} className="animate-spin" /> : null} Test connection
              </Button>
              {testResult && (testResult.connected
                ? <span className="text-xs text-emerald-400 flex items-center gap-1"><Check size={13} /> Connected · {testResult.latency_ms} ms</span>
                : <span className="text-xs text-red-400 flex items-center gap-1"><X size={13} /> {testResult.message}</span>)}
            </div>
          </div>
        )}
        {activeInfo?.local && (
          <div className="space-y-3 pt-3 border-t border-border">
            <Input label="Endpoint URL" value={cfg.base_url}
              onChange={(e) => patch({ ai: { providers: { [active]: { base_url: e.target.value } } } })} />
            <div className="flex items-center gap-2">
              <Button size="sm" onClick={testConnection} disabled={testing}>
                {testing ? <Loader2 size={13} className="animate-spin" /> : null} Test connection
              </Button>
              {testResult && (testResult.connected
                ? <span className="text-xs text-emerald-400 flex items-center gap-1"><Check size={13} /> Connected · {testResult.latency_ms} ms</span>
                : <span className="text-xs text-red-400 flex items-center gap-1"><X size={13} />
                    {active === "ollama" ? "Ollama not detected — start Ollama to enable local AI." : testResult.message}</span>)}
            </div>
            {recs && active === "ollama" && (
              <Card className="!p-4 bg-accent/5 border-accent/30">
                <div className="text-xs font-medium mb-1">💡 Recommended for your PC</div>
                <div className="text-sm font-semibold">{recs.recommended}</div>
                <div className="text-xs text-muted mt-1">{recs.note}</div>
              </Card>
            )}
          </div>
        )}

        <div className="pt-4 mt-1">
          <div className="flex items-end gap-2">
            <Select className="flex-1" label="Model (queried live from provider)"
              value={cfg.model}
              onChange={(v) => patch({ ai: { providers: { [active]: { model: v } } } })}
              options={[
                ...(cfg.model && !models.includes(cfg.model) ? [{ value: cfg.model, label: cfg.model }] : []),
                ...models.map((m) => ({ value: m, label: m })),
              ]} />
            <Button size="md" onClick={refreshModels} disabled={modelsLoading} aria-label="Refresh models">
              <RefreshCw size={14} className={modelsLoading ? "animate-spin" : ""} />
            </Button>
          </div>
          {modelsError && <p className="text-xs text-red-400 mt-1.5">Couldn't load models: {modelsError}</p>}
        </div>
      </Section>

      <Section title="Mode" description="Hybrid falls back automatically so you never lose a transcription.">
        <div className="grid grid-cols-3 gap-2 mb-3">
          {(["cloud", "local", "hybrid"] as const).map((m) => (
            <button key={m} onClick={() => patch({ ai: { mode: m } })}
              className={cn("rounded-xl border p-3 text-sm capitalize transition-all",
                settings.ai.mode === m ? "border-accent bg-accent/10 font-medium" : "border-border hover:border-accent/40")}>
              {m}
            </button>
          ))}
        </div>
        <Toggle label="Minimize API costs" description="Prefer local AI whenever possible"
          checked={settings.ai.minimize_costs} onChange={(v) => patch({ ai: { minimize_costs: v } })} />
        <Toggle label="Offline mode" description="Never send anything to the cloud"
          checked={settings.ai.offline_only} onChange={(v) => patch({ ai: { offline_only: v } })} />
      </Section>

      <Section title="Style preset" description="How the AI edits your words.">
        <div className="grid grid-cols-2 gap-2">
          {Object.entries(presets).map(([id, p]) => (
            <button key={id} onClick={() => patch({ ai: { preset: id } })}
              className={cn("rounded-xl border p-3 text-left transition-all",
                settings.ai.preset === id ? "border-accent bg-accent/10" : "border-border hover:border-accent/40")}>
              <div className="text-sm font-medium">{p.label}</div>
              <div className="text-[11px] text-muted mt-0.5">{p.description}</div>
            </button>
          ))}
        </div>
        <div className="mt-4">
          <div className="text-xs text-muted mb-1.5">Custom instructions (appended to the prompt)</div>
          <textarea
            value={settings.ai.custom_instructions}
            onChange={(e) => patch({ ai: { custom_instructions: e.target.value } })}
            rows={3}
            placeholder="e.g. Always spell my name as 'Avrom'. Use Oxford commas."
            className="w-full rounded-xl bg-elevated border border-border px-3 py-2 text-sm placeholder:text-muted/60 focus:border-accent transition-colors resize-none"
          />
        </div>
      </Section>

      <Section title="Generation" description="Performance profile adjusts temperature, token limits, and prompt length.">
        <div className="grid grid-cols-3 gap-2 mb-4">
          {([["quality", "Maximum Quality"], ["balanced", "Balanced"], ["speed", "Maximum Speed"]] as const).map(([id, label]) => (
            <button key={id} onClick={() => patch({ ai: { performance: id } })}
              className={cn("rounded-xl border p-3 text-sm transition-all",
                settings.ai.performance === id ? "border-accent bg-accent/10 font-medium" : "border-border hover:border-accent/40")}>
              {label}
            </button>
          ))}
        </div>
        <Slider label="Temperature" min={0} max={1} step={0.05} value={cfg.temperature}
          onChange={(v) => patch({ ai: { providers: { [active]: { temperature: v } } } })} />
        <Slider label="Max tokens" min={256} max={8192} step={256} value={cfg.max_tokens}
          onChange={(v) => patch({ ai: { providers: { [active]: { max_tokens: v } } } })} />
        <Slider label="Request timeout" min={5} max={120} step={5} value={cfg.timeout_s}
          format={(v) => `${v}s`} onChange={(v) => patch({ ai: { providers: { [active]: { timeout_s: v } } } })} />
        <Slider label="Retries" min={1} max={5} step={1} value={settings.ai.retries}
          onChange={(v) => patch({ ai: { retries: v } })} />
      </Section>
    </div>
  );
}
